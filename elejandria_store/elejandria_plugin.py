# -*- coding: utf-8 -*-
"""
Tienda de Elejandría para "Conseguir libros" de calibre.

La búsqueda del sitio funciona con Google (JavaScript) y no devuelve resultados
en HTML, así que la tienda arma su propio catálogo recorriendo el índice
alfabético (/libros/a, /libros/b, ...) y lo guarda en caché durante unos días.
Los enlaces de descarga se leen de la ficha de cada libro.
"""

import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

BASE = 'https://www.elejandria.com/'
BOOK_RE = re.compile(r'^https?://(?:www\.)?elejandria\.com/libro/(?!descargar/|link_descarga)'
                     r'[^/]+/[^/]+/(\d+)/?$')
INDEX_RE = re.compile(r'^https?://(?:www\.)?elejandria\.com/libros/[^/?#]{1,3}(?:/\d+|\?[^#]*)?$')
DL_PAGE_RE = re.compile(r'/libro/descargar/[^"\']+/(\d+)/(\d+)')
FORMAT_RE = re.compile(r'Descargar en\s+(ePub|EPUB|PDF|MOBI|Mobi|AZW3|TXT|FB2)', re.I)
CACHE_DAYS = 7
MAX_INDEX_PAGES = 600

_CATALOG_LOCK = threading.Lock()
_CATALOG = None


# --------------------------------------------------------------- utilidades

def to_text(s):
    if isinstance(s, bytes):
        return s.decode('utf-8', 'replace')
    return s or ''


def norm(s):
    s = unicodedata.normalize('NFKD', to_text(s))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9ñ ]+', ' ', s.lower()).strip()


def nice_case(s):
    """'MIGUEL DE CERVANTES' -> 'Miguel de Cervantes' (solo si viene todo en mayúsculas)."""
    if not s or not s.isupper():
        return s
    small = {'de', 'del', 'la', 'las', 'los', 'el', 'y', 'e', 'en', 'a', 'o', 'u', 'al', 'von', 'van', 'da', 'di'}
    words = s.lower().split()
    def cap(w):
        return '-'.join(x[:1].upper() + x[1:] for x in w.split('-'))
    return ' '.join(w if (i and w in small) else cap(w) for i, w in enumerate(words))


def _root(raw):
    from lxml import html as lhtml
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'replace')
    raw = re.sub(r'^\s*<\?xml[^>]*>', '', raw)
    return lhtml.fromstring(raw)


def parse_listing(raw, page_url=BASE):
    """Devuelve (libros, enlaces_de_indice). libros: {id: {...}}"""
    root = _root(raw)
    books = {}
    index_links = set()
    for a in root.iter('a'):
        href = urljoin(page_url, a.get('href') or '')
        if INDEX_RE.match(href):
            index_links.add(href.split('#')[0])
            continue
        m = BOOK_RE.match(href)
        if not m:
            continue
        bid = m.group(1)
        b = books.setdefault(bid, {'id': bid, 'url': href, 'title': '', 'author': '', 'cover': ''})
        img = a.find('.//img')
        if img is not None:
            src = img.get('data-src') or img.get('src') or ''
            if '/covers/' in src:
                b['cover'] = urljoin(page_url, src)
            alt = img.get('alt') or ''
            if alt.startswith('Descargar ') and not b.get('_alt'):
                b['_alt'] = alt[10:].strip()
        t = (a.get('title') or '').strip()
        if t.startswith('Libro '):
            b['title'] = t[6:].strip()
        elif not b['title']:
            txt = a.text_content().strip()
            if txt:
                b['title'] = nice_case(txt)
        if not b['author']:
            # el autor está en el mismo bloque de la tarjeta
            node = a.getparent()
            for _ in range(4):
                if node is None:
                    break
                aut = [x for x in node.iter('a') if '/autor/' in (x.get('href') or '')]
                if aut:
                    at = (aut[0].get('title') or '').strip()
                    b['author'] = at[10:].strip() if at.startswith('Libros de ') else nice_case(aut[0].text_content().strip())
                    break
                node = node.getparent()
    for b in books.values():
        alt = b.pop('_alt', '')
        if alt and b['author'] and alt.endswith(' de ' + b['author']) and not b['title']:
            b['title'] = alt[:-len(' de ' + b['author'])]
        elif alt and not b['title']:
            b['title'] = alt
    return books, index_links


