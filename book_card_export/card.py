#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

import math
import re
from html import escape

from qt.core import (
    QAbstractTextDocumentLayout, QApplication, QColor, QFont, QImage,
    QPainter, QPainterPath, QPalette,
    QRectF, Qt, QTextDocument, QUrl,
)

try:
    load_translations()
except NameError:
    pass

from calibre_plugins.book_card_export.config import (
    active_fields, emoji_map, prefs, tag_emoji_map,
)
from calibre_plugins.book_card_export import tgtext

THEMES = {
    'light': dict(bg='#ffffff', fg='#222222', label='#666666', value='#1a4fa0',
                  title='#111111', author='#444444', footer='#999999'),
    'dark': dict(bg='#1f1f23', fg='#e6e6e6', label='#a8a8a8', value='#7fb0ff',
                 title='#ffffff', author='#cfcfcf', footer='#777777'),
}


def current_theme():
    '''Theme colors, with the background chosen by the user.
    bg is None for a transparent background.'''
    theme = dict(THEMES.get(prefs['theme'], THEMES['light']))
    mode = prefs['background']
    if mode == 'custom':
        theme['bg'] = prefs['bg_color'] or theme['bg']
    elif mode == 'transparent':
        theme['bg'] = None
    return theme


def stars(value):
    try:
        v = float(value or 0) / 2.0
    except Exception:
        return ''
    if v <= 0:
        return ''
    full = int(v)
    return '★' * full + ('½' if v - full >= 0.5 else '')


def collect(db, book_id):
    '''db is the new_api Cache. Returns everything needed for the card.'''
    mi = db.get_metadata(book_id, get_cover=False)
    fm = db.field_metadata
    rows = []
    for key in active_fields(_legacy_db()):
        try:
            meta = fm[key]
        except Exception:
            continue
        dt = meta.get('datatype')
        try:
            name, val = mi.format_field(key)
        except Exception:
            name, val = meta.get('name') or key, None
        name = name or meta.get('name') or key
        if dt == 'rating':
            val = stars(mi.get(key))
        if val is None or val == '' or (dt == 'bool' and val is None):
            continue
        val = str(val)
        if dt == 'comments':
            html_val = val if '<' in val else escape(val).replace('\n', '<br>')
            text_val = tgtext.html_to_telegram(val)
        else:
            html_val = escape(val)
            text_val = val
        rows.append((key, name, html_val, text_val, dt))

    cover = db.cover(book_id, as_image=True)
    if cover is None or cover.isNull():
        cover = QImage(I('default_cover.png'))
    authors = ' & '.join(mi.authors or [])
    return dict(
        id=book_id, title=mi.title or _('Unknown'), authors=authors,
        rows=rows, comments_html=mi.comments or '', tags=list(mi.tags or []),
        cover=cover,
    )


def _legacy_db():
    from calibre.gui2.ui import get_gui
    return get_gui().current_db


def telegram_text(data):
    rows = [(k, n, t, dt) for k, n, h, t, dt in data['rows']]
    return tgtext.build_text(
        dict(title=data['title'], authors=data['authors'], rows=rows,
             comments_html=data['comments_html'], tags=data['tags']),
        emojis=prefs['emojis'], hashtags=prefs['hashtags'],
        emoji_map=emoji_map(), tag_emojis=tag_emoji_map(),
        tag_emojis_on=prefs['tg_tag_emojis'])


def caption_limit():
    return tgtext.CAPTION_LIMIT_PREMIUM if prefs['premium'] else tgtext.CAPTION_LIMIT


def rounded_cover(img, width, scale, bg):
    '''Cover scaled to width*scale pixels, with rounded corners over bg.'''
    w = int(width * scale)
    img = img.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
    out = QImage(img.size(), QImage.Format.Format_ARGB32)
    out.fill(QColor(bg) if bg else QColor(0, 0, 0, 0))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    r = 7 * scale
    path.addRoundedRect(QRectF(0, 0, img.width(), img.height()), r, r)
    p.setClipPath(path)
    p.drawImage(0, 0, img)
    p.end()
    return out


def _emoji_img(doc, e, size):
    '''HTML for an emoji: bundled image if there is one, otherwise the text.'''
    if not e:
        return ''
    from calibre_plugins.book_card_export.emoji_picker import emoji_key, emoji_pixmap
    pm = emoji_pixmap(e)
    if pm is None:
        return escape(e) + ' '
    url = 'bce-emoji-' + emoji_key(e)
    rt = QTextDocument.ResourceType.ImageResource
    doc.addResource(int(getattr(rt, 'value', rt)), QUrl(url), pm.toImage())
    return ('<img src="%s" width="%d" height="%d" style="vertical-align: middle">&nbsp;'
            % (url, size, size))


