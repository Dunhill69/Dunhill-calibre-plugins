#!/usr/bin/env python
# Arma el EPUB o el TXT con los capítulos descargados.

import uuid
import zipfile
from xml.sax.saxutils import escape as _esc


def esc(text):
    try:
        from calibre.utils.cleantext import clean_xml_chars
        text = clean_xml_chars(text)
    except Exception:
        pass
    return _esc(text or '', {'"': '&quot;'})


CSS = '''body { font-family: serif; line-height: 1.5; margin: 0 4%; }
h1 { text-align: center; margin: 1.5em 0 1em; font-size: 1.4em; }
h2 { text-align: center; margin: 1em 0; font-size: 1.2em; }
p { text-indent: 1.2em; margin: 0 0 0.4em; text-align: justify; }
p.meta { text-indent: 0; text-align: center; font-style: italic; }
div.cover { text-align: center; height: 100%; }
div.cover img { max-width: 100%; max-height: 100%; }
'''


def xhtml(title, body):
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
            '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">\n'
            '<html xmlns="http://www.w3.org/1999/xhtml">\n<head>\n'
            '<title>%s</title>\n'
            '<link rel="stylesheet" type="text/css" href="style.css"/>\n'
            '</head>\n<body>\n%s\n</body>\n</html>\n') % (esc(title), body)


def paras_html(paras):
    return '\n'.join('<p>%s</p>' % esc(p) for p in paras)


def to_jpeg(data):
    """Pasa la portada a JPEG (el sitio a veces usa WebP)."""
    if not data:
        return None
    try:
        from calibre.utils.img import image_from_data, image_to_data
        return image_to_data(image_from_data(data), fmt='JPEG')
    except Exception:
        return data if data[:3] == b'\xff\xd8\xff' else None


def build_epub(path, info, chapters, cover=None, language='en'):
    """chapters: lista de (título, [párrafos])."""
    book_id = 'urn:uuid:%s' % uuid.uuid4()
    title = info['title']
    authors = info['authors']
    cover = to_jpeg(cover)

    manifest, spine, nav = [], [], []
    files = {}

    files['OEBPS/style.css'] = CSS
    manifest.append('<item id="css" href="style.css" media-type="text/css"/>')

    if cover:
        files['OEBPS/cover.jpg'] = cover
        manifest.append('<item id="cover-image" href="cover.jpg" media-type="image/jpeg"/>')
        files['OEBPS/titlepage.xhtml'] = xhtml(
            title, '<div class="cover"><img src="cover.jpg" alt="%s"/></div>' % esc(title))
        manifest.append('<item id="titlepage" href="titlepage.xhtml" '
                        'media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="titlepage" linear="yes"/>')

    info_body = ['<h1>%s</h1>' % esc(title),
                 '<p class="meta">%s</p>' % esc(' & '.join(authors))]
    if info.get('alternative'):
        info_body.append('<p class="meta">%s</p>' % esc(info['alternative']))
    extra = []
    if info.get('status'):
        extra.append('Estado: ' + info['status'])
    if info.get('tags'):
        extra.append('Etiquetas: ' + ', '.join(info['tags']))
    info_body += ['<p class="meta">%s</p>' % esc(x) for x in extra]
    if info.get('summary'):
        info_body.append('<h2>Sinopsis</h2>')
        info_body.append(paras_html(info['summary']))
    info_body.append('<p class="meta">Fuente: %s</p>' % esc(info['url']))
    files['OEBPS/info.xhtml'] = xhtml(title, '\n'.join(info_body))
    manifest.append('<item id="info" href="info.xhtml" media-type="application/xhtml+xml"/>')
    spine.append('<itemref idref="info"/>')
    nav.append((title, 'info.xhtml'))

    for i, (ch_title, paras) in enumerate(chapters, 1):
        name = 'chap_%04d.xhtml' % i
        body = '<h2>%s</h2>\n%s' % (esc(ch_title), paras_html(paras))
        files['OEBPS/' + name] = xhtml(ch_title, body)
        manifest.append('<item id="c%d" href="%s" media-type="application/xhtml+xml"/>'
                        % (i, name))
        spine.append('<itemref idref="c%d"/>' % i)
        nav.append((ch_title, name))

    manifest.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')

    md = ['<dc:title>%s</dc:title>' % esc(title)]
    md += ['<dc:creator opf:role="aut">%s</dc:creator>' % esc(a) for a in authors]
    md.append('<dc:language>%s</dc:language>' % language)
    md.append('<dc:identifier id="BookId">%s</dc:identifier>' % book_id)
    md.append('<dc:source>%s</dc:source>' % esc(info['url']))
    md.append('<dc:publisher>danmeinovel.com</dc:publisher>')
    if info.get('summary'):
        desc = ''.join('<p>%s</p>' % esc(p) for p in info['summary'])
        if info.get('alternative'):
            desc += '<p><i>Títulos alternativos:</i> %s</p>' % esc(info['alternative'])
        md.append('<dc:description>%s</dc:description>' % esc(desc))
    md += ['<dc:subject>%s</dc:subject>' % esc(t) for t in info.get('tags', [])]
    if cover:
        md.append('<meta name="cover" content="cover-image"/>')

    files['OEBPS/content.opf'] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
        'unique-identifier="BookId">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">\n%s\n</metadata>\n'
        '<manifest>\n%s\n</manifest>\n'
        '<spine toc="ncx">\n%s\n</spine>\n'
        '%s</package>\n') % (
            '\n'.join(md), '\n'.join(manifest), '\n'.join(spine),
            ('<guide><reference type="cover" title="Portada" href="titlepage.xhtml"/></guide>\n'
             if cover else ''))

    points = '\n'.join(
        '<navPoint id="n%d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
        '<content src="%s"/></navPoint>' % (i, i, esc(t), src)
        for i, (t, src) in enumerate(nav, 1))
    files['OEBPS/toc.ncx'] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        '<head><meta name="dtb:uid" content="%s"/></head>\n'
        '<docTitle><text>%s</text></docTitle>\n<navMap>\n%s\n</navMap>\n</ncx>\n'
    ) % (book_id, esc(title), points)

    container = ('<?xml version="1.0" encoding="utf-8"?>\n'
                 '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                 'media-type="application/oebps-package+xml"/></rootfiles></container>\n')

    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip',
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr('META-INF/container.xml', container, compress_type=zipfile.ZIP_DEFLATED)
        for name, data in files.items():
            if isinstance(data, str):
                data = data.encode('utf-8')
            zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return path


def build_txt(path, info, chapters):
    out = [info['title'], ' & '.join(info['authors'])]
    if info.get('alternative'):
        out.append(info['alternative'])
    if info.get('tags'):
        out.append('Etiquetas: ' + ', '.join(info['tags']))
    out.append('')
    if info.get('summary'):
        out += info['summary'] + ['']
    out += ['Fuente: ' + info['url'], '', '']
    for ch_title, paras in chapters:
        out += [ch_title, ''] + ['\n\n'.join(paras), '', '']
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    return path
