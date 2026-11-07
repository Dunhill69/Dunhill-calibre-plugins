# -*- coding: utf-8 -*-
"""
Descarga, interpretación y traducción del Changelog oficial de calibre.

Formato del archivo (https://raw.githubusercontent.com/kovidgoyal/calibre/master/Changelog.txt):

    {{{ 9.11.0 2026-07-02

    :: new features

    - [major] Título del cambio
      Descripción opcional, indentada

    :: bug fixes

    - [12345] Otro cambio
    }}}
"""

import html
import json
import os
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    load_translations()
except NameError:
    pass

CHANGELOG_URL = 'https://raw.githubusercontent.com/kovidgoyal/calibre/master/Changelog.txt'
TRANSLATE_URL = 'https://translate.googleapis.com/translate_a/single'
UA = {'User-Agent': 'Mozilla/5.0'}

HEADER_RE = re.compile(r'^\{\{\{\s+(\d+\.\d+\.\d+)\s+(\S+)')
TICKETS_RE = re.compile(r'^\[[^\]]*\]\s*')

# Solo se traducen estas secciones; en las de "recipes" los ítems son nombres propios.
TRANSLATABLE_SECTIONS = {'new features', 'bug fixes'}


# ---------------------------------------------------------------- SSL

_ssl_ctx = None
_ssl_lock = threading.Lock()


def ssl_context():
    """Contexto SSL que SÍ verifica certificados y funciona en los tres sistemas.

    El Python que trae calibre en macOS no encuentra solo los certificados del sistema,
    por eso se cargan explícitamente: primero /etc/ssl/cert.pem (incluido en macOS) y,
    si no está, los certificados raíz exportados del llavero del sistema.
    """
    global _ssl_ctx
    with _ssl_lock:
        if _ssl_ctx is not None:
            return _ssl_ctx
        ctx = ssl.create_default_context()
        if sys.platform == 'darwin':
            loaded = False
            for path in ('/etc/ssl/cert.pem', '/private/etc/ssl/cert.pem'):
                if os.path.exists(path):
                    try:
                        ctx.load_verify_locations(cafile=path)
                        loaded = True
                        break
                    except Exception:
                        pass
            if not loaded:
                try:
                    pem = subprocess.run(
                        ['/usr/bin/security', 'find-certificate', '-a', '-p',
                         '/System/Library/Keychains/SystemRootCertificates.keychain'],
                        capture_output=True, text=True, timeout=20).stdout
                    if pem:
                        ctx.load_verify_locations(cadata=pem)
                except Exception:
                    pass
        try:
            import certifi
            ctx.load_verify_locations(cafile=certifi.where())
        except Exception:
            pass
        _ssl_ctx = ctx
        return ctx


def parse_v(value):
    """'9.11.0' o (9, 11, 0) -> (9, 11, 0). Siempre devuelve 3 números."""
    if isinstance(value, (tuple, list)):
        parts = [int(x) for x in value]
    else:
        parts = [int(x) for x in re.findall(r'\d+', str(value or ''))]
    parts = parts[:3]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


# ---------------------------------------------------------------- descarga