def parse_book_page(raw, page_url):
    """Datos de la ficha: título, autor, portada, formatos {FMT: url_pagina_descarga}."""
    root = _root(raw)
    info = {'title': '', 'author': '', 'cover': '', 'formats': {}}
    for s in root.xpath('//script[@type="application/ld+json"]'):
        try:
            data = json.loads(s.text_content())
        except Exception:
            continue
        book = data.get('mainEntity') if isinstance(data, dict) else None
        if isinstance(book, dict) and book.get('@type') == 'Book':
            info['title'] = book.get('name') or ''
            a = book.get('author')
            info['author'] = a.get('name', '') if isinstance(a, dict) else (a or '')
            info['cover'] = book.get('image') or ''
    if not info['cover']:
        og = root.xpath('//meta[@property="og:image"]/@content')
        info['cover'] = og[0] if og else ''
    for a in root.xpath('//a[contains(@href, "/libro/descargar/")]'):
        m = FORMAT_RE.search(a.text_content())
        if m:
            fmt = m.group(1).upper()
            info['formats'].setdefault(fmt, urljoin(page_url, a.get('href')))
    return info


def direct_link(download_page_url):
    """/libro/descargar/<slug>/<autor>/<libro>/<archivo> -> /libro/link_descarga_libro/<libro>/<archivo>"""
    m = DL_PAGE_RE.search(download_page_url)
    if m:
        return urljoin(BASE, f'libro/link_descarga_libro/{m.group(1)}/{m.group(2)}')
    return download_page_url


BOOK_EXTS = ('.epub', '.pdf', '.mobi', '.azw3', '.txt', '.fb2', '.zip')


def resolve_download(url, referer, timeout):
    """Sigue las redirecciones del enlace sin bajar el archivo. Si la URL final
    termina en una extensión de libro se usa esa (calibre deduce el formato del
    nombre); si no, se deja el enlace original."""
    from calibre import browser
    br = browser()
    br.addheaders.append(('Referer', referer))
    try:
        r = br.open_novisit(url, timeout=timeout)
        final = r.geturl()
        r.close()
        if final.lower().split('?')[0].endswith(BOOK_EXTS):
            return final
    except Exception:
        pass
    return url


def search_catalog(catalog, query, max_results):
    words = norm(query).split()
    if not words:
        return []
    scored = []
    for b in catalog.values():
        nt, na = norm(b['title']), norm(b['author'])
        hay = nt + ' ' + na
        if all(w in hay for w in words):
            score = sum(2 for w in words if w in nt.split()) + sum(1 for w in words if w in na.split())
            if nt == norm(query):
                score += 10
            scored.append((-score, nt, b))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [b for _, _, b in scored[:max_results]]


# -------------------------------------------------------------- catálogo

def _cache_path():
    from calibre.utils.config import config_dir
    return os.path.join(config_dir, 'plugins', 'elejandria_catalogo.json')


def _download(url, timeout):
    from calibre import browser
    br = browser()
    return br.open_novisit(url, timeout=timeout).read()


def build_catalog(timeout=30, fetch=None, log=print):
    """Recorre el índice alfabético en paralelo. fetch(url) -> bytes (inyectable para pruebas)."""
    fetch = fetch or (lambda u: _download(u, timeout))
    start = urljoin(BASE, 'libros/a')
    seen, pending = set(), [start]
    catalog = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        while pending and len(seen) < MAX_INDEX_PAGES:
            batch = [u for u in dict.fromkeys(pending) if u not in seen][:24]
            pending = [u for u in pending if u not in batch and u not in seen]
            seen.update(batch)
            for url, raw in zip(batch, pool.map(lambda u: _safe(fetch, u, log), batch)):
                if not raw:
                    continue
                books, links = parse_listing(raw, url)
                for bid, b in books.items():
                    old = catalog.get(bid)
                    if not old:
                        catalog[bid] = b
                    else:
                        for k, v in b.items():
                            if v and not old.get(k):
                                old[k] = v
                pending.extend(l for l in links if l not in seen)
    log(f'Elejandría: catálogo con {len(catalog)} libros ({len(seen)} páginas de índice)')
    return catalog


def _safe(fetch, url, log):
    try:
        return fetch(url)
    except Exception as e:
        log(f'Elejandría: error al leer {url}: {e}')
        return None


_REFRESHING = False


def _save_cache(catalog):
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'time': time.time(), 'books': catalog}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        print('Elejandría: no se pudo guardar el catálogo:', e)


