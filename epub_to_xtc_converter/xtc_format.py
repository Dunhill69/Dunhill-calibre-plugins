# -*- coding: utf-8 -*-
"""
Escritura del formato XTC / XTCH (lector Xteink X4 y firmware CrossPoint).

Puro Python, sin dependencias, para que pueda usarse tanto dentro de calibre
como fuera (pruebas).

Estructura del archivo:
    Cabecera (56 bytes)
    Metadatos (256 bytes)
    Capítulos (96 bytes c/u)
    Tabla de páginas (16 bytes c/u)
    Páginas XTG (1 bit) o XTH (2 bits, 4 grises)

XTC  + páginas XTG -> blanco y negro   (extensión .xtc)
XTCH + páginas XTH -> 4 tonos de gris  (extensión .xtch)
"""

import struct
import time

XTC_MAGIC = 0x00435458   # "XTC\0"
XTCH_MAGIC = 0x48435458  # "XTCH"
XTG_MAGIC = 0x00475458   # "XTG\0"
XTH_MAGIC = 0x00485458   # "XTH\0"

HEADER_SIZE = 56
METADATA_SIZE = 256
CHAPTER_SIZE = 96
INDEX_ENTRY_SIZE = 16
PAGE_HEADER_SIZE = 22

BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))

# Tabla para empaquetar 8 bytes con valores 0/1 en un byte (MSB primero)
_PACK8 = {}
for _v in range(256):
    _PACK8[bytes((_v >> (7 - _i)) & 1 for _i in range(8))] = _v
del _v


def _pack_bits(bits):
    """bits: bytes con valores 0/1, longitud múltiplo de 8 -> bytes empaquetados."""
    p = _PACK8
    return bytes([p[bits[i:i + 8]] for i in range(0, len(bits), 8)])


def _checksum(data):
    return sum(data) & 0xFFFFFFFFFFFFFFFF


def _page(magic, width, height, bitmap):
    return struct.pack('<IHHBBIQ', magic, width, height, 0, 0, len(bitmap), _checksum(bitmap)) + bitmap


def _table(func):
    return bytes(func(v) for v in range(256))


class PageEncoder:
    """Convierte una página en escala de grises (bytes, 1 byte por píxel,
    fila por fila) en una página XTG o XTH lista para el contenedor."""

    def __init__(self, width, height, grayscale=True, threshold=128, levels=(80, 160, 240), dither=False):
        self.width = width
        self.height = height
        self.grayscale = grayscale
        self.dither = dither
        if dither:
            self._init_dither()
        elif grayscale:
            t1, t2, t3 = levels

            def stored(v):
                # nivel: 0 negro, 1 gris oscuro, 2 gris claro, 3 blanco
                q = 0 if v < t1 else 1 if v < t2 else 2 if v < t3 else 3
                # valor que espera el lector: blanco 0, gris oscuro 1, gris claro 2, negro 3
                return (3, 1, 2, 0)[q]
            self._hi = _table(lambda v: stored(v) >> 1)
            self._lo = _table(lambda v: stored(v) & 1)
        else:
            # XTG: 1 = blanco, 0 = negro
            self._bw = _table(lambda v: 1 if v >= threshold else 0)

    def _init_dither(self):
        # Tramado ordenado (Bayer 4x4): rápido con bytes.translate y se ve bien en e-ink
        self._dtabs = []
        for row in BAYER4:
            trow = []
            for b in row:
                t = (b + 0.5) / 16.0
                if self.grayscale:
                    def stored(v, t=t):
                        q = min(3, int(v * 3 / 255.0 + t))
                        return (3, 1, 2, 0)[q]
                    trow.append((_table(lambda v: stored(v) >> 1), _table(lambda v: stored(v) & 1)))
                else:
                    trow.append((_table(lambda v, t=t: 1 if v / 255.0 >= t else 0),))
            self._dtabs.append(trow)

    def _dithered(self, gray):
        """Devuelve una tupla de planos (bytes 0/1 por píxel) ya tramados."""
        w, h = self.width, self.height
        nplanes = len(self._dtabs[0][0])
        outs = [bytearray(w * h) for _ in range(nplanes)]
        for y in range(h):
            trow = self._dtabs[y & 3]
            base = y * w
            row = gray[base:base + w]
            for px in range(min(4, w)):
                seg = row[px::4]
                tabs = trow[px]
                for k in range(nplanes):
                    outs[k][base + px:base + w:4] = seg.translate(tabs[k])
        return [bytes(o) for o in outs]

    @staticmethod
    def quantize_levels(levels=(80, 160, 240)):
        """Tabla gris -> gris representable (0, 85, 170, 255), útil para vistas previas."""
        t1, t2, t3 = levels
        return _table(lambda v: 0 if v < t1 else 85 if v < t2 else 170 if v < t3 else 255)

    def encode(self, gray):
        w, h = self.width, self.height
        if len(gray) != w * h:
            raise ValueError('Page size mismatch: %d bytes for %dx%d' % (len(gray), w, h))
        if self.grayscale:
            return self._encode_xth(bytes(gray))
        return self._encode_xtg(bytes(gray))

    def _encode_xtg(self, gray):
        w, h = self.width, self.height
        bits = self._dithered(gray)[0] if self.dither else gray.translate(self._bw)
        if w % 8:
            pad = b'\x01' * (8 - w % 8)
            bits = b''.join(bits[y * w:(y + 1) * w] + pad for y in range(h))
        return _page(XTG_MAGIC, w, h, _pack_bits(bits))

    def _encode_xth(self, gray):
        w, h = self.width, self.height
        pad = b'\x00' * ((8 - h % 8) % 8)
        planes = []
        if self.dither:
            planes_vals = self._dithered(gray)
        else:
            planes_vals = [gray.translate(self._hi), gray.translate(self._lo)]
        for vals in planes_vals:
            # columnas de derecha a izquierda, 8 píxeles verticales por byte
            cols = b''.join(vals[x::w] + pad for x in range(w - 1, -1, -1))
            planes.append(_pack_bits(cols))
        return _page(XTH_MAGIC, w, h, planes[0] + planes[1])