def fetch_changelog_text(timeout=10, max_bytes=96 * 1024):
    """Descarga solo el principio del archivo (las versiones más nuevas están arriba)."""
    headers = dict(UA)
    headers['Range'] = 'bytes=0-%d' % (max_bytes - 1)
    req = urllib.request.Request(CHANGELOG_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
        # read(max_bytes) limita la descarga aunque el servidor ignore el Range
        return r.read(max_bytes).decode('utf-8', errors='replace')


# ---------------------------------------------------------------- interpretación

def parse_changelog(text):
    releases = []
    cur = section = None
    for raw in text.splitlines():
        if raw.lstrip().startswith('#'):
            continue
        m = HEADER_RE.match(raw)
        if m:
            cur = {'version': m.group(1), 'date': m.group(2), 'sections': []}
            releases.append(cur)
            section = None
            continue
        if cur is None:
            continue
        s = raw.strip()
        if s.startswith('}}}'):
            cur = section = None
            continue
        if not s:
            continue
        if s.startswith('::'):
            section = {'key': s[2:].strip().lower(), 'items': []}
            cur['sections'].append(section)
            continue
        if section is None:
            continue
        if s.startswith('- '):
            body = s[2:].strip()
            major = False
            mt = TICKETS_RE.match(body)
            if mt:
                major = 'major' in mt.group(0).lower()
                body = body[mt.end():].strip()
            section['items'].append({'text': body, 'desc': '', 'major': major})
        elif section['items']:
            item = section['items'][-1]
            item['desc'] = (item['desc'] + ' ' + s).strip()
    return releases


def select_release(releases, target_v):
    """Solo la entrada de la versión que se va a instalar.
    Si todavía no figura en el changelog, la versión publicada más reciente que no la supere."""
    tgt = parse_v(target_v)
    for r in releases:
        if parse_v(r['version']) == tgt:
            return [r]
    older = [r for r in releases if parse_v(r['version']) < tgt]
    return older[:1] or releases[:1]


# ---------------------------------------------------------------- traducción

def raw_ui_language():
    """Idioma tal como lo informa calibre (para diagnóstico)."""
    try:
        from calibre.utils.localization import get_lang
        return str(get_lang())
    except Exception as e:
        return 'unknown (%s)' % e


def ui_language():
    """Código de idioma para Google Translate según la interfaz de calibre, o None si es inglés."""
    try:
        from calibre.utils.localization import get_lang
        lang = (get_lang() or 'en').replace('-', '_')
    except Exception:
        return None
    if lang.lower().startswith('en'):
        return None
    special = {
        'zh_CN': 'zh-CN', 'zh_SG': 'zh-CN',
        'zh_TW': 'zh-TW', 'zh_HK': 'zh-TW',
        'nb': 'no', 'nn': 'no',
    }
    return special.get(lang) or lang.split('_')[0]


# Servidores de traducción gratuitos de Google, en orden de preferencia.
# Si el primero rechaza los pedidos desde una conexión (429, 409...), se prueba el segundo.
TRANSLATE_ENDPOINTS = (
    ('translate.googleapis.com', TRANSLATE_URL,
     {'client': 'gtx', 'sl': 'en', 'dt': 't'}),
    ('clients5.google.com', 'https://clients5.google.com/translate_a/t',
     {'client': 'dict-chrome-ex', 'sl': 'en'}),
)
RETRY_CODES = {408, 409, 425, 429}


def _first_text(data):
    """Extrae el texto traducido de la respuesta, cualquiera sea el servidor."""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        if 'sentences' in data:
            return ''.join(s.get('trans', '') for s in data['sentences'])
        return _first_text(data.get('translation') or data.get('text') or '')
    if isinstance(data, list) and data:
        first = data[0]
        # Formato gtx: [[["traducción", "original", ...], ...], ...]
        if isinstance(first, list) and first and isinstance(first[0], list):
            return ''.join(seg[0] for seg in first if seg and isinstance(seg[0], str))
        return _first_text(first)
    raise ValueError('Unexpected translation response')


def _request(name, url, base_params, text, target, timeout, attempts):
    params = dict(base_params, tl=target, q=text)
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params), headers=UA)
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
                return _first_text(json.loads(r.read().decode('utf-8')))
        except urllib.error.HTTPError as e:
            # 429/409 = Google rechaza pedidos desde esta conexión; 5xx = falla temporal
            if attempt + 1 >= attempts or not (e.code in RETRY_CODES or e.code >= 500):
                raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt + 1 >= attempts:
                raise
        time.sleep(2 * (attempt + 1))


_failed_endpoints = set()   # servidores que ya rechazaron pedidos en esta sesión


