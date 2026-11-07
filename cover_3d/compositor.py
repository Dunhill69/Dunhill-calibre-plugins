import array
import math
import base64
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from calibre_plugins.cover3d.overlays_data import (
    edges_png,
    spine_linearburn_png,
    spine_linearburn_rtl_png,
    spine_normal_png,
    spine_normal_rtl_png,
    spine_softlight_png,
    spine_softlight_rtl_png,
)

_OVERLAYS = {
    'edges': edges_png,
    'spine-linearburn': spine_linearburn_png,
    'spine-linearburn-rtl': spine_linearburn_rtl_png,
    'spine-normal': spine_normal_png,
    'spine-normal-rtl': spine_normal_rtl_png,
    'spine-softlight': spine_softlight_png,
    'spine-softlight-rtl': spine_softlight_rtl_png,
}

_decoded_overlays = {}
_resized_cache = {}
_SOFT_LIGHT_LUT = None

def _decode_overlay(name):
    if name in _decoded_overlays:
        return _decoded_overlays[name]
    b64 = _OVERLAYS.get(name)
    if not b64:
        return None
    img = Image.open(BytesIO(base64.b64decode(b64))).convert('RGBA')
    _decoded_overlays[name] = img
    return img

def _get_resized_overlay(name, size):
    key = (name, size)
    if key in _resized_cache:
        return _resized_cache[key]
    img = _decode_overlay(name)
    if img is None:
        return None
    resized = img.resize(size, Image.BICUBIC)
    _resized_cache[key] = resized
    return resized

def _build_soft_light_lut():
    global _SOFT_LIGHT_LUT
    if _SOFT_LIGHT_LUT is not None:
        return _SOFT_LIGHT_LUT
    _SOFT_LIGHT_LUT = array.array('H', [0] * 65536)
    for bv in range(256):
        bf = bv / 255.0
        g = bf if bf < 0.25 else ((16.0 * bf - 12.0) * bf + 4.0) * bf
        for sv in range(256):
            sf = sv / 255.0
            if sf <= 0.5:
                val = bf - (1.0 - 2.0 * sf) * bf * (1.0 - bf)
            else:
                val = bf + (2.0 * sf - 1.0) * (g - bf)
            _SOFT_LIGHT_LUT[bv * 256 + sv] = max(0, min(255, round(val * 255.0)))
    return _SOFT_LIGHT_LUT

def _multiply_blend(base, overlay):
    base_r, base_g, base_b, base_a = base.split()
    over_r, over_g, over_b, over_a = overlay.split()
    final_r = Image.composite(ImageChops.multiply(base_r, over_r), base_r, over_a)
    final_g = Image.composite(ImageChops.multiply(base_g, over_g), base_g, over_a)
    final_b = Image.composite(ImageChops.multiply(base_b, over_b), base_b, over_a)
    return Image.merge('RGBA', (final_r, final_g, final_b, base_a))