def build_document(data, scale=2.0):
    theme = current_theme()
    cw = int(prefs['cover_width'])
    width = int(prefs['card_width'])
    doc = QTextDocument()
    f = QFont(QApplication.font())
    f.setPixelSize(15)
    doc.setDefaultFont(f)
    doc.setDocumentMargin(28)

    cover = rounded_cover(data['cover'], cw, scale, theme['bg'])
    ch = int(cover.height() / scale)
    rt = QTextDocument.ResourceType.ImageResource
    doc.addResource(int(getattr(rt, 'value', rt)), QUrl('bce-cover'), cover)

    css = '''
    td {{ color: {fg}; }}
    .title {{ font-size: 26px; font-weight: bold; color: {title}; margin-bottom: 2px; }}
    .author {{ font-size: 17px; color: {author}; margin-bottom: 12px; }}
    .label {{ color: {label}; font-style: italic; }}
    .value {{ color: {value}; }}
    .comments {{ color: {fg}; }}
    .footer {{ font-size: 11px; color: {footer}; }}
    '''.format(**theme) + (prefs['extra_css'] or '')
    doc.setDefaultStyleSheet(css)

    emap = emoji_map()
    card_emojis = prefs['card_emojis']
    tmap = tag_emoji_map() if prefs['card_tag_emojis'] else {}

    def field_label(key, name):
        e = tgtext.field_emoji(key, name, emap) if card_emojis else ''
        return _emoji_img(doc, e, 17) + escape(name)

    def field_value(key, html_val):
        if key == 'tags' and tmap and data.get('tags'):
            parts = []
            for tag in data['tags']:
                parts.append(_emoji_img(doc, tmap.get(tag.lower(), ''), 17) + escape(tag))
            return ', '.join(parts)
        return html_val

    rows_html = ''.join(
        '<tr><td class="label" align="right" valign="middle" style="padding-right:8px">%s</td>'
        '<td class="value" valign="middle">%s</td></tr>' % (field_label(key, name),
                                                           field_value(key, html_val))
        for key, name, html_val, text_val, dt in data['rows'])
    title_html = (_emoji_img(doc, tgtext.field_emoji('title', '', emap), 26) if card_emojis else '') + escape(data['title'])
    authors_html = (_emoji_img(doc, tgtext.field_emoji('authors', '', emap), 18) if card_emojis else '') + escape(data['authors'])
    footer = ('<p class="footer" align="right">%s</p>' % escape(_('Exported from calibre'))
              if prefs['footer'] else '')
    html = '''
    <table width="100%%" cellspacing="0" cellpadding="0" border="0"><tr>
      <td width="%(cw)d" valign="top"><img src="bce-cover" width="%(cw)d" height="%(ch)d"></td>
      <td width="26"></td>
      <td valign="top">
        <p class="title">%(title)s</p>
        <p class="author">%(authors)s</p>
        <table cellspacing="0" cellpadding="2" border="0">%(rows)s</table>
        <div class="comments">%(comments)s</div>
        %(footer)s
      </td>
    </tr></table>''' % dict(
        cw=cw, ch=ch, title=title_html, authors=authors_html,
        rows=rows_html, comments=_clean_comments(data['comments_html']), footer=footer)
    doc.setHtml(html)
    doc.setTextWidth(width)
    return doc, theme


def _clean_comments(html):
    if not html:
        return ''
    if '<' not in html:
        return ''.join('<p>%s</p>' % escape(p).replace('\n', '<br>')
                       for p in re.split(r'\n\s*\n', html.strip()))
    # remove <html>/<body> wrappers and inline colors, so the theme/CSS apply
    html = re.sub(r'(?is)</?(html|body|head)[^>]*>', '', html)
    html = re.sub(r'(?i)color\s*:\s*[^;"\']+;?', '', html)
    return html


def _paint(doc, theme, painter, width, height):
    if theme['bg']:
        painter.fillRect(QRectF(0, 0, width, height), QColor(theme['bg']))
    ctx = QAbstractTextDocumentLayout.PaintContext()
    ctx.palette.setColor(QPalette.ColorRole.Text, QColor(theme['fg']))
    doc.documentLayout().draw(painter, ctx)


def render_image(data, scale=2.0):
    doc, theme = build_document(data, scale)
    width = int(prefs['card_width'])
    height = int(math.ceil(doc.size().height()))
    img = QImage(int(width * scale), int(height * scale), QImage.Format.Format_ARGB32)
    img.fill(QColor(theme['bg']) if theme['bg'] else QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.scale(scale, scale)
    _paint(doc, theme, p, width, height)
    p.end()
    return img


def checkerboard_preview(img):
    '''The image over a grey checkerboard, to see a transparent background.'''
    out = QImage(img.size(), QImage.Format.Format_RGB32)
    p = QPainter(out)
    s = 24
    for y in range(0, out.height(), s):
        for x in range(0, out.width(), s):
            c = QColor('#e6e6e6') if (x // s + y // s) % 2 == 0 else QColor('#c8c8c8')
            p.fillRect(x, y, s, s, c)
    p.drawImage(0, 0, img)
    p.end()
    return out


def image_ext():
    '''A transparent background is only possible in PNG.'''
    if prefs['background'] == 'transparent':
        return 'png'
    return prefs['image_format']


def save_image(data, path, fmt=None):
    fmt = (fmt or prefs['image_format']).lower()
    img = render_image(data)
    if fmt in ('jpg', 'jpeg'):
        if img.hasAlphaChannel():
            # JPG has no transparency: put the card over white
            flat = QImage(img.size(), QImage.Format.Format_RGB32)
            flat.fill(QColor('#ffffff'))
            p = QPainter(flat)
            p.drawImage(0, 0, img)
            p.end()
            img = flat
        return img.save(path, 'JPG', 92)
    return img.save(path, 'PNG')


def safe_filename(data, ext):
    base = '%s - %s' % (data['title'], data['authors']) if data['authors'] else data['title']
    base = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', base).strip(' .')[:150] or 'book'
    return '%s.%s' % (base, ext)
