# -*- coding: utf-8 -*-
"""
Búsqueda en Goodreads y extracción de premios literarios.

Los premios se leen de los datos estructurados de la página del libro:
  1. __NEXT_DATA__ (apolloState -> Work.details.awardsWon / choiceAwards),
     con nombre, categoría, año y si fue ganador o nominado.
  2. Si no están, el JSON-LD de la página ("awards": texto separado por comas).
  3. Páginas viejas: los enlaces <a class="award">.
Los premios importantes (Pulitzer, Nobel, Hugo...) van siempre primero.
"""

try:
    load_translations()
except NameError:
    pass

import datetime
import html as htmlmod
import json
import re
import time
import unicodedata
from threading import Thread

from urllib.parse import quote

try:
    from calibre_plugins.goodreads_awards.config import prefs
except ImportError:  # pruebas fuera de calibre
    prefs = {}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Referer': 'https://www.goodreads.com/',
}

# Si el premio contiene cualquiera de estas palabras va al principio
PREMIOS_PRIORITARIOS = [
    'Pulitzer', 'Nobel', 'Hugo', 'Nebula', 'Booker', 'National Book Award',
    'Costa Book Award', "Women's Prize", 'Británico del Libro', 'Man Booker',
    'International Booker', 'Prix Goncourt', 'Miguel de Cervantes', 'Rómulo Gallegos',
    'Newbery', 'Carnegie', 'Edgar', 'World Fantasy', 'Locus', 'Arthur C. Clarke',
    'Premio Planeta', 'Premio Nadal', 'Premio Alfaguara',
]

# Palabras que marcan que NO es un premio ganado
NO_GANADOR = ('nominee', 'nominated', 'nominado', 'nominada', 'longlist', 'shortlist',
              'finalist', 'finalista', 'honorable mention', 'mención')


def _get(key, default=None):
    try:
        return prefs.get(key, default)
    except Exception:
        return default


try:
    from calibre_plugins.goodreads_awards.fetcher import (
        CamoufoxFetcher, SimpleFetcher, camoufox_available, wait_future, READY_SEARCH, READY_BOOK)
except ImportError:  # pruebas fuera de calibre
    from fetcher import CamoufoxFetcher, SimpleFetcher, camoufox_available, wait_future, READY_SEARCH, READY_BOOK

_session = {'camoufox': None, 'simple': None}


def begin_session():
    """Prepara las descargas de una tanda de libros."""
    if _session['camoufox'] is None and camoufox_available():
        _session['camoufox'] = CamoufoxFetcher()


def end_session():
    """Cierra el navegador Camoufox al terminar la tanda."""
    cf, _session['camoufox'] = _session['camoufox'], None
    if cf is not None:
        cf.close()


def using_camoufox():
    return _session['camoufox'] is not None


def _fetch(url, ready=None):
    """Devuelve (html, url final después de las redirecciones)."""
    cf = _session['camoufox']
    try:
        if cf is not None:
            # El primer pedido incluye arrancar el navegador (y, la primera vez
            # que se usa, que calibre lo descargue), por eso la espera larga
            html, final = wait_future(cf.submit(url, ready, 90), 600)
        else:
            if _session['simple'] is None:
                _session['simple'] = SimpleFetcher(HEADERS)
            html, final = _session['simple'].get(url)
    except Exception as e:
        raise ConnectionError('Error downloading {0}: {1}'.format(url, e))
    if not (html or '').strip():
        raise ConnectionError('Goodreads returned an empty page for {0}. It is blocking automated downloads; '
                              'calibre 9.17 or newer is needed to get past it.'.format(url))
    return html, final or url


def _fetch_html(url, ready=None):
    return _fetch(url, ready)[0]


def _clean(text):
    text = re.sub(r'<[^>]+>', '', text or '')
    return re.sub(r'\s+', ' ', htmlmod.unescape(text)).strip()