def _soft_light_blend(base, overlay):
    lut = _build_soft_light_lut()
    over_a = overlay.split()[3]
    bbox = over_a.getbbox()
    if not bbox:
        return base.copy()
    crop_base = base.crop(bbox)
    crop_over = overlay.crop(bbox)
    crop_a = over_a.crop(bbox)
    lut_rows = {}
    for lv in range(0, 256, 16):
        lut_rows[lv] = bytes(min(255, max(0, lut[b * 256 + lv])) for b in range(256))
    result_channels = []
    for ch in range(3):
        base_ch = crop_base.split()[ch]
        over_ch = crop_over.split()[ch]
        quant = over_ch.point(lambda x: (x // 16) * 16)
        result_ch = base_ch.copy()
        for lv in range(0, 256, 16):
            lut_row = lut_rows[lv]
            blended = base_ch.point(lut_row)
            mask = Image.eval(quant, lambda x, target=lv: 255 if x == target else 0)
            mask = ImageChops.multiply(mask, crop_a)
            if not mask.getbbox():
                continue
            result_ch = Image.composite(blended, result_ch, mask)
        result_channels.append(result_ch)
    result_channels.append(crop_base.split()[3])
    result = Image.merge('RGBA', result_channels)
    canvas = base.copy()
    canvas.paste(result, (bbox[0], bbox[1]))
    return canvas

def _find_perspective_coefficients(pa, pb):
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0]*p1[0], -p2[0]*p1[1], p2[0]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1]*p1[0], -p2[1]*p1[1], p2[1]])
    n = 8
    for i in range(n):
        max_el = abs(matrix[i][i])
        max_row = i
        for k in range(i + 1, n):
            if abs(matrix[k][i]) > max_el:
                max_el = abs(matrix[k][i])
                max_row = k
        matrix[i], matrix[max_row] = matrix[max_row], matrix[i]
        pivot = matrix[i][i]
        if abs(pivot) < 1e-10:
            return [1, 0, 0, 0, 1, 0, 0, 0]
        for j in range(i, n + 1):
            matrix[i][j] /= pivot
        for k in range(n):
            if k != i:
                c = -matrix[k][i]
                for j in range(i, n + 1):
                    matrix[k][j] += c * matrix[i][j]
    return [matrix[x][n] for x in range(n)]

MAX_WIDTH = 1600

# Colores del canto superior (hojas): tono papel, no blanco puro, para que no
# resalte demasiado, sobre todo con portadas claras.
PAGE_FRONT = (214, 206, 190)   # junto a la portada
PAGE_BACK = (172, 164, 150)    # hacia el fondo del libro
PAGE_LINE_DARKEN = 14          # líneas de las hojas
PAGE_BORDER = (70, 64, 56, 255)


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _mix(a, b, t):
    return tuple(round(a[k] + (b[k] - a[k]) * t) for k in range(3))


def _band_color(col_front, col_back, t, rounded):
    if not rounded:
        return _mix(col_front, col_back, t)
    # Lomo redondeado: un brillo suave a un tercio del ancho
    light = tuple(min(255, round(c * 1.45 + 18)) for c in col_front)
    if t < 0.3:
        return _mix(col_front, light, t / 0.3)
    return _mix(light, col_back, (t - 0.3) / 0.7)


def _draw_band(draw, f0, f1, b1, b0, col_front, col_back, rounded=False):
    """Cara lateral (lomo) con degradé desde el borde de la portada (f0-f1)
    hacia atrás (b0-b1). Con rounded=True simula un lomo redondeado."""
    if col_front == col_back and not rounded:
        draw.polygon([f0, f1, b1, b0], fill=tuple(col_front) + (255,))
        return
    steps = max(1, int(round(abs(b0[0] - f0[0]))))
    for i in range(steps):
        t0, t1 = i / steps, (i + 1) / steps
        tm = (t0 + t1) / 2
        col = _band_color(col_front, col_back, tm, rounded)
        quad = [_lerp(f0, b0, t0), _lerp(f1, b1, t0), _lerp(f1, b1, t1), _lerp(f0, b0, t1)]
        draw.polygon(quad, fill=col + (255,))


def _bilerp(f0, f1, b1, b0, s, t):
    return _lerp(_lerp(f0, f1, s), _lerp(b0, b1, s), t)


