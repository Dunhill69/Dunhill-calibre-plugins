# -*- coding: utf-8 -*-
"""
Trabajo en segundo plano (proceso de trabajo de calibre).

Para cada libro:
  1. calibre convierte el libro a PDF con el tamaño físico de la pantalla
     (mismo motor que usa calibre para "Convertir libros" -> PDF).
  2. pdftoppm (incluido con calibre) dibuja cada página en escala de grises
     con la resolución exacta del lector (480x800 en el X4).
  3. Cada página se pasa a 1 bit (XTG) o 4 grises (XTH) y se arma el
     contenedor XTC/XTCH con título, autor y capítulos (del índice del libro).
"""

import glob
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

try:
    from calibre_plugins.epub_to_xtc_converter.xtc_format import (
        PageEncoder, XTCWriter, chapters_from_outline)
except ImportError:  # pruebas fuera de calibre
    from xtc_format import PageEncoder, XTCWriter, chapters_from_outline

iswindows = sys.platform.startswith('win')
CHUNK = 40  # páginas que se dibujan por cada llamada a pdftoppm

DEFAULTS = {
    'grayscale': True,      # True: 4 grises (.xtch) / False: blanco y negro (.xtc)
    'width': 480,
    'height': 800,
    'dpi': 220,             # densidad real de la pantalla del X4
    'font_size': 13,        # tamaño de letra base (px CSS), probado en el X4
    'margin_lr': 8.0,       # márgenes laterales (pt)
    'margin_tb': 10.0,      # márgenes superior e inferior (pt)
    'hyphenate': True,
    'page_numbers': False,
    'dither': False,
    'threshold': 128,       # corte negro/blanco en modo 1 bit
    'toc_levels': 2,        # niveles del índice que se usan como capítulos
    'remove_spacing': False,  # quitar espacio entre párrafos
    'justify': True,        # justificar el texto
    'xtch_as_xtc': False,   # guardar los archivos de 4 grises con extensión .xtc
}


def page_geometry(settings):
    """Tamaño de la página del PDF en puntos para que, a la densidad del
    lector, ocupe exactamente width x height píxeles."""
    dpi = float(settings['dpi'])
    return settings['width'] * 72.0 / dpi, settings['height'] * 72.0 / dpi


# ---------------------------------------------------------------- poppler

def _tools():
    pdfinfo, pdftoppm, pdftohtml = 'pdfinfo', 'pdftoppm', 'pdftohtml'
    try:
        from calibre.ebooks.metadata.pdf import get_tools
        pdfinfo, pdftoppm = get_tools()
        from calibre.ebooks.pdf.pdftohtml import PDFTOHTML
        pdftohtml = PDFTOHTML
    except Exception:
        if iswindows:
            pdfinfo, pdftoppm, pdftohtml = (x + '.exe' for x in (pdfinfo, pdftoppm, pdftohtml))
    return pdfinfo, pdftoppm, pdftohtml