def _norm(text):
    """Minúsculas, sin acentos ni signos, para comparar títulos."""
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r'\(.*?\)', ' ', text)  # "(Dune, #1)"
    return ' '.join(re.sub(r'[^\w]+', ' ', text).split())


# ---------------------------------------------------------------- búsqueda

def parse_search(html):
    """Resultados de la página de búsqueda: lista de dicts id, title, author, url."""
    results, seen = [], set()
    # Cada resultado es una fila <tr itemscope itemtype="http://schema.org/Book">
    rows = re.split(r'<tr[^>]+itemtype="https?://schema\.org/Book"', html)[1:] or [html]
    for row in rows:
        m = re.search(r'<a[^>]+class="bookTitle"[^>]*href="/book/show/(\d+)[^"]*"[^>]*>(.*?)</a>', row, re.DOTALL)
        if not m:
            m = re.search(r'<a[^>]+href="/book/show/(\d+)[^"]*"[^>]*class="bookTitle"[^>]*>(.*?)</a>', row, re.DOTALL)
        if not m:
            continue
        gr_id, title = m.group(1), _clean(m.group(2))
        if not title or gr_id in seen:
            continue
        seen.add(gr_id)
        am = re.search(r'class="authorName"[^>]*>(.*?)</a>', row, re.DOTALL)
        results.append({'id': gr_id, 'title': title, 'author': _clean(am.group(1)) if am else '',
                        'url': 'https://www.goodreads.com/book/show/' + gr_id})
    if not results:
        # Formato desconocido: cualquier enlace a un libro con texto
        for m in re.finditer(r'href="/book/show/(\d+)[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL):
            gr_id, title = m.group(1), _clean(m.group(2))
            if title and gr_id not in seen:
                seen.add(gr_id)
                results.append({'id': gr_id, 'title': title, 'author': '',
                                'url': 'https://www.goodreads.com/book/show/' + gr_id})
    return results


def search_books(title, authors):
    """Devuelve (coincidencias, todos los resultados). Si ningún título
    coincide, la lista de coincidencias queda vacía y se puede ofrecer
    al usuario la lista completa."""
    first_author = authors[0].split(',')[0].strip() if authors else ''
    if first_author.lower() in ('unknown', 'desconocido', 'anónimo', 'anonimo', 'anonymous'):
        first_author = ''  # "Desconocido" no es un autor y estropea la búsqueda
    url = 'https://www.goodreads.com/search?search_type=books&q=' + quote('{0} {1}'.format(title, first_author).strip())
    print('[Goodreads Awards] Search: ' + url)
    html, final = _fetch(url, READY_SEARCH)
    m = re.search(r'/book/show/(\d+)', final or '')
    if m:
        # Goodreads fue directo a la página del libro (un único resultado)
        tm = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', html)
        found = {'id': m.group(1), 'title': htmlmod.unescape(tm.group(1)) if tm else title, 'author': '',
                 'url': 'https://www.goodreads.com/book/show/' + m.group(1)}
        print('[Goodreads Awards] Redirected to the book page: ' + final)
        return [found], [found]
    results = parse_search(html)[:10]
    wanted = _norm(title)
    matches = [r for r in results if wanted and (_norm(r['title']) in wanted or wanted in _norm(r['title']))]
    print('[Goodreads Awards] Results: %d, matching title: %d' % (len(results), len(matches)))
    return matches, results


# ---------------------------------------------------------------- premios

def _year(ms):
    try:
        return (datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=int(ms))).year
    except Exception:
        return None


def _award_text(a):
    name = _clean(a.get('name') or '')
    if not name:
        return None, False
    designation = (a.get('designation') or '').upper()
    winner = designation in ('', 'WINNER')
    if designation and designation != 'WINNER':
        name += ' ' + designation.capitalize()   # "Hugo Award Nominee"
    category = _clean(a.get('category') or '')
    if category:
        name += ' for ' + category
    year = _year(a['awardedAt']) if a.get('awardedAt') is not None else None
    if year:
        name += ' (%d)' % year
    return name, winner


