#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

'''
Book work: create, replace or remove the synopsis page.

The page is always saved as "synopsis_page.xhtml" and the image as
"synopsis_page_cover.jpg", so the plugin can find them again to replace or
remove them without touching anything else in the book. Files created by
the earlier Spanish-named builds ("hoja_sinopsis*") are recognized too.
'''

import posixpath

try:
    load_translations()
except NameError:
    pass

HTML_BASENAME = 'synopsis_page.xhtml'
IMG_BASENAME = 'synopsis_page_cover'
LEGACY_HTML = ('hoja_sinopsis.xhtml',)
LEGACY_IMG = ('hoja_sinopsis_portada',)


class SynopsisError(Exception):
    pass


# --------------------------------------------------------------------------
# Container helpers
# --------------------------------------------------------------------------

def _existing_items(container):
    html, imgs = [], []
    for name in list(container.name_path_map):
        base = posixpath.basename(name)
        if base == HTML_BASENAME or base in LEGACY_HTML:
            html.append(name)
        elif base.startswith((IMG_BASENAME,) + LEGACY_IMG):
            imgs.append(name)
    return html, imgs


def _remove_from_toc(container, names):
    try:
        from calibre.ebooks.oeb.polish.toc import get_toc, commit_toc
        toc = get_toc(container)
    except Exception:
        return
    changed = []

    def walk(node):
        for child in list(node.children):
            if child.dest in names:
                node.children.remove(child)
                changed.append(child)
            else:
                walk(child)
    walk(toc)
    if changed:
        try:
            commit_toc(container, toc)
        except Exception:
            pass


def _remove_existing(container):
    html, imgs = _existing_items(container)
    if html:
        _remove_from_toc(container, set(html))
    for name in html + imgs:
        container.remove_item(name)
    return bool(html or imgs)


def _looks_like_cover(container, name):
    low = posixpath.basename(name).lower()
    if 'cover' in low or 'portada' in low or 'titlepage' in low:
        return True
    # A page holding only an image (or svg) and almost no text
    try:
        root = container.parsed(name)
        text = ''.join(root.itertext()).strip()
        imgs = root.xpath('//*[local-name()="img" or local-name()="image"]')
        return bool(imgs) and len(text) < 30
    except Exception:
        return False


def _insert_index(container, position):
    spine = [name for name, linear in container.spine_names]
    if position == 'start' or not spine:
        return 0, spine
    if position == 'end':
        return len(spine), spine
    # after_cover
    try:
        from calibre.ebooks.oeb.polish.cover import find_cover_page
        cover_page = find_cover_page(container)
    except Exception:
        cover_page = None
    if cover_page and cover_page in spine:
        return spine.index(cover_page) + 1, spine
    if _looks_like_cover(container, spine[0]):
        return 1, spine
    return 0, spine


def _text_dir(container, spine, idx):
    # The folder holding the book text (e.g. OEBPS/Text)
    for i in (idx, idx - 1, 0):
        if 0 <= i < len(spine):
            return posixpath.dirname(spine[i])
    return posixpath.dirname(container.opf_name)


def _image_dir(container, fallback):
    for name, mt in container.mime_map.items():
        if mt and mt.startswith('image/'):
            return posixpath.dirname(name)
    return fallback


def _join(d, base):
    return posixpath.join(d, base) if d else base


def _shrink_cover(data, max_height):
    try:
        from calibre.utils.img import image_from_data, scale_image
        img = image_from_data(data)
        if img.height() > max_height:
            w, h, data = scale_image(data, height=max_height,
                                     width=int(img.width() * max_height / img.height()),
                                     compression_quality=88)
    except Exception:
        pass
    return data


# --------------------------------------------------------------------------
# Page HTML
# --------------------------------------------------------------------------

CSS = '''
body.synopsis-page { margin: 0; padding: 0 0.5em; }
div.sp-cover { text-align: center; margin: 1em 0 1em 0; page-break-inside: avoid; text-indent: 0; }
div.sp-cover img { width: %(width)d%%; max-width: %(width)d%%; height: auto; max-height: 55vh; %(img_style)s }
div.sp-cover.sp-left { float: left; width: %(width)d%%; margin: 0.25em 1em 0.5em 0; }
div.sp-cover.sp-right { float: right; width: %(width)d%%; margin: 0.25em 0 0.5em 1em; }
div.sp-cover.sp-left img, div.sp-cover.sp-right img { width: 100%%; max-width: 100%%; max-height: none; }
div.sp-end { clear: both; height: 0; }
h1.sp-title { text-align: center; font-size: 1.3em; margin: 0.6em 0 0.1em 0; text-indent: 0; }
p.sp-author { text-align: center; font-style: italic; margin: 0 0 0.2em 0; text-indent: 0; }
p.sp-series { text-align: center; font-size: 0.9em; margin: 0 0 0.2em 0; text-indent: 0; }
h2.sp-heading { text-align: center; font-size: 1.1em; font-variant: small-caps; letter-spacing: 0.08em; margin: 1em 0 0.6em 0; text-indent: 0; }
div.sp-text { text-align: %(align)s; }
div.sp-text p { margin: 0 0 0.35em 0; text-indent: %(indent)s; }
'''

IMG_STYLES = {
    'none': '',
    'line': 'border: 1px solid #555;',
    'shadow': 'border: 1px solid #bbb; box-shadow: 0.25em 0.25em 0.6em rgba(0,0,0,0.35);',
}

COVER_CLASSES = {
    'top': 'sp-cover',
    'left': 'sp-cover sp-left',
    'right': 'sp-cover sp-right',
    'bottom': 'sp-cover',
}