def _draw_top(draw, f0, f1, b1, b0, pixel_ratio, hard, board_col, far_end, spine_cols=None, fore_drop=0):
    """Canto superior. Tapa blanda: hojas al ras. Tapa dura, como un libro real:
    los dos cartones sobresalen de las hojas (las «cejas», unos 3 mm), así que
    las hojas quedan metidas y más abajo; entre los cartones, pasando el final
    de las hojas, queda el hueco (no un cartón que cierre el libro). Del lado
    del lomo, la cabeza del lomo une los dos cartones.

    far_end: 1 si la apertura está en f1 (lomo a la izquierda), 0 si está en f0."""
    if not hard:
        _draw_page_edge(draw, f0, f1, b1, b0, pixel_ratio)
        return
    P = lambda s_, t_: _bilerp(f0, f1, b1, b0, s_, t_)
    quad = lambda sa_, sb_, ta_, tb_: [P(sa_, ta_), P(sb_, ta_), P(sb_, tb_), P(sa_, tb_)]
    length = math.hypot(f1[0] - f0[0], f1[1] - f0[1]) or 1
    depth = math.hypot(b0[0] - f0[0], b0[1] - f0[1]) or 1
    board = 0.14                                  # grosor de cada cartón (en la profundidad)
    head = min(0.03, max(0.012, (depth * board * 1.6) / length))   # cabeza del lomo ~ un cartón
    square = 0.025                                # ceja del lado de la apertura (~3 mm)
    if far_end == 1:
        h0, h1, p0, p1 = 0.0, head, head, 1 - square
    else:
        h0, h1, p0, p1 = 1 - head, 1.0, square, 1 - head
    # La contratapa es un cartón entero: en la esquina de la apertura su canto
    # baja en vertical hasta esconderse detrás de las hojas y de la tapa (por
    # eso se dibuja primero). Entre ese canto y el
    # final de las hojas queda el hueco abierto (se ve el fondo).
    back_col = tuple(round(c * 0.85) for c in board_col)
    if fore_drop > 0:
        e = 1.0 if far_end == 1 else 0.0
        a_, b_ = P(e, 1 - board), P(e, 1)
        draw.polygon([a_, b_, (b_[0], b_[1] + fore_drop), (a_[0], a_[1] + fore_drop)], fill=back_col + (255,))
        # filo claro del cartón
        draw.line([a_, (a_[0], a_[1] + fore_drop)], fill=tuple(min(255, round(c * 1.35 + 20)) for c in back_col) + (255,),
                  width=max(1, round(0.8 * pixel_ratio)))
    # Hojas, metidas: un poco más abajo que los cartones. Junto a cada cartón,
    # una franja de sombra; más allá del final de las hojas no se dibuja nada,
    # así que entre los cartones se ve el fondo (el libro queda abierto).
    ta, tb = board + 0.05, 1 - board - 0.05
    gap = tuple(round(c * 0.35) for c in board_col)
    draw.polygon(quad(p0, p1, board, 1 - board), fill=gap + (255,))
    _draw_page_edge(draw, *quad(p0, p1, ta, tb), pixel_ratio, border=False)
    # Cartones delantero y trasero, de punta a punta
    draw.polygon(quad(0, 1, 0, board), fill=tuple(board_col) + (255,))
    back_col = tuple(round(c * 0.85) for c in board_col)
    draw.polygon(quad(0, 1, 1 - board, 1), fill=back_col + (255,))
    # Cabeza del lomo: une los dos cartones del lado del lomo
    front, back = spine_cols or (board_col, board_col)
    steps = max(1, int(round(abs(P(h0, 1)[1] - P(h0, 0)[1]))) * 2)
    for i in range(steps):
        t0, t1 = i / steps, (i + 1) / steps
        col = _band_color(front, back, (t0 + t1) / 2, True)
        draw.polygon(quad(h0, h1, t0, t1), fill=col + (255,))
    draw.line([f0, f1], fill=PAGE_BORDER, width=max(1, round(1.5 * pixel_ratio)))