def _fixed(text, size):
    """Texto UTF-8 terminado en cero, recortado sin partir caracteres."""
    raw = (text or '').encode('utf-8')
    if len(raw) > size - 1:
        raw = raw[:size - 1]
        while raw:
            try:
                raw.decode('utf-8')
                break
            except UnicodeDecodeError:
                raw = raw[:-1]
    return raw + b'\x00' * (size - len(raw))


class XTCWriter:
    """Arma el contenedor. Las páginas se van guardando en un archivo temporal
    (`pages_file`) para no tener todo el libro en memoria."""

    def __init__(self, width, height, grayscale=True):
        self.width = width
        self.height = height
        self.grayscale = grayscale
        self.sizes = []

    def add_page(self, page_bytes, pages_file):
        pages_file.write(page_bytes)
        self.sizes.append(len(page_bytes))

    def write(self, out, pages_file_path, title='', author='', publisher='', language='',
              chapters=(), cover_page=None, create_time=None):
        """chapters: lista de (nombre, primera_página, última_página), 0-based."""
        n = len(self.sizes)
        if not n:
            raise ValueError('No pages')
        if n > 0xFFFF:
            raise ValueError('Too many pages (%d)' % n)
        chapters = [c for c in chapters if 0 <= c[1] < n]

        metadata_offset = HEADER_SIZE
        chapter_offset = metadata_offset + METADATA_SIZE
        index_offset = chapter_offset + CHAPTER_SIZE * len(chapters)
        data_offset = index_offset + INDEX_ENTRY_SIZE * n

        out.write(struct.pack(
            '<IBBHBBBBIQQQQII',
            XTCH_MAGIC if self.grayscale else XTC_MAGIC,
            1, 0,                       # versión 1.0
            n,
            0,                          # dirección de lectura: izquierda a derecha
            1,                          # tiene metadatos
            0,                          # sin miniaturas
            1 if chapters else 0,
            0,                          # página actual
            metadata_offset, index_offset, data_offset,
            0,                          # miniaturas
            chapter_offset if chapters else 0,
            0))

        out.write(_fixed(title, 128))
        out.write(_fixed(author, 64))
        out.write(_fixed(publisher, 32))
        out.write(_fixed(language, 16))
        out.write(struct.pack('<IHH', int(create_time if create_time is not None else time.time()) & 0xFFFFFFFF,
                              0xFFFF if cover_page is None else cover_page, len(chapters)))
        out.write(b'\x00' * 8)

        for name, start, end in chapters:
            end = max(start, min(end, n - 1))
            # En el archivo las páginas de los capítulos van numeradas desde 1
            out.write(_fixed(name, 80) + struct.pack('<HH', start + 1, end + 1) + b'\x00' * 12)

        offset = data_offset
        for size in self.sizes:
            out.write(struct.pack('<QIHH', offset, size, self.width, self.height))
            offset += size

        with open(pages_file_path, 'rb') as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)