def _load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if data.get('books'):
            return data
    except Exception:
        pass
    return None


def _load_bundled(plugin_path):
    """Catálogo incluido en el zip del complemento (para que la 1.ª búsqueda sea inmediata)."""
    if not plugin_path:
        return None
    try:
        import zipfile
        with zipfile.ZipFile(plugin_path) as zf:
            data = json.loads(zf.read('catalogo_inicial.json').decode('utf-8'))
        return data if data.get('books') else None
    except Exception:
        return None


def _refresh_in_background(timeout):
    global _REFRESHING

    def run():
        global _CATALOG, _REFRESHING
        try:
            catalog = build_catalog(timeout)
            # solo se reemplaza si el recorrido salió completo (evita perder libros por un corte)
            if catalog and len(catalog) >= 0.8 * len(_CATALOG or {}):
                _save_cache(catalog)
                with _CATALOG_LOCK:
                    _CATALOG = catalog
        finally:
            _REFRESHING = False

    if not _REFRESHING:
        _REFRESHING = True
        threading.Thread(target=run, name='ElejandriaCatalog', daemon=True).start()


def get_catalog(timeout=30, plugin_path=None):
    """Devuelve el catálogo sin hacer esperar a la búsqueda: usa la caché (o el
    catálogo incluido en el complemento) y, si está viejo, lo actualiza en segundo plano."""
    global _CATALOG
    with _CATALOG_LOCK:
        if _CATALOG is not None:
            return _CATALOG
        data = _load_json(_cache_path()) or _load_bundled(plugin_path)
        if data:
            _CATALOG = data['books']
            if time.time() - data.get('time', 0) > CACHE_DAYS * 86400:
                _refresh_in_background(timeout)
            return _CATALOG
    # Sin nada guardado: hay que armarlo ahora (solo la primera vez)
    catalog = build_catalog(timeout)
    if catalog:
        _save_cache(catalog)
        with _CATALOG_LOCK:
            _CATALOG = catalog
    return catalog


# ------------------------------------------------------------ tienda (GUI)

try:
    from calibre.gui2.store import StorePlugin
    from calibre.gui2.store.basic_config import BasicStoreConfig
    from calibre.gui2.store.search_result import SearchResult
except ImportError:  # permite importar el módulo fuera de calibre (pruebas)
    class StorePlugin:
        pass

    class BasicStoreConfig:
        pass
    SearchResult = None


class ElejandriaStorePlugin(BasicStoreConfig, StorePlugin):

    def open(self, parent=None, detail_item=None, external=False):
        url = detail_item or BASE
        try:
            if external or self.config.get('open_external', False):
                raise RuntimeError
            from calibre.gui2.store.web_store_dialog import WebStoreDialog
            d = WebStoreDialog(self.gui, BASE, parent, url)
            d.setWindowTitle(self.name)
            d.set_tags(self.config.get('tags', ''))
            d.exec()
        except Exception:
            from calibre.gui2 import open_url
            from qt.core import QUrl
            open_url(QUrl(url))

    def search(self, query, max_results=10, timeout=60):
        query = to_text(query)  # calibre pasa la búsqueda como bytes
        try:
            plugin_path = getattr(getattr(self, 'base_plugin', None), 'plugin_path', None)
            catalog = get_catalog(timeout=min(timeout, 30), plugin_path=plugin_path)
            found = search_catalog(catalog, query, max_results)
        except Exception:
            import traceback
            print('Elejandría: ERROR en la búsqueda')
            traceback.print_exc()
            raise
        for b in found:
            s = SearchResult()
            s.title = b['title']
            s.author = b['author']
            s.price = '$0.00'
            s.cover_url = b.get('cover') or ''
            s.detail_item = b['url']
            s.drm = SearchResult.DRM_UNLOCKED
            s.formats = 'EPUB, PDF, MOBI'
            yield s

    def get_details(self, search_result, timeout):
        try:
            raw = _download(search_result.detail_item, timeout)
        except Exception:
            return False
        info = parse_book_page(raw, search_result.detail_item)
        if info['cover'] and not search_result.cover_url:
            search_result.cover_url = info['cover']
        search_result.downloads = {}
        for fmt, page in info['formats'].items():
            search_result.downloads[fmt] = resolve_download(direct_link(page), page, timeout)
        search_result.formats = ', '.join(search_result.downloads)
        return True