def _run(cmd, cwd=None):
    kw = {}
    if iswindows:
        kw['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    out, err = p.communicate()
    if p.returncode != 0:
        raise RuntimeError('%s failed (%s): %s' % (os.path.basename(cmd[0]), p.returncode,
                                                   err.decode('utf-8', 'replace')[-2000:]))
    return out


def pdf_page_count(pdf, tools=None):
    pdfinfo = (tools or _tools())[0]
    out = _run([pdfinfo, os.path.basename(pdf)], cwd=os.path.dirname(pdf))
    m = re.search(rb'^Pages:\s*(\d+)', out, re.MULTILINE)
    if not m:
        raise RuntimeError('Could not read the number of pages of the PDF')
    return int(m.group(1))


def pdf_outline(pdf, max_depth=2, tools=None):
    """Índice del PDF como lista de (título, página 1-based)."""
    pdftohtml = (tools or _tools())[2]
    try:
        out = _run([pdftohtml, '-xml', '-i', '-q', '-nodrm', '-stdout', '-f', '1', '-l', '1', os.path.basename(pdf)],
                   cwd=os.path.dirname(pdf))
    except Exception:
        traceback.print_exc()
        return []
    text = out.decode('utf-8', 'replace')
    start = text.find('<outline>')
    if start < 0:
        return []
    ans = []
    depth = 0
    for m in re.finditer(r'<outline>|</outline>|<item(?:\s+page="(\d+)")?\s*>(.*?)</item>', text[start:], re.DOTALL):
        tok = m.group(0)
        if tok == '<outline>':
            depth += 1
        elif tok == '</outline>':
            depth -= 1
            if depth <= 0:
                break
        elif m.group(1) and depth <= max_depth:
            title = html.unescape(re.sub(r'<[^>]+>', '', m.group(2)))
            ans.append((title, int(m.group(1))))
    return ans


def read_pgm(path):
    with open(path, 'rb') as f:
        data = f.read()
    # Cabecera P5: "P5 <ancho> <alto> <máx>" + un espacio + datos
    fields, pos = [], 0
    while len(fields) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b'#':
            pos = data.index(b'\n', pos) + 1
            continue
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        fields.append(data[pos:end])
        pos = end
    if fields[0] != b'P5':
        raise ValueError('Not a binary PGM file')
    w, h, maxval = int(fields[1]), int(fields[2]), int(fields[3])
    if maxval != 255:
        raise ValueError('Unsupported PGM depth')
    return w, h, data[pos + 1:pos + 1 + w * h]


def render_pages(pdf, width, height, tmpdir, tools=None, first=1, last=None, chunk=CHUNK):
    """Genera (número de página, bytes en gris) de cada página del PDF."""
    pdftoppm = (tools or _tools())[1]
    if last is None:
        last = pdf_page_count(pdf, tools)
    page = first
    while page <= last:
        end = min(last, page + chunk - 1)
        for old in glob.glob(os.path.join(tmpdir, 'pg-*.pgm')):
            os.remove(old)
        _run([pdftoppm, '-gray', '-scale-to-x', str(width), '-scale-to-y', str(height),
              '-f', str(page), '-l', str(end), os.path.abspath(pdf), os.path.join(tmpdir, 'pg')])
        files = []
        for p in glob.glob(os.path.join(tmpdir, 'pg-*.pgm')):
            m = re.search(r'pg-0*(\d+)\.pgm$', p)
            if m:
                files.append((int(m.group(1)), p))
        files.sort()
        if len(files) != end - page + 1:
            raise RuntimeError('pdftoppm rendered %d pages instead of %d' % (len(files), end - page + 1))
        for num, p in files:
            w, h, gray = read_pgm(p)
            if (w, h) != (width, height):
                raise RuntimeError('Page %d has size %dx%d instead of %dx%d' % (num, w, h, width, height))
            os.remove(p)
            yield num, gray
        page = end + 1


# ---------------------------------------------------------------- calibre

def conversion_recommendations(settings):
    from calibre.customize.conversion import OptionRecommendation
    H = OptionRecommendation.HIGH
    wpt, hpt = page_geometry(settings)
    lr = float(settings['margin_lr'])
    tb = float(settings['margin_tb'])
    bottom = max(tb, 16.0) if settings['page_numbers'] else tb
    fs = int(settings['font_size'])
    recs = [
        ('custom_size', '%.3fx%.3f' % (wpt, hpt), H),
        ('unit', 'point', H),
        ('use_profile_size', False, H),
        ('pdf_use_document_margins', False, H),
        ('pdf_page_margin_left', lr, H), ('margin_left', lr, H),
        ('pdf_page_margin_right', lr, H), ('margin_right', lr, H),
        ('pdf_page_margin_top', tb, H), ('margin_top', tb, H),
        ('pdf_page_margin_bottom', bottom, H), ('margin_bottom', bottom, H),
        ('pdf_default_font_size', fs, H),
        # Reescala todas las letras del libro, aunque su CSS use tamaños fijos (pt)
        ('base_font_size', round(fs * 0.75, 2), H),
        ('pdf_mono_font_size', max(8, fs - 2), H),
        ('pdf_hyphenate', bool(settings['hyphenate']), H),
        ('pdf_page_numbers', bool(settings['page_numbers']), H),
        ('pdf_add_toc', False, H),
        ('preserve_cover_aspect_ratio', True, H),
    ]
    recs.append(('change_justification', 'justify' if settings.get('justify', True) else 'original', H))
    if settings.get('remove_spacing'):
        recs.append(('remove_paragraph_spacing', True, H))
    return recs


def convert_one(book, settings, workdir, progress, log=print, tools=None):
    """book: dict con input, output, title, authors, publisher, language.
    progress(fracción 0-1, mensaje)."""
    from calibre.gui2.convert.gui_conversion import gui_convert
    from calibre.utils.logging import Log

    tools = tools or _tools()
    pdf = os.path.join(workdir, 'book.pdf')
    log('Converting %s to PDF (%s)' % (book['title'], ' '.join(map(str, page_geometry(settings)))))

    def conv_progress(frac, msg=''):
        try:
            progress(0.5 * float(frac), msg)
        except Exception:
            pass

    gui_convert(book['input'], pdf, conversion_recommendations(settings), notification=conv_progress, log=Log())
    if not os.path.exists(pdf):
        raise RuntimeError('calibre did not produce the PDF')
    return pdf_to_xtc(pdf, book, settings, workdir, lambda f, m='': progress(0.5 + 0.5 * f, m), log, tools)


def pdf_to_xtc(pdf, book, settings, workdir, progress, log=print, tools=None):
    tools = tools or _tools()
    w, h, gs = int(settings['width']), int(settings['height']), bool(settings['grayscale'])
    count = pdf_page_count(pdf, tools)
    if count > 0xFFFF:
        raise RuntimeError('Too many pages: %d' % count)
    log('PDF has %d pages' % count)
    outline = pdf_outline(pdf, int(settings.get('toc_levels', 2)), tools)
    chapters = chapters_from_outline(outline, count)
    log('Chapters: %d' % len(chapters))

    enc = PageEncoder(w, h, gs, threshold=int(settings.get('threshold', 128)),
                      dither=bool(settings.get('dither')))
    writer = XTCWriter(w, h, gs)
    pages_path = os.path.join(workdir, 'pages.bin')
    render_dir = os.path.join(workdir, 'render')
    os.makedirs(render_dir, exist_ok=True)
    blank = 0
    min_ink = max(1, (w * h) // 2000)
    with open(pages_path, 'wb') as pf:
        for num, gray in render_pages(pdf, w, h, render_dir, tools, 1, count):
            if len(gray) - gray.count(b'\xff') < min_ink:
                blank += 1
            writer.add_page(enc.encode(gray), pf)
            if num % 5 == 0 or num == count:
                progress(num / float(count), 'Page %d / %d' % (num, count))
    tmp_out = book['output'] + '.part'
    with open(tmp_out, 'wb') as out:
        writer.write(out, pages_path, title=book.get('title', ''), author=book.get('authors', ''),
                     publisher=book.get('publisher', ''), language=book.get('language', ''),
                     chapters=chapters)
    os.replace(tmp_out, book['output'])
    os.remove(pages_path)
    log('Blank pages: %d' % blank)
    return count, len(chapters), blank


def convert_books(books, settings, notification=lambda x, y: y):
    """Punto de entrada del trabajo 'arbitrary_n' de calibre."""
    s = dict(DEFAULTS)
    s.update(settings or {})
    tools = _tools()
    results = []
    n = len(books)
    for i, book in enumerate(books):
        def progress(frac, msg='', i=i):
            notification((i + min(max(frac, 0.0), 1.0)) / n, msg)
        workdir = tempfile.mkdtemp(prefix='xtc_')
        res = {'book_id': book['book_id'], 'title': book['title'], 'output': book['output']}
        try:
            notification(i / float(n), book['title'])
            pages, chapters, blank = convert_one(book, s, workdir, progress, tools=tools)
            res.update(ok=True, pages=pages, chapters=chapters, blank=blank)
            # Casi todo en blanco: el texto no se dibujó (faltan fuentes, p. ej. calibre bajo Wine)
            if pages >= 3 and blank * 2 > pages:
                res['ok'] = False
                res['blank_book'] = True
            print('OK: %s (%d pages, %d chapters)' % (book['title'], pages, chapters))
        except Exception:
            tb = traceback.format_exc()
            print('ERROR: %s\n%s' % (book['title'], tb))
            res.update(ok=False, error=tb)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            sys.stdout.flush()
        results.append(res)
    notification(1.0, '')
    return results