def _gtx(text, target, timeout, attempts=3):
    errors = []
    endpoints = [e for e in TRANSLATE_ENDPOINTS if e[0] not in _failed_endpoints] or list(TRANSLATE_ENDPOINTS)
    for name, url, base_params in endpoints:
        try:
            return _request(name, url, base_params, text, target, timeout, attempts)
        except Exception as e:
            _failed_endpoints.add(name)
            code = getattr(e, 'code', None)
            errors.append('%s: %s' % (name, ('HTTP %s' % code) if code else ('%s: %s' % (type(e).__name__, e))))
    raise RuntimeError('; '.join(errors))


def _translate_chunk(lines, target, timeout):
    result = _gtx('\n'.join(lines), target, timeout).split('\n')
    if len(result) == len(lines):
        return [x.strip() for x in result]
    if len(lines) == 1:
        return [' '.join(x.strip() for x in result)]
    # El traductor juntó o partió líneas: se divide el bloque en dos (pocos pedidos extra,
    # en lugar de uno por línea, que dispara el límite de Google)
    mid = len(lines) // 2
    return _translate_chunk(lines[:mid], target, timeout) + _translate_chunk(lines[mid:], target, timeout)


def translate_texts(texts, target, timeout=10, chunk_chars=1200):
    """Traduce una lista de textos en pocas peticiones, conservando el orden."""
    out, chunk, size = [], [], 0
    for t in texts:
        t = t.replace('\n', ' ').strip()
        if chunk and size + len(t) + 1 > chunk_chars:
            out.extend(_translate_chunk(chunk, target, timeout))
            chunk, size = [], 0
        chunk.append(t)
        size += len(t) + 1
    if chunk:
        out.extend(_translate_chunk(chunk, target, timeout))
    return out


def translate_releases(releases, target, timeout=10):
    """Agrega 'text_tr' y 'desc_tr' a los ítems traducibles. Lanza excepción si falla."""
    slots = []
    for r in releases:
        for sec in r['sections']:
            label = _section_label(sec['key'])
            if label == _ENGLISH_LABELS.get(sec['key'], label):
                # El plugin no tiene traducción propia para este título: se traduce con el resto
                slots.append((sec, 'label_tr', label))
            if sec['key'] not in TRANSLATABLE_SECTIONS:
                continue
            for item in sec['items']:
                slots.append((item, 'text_tr', item['text']))
                if item['desc']:
                    slots.append((item, 'desc_tr', item['desc']))
    if not slots:
        return
    translated = translate_texts([s[2] for s in slots], target, timeout)
    for (item, key, _orig), tr in zip(slots, translated):
        item[key] = tr or _orig


# ---------------------------------------------------------------- presentación

_ENGLISH_LABELS = {
    'new features': 'New features',
    'bug fixes': 'Bug fixes',
    'improved recipes': 'Improved news sources',
    'new recipes': 'New news sources',
}


def _section_label(key):
    labels = {
        'new features': _('New features'),
        'bug fixes': _('Bug fixes'),
        'improved recipes': _('Improved news sources'),
        'new recipes': _('New news sources'),
    }
    return labels.get(key, key.capitalize())


def render_html(releases, translated=False):
    if not releases:
        return ''
    esc = html.escape
    parts = []
    for r in releases:
        parts.append(
            '<p style="margin:10px 0 2px 0"><b style="font-size:large">v%s</b> '
            '<span style="color:gray">(%s)</span></p>' % (esc(r['version']), esc(r['date'])))
        for sec in r['sections']:
            if not sec['items']:
                continue
            label = (sec.get('label_tr') if translated else None) or _section_label(sec['key'])
            parts.append('<p style="margin:4px 0 0 0"><i>%s</i></p><ul style="margin-top:2px">'
                         % esc(label))
            for item in sec['items']:
                text = item.get('text_tr') if translated else None
                text = esc(text or item['text'])
                if item['major']:
                    text = '<b>%s</b>' % text
                desc = item.get('desc_tr') if translated else None
                desc = desc or item['desc']
                if desc:
                    text += '<br><span style="color:gray">%s</span>' % esc(desc)
                parts.append('<li>%s</li>' % text)
            parts.append('</ul>')
    return ''.join(parts)
