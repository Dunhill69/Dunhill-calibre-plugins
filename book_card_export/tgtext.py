#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''Telegram text: no Qt or calibre imports here, so it can be tested alone.'''

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

import re
from html.parser import HTMLParser

CAPTION_LIMIT = 1024
CAPTION_LIMIT_PREMIUM = 4096
MESSAGE_LIMIT = 4096

STANDARD_EMOJIS = {
    'series': '📚', 'tags': '🏷️', 'publisher': '🏢', 'pubdate': '📅',
    'rating': '⭐', 'languages': '🌐', 'formats': '💾', 'identifiers': '🔗',
    'timestamp': '🗓️', 'last_modified': '✏️', 'size': '📦',
}
DEFAULT_EMOJI = '▪️'


class _HtmlToTelegram(HTMLParser):
    BLOCK = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote',
             'tr', 'ul', 'ol', 'table'}

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.out = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append('\n\n')
        elif tag == 'li':
            self.out.append('\n• ')
        elif tag == 'br':
            self.out.append('\n')
        elif tag in ('b', 'strong'):
            self.out.append('**')
        elif tag in ('i', 'em'):
            self.out.append('__')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head'):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append('\n\n')
        elif tag in ('b', 'strong'):
            self.out.append('**')
        elif tag in ('i', 'em'):
            self.out.append('__')

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r'\s+', ' ', data))


def html_to_telegram(html_text):
    if not html_text:
        return ''
    if '<' not in html_text:
        # plain text comments
        paras = re.split(r'\n\s*\n', html_text.strip())
        return '\n\n'.join(re.sub(r'[ \t]+', ' ', p).strip() for p in paras)
    p = _HtmlToTelegram()
    p.feed(html_text)
    p.close()
    t = ''.join(p.out)
    t = t.replace('\xa0', ' ')
    t = re.sub(r'[ \t]*\n[ \t]*', '\n', t)
    # markers that wrap nothing, or only spaces/newlines
    for m in (r'\*\*', '__'):
        t = re.sub(m + r'(\s*)' + m, r'\1', t)
    t = re.sub(r' +([,.;:])', r'\1', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


def plain(text):
    return text.replace('**', '').replace('__', '')


def tg_len(text):
    '''Length as Telegram counts it (UTF-16 units, without the markers).'''
    return len(plain(text).encode('utf-16-le')) // 2


def hashtag(tag):
    t = re.sub(r'[^\w]+', '', tag.title(), flags=re.UNICODE)
    return '#' + t if t else ''


def field_emoji(key, name, emoji_map):
    '''Emoji of a field ('' = none). emoji_map keys are in lower case.'''
    if key.lower() in emoji_map:
        return emoji_map[key.lower()]
    if (name or '').lower() in emoji_map:
        return emoji_map[(name or '').lower()]
    if key in ('title', 'authors'):
        return {'title': '📖', 'authors': '✍️'}[key]
    return STANDARD_EMOJIS.get(key, DEFAULT_EMOJI)


def tags_with_emojis(tags, tag_emojis):
    '''"🕵️ Policial, 🔪 Thriller, Sagas" (tag_emojis keys in lower case).'''
    out = []
    for tag in tags:
        e = tag_emojis.get(tag.lower(), '')
        out.append('%s %s' % (e, tag) if e else tag)
    return ', '.join(out)


def build_text(data, emojis=True, hashtags=False, emoji_map=None,
               tag_emojis=None, tag_emojis_on=False):
    '''data: dict with title, authors, rows [(key, name, text, datatype)],
    comments_html, tags.'''
    emoji_map = emoji_map or {}

    def emo(key, name=''):
        if not emojis:
            return ''
        e = field_emoji(key, name, emoji_map)
        return e + ' ' if e else ''

    lines = []
    lines.append(emo('title') + '**%s**' % data['title'])
    if data.get('authors'):
        lines.append(emo('authors') + data['authors'])
    for key, name, text, datatype in data.get('rows', ()):
        if not text:
            continue
        if key == 'tags' and tag_emojis_on and tag_emojis and data.get('tags'):
            text = tags_with_emojis(data['tags'], tag_emojis)
        text = ' '.join(text.split()) if datatype != 'comments' else text
        lines.append('%s**%s:** %s' % (emo(key, name), name, text))
    parts = ['\n'.join(lines)]
    synopsis = html_to_telegram(data.get('comments_html') or '')
    if synopsis:
        parts.append(synopsis)
    if hashtags and data.get('tags'):
        tags = ' '.join(h for h in (hashtag(t) for t in data['tags']) if h)
        if tags:
            parts.append(tags)
    return '\n\n'.join(parts)


def split_text(text, limit, notice):
    '''Split into the photo caption (<= limit) and the following message(s).
    Cuts between paragraphs; if a paragraph is too long, between sentences.'''
    if tg_len(text) <= limit:
        return [text]
    paras = text.split('\n\n')
    pieces = []
    for p in paras:
        if tg_len(p) <= limit - tg_len(notice) - 2:
            pieces.append(p)
        else:
            sentences = re.split(r'(?<=[.!?…»])\s+', p)
            cur = ''
            for s in sentences:
                cand = (cur + ' ' + s).strip()
                if cur and tg_len(cand) > limit - tg_len(notice) - 2:
                    pieces.append(cur)
                    cur = s
                else:
                    cur = cand
            if cur:
                pieces.append(cur)
    out = []
    cur = ''
    for i, p in enumerate(pieces):
        lim = limit if not out else MESSAGE_LIMIT
        cand = p if not cur else cur + '\n\n' + p
        reserve = tg_len('\n\n' + notice) if (not out and i < len(pieces) - 1) else 0
        if cur and tg_len(cand) + reserve > lim:
            out.append(cur)
            cur = p
        else:
            cur = cand
    if cur:
        out.append(cur)
    if len(out) > 1:
        out[0] = out[0] + '\n\n' + notice
    return out