def _awards_from_next_data(html):
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        state = json.loads(m.group(1))['props']['pageProps']['apolloState']
    except Exception:
        return None
    found = []

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ('awardsWon', 'choiceAwards') and isinstance(v, list):
                    for a in v:
                        if isinstance(a, dict):
                            found.append(a)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    for key, val in state.items():
        if key.startswith('Work:'):
            walk(val)
    if not found:
        # Algunas páginas cuelgan los premios del nodo Book
        for key, val in state.items():
            if key.startswith('Book:'):
                walk(val)
    ans = []
    for a in found:
        text, winner = _award_text(a)
        if text and text not in [t for t, w in ans]:
            ans.append((text, winner))
    return ans


def _awards_from_ldjson(html):
    for m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        awards = data.get('awards') if isinstance(data, dict) else None
        if awards:
            # "Premio A (2001), Premio B Nominee (2003)"
            parts = re.findall(r'[^,]+?\(\d{4}\)|[^,]+$', awards)
            ans = []
            for p in (parts or awards.split(',')):
                p = _clean(p)
                if p:
                    ans.append((p, not any(w in p.lower() for w in NO_GANADOR)))
            return ans
    return None


def _awards_from_legacy(html):
    ans = []
    for m in re.finditer(r'<a[^>]+class="award"[^>]*>(.*?)</a>', html, re.DOTALL):
        p = _clean(m.group(1))
        if p:
            ans.append((p, not any(w in p.lower() for w in NO_GANADOR)))
    return ans


def extract_awards(html):
    """Lista de (texto del premio, es_ganador)."""
    for func in (_awards_from_next_data, _awards_from_ldjson, _awards_from_legacy):
        ans = func(html)
        if ans:
            return ans
    return []


def _year_of(text):
    m = re.search(r'\((\d{4})\)', text)
    return int(m.group(1)) if m else 0


def select_awards(awards, settings=None):
    """Aplica orden, prioridad y filtros de la configuración.
    Orden: premios importantes primero; dentro de cada grupo, los ganados
    antes que las nominaciones y luego del más nuevo al más viejo."""
    get = (lambda k, d=None: settings.get(k, d)) if settings is not None else _get
    if get('solo_ganadores', False):
        awards = [a for a in awards if a[1]]
    awards = sorted(awards, key=lambda a: (not a[1], -_year_of(a[0])))

    def important(t):
        return any(kw.lower() in t.lower() for kw in PREMIOS_PRIORITARIOS)
    prioritarios = [t for t, w in awards if important(t)]
    normales = [t for t, w in awards if not important(t)]
    if get('solo_premio_principal', False) and prioritarios:
        return [prioritarios[0]]
    final = prioritarios + normales
    max_val = str(get('max_premios', 'All'))
    if max_val not in ('All', 'Todos'):
        try:
            final = final[:int(max_val)]
        except ValueError:
            pass
    return final


def scrape_awards(url, title=''):
    html = _fetch_html(url, READY_BOOK)
    awards = extract_awards(html)
    print('[Goodreads Awards] %s: %d awards found: %r' % (title, len(awards), awards))
    final = select_awards(awards)
    return {'premios': final} if final else {}


class FetchWorker(Thread):
    def __init__(self, tasks, progress_cb, done_cb):
        super().__init__(daemon=True)
        self.tasks = tasks
        self.progress_cb = progress_cb
        self.done_cb = done_cb
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            for i, (book_id, url, title) in enumerate(self.tasks):
                if self._abort:
                    break
                try:
                    data = scrape_awards(url, title)
                    error = None
                except Exception as e:
                    data, error = {}, str(e)
                if self._abort:
                    break
                self.progress_cb(book_id, data, error)
                if i < len(self.tasks) - 1:
                    # pausa entre pedidos para no saturar Goodreads
                    for _i in range(15):
                        if self._abort:
                            break
                        time.sleep(0.1)
        finally:
            self.done_cb()