def _draw_page_edge(draw, f0, f1, b1, b0, pixel_ratio, border=True):
    """Dibuja el canto superior: f0-f1 es el borde junto a la portada y
    b0-b1 el borde del fondo. Se pinta en franjas con degradé y líneas de hojas."""
    steps = max(1, int(round(abs(b0[1] - f0[1]))) * 2)
    line_every = max(2, steps // 6)
    for i in range(steps):
        t0, t1 = i / steps, (i + 1) / steps
        tm = (t0 + t1) / 2
        col = [round(PAGE_FRONT[k] + (PAGE_BACK[k] - PAGE_FRONT[k]) * tm) for k in range(3)]
        if i and i % line_every == 0:
            col = [max(0, c - PAGE_LINE_DARKEN) for c in col]
        quad = [_lerp(f0, b0, t0), _lerp(f1, b1, t0), _lerp(f1, b1, t1), _lerp(f0, b0, t1)]
        draw.polygon(quad, fill=tuple(col) + (255,))
    # Borde fino que separa el canto de la portada
    if border:
        draw.line([f0, f1], fill=PAGE_BORDER, width=max(1, round(1.5 * pixel_ratio)))


# Grosor relativo del libro según la encuadernación
THICKNESS = {'soft': 1.0, 'hard': 1.15, 'thick': 2.8}
# Ancho real del lomo respecto del ancho de la portada (para dibujar su contenido)
SPINE_RATIO = {'soft': 0.08, 'hard': 0.09, 'thick': 0.16}


def _load_font(size, bold=True):
    """Fuente para el texto del lomo: la Liberation Serif que trae calibre;
    si no, alguna del sistema; en último caso la de Pillow."""
    from PIL import ImageFont
    name = 'LiberationSerif-Bold.ttf' if bold else 'LiberationSerif-Regular.ttf'
    candidates = []
    try:
        import builtins
        candidates.append(builtins.P('fonts/liberation/' + name))
    except Exception:
        pass
    candidates += [name, 'DejaVuSerif-Bold.ttf' if bold else 'DejaVuSerif.ttf',
                   'georgiab.ttf' if bold else 'georgia.ttf', 'timesbd.ttf' if bold else 'times.ttf',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf']
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _fit_text(draw, text, max_len, size, min_size, bold=True):
    """Achica la letra hasta que el texto entre en max_len; si ni así entra, lo corta con «…»."""
    size = max(min_size, int(size))
    while True:
        font = _load_font(size, bold)
        w = draw.textlength(text, font=font)
        if w <= max_len or size <= min_size:
            break
        size = max(min_size, int(size * 0.92))
    while text and draw.textlength(text, font=font) > max_len:
        text = text[:-2].rstrip() + '…' if len(text) > 2 else ''
    return text, font


def _spine_texture(cover_rgb, sw, h, mode, base_col, title, author, rtl):
    """Contenido plano del lomo (sw x h). x = 0 es el borde de atrás en
    libros de izquierda a derecha y el borde de la portada en los RTL."""
    if mode == 'stretch':
        # La franja del borde de la portada, estirada: la ilustración parece seguir por el lomo
        strip = max(2, cover_rgb.width // 25)
        box = (cover_rgb.width - strip, 0, cover_rgb.width, cover_rgb.height) if rtl else (0, 0, strip, cover_rgb.height)
        tex = cover_rgb.crop(box).resize((sw, h), Image.BICUBIC)
        if not rtl:
            tex = tex.transpose(Image.Transpose.FLIP_LEFT_RIGHT)  # el borde de la portada queda junto a la portada
        return tex.convert('RGBA')
    tex = Image.new('RGBA', (h, sw), tuple(base_col) + (255,))   # horizontal, luego se gira
    if mode == 'title' and (title or author):
        d = ImageDraw.Draw(tex)
        lum = 0.299 * base_col[0] + 0.587 * base_col[1] + 0.114 * base_col[2]
        ink = (245, 240, 228, 255) if lum < 140 else (25, 22, 20, 255)
        pad = round(h * 0.05)
        t_text, t_font = _fit_text(d, (title or '').strip(), h * 0.62 - pad, sw * 0.42, max(6, sw * 0.18))
        a_text, a_font = _fit_text(d, (author or '').strip(), h * 0.30 - pad, sw * 0.30, max(6, sw * 0.15), bold=False)
        cy = sw / 2
        if t_text:
            d.text((pad, cy), t_text, font=t_font, fill=ink, anchor='lm')
        if a_text:
            d.text((h - pad, cy), a_text, font=a_font, fill=ink, anchor='rm')
        # filetes decorativos arriba y abajo
        lw = max(1, round(sw * 0.03))
        for x in (round(pad * 0.45), h - round(pad * 0.45)):
            d.line([(x, sw * 0.18), (x, sw * 0.82)], fill=ink, width=lw)
    # texto de arriba hacia abajo, como en los lomos en español e inglés
    # (girado a la derecha: la parte de arriba de las letras mira hacia la portada)
    return tex.rotate(-90, expand=True)


def _shade_spine(tex, front_at_right):
    """Oscurece el lomo: más cerca del fondo, más oscuro."""
    w, h = tex.size
    grad = Image.new('L', (w, 1))
    for x in range(w):
        t = x / max(1, w - 1)
        t = t if front_at_right else 1 - t      # t = 1 junto a la portada
        grad.putpixel((x, 0), round(255 * (0.62 + 0.30 * t)))
    grad = grad.resize((w, h))
    r, g, b, a = tex.split()
    shade = Image.merge('RGB', (grad, grad, grad))
    rgb = ImageChops.multiply(Image.merge('RGB', (r, g, b)), shade)
    return Image.merge('RGBA', (*rgb.split(), a))


DEFAULT_ANGLE = 30   # grados de giro del libro (0 = de frente)
DEFAULT_TOP = 20     # cuánto se ve el canto superior (sobre 500 px de ancho)
_REF_SIN = math.sin(math.radians(32))  # ángulo de referencia del diseño original


def generate_cover(cover_bytes, pixel_ratio=1, rtl=False, fmt='png', background=None, width=None,
                   angle=DEFAULT_ANGLE, top=DEFAULT_TOP, shadow=True, spine='black',
                   binding='soft', title='', author=''):
    cover = Image.open(BytesIO(cover_bytes)).convert('RGBA')
    # width: ancho de la portada en píxeles antes de la perspectiva.
    #   None -> 500 * pixel_ratio (comportamiento original)
    #   0    -> el ancho de la portada original (con tope MAX_WIDTH)
    if width == 0:
        width = min(cover.width, MAX_WIDTH)
    if width:
        pixel_ratio = max(width, 100) / 500.0
    orig_w = round(500 * pixel_ratio)
    orig_h = round(orig_w * (cover.height / cover.width))
    cover = cover.resize((orig_w, orig_h), Image.BICUBIC)

    # Color del lomo: negro, o el color medio del borde de la portada del lado
    # del lomo (antes de aplicar las sombras del efecto).
    if spine in ('cover', 'title', 'stretch'):
        strip_w = max(2, orig_w // 12)
        box = (orig_w - strip_w, 0, orig_w, orig_h) if rtl else (0, 0, strip_w, orig_h)
        avg = cover.convert('RGB').crop(box).resize((1, 1), Image.BOX).getpixel((0, 0))
        spine_front = tuple(round(c * 0.72) for c in avg)
        spine_back = tuple(round(c * 0.45) for c in avg)
    else:
        spine_front = spine_back = (30, 30, 30)
    # Color del canto de los cartones (tapa dura): el del borde superior de la portada
    top_avg = cover.convert('RGB').crop((0, 0, orig_w, max(2, orig_h // 40))).resize((1, 1), Image.BOX).getpixel((0, 0))
    board_col = tuple(round(c * 0.8) for c in top_avg)
    hard = binding == 'hard'
    flat_rgb = cover.convert('RGB')

    suffix = '-rtl' if rtl else ''
    spine_lb = _get_resized_overlay(f'spine-linearburn{suffix}', (orig_w, orig_h)) or _get_resized_overlay('spine-linearburn', (orig_w, orig_h))
    if spine_lb: cover = _multiply_blend(cover, spine_lb)
    spine_n = _get_resized_overlay(f'spine-normal{suffix}', (orig_w, orig_h)) or _get_resized_overlay('spine-normal', (orig_w, orig_h))
    if spine_n: cover = Image.alpha_composite(cover, spine_n)
    spine_sl = _get_resized_overlay(f'spine-softlight{suffix}', (orig_w, orig_h)) or _get_resized_overlay('spine-softlight', (orig_w, orig_h))
    if spine_sl: cover = _soft_light_blend(cover, spine_sl)
    edges = _get_resized_overlay('edges', (orig_w, orig_h))
    if edges: cover = Image.alpha_composite(cover, edges)

    # Geometría según el ángulo de giro (en grados) y el canto superior.
    # Con 32° se obtiene exactamente el diseño original (0.85 / 0.20 / 40 px).
    theta = math.radians(max(0.0, min(float(angle), 70.0)))
    w_proj = max(1, round(orig_w * math.cos(theta)))
    slant_y = round(orig_w * math.sin(theta) * (0.20 / _REF_SIN))
    # Leve achatamiento vertical por el giro: 4% a 32°, nada de frente (0°).
    h_proj = round(orig_h * (1 - 0.04 * math.sin(theta) / _REF_SIN))
    thickness = round(40 * pixel_ratio * math.sin(theta) / _REF_SIN * THICKNESS.get(binding, 1.0))
    # El canto superior acompaña al ángulo: con el libro de frente casi no se
    # ve, y crece al girarlo (con 32° vale exactamente lo elegido).
    depth_y = round(max(0, top) * pixel_ratio * math.sin(theta) / _REF_SIN)
    margin = round(90 * pixel_ratio)

    canvas_w = margin * 2 + thickness + w_proj
    canvas_h = margin * 2 + depth_y + slant_y + h_proj
    src_pts = [(0, 0), (orig_w, 0), (orig_w, orig_h), (0, orig_h)]

    if not rtl:
        x0 = margin + thickness
        y0 = margin + depth_y + slant_y
        TL, TR = (x0, y0), (x0 + w_proj, y0 - slant_y)
        BR, BL = (x0 + w_proj, y0 - slant_y + h_proj), (x0, y0 + h_proj)
        dst_pts = [TL, TR, BR, BL]
        TL_spine = (TL[0] - round(thickness * 0.8), TL[1] - depth_y)
        BL_spine = (BL[0] - round(thickness * 0.8), BL[1] - depth_y)
        TR_pages = (TR[0] - round(thickness * 0.8), TR[1] - depth_y)
        shadow_poly = [TL_spine, TR_pages, TR, BR, BL, BL_spine]
    else:
        x0 = margin
        y0 = margin + depth_y
        TL, TR = (x0, y0), (x0 + w_proj, y0 + slant_y)
        BR, BL = (x0 + w_proj, y0 + slant_y + h_proj), (x0, y0 + h_proj)
        dst_pts = [TL, TR, BR, BL]
        TL_pages = (TL[0] + round(thickness * 0.8), TL[1] - depth_y)
        TR_spine = (TR[0] + round(thickness * 0.8), TR[1] - depth_y)
        BR_spine = (BR[0] + round(thickness * 0.8), BR[1] - depth_y)
        shadow_poly = [TL, TL_pages, TR_spine, BR_spine, BR, BL]

    coefs = _find_perspective_coefficients(dst_pts, src_pts)
    
    # Mapeo forzando transparencia
    mask = Image.new('L', cover.size, 255)
    mask_3d = mask.transform((canvas_w, canvas_h), Image.Transform.PERSPECTIVE, coefs, Image.BICUBIC)
    cover_3d = cover.transform((canvas_w, canvas_h), Image.Transform.PERSPECTIVE, coefs, Image.BICUBIC)
    cover_3d.putalpha(mask_3d)

    shadow_img = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_img)
    shadow_offset_x = round(15 * pixel_ratio) if not rtl else round(-15 * pixel_ratio)
    shadow_offset_y = round(20 * pixel_ratio)
    shadow_poly_shifted = [(x + shadow_offset_x, y + shadow_offset_y) for x, y in shadow_poly]
    shadow_draw.polygon(shadow_poly_shifted, fill=(0, 0, 0, 95)) 
    if shadow:
        shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(15 * pixel_ratio))

    canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
    if shadow:
        canvas = Image.alpha_composite(canvas, shadow_img)

    if depth_y > 0 or thickness > 1:
        # Se dibuja al triple de tamaño y se reduce: bordes suaves, sin serrucho.
        ss = 3
        layer = Image.new('RGBA', (canvas_w * ss, canvas_h * ss), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        S = lambda *pts: [(x * ss, y * ss) for x, y in pts]
        if not rtl:
            _draw_band(draw, *S(TL, BL, BL_spine, TL_spine), spine_front, spine_back, rounded=hard)
            if depth_y > 0:
                _draw_top(draw, *S(TL, TR, TR_pages, TL_spine), pixel_ratio * ss, hard, board_col, far_end=1,
                          spine_cols=(spine_front, spine_back), fore_drop=h_proj * ss)
        else:
            _draw_band(draw, *S(TR, BR, BR_spine, TR_spine), spine_front, spine_back, rounded=hard)
            if depth_y > 0:
                _draw_top(draw, *S(TL, TR, TR_spine, TL_pages), pixel_ratio * ss, hard, board_col, far_end=0,
                          spine_cols=(spine_front, spine_back), fore_drop=h_proj * ss)
        layer = layer.resize((canvas_w, canvas_h), Image.LANCZOS)
        canvas = Image.alpha_composite(canvas, layer)

    # Lomo con contenido (título y autor, o la portada estirada)
    if spine in ('title', 'stretch') and thickness > 2:
        sw = max(8, round(orig_w * SPINE_RATIO.get(binding, 0.08)))
        tex = _spine_texture(flat_rgb, sw, orig_h, spine, spine_front, title, author, rtl)
        tex = _shade_spine(tex, front_at_right=not rtl)
        if not rtl:
            quad = [TL_spine, TL, BL, BL_spine]
        else:
            quad = [TR, TR_spine, BR_spine, BR]
        src = [(0, 0), (sw, 0), (sw, orig_h), (0, orig_h)]
        k = _find_perspective_coefficients(quad, src)
        smask = Image.new('L', tex.size, 255).transform((canvas_w, canvas_h), Image.Transform.PERSPECTIVE, k, Image.BICUBIC)
        stex = tex.transform((canvas_w, canvas_h), Image.Transform.PERSPECTIVE, k, Image.BICUBIC)
        stex.putalpha(ImageChops.multiply(smask, stex.split()[3]))
        canvas = Image.alpha_composite(canvas, stex)

    canvas = Image.alpha_composite(canvas, cover_3d)

    # Recorte ajustado: se descarta el margen vacío y se deja solo un pequeño
    # aire alrededor del libro y su sombra.
    alpha = canvas.split()[3].point(lambda a: 255 if a > 6 else 0)
    bbox = alpha.getbbox()
    if bbox:
        pad = round((8 if shadow else 1) * pixel_ratio)
        bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                min(canvas_w, bbox[2] + pad), min(canvas_h, bbox[3] + pad))
        canvas = canvas.crop(bbox)

    # Calibre guarda siempre las portadas como JPEG (cover.jpg), que no admite
    # transparencia: lo transparente termina en blanco. Por eso se rellena el
    # fondo con un color sólido (por defecto, el de la cuadrícula de portadas).
    if background is not None:
        bg = Image.new('RGBA', canvas.size, tuple(background[:3]) + (255,))
        canvas = Image.alpha_composite(bg, canvas).convert('RGB')

    buf = BytesIO()
    canvas.save(buf, format='PNG')
    return buf.getvalue()