def chapters_from_outline(entries, page_count):
    """entries: lista de (título, página 1-based) en el orden del índice.
    Devuelve (nombre, inicio, fin) 0-based, ordenados por página.
    Si varias entradas caen en la misma página se deja solo la primera
    (normalmente el capítulo y no sus subtítulos)."""
    items = []
    seen = set()
    for title, page in entries:
        title = ' '.join((title or '').split())
        if not title or page is None:
            continue
        p = int(page) - 1
        if not (0 <= p < page_count) or p in seen:
            continue
        seen.add(p)
        items.append((title, p))
    items.sort(key=lambda x: x[1])
    ans = []
    for i, (title, start) in enumerate(items):
        nxt = page_count
        for _, s in items[i + 1:]:
            if s > start:
                nxt = s
                break
        ans.append((title, start, max(start, nxt - 1)))
    return ans


# ---------------------------------------------------------------- lectura

# byte -> 8 bytes con el valor de cada bit (MSB primero), escalado
def _unpack_table(one):
    return [bytes(one if (v >> (7 - i)) & 1 else 0 for i in range(8)) for v in range(256)]


_UNPACK_255 = _unpack_table(255)
_UNPACK_2 = _unpack_table(2)
_UNPACK_1 = _unpack_table(1)
# valor guardado en XTH -> gris (0 blanco, 1 gris oscuro, 2 gris claro, 3 negro)
_XTH_GRAY = bytes([255, 85, 170, 0] + [0] * 252)


class NotXTC(ValueError):
    pass


class XTCReader:
    """Lee un XTC/XTCH sin cargar todo el archivo en memoria."""

    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            head = f.read(HEADER_SIZE)
            if len(head) < 48:
                raise NotXTC('File too small')
            magic = struct.unpack('<I', head[:4])[0]
            if magic not in (XTC_MAGIC, XTCH_MAGIC):
                raise NotXTC('Not an XTC file')
            self.grayscale = magic == XTCH_MAGIC
            (self.page_count,) = struct.unpack('<H', head[6:8])
            has_meta, has_chapters = head[9], head[11]
            meta_off, index_off, data_off = struct.unpack('<QQQ', head[16:40])
            chap_off = struct.unpack('<I', head[48:52])[0] if len(head) >= 52 and index_off >= HEADER_SIZE else 0
            self.title = self.author = self.publisher = self.language = ''

            def text(raw):
                return raw.split(b'\x00', 1)[0].decode('utf-8', 'replace')
            if has_meta and meta_off:
                f.seek(meta_off)
                m = f.read(METADATA_SIZE)
                self.title, self.author = text(m[:128]), text(m[128:192])
                self.publisher, self.language = text(m[192:224]), text(m[224:240])
            f.seek(index_off)
            table = f.read(INDEX_ENTRY_SIZE * self.page_count)
            self.pages = [struct.unpack('<QIHH', table[i * 16:i * 16 + 16]) for i in range(self.page_count)]
            self.chapters = []
            if has_chapters and chap_off:
                end = index_off if index_off > chap_off else data_off
                f.seek(chap_off)
                raw = f.read(max(0, end - chap_off))
                for i in range(len(raw) // CHAPTER_SIZE):
                    c = raw[i * CHAPTER_SIZE:(i + 1) * CHAPTER_SIZE]
                    name = text(c[:80])
                    s, e = struct.unpack('<HH', c[80:84])
                    if not name and not s and not e:
                        break
                    s, e = max(0, s - 1), max(0, e - 1)
                    if s < self.page_count:
                        self.chapters.append((name, s, min(e, self.page_count - 1)))
        if not self.pages:
            raise NotXTC('No pages')
        self.width, self.height = self.pages[0][2], self.pages[0][3]

    def page(self, index):
        """Devuelve (ancho, alto, bytes en gris fila por fila)."""
        off, size, w, h = self.pages[index]
        with open(self.path, 'rb') as f:
            f.seek(off)
            data = f.read(size)
        magic, pw, ph = struct.unpack('<IHH', data[:8])
        bitmap = data[PAGE_HEADER_SIZE:]
        if magic == XTG_MAGIC:
            rb = (pw + 7) // 8
            un = _UNPACK_255
            rows = []
            for y in range(ph):
                row = b''.join([un[b] for b in bitmap[y * rb:(y + 1) * rb]])
                rows.append(row[:pw])
            return pw, ph, b''.join(rows)
        if magic == XTH_MAGIC:
            cb = (ph + 7) // 8
            plane = pw * cb
            hi = b''.join([_UNPACK_2[b] for b in bitmap[:plane]])
            lo = b''.join([_UNPACK_1[b] for b in bitmap[plane:2 * plane]])
            vals = bytes(map(int.__add__, hi, lo)).translate(_XTH_GRAY)
            hp = cb * 8
            # columnas guardadas de derecha a izquierda: fila y = vals[y::hp] invertida
            return pw, ph, b''.join(vals[y::hp][::-1] for y in range(ph))
        raise NotXTC('Unknown page format')