def place_floating_cover(root, after_par):
    '''Move the floating cover so it sits after paragraph N of the
    synopsis (0 = at the start of the text).'''
    def has_class(e, c):
        return c in (e.get('class') or '').split()
    text = [e for e in root.iter('{*}div') if has_class(e, 'sp-text')]
    if not text or after_par <= 0:
        return
    text = text[0]
    cover = [e for e in text.iter('{*}div') if has_class(e, 'sp-cover')]
    if not cover:
        return
    cover = cover[0]
    pars = list(text.iter('{*}p'))
    if not pars:
        return
    target = pars[min(after_par, len(pars)) - 1]
    cover.getparent().remove(cover)
    target.addnext(cover)


def _lang(mi):
    try:
        from calibre.utils.localization import lang_as_iso639_1
        for code in (mi.languages or []):
            iso = lang_as_iso639_1(code)
            if iso:
                return iso
    except Exception:
        pass
    return 'en'


def build_html(mi, img_href, prefs):
    from calibre import prepare_string_for_xml as esc
    from calibre.ebooks.metadata import authors_to_string, fmt_sidx
    from calibre.library.comments import comments_to_html

    css = CSS % dict(
        width=max(10, min(100, int(prefs['cover_width']))),
        img_style=IMG_STYLES.get(prefs['cover_style'], ''),
        align='justify' if prefs['justify'] else 'left',
        indent='1.5em' if prefs['indent'] else '0',
    )
    pos = prefs.get('cover_position', 'top')
    if pos not in COVER_CLASSES:
        pos = 'top'
    img_div = ''
    if img_href:
        img_div = '<div class="%s"><img src="%s" alt="%s"/></div>' % (
            COVER_CLASSES[pos], esc(img_href, True), esc(_('Cover'), True))
    body = []
    if img_div and pos == 'top':
        body.append(img_div)
    if prefs['show_title'] and mi.title:
        body.append('<h1 class="sp-title">%s</h1>' % esc(mi.title))
    if prefs['show_authors'] and mi.authors:
        body.append('<p class="sp-author">%s</p>' % esc(authors_to_string(mi.authors)))
    if prefs['show_series'] and mi.series:
        body.append('<p class="sp-series">%s %s</p>' % (
            esc(mi.series), esc(fmt_sidx(mi.series_index or 1))))
    if prefs['show_heading'] and prefs['heading_text'].strip():
        body.append('<h2 class="sp-heading">%s</h2>' % esc(prefs['heading_text'].strip()))
    floating = img_div if pos in ('left', 'right') else ''
    body.append('<div class="sp-text">%s%s<div class="sp-end"></div></div>' % (
        floating, comments_to_html(mi.comments)))
    if img_div and pos == 'bottom':
        body.append(img_div)

    return '''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}" lang="{lang}">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
<title>{title}</title>
<style type="text/css">{css}</style>
</head>
<body class="synopsis-page">
{body}
</body>
</html>
'''.format(lang=_lang(mi), title=esc(prefs['toc_title'] or _('Synopsis')),
           css=css, body='\n'.join(body))


# --------------------------------------------------------------------------
# Public operations
# --------------------------------------------------------------------------

def _open(path, log):
    from calibre.ebooks.oeb.polish.container import get_container
    container = get_container(path, log=log, tweak_mode=True)
    if container.book_type not in ('epub', 'azw3'):
        raise SynopsisError(_('the file is neither EPUB nor AZW3'))
    return container


def _toc_pos(toc, spine, idx):
    # Put the entry before the first entry that points further on
    order = {name: i for i, name in enumerate(spine)}
    for i, child in enumerate(toc.children):
        if order.get(child.dest, -1) >= idx:
            return i
    return len(toc.children)


def add_synopsis(path, mi, cover_data, prefs, log):
    '''Add (or replace) the page. Returns True if an older one was replaced.'''
    container = _open(path, log)
    replaced = _remove_existing(container)

    idx, spine = _insert_index(container, prefs['position'])
    tdir = _text_dir(container, spine, idx)
    html_name = _join(tdir, HTML_BASENAME)

    img_href = None
    if cover_data:
        cover_data = _shrink_cover(cover_data, int(prefs['max_cover_height']))
        img_name = _join(_image_dir(container, tdir), IMG_BASENAME + '.jpg')
        container.add_file(img_name, cover_data)
        img_href = container.name_to_href(img_name, html_name)

    raw = build_html(mi, img_href, prefs).encode('utf-8')
    container.add_file(html_name, raw, spine_index=idx)
    # Run it through calibre's parser so the result is valid XHTML
    root = container.parsed(html_name)
    if prefs.get('cover_position') in ('left', 'right'):
        place_floating_cover(root, int(prefs.get('cover_after_par', 0)))
    container.dirty(html_name)

    if prefs['add_to_toc']:
        try:
            from calibre.ebooks.oeb.polish.toc import get_toc, commit_toc
            toc = get_toc(container)
            node = toc.add(prefs['toc_title'] or _('Synopsis'), html_name)
            toc.children.remove(node)
            toc.children.insert(0 if idx <= 1 else _toc_pos(toc, spine, idx), node)
            commit_toc(container, toc)
        except Exception:
            log.exception('Could not add the page to the Table of Contents')

    container.commit()
    return replaced


def remove_synopsis(path, log):
    '''Remove the page. Returns True if there was one.'''
    container = _open(path, log)
    if not _remove_existing(container):
        return False
    container.commit()
    return True
