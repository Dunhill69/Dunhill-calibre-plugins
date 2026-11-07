import gzip
import hashlib
import json
import os
import re
import time
import threading
import unicodedata
import urllib.parse

from bs4 import BeautifulSoup

try:
    load_translations()
except NameError:
    def _(x):
        return x
from qt.core import QThread, pyqtSignal

GOODREADS = 'https://www.goodreads.com'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')

# Códigos con los que Goodreads indica que limitó las consultas: se frena todo
RATE_LIMIT_CODES = {403, 429, 503}
# Errores pasajeros del servidor: un solo reintento
RETRY_CODES = {500, 502, 504}
# Pausa mínima entre dos pedidos reales a Goodreads (los de la caché no esperan)
REQUEST_PAUSE = 1.2
# Cuántos resultados de búsqueda se revisan antes de rendirse
MAX_SEARCH_CANDIDATES = 4
# Máximo de fichas que se abren para verificar resultados de búsqueda
MAX_PAGE_CHECKS = 3
# Parecido mínimo de título (0 a 1) para considerar un resultado
MIN_TITLE_SIMILARITY = 0.6

# Días que se guarda cada tipo de página en la caché
CACHE_DAYS_SERIES = 3      # la lista de una serie (puede sumar libros nuevos)
CACHE_DAYS_OTHER = 30      # fichas, búsquedas, ediciones y portadas

# Idioma buscado en las ediciones: el de la interfaz de calibre o el elegido en
# la configuración. Lo fija configure_language() al crear cada cliente.
try:
    from calibre_plugins.goodreads_series_explorer import lang as _lang
except ImportError:  # pruebas fuera de calibre
    import lang as _lang

TARGET_CODE = 'spa'                 # código de calibre (ISO 639-2/T)
TARGET_LANGUAGES = {'spanish', 'castilian', 'espanol', 'castellano', 'spa'}
TARGET_NAME = 'Spanish'             # nombre en inglés, para el registro
TARGET_IS_ENGLISH = False


def configure_language(settings=None):
    global TARGET_CODE, TARGET_LANGUAGES, TARGET_NAME, TARGET_IS_ENGLISH
    code = _lang.resolve((settings or {}).get('edition_language', 'auto'))
    TARGET_CODE = code
    TARGET_LANGUAGES = _lang.match_names(code) | {code, _lang.goodreads_code(code)}
    TARGET_NAME = _lang.english_name(code).split(';')[0]
    TARGET_IS_ENGLISH = code == 'eng'
    return code

MORE_TEXTS = {'more', '...more', '…more', 'less', '(less)', '...less',
              'show more', 'show less', 'mostrar más', 'mostrar menos'}


def load_settings():
    """Ajustes del complemento; si no se pueden leer, los valores por defecto."""
    try:
        from calibre_plugins.goodreads_series_explorer.prefs import settings
        return settings()
    except Exception:
        return {}


class HttpError(Exception):
    def __init__(self, code):
        super().__init__(f'HTTP {code}')
        self.code = code


class RateLimited(Exception):
    """Goodreads limitó las consultas: hay que dejar de pedir por un rato."""


class BrowserUnavailable(Exception):
    """El navegador interno de calibre no se pudo iniciar."""


class NotCached(Exception):
    """Se pidió una página solo desde la caché y no estaba guardada."""


# ---------------------------------------------------------------- utilidades

def strip_accents(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text or '')
                   if not unicodedata.combining(c))


def norm_series(name):
    """'The Good Daughter Series' -> 'good daughter'."""
    name = strip_accents(name).lower()
    name = re.sub(r'\b(series|serie|saga|trilogy|trilogia)\b', ' ', name)
    name = re.sub(r'^\s*(the|la|el|los|las)\s+', ' ', name)
    name = re.sub(r'[^\w]+', ' ', name)
    return ' '.join(name.split())


def author_tokens(name):
    name = strip_accents(name).lower()
    return {t for t in re.split(r'[^\w]+', name) if len(t) > 1}


def authors_match(calibre_authors, found_author):
    """Coincide si comparte el apellido (o dos palabras) con algún autor de calibre."""
    found = author_tokens(found_author)
    if not found:
        return False
    for author in calibre_authors or []:
        if ',' in author:
            surname = strip_accents(author.split(',')[0]).lower().strip()
        else:
            parts = strip_accents(author).lower().split()
            surname = parts[-1] if parts else ''
        if surname and surname in found:
            return True
        if len(author_tokens(author) & found) >= 2:
            return True
    return False


def parse_index(num_text):
    """'Book 0.5' -> 0.5, '#2' -> 2.0, 'Books 1-3' -> None."""
    if not num_text:
        return None
    if re.search(r'\d\s*[-–]\s*\d', num_text):
        return None
    m = re.search(r'\d+(?:\.\d+)?', num_text)
    return float(m.group(0)) if m else None


# Palabras que delatan un pack, estuche o recopilación de varios libros
STRONG_PACK_WORDS = re.compile(
    r'\b(pack|box(ed)?\s*set|boxset|bundle|estuche|'
    r'books?\s*\d+\s*[-–]\s*\d+|libros?\s*\d+\s*[-–y]\s*\d+|'
    r'\d+[-\s]book|set\s+of\s+\d+)\b', re.I)
# Más ambiguas: un libro individual puede llamarse "The Collection"
WEAK_PACK_WORDS = re.compile(r'\b(collection|colecci[oó]n|omnibus|[oó]mnibus)\b', re.I)


def is_compilation(num_text, title):
    """True para 'Book 1-2', 'Books 1-3.5' o títulos tipo 'Pack Serie...',
    'Box Set', 'Estuche'. Los libros individuales tienen un solo número."""
    if num_text and re.search(r'\d\s*[-–]\s*\d', num_text):
        return True
    if STRONG_PACK_WORDS.search(title or ''):
        return True
    # Sin número en la serie, "Collection" u "Omnibus" sí indican recopilación
    return parse_index(num_text) is None and bool(WEAK_PACK_WORDS.search(title or ''))


# Agregados de idioma: (Spanish Edition), (Edición en español), [French]... (ver lang.py)
LANGUAGE_TAG = _lang.LANGUAGE_TAG
# Agregados de serie: (Empíreo, #1), (Empíreo #3.5), (Saga X, libro 2), (Book 1-3)
SERIES_TAG = re.compile(
    r'\s*[(\[][^()\[\]]*?(?:#|\b(?:libro|book|vol\.?|volumen|tomo|parte|part)\s+)\s*'
    r'\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?\s*[)\]]', re.I)


def clean_title(title):
    """Quita de un título los agregados de idioma y de serie.
    'Alas de sangre (Empíreo, #1) (Spanish Edition)' -> 'Alas de sangre'."""
    if not title:
        return title
    cleaned = LANGUAGE_TAG.sub('', title)
    cleaned = SERIES_TAG.sub('', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip(' -–:;,')
    return cleaned or title.strip()


def norm_title(title):
    """Forma de comparar títulos: sin agregados entre paréntesis, sin acentos,
    sin mayúsculas ni signos. 'Alas de Sangre: (Empíreo 1)' -> 'alas de sangre'."""
    t = clean_title(title or '')
    t = re.sub(r'[(\[][^()\[\]]*[)\]]', ' ', t)
    t = strip_accents(t).lower()
    t = re.sub(r'[^\w]+', ' ', t)
    return ' '.join(t.split())


def latin_ratio(text):
    letters = [c for c in text or '' if c.isalpha()]
    if not letters:
        return 1.0
    latin = sum(1 for c in letters if 'LATIN' in unicodedata.name(c, ''))
    return latin / len(letters)


def classify(num_text, title):
    """Tipo de entrada de la página de la serie:
    'single' = libro individual; 'pack' = pack, estuche o recopilación;
    'extra' = edición dividida o extranjera, libro sin publicar o complemento."""
    if is_compilation(num_text, title):
        return 'pack', _('box set or collection')
    if num_text and re.search(r'\bpart\b|\bparte\b|\bvol(ume|umen)?\b', num_text, re.I):
        return 'extra', _('edition split into parts')
    if latin_ratio(title) < 0.5:
        return 'extra', _('edition in another script')
    if re.fullmatch(r'\s*(untitled|sin t[ií]tulo|tba|tbd)\s*(#?\d+)?\s*', title or '', re.I):
        return 'extra', _('book not published yet')
    if parse_index(num_text) is None:
        return 'extra', _('companion book without a number in the series')
    return 'single', ''


def same_index(a, b):
    return a is not None and b is not None and abs(float(a) - float(b)) < 0.001


# --------------------------------------------------------------------- caché

def cache_dir():
    from calibre.utils.config import config_dir
    path = os.path.join(config_dir, 'plugins', 'goodreads_series_explorer_cache')
    os.makedirs(path, exist_ok=True)
    return path


def clear_cache():
    """Borra la caché; devuelve cuántos archivos se eliminaron."""
    path = cache_dir()
    count = 0
    for name in os.listdir(path):
        if name.endswith('.gz'):
            try:
                os.remove(os.path.join(path, name))
                count += 1
            except OSError:
                pass
    return count


# Señales de que Goodreads devolvió una página de verificación o bloqueo en vez
# del contenido real (suele llegar con código 200 o 202, por eso no da error)
BLOCK_MARKERS = (
    'awswaf', 'gokuprops', 'challenge-container', 'captcha', 'are you a robot',
    'verify you are human', 'javascript is disabled', 'enable javascript',
    'request could not be satisfied', 'access denied',
)
# Algo que toda página real de Goodreads trae
REAL_PAGE_MARKERS = ('og:title', '__next_data__', 'booktitle', 'tablelist', '| goodreads',
                     'listwithdividers', 'responsiveseriesheader', 'elementlist')


def page_problem(url, data):
    """Devuelve una descripción si la respuesta de Goodreads no es una página real
    (bloqueo, verificación o página vacía), o None si parece válida."""
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc != 'www.goodreads.com' or '/auto_complete' in parsed.path:
        return None
    if not data:
        return 'respuesta vacía'
    text = data[:400000].decode('utf-8', 'replace').lower()
    # Una página con contenido real es válida aunque traiga scripts de protección
    if any(m in text for m in REAL_PAGE_MARKERS):
        return None
    for marker in BLOCK_MARKERS:
        if marker in text:
            return f'página de verificación o bloqueo ("{marker}", {len(data) // 1024} KB)'
    # Fichas, series, autores y ediciones siempre traen título; la búsqueda puede venir vacía
    content_page = any(k in parsed.path for k in ('/book/show/', '/book/isbn/', '/series/',
                                                  '/work/editions/', '/author/'))
    if content_page:
        return f'no parece una página de Goodreads ({len(data) // 1024} KB, sin título)'
    return None


class PageCache:
    def __init__(self, settings=None):
        self.path = cache_dir()
        settings = settings or {}
        self.days_lists = float(settings.get('cache_days_series', CACHE_DAYS_SERIES))
        self.days_other = float(settings.get('cache_days_other', CACHE_DAYS_OTHER))

    def _file(self, url):
        return os.path.join(self.path, hashlib.sha1(url.encode('utf-8')).hexdigest() + '.gz')

    def _max_age(self, url):
        is_list = '/series/' in url or '/author/list/' in url
        return (self.days_lists if is_list else self.days_other) * 86400

    def get(self, url):
        f = self._file(url)
        try:
            if time.time() - os.path.getmtime(f) > self._max_age(url):
                return None
            with gzip.open(f, 'rb') as fh:
                data = fh.read()
        except OSError:
            return None
        # Páginas de bloqueo guardadas por versiones anteriores: se descartan
        if page_problem(url, data):
            try:
                os.remove(f)
            except OSError:
                pass
            return None
        return data

    def put(self, url, data):
        f = self._file(url)
        tmp = f'{f}.{os.getpid()}.{threading.get_ident()}.tmp'
        try:
            with gzip.open(tmp, 'wb') as fh:
                fh.write(data)
            os.replace(tmp, f)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass


# ------------------------------------------------- acceso a Goodreads

# Momento del último pedido real, compartido por todos los hilos del complemento
_last_request = [0.0]
_request_lock = threading.Lock()

# Navegador interno de calibre (Chromium), compartido y creado a demanda
_web_browser = []
_web_lock = threading.Lock()
# En modo automático: desde cuándo se usa el navegador interno tras un bloqueo
_browser_since = [0.0]
BROWSER_STICKY_SECONDS = 30 * 60


def web_browser():
    with _web_lock:
        if not _web_browser:
            from calibre.scraper.qt import WebEngineBrowser
            _web_browser.append(WebEngineBrowser())
        return _web_browser[0]


# ------------------------------------------------ Camoufox (calibre 9.17+)

def camoufox_available():
    try:
        import calibre.web.automate.browser  # noqa
        return True
    except Exception:
        return False


class CamoufoxFetcher:
    """Navegador Camoufox de calibre (un Firefox preparado para pasar los
    controles antirrobots), en su propio hilo con su propio bucle asyncio.
    Lo comparten todos los hilos del complemento; se cierra al cerrar la ventana."""

    READY = re.compile('|'.join(re.escape(m) for m in REAL_PAGE_MARKERS), re.IGNORECASE)

    def __init__(self):
        self.loop = None
        self.browser = None
        self.page = None
        self.failed = None
        self.lock = threading.Lock()

    def _start_loop(self):
        import asyncio
        with self.lock:
            if self.loop is None:
                self.loop = asyncio.new_event_loop()
                threading.Thread(target=self.loop.run_forever, name='GRSeriesCamoufox', daemon=True).start()
        return self.loop

    async def _launch(self):
        from calibre.web.automate.browser import Browser, Warmup
        # Un par de sitios comunes antes de Goodreads: así no parece un navegador recién creado
        br = Browser(headless=True, warmup=Warmup(min_num=1, max_num=2,
                                                  excluded_domains=('goodreads.com',)))
        await br.launch()
        # Se guarda recién cuando arrancó: si falla, se usa el otro navegador
        self.page = await br.new_page()
        self.browser = br

    async def _get(self, url, timeout):
        import asyncio
        if self.browser is None:
            await self._launch()
        deadline = time.monotonic() + timeout
        await self.page.open(url, wait='domcontentloaded', timeout=timeout)
        html = ''
        # Si Goodreads muestra un desafío antirrobots, el navegador lo resuelve y
        # recarga la página: se espera a que aparezca el contenido real
        while True:
            try:
                html = await self.page.html()
            except Exception:
                html = ''
            if self.READY.search(html or '') or time.monotonic() > deadline:
                break
            await asyncio.sleep(1)
        return (html or '').encode('utf-8')

    def get(self, url, timeout=45):
        import asyncio
        if self.failed:
            raise BrowserUnavailable(self.failed)
        loop = self._start_loop()
        # El primer pedido incluye abrir el navegador (y, si nunca se usó, que
        # calibre lo descargue), por eso la espera larga
        fut = asyncio.run_coroutine_threadsafe(self._get(url, timeout), loop)
        try:
            return fut.result(timeout + (600 if self.browser is None else 30))
        except BrowserUnavailable:
            raise
        except Exception as e:
            if self.browser is None:
                self.failed = str(e) or e.__class__.__name__
                raise BrowserUnavailable(self.failed)
            raise

    def close(self):
        import asyncio
        loop, self.loop = self.loop, None
        if loop is None:
            return

        async def _close():
            br, self.browser, self.page = self.browser, None, None
            if br is not None:
                try:
                    await br.close()
                except Exception:
                    pass

        fut = asyncio.run_coroutine_threadsafe(_close(), loop)

        def stop():
            try:
                fut.result(60)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        threading.Thread(target=stop, daemon=True).start()


_camoufox = []
_camoufox_lock = threading.Lock()


def camoufox():
    with _camoufox_lock:
        if not _camoufox:
            _camoufox.append(CamoufoxFetcher())
        return _camoufox[0]


def shutdown_browser():
    """Cierra Camoufox (se llama al cerrar la ventana del complemento)."""
    with _camoufox_lock:
        cf = _camoufox.pop() if _camoufox else None
    if cf is not None:
        cf.close()


def _is_timeout(e):
    """True si el error es un tiempo de espera agotado (o una conexión cortada)."""
    import socket
    seen = 0
    while e is not None and seen < 5:
        if isinstance(e, (socket.timeout, TimeoutError, ConnectionResetError)):
            return True
        text = str(e).lower()
        if 'timed out' in text or 'timeout' in text or 'connection reset' in text:
            return True
        e = getattr(e, 'reason', None) or e.__cause__ or e.__context__
        seen += 1
    return False


class GoodreadsClient:
    def __init__(self, log, settings=None):
        self.log = log
        self.settings = settings if settings is not None else load_settings()
        configure_language(self.settings)
        self.mode = self.settings.get('connection_mode', 'auto')
        self.pause = float(self.settings.get('request_pause', REQUEST_PAUSE))
        self.cache = PageCache(self.settings)
        self.br = None
        self.aborted = lambda: False
        self.network_requests = 0
        self.cache_hits = 0

    def _browser(self):
        if self.br is None:
            # Navegador incluido en calibre (requests no viene con calibre)
            from calibre import browser
            br = browser(user_agent=USER_AGENT)
            br.addheaders += [
                ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,'
                           'image/avif,image/webp,*/*;q=0.8'),
                ('Accept-Language', _lang.accept_language(TARGET_CODE)),
                ('Referer', GOODREADS + '/'),
            ]
            self.br = br
        return self.br

    def fetch(self, url, cache_only=False, quiet=False, timeout=12):
        cached = self.cache.get(url)
        if cached is not None:
            self.cache_hits += 1
            if not quiet:
                self.log(f'· {url} (desde la caché)')
            return cached
        if cache_only:
            raise NotCached(url)

        is_goodreads = urllib.parse.urlparse(url).netloc == 'www.goodreads.com'
        use_browser = is_goodreads and (
            self.mode == 'browser'
            or (self.mode == 'auto' and time.time() - _browser_since[0] < BROWSER_STICKY_SECONDS))
        try:
            return self._network_fetch(url, quiet, timeout, use_browser)
        except BrowserUnavailable as e:
            # Sin navegador interno: se usa la conexión normal
            self.log(f'   El navegador interno de calibre no está disponible ({e}); '
                     f'se usa la conexión normal.')
            self.mode = 'normal'
            return self._network_fetch(url, quiet, timeout, False)
        except RateLimited as blocked:
            if not (is_goodreads and self.mode == 'auto' and not use_browser):
                raise
            first_block = blocked
        # Modo automático: Goodreads bloqueó la conexión normal; se reintenta con el
        # navegador interno de calibre y se sigue usando un rato
        self.log('   Se reintenta con el navegador interno de calibre.')
        _browser_since[0] = time.time()
        try:
            return self._network_fetch(url, quiet, timeout, True)
        except BrowserUnavailable as e:
            self.log(f'   El navegador interno de calibre no está disponible ({e}).')
            self.mode = 'normal'
            _browser_since[0] = 0.0
            raise first_block

    def _wait_turn(self, url):
        # Solo se espacian los pedidos a Goodreads; las portadas vienen de otros
        # servidores y no cuentan para el límite
        if urllib.parse.urlparse(url).netloc == 'www.goodreads.com':
            with _request_lock:
                wait = self.pause - (time.time() - _last_request[0])
                if wait > 0:
                    time.sleep(wait)
                _last_request[0] = time.time()

    def _browser_open(self, url, timeout):
        """Descarga con el navegador interno de calibre: Camoufox si está
        (calibre 9.17 o posterior), si no el Chromium de calibre. Devuelve (datos, código)."""
        if camoufox_available():
            try:
                return camoufox().get(url, timeout=max(timeout, 45)), None
            except BrowserUnavailable as e:
                self.log(f'   Camoufox no está disponible ({e}); se usa el navegador Chromium de calibre.')
        try:
            br = web_browser()
        except Exception as e:
            raise BrowserUnavailable(str(e))
        try:
            resp = br.open_novisit(url, timeout=max(timeout, 30))
            data = resp.read()
            return data, getattr(resp, 'status', None)
        except Exception as e:
            m = re.search(r'\b([45]\d\d)\b', str(e))
            err = Exception(str(e))
            err.code = int(m.group(1)) if m else None
            raise err

    def _network_fetch(self, url, quiet, timeout, use_browser):
        how = ((' (Camoufox)' if camoufox_available() and not camoufox().failed else ' (navegador interno)')
               if use_browser else '')
        for attempt in range(2):
            if self.aborted():
                return None
            self._wait_turn(url)
            if not quiet:
                self.log(f'→ {url}{how}')
            self.network_requests += 1
            try:
                if use_browser:
                    data, status = self._browser_open(url, timeout)
                else:
                    resp = self._browser().open_novisit(url, timeout=timeout)
                    data = resp.read()
                    status = getattr(resp, 'code', None)
                    if status is None and hasattr(resp, 'getcode'):
                        status = resp.getcode()
            except BrowserUnavailable:
                raise
            except Exception as e:
                code = getattr(e, 'code', None)
                if not quiet:
                    self.log(f'   Error: {"HTTP " + str(code) if code else e}')
                if code in RATE_LIMIT_CODES:
                    raise RateLimited(f'HTTP {code}')
                if code is None and not use_browser and _is_timeout(e) and \
                        urllib.parse.urlparse(url).netloc == 'www.goodreads.com':
                    # Goodreads a veces no bloquea con un mensaje: deja la conexión
                    # colgada. Se trata como un bloqueo para pasar al navegador interno.
                    raise RateLimited('Goodreads no respondió (tiempo de espera agotado)')
                if code in RETRY_CODES and attempt == 0:
                    time.sleep(3)
                    continue
                if code is None:
                    raise
                raise HttpError(code)
            if status and status >= 400 and status not in (404,):
                if not quiet:
                    self.log(f'   Error: HTTP {status}')
                if status in RATE_LIMIT_CODES:
                    raise RateLimited(f'HTTP {status}')
                raise HttpError(status)
            if status == 404:
                raise HttpError(404)
            problem = page_problem(url, data)
            if status == 202 and not problem:
                problem = 'respuesta 202 (verificación de Goodreads)'
            if problem:
                # No se guarda en la caché y se frena: es un bloqueo temporal
                if not quiet:
                    self.log(f'   Goodreads no devolvió la página real: {problem}.')
                raise RateLimited(problem)
            if not quiet:
                self.log(f'   OK, {len(data) // 1024} KB')
            if data:
                self.cache.put(url, data)
            return data
        return None

    def html(self, url, cache_only=False, quiet=False):
        raw = self.fetch(url, cache_only=cache_only, quiet=quiet)
        return raw.decode('utf-8', 'replace') if raw else None

    def try_html(self, url, cache_only=False, quiet=False):
        """Como html(), pero devuelve None ante errores comunes.
        Un bloqueo (RateLimited) se deja pasar para frenar todo."""
        try:
            return self.html(url, cache_only=cache_only, quiet=quiet)
        except (HttpError, NotCached):
            return None
        except RateLimited:
            raise
        except Exception as e:
            self.log(f'   Error al leer {url}: {e}')
            return None

    def image(self, url, cache_only=False):
        if not url:
            return None
        try:
            data = self.fetch(url, cache_only=cache_only, quiet=True, timeout=10)
        except (RateLimited, HttpError, NotCached):
            return None
        except Exception:
            return None
        return data if data and len(data) > 500 else None

    def open_library_cover(self, isbn=None, gr_id=None, cache_only=False):
        urls = []
        if isbn:
            urls.append(f'https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false')
        if gr_id:
            urls.append(f'https://covers.openlibrary.org/b/goodreads/{gr_id}-L.jpg?default=false')
        for url in urls:
            data = self.image(url, cache_only=cache_only)
            if data:
                return data
        return None


# ------------------------------------------------------------ análisis HTML

def format_url(href):
    if not href:
        return None
    if href.startswith('//'):
        return 'https:' + href
    if href.startswith('http'):
        return href
    return GOODREADS + href


def book_id_from_url(url):
    m = re.search(r'/book/show/(\d+)', url or '')
    return m.group(1) if m else None


def clean_isbn(value):
    isbn = re.sub(r'[^0-9Xx]', '', str(value or '')).upper()
    return isbn if len(isbn) in (10, 13) else None


def first_with_text(node, selectors):
    for sel in selectors:
        for tag in node.select(sel):
            if tag.get_text(strip=True):
                return tag
    return None


# Letras con signos propias de cada idioma. Un título con otras letras con signos
# (ă, ș, ț, ł, ø...) es de una edición extranjera.
_OWN_LETTERS = {
    'eng': '', 'spa': 'áéíóúüñ', 'por': 'áâãàçéêíóôõú', 'fra': 'àâæçéèêëîïôœùûüÿ',
    'deu': 'äöüß', 'ita': 'àèéìíîòóùú', 'cat': 'àçéèíïóòúü·', 'glg': 'áéíóúñü',
    'nld': 'éëïöü', 'pol': 'ąćęłńóśźż', 'ces': 'áčďéěíňóřšťúůýž', 'ron': 'ăâîșțşţ',
    'hun': 'áéíóöőúüű', 'tur': 'çğıöşü', 'swe': 'åäöé', 'dan': 'æøåé', 'nor': 'æøåé',
    'fin': 'äöå',
}


def foreign_title(title):
    """True si el título tiene letras con signos que no se usan en el idioma buscado
    (ni en inglés): normalmente es el de una edición en otro idioma."""
    own = _OWN_LETTERS.get(TARGET_CODE)
    if own is None or not title:
        return False
    for ch in title.lower():
        if ch.isalpha() and ord(ch) > 127 and ch not in own:
            # solo alfabeto latino: los otros alfabetos ya se tratan aparte
            if 'LATIN' in unicodedata.name(ch, ''):
                return True
    return False


def is_target_language(text):
    """Goodreads escribe el idioma de varias formas: 'Spanish', 'Spanish; Castilian',
    'Español'... Se acepta si cualquiera de las partes es el idioma buscado."""
    parts = re.split(r'[;,/()]', strip_accents(text or '').lower())
    return any(p.strip() in TARGET_LANGUAGES for p in parts)


def series_info(html, strict=False):
    """(url_de_la_serie, número_en_la_serie) de la ficha de un libro."""
    soup = BeautifulSoup(html, 'html.parser')
    selectors = [
        'div.BookPageTitleSection h3 a[href*="/series/"]',
        'h2#bookSeries a[href*="/series/"]',
        '#bookSeries a[href*="/series/"]',
    ]
    if not strict:
        selectors.append('a[href*="/series/"]')
    for sel in selectors:
        a = soup.select_one(sel)
        if a and a.get('href'):
            m = re.search(r'#\s*(\d+(?:\.\d+)?)', a.get_text(' ', strip=True))
            return format_url(a['href']), (float(m.group(1)) if m else None)
    if not strict:
        match = re.search(r'/series/(?:show/)?(\d+(?:-[\w-]+)?)', html)
        if match:
            return f'{GOODREADS}/series/{match.group(1)}', None
    return None, None


def series_id(url):
    m = re.search(r'/series/(?:show/)?(\d+)', url or '')
    return m.group(1) if m else None


def series_details(html):
    """(id_de_serie, nombre, número) de la ficha de un libro, o (None, '', None)."""
    soup = BeautifulSoup(html, 'html.parser')
    for sel in ('div.BookPageTitleSection h3 a[href*="/series/"]',
                'h2#bookSeries a[href*="/series/"]', '#bookSeries a[href*="/series/"]'):
        a = soup.select_one(sel)
        if a and a.get('href'):
            text = a.get_text(' ', strip=True).strip('() ')
            m = re.search(r'#\s*(\d+(?:\.\d+)?)', text)
            name = re.sub(r',?\s*#.*$', '', text).strip(' ,')
            return series_id(a['href']), name, (float(m.group(1)) if m else None)
    return None, '', None


def parse_book_page(html):
    """Título, autor, sinopsis, portada, ISBN, idioma y lista de ediciones de una
    ficha. Soporta el diseño nuevo (React) y el antiguo."""
    soup = BeautifulSoup(html, 'html.parser')
    data = {'title': '', 'author': '', 'synopsis': '', 'cover_url': '',
            'isbn': None, 'language': '', 'work_url': None}

    t = first_with_text(soup, ['h1[data-testid="bookTitle"]', 'h1#bookTitle', 'h1.Text__title1'])
    if t:
        data['title'] = t.get_text(' ', strip=True)
    else:
        og = soup.select_one('meta[property="og:title"]')
        if og and og.get('content'):
            data['title'] = og['content'].strip()

    a = first_with_text(soup, [
        'span.ContributorLink__name[data-testid="name"]',
        'a.ContributorLink span.ContributorLink__name',
        'a.authorName span[itemprop="name"]', 'a.authorName'])
    if a:
        data['author'] = a.get_text(' ', strip=True)

    desc = (soup.select_one('div[data-testid="description"] span.Formatted')
            or soup.select_one('div.BookPageMetadataSection__description span.Formatted'))
    if desc is None:
        spans = soup.select('div#description span')
        desc = spans[-1] if spans else None
    if desc is not None:
        for b in desc.select('button'):
            b.decompose()
        data['synopsis'] = desc.get_text(' ', strip=True)
    if not data['synopsis']:
        og = soup.select_one('meta[property="og:description"]')
        if og and og.get('content'):
            data['synopsis'] = og['content'].strip()

    img = (soup.select_one('div.BookCover__image img.ResponsiveImage')
           or soup.select_one('img#coverImage'))
    if img and img.get('src'):
        data['cover_url'] = format_url(img['src'])
    if not data['cover_url']:
        og = soup.select_one('meta[property="og:image"]')
        if og and og.get('content') and 'nophoto' not in og['content']:
            data['cover_url'] = format_url(og['content'])

    m = re.search(r'"language"\s*:\s*\{[^{}]*?"name"\s*:\s*"([^"]+)"', html)
    if m:
        data['language'] = m.group(1)
    else:
        m = re.search(r'itemprop=["\']inLanguage["\'][^>]*>\s*([^<]+)<', html)
        if m:
            data['language'] = m.group(1).strip()

    m = re.search(r'"isbn13"\s*:\s*"(\d{13})"', html) or re.search(r'"isbn"\s*:\s*"([\dXx]{10})"', html)
    if m:
        data['isbn'] = clean_isbn(m.group(1))

    m = re.search(r'(?:https://www\.goodreads\.com)?/work/editions/(\d+)', html)
    data['work_id'] = None
    if m:
        data['work_url'] = f'{GOODREADS}/work/editions/{m.group(1)}'
        data['work_id'] = m.group(1)
    else:
        m = re.search(r'"workId"\s*:\s*"?(\d+)', html) or re.search(r'kca://work/amzn1\.gr\.work\.v\d\.(\w+)', html)
        if m and m.group(1).isdigit():
            data['work_id'] = m.group(1)

    data['author_url'] = None
    a = soup.select_one('a.ContributorLink[href*="/author/show/"]') or soup.select_one(
        'a.authorName[href*="/author/show/"]')
    if a:
        data['author_url'] = format_url(a['href'].split('?')[0])

    m = re.search(r'"originalTitle"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
    data['original_title'] = ''
    if m:
        try:
            data['original_title'] = json.loads(f'"{m.group(1)}"')
        except Exception:
            data['original_title'] = m.group(1)

    data['canonical_id'] = None
    for sel in ('link[rel="canonical"]', 'meta[property="og:url"]'):
        tag = soup.select_one(sel)
        href = tag and (tag.get('href') or tag.get('content'))
        if href and book_id_from_url(href):
            data['canonical_id'] = book_id_from_url(href)
            break
    return data


# ------------------------------------------------- parecido de títulos

STOPWORDS = {
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 'de', 'del', 'y', 'e', 'o',
    'en', 'a', 'al', 'con', 'por', 'para', 'lo',
    'the', 'an', 'of', 'and', 'or', 'to', 'in', 'on', 'for', 'with',
}


def main_title(title):
    """Título sin subtítulo: lo que está antes de ':' o ' - '."""
    t = clean_title(title or '')
    part = re.split(r'\s*[:–—]\s*|\s+-\s+|\.\s+', t, maxsplit=1)[0].strip()
    return part if len(part) >= 2 else t


def title_tokens(title):
    words = norm_title(title).split()
    tokens = {w for w in words if w not in STOPWORDS}
    return tokens or set(words)


def title_similarity(a, b):
    """Parecido entre dos títulos de 0 a 1. Compara el título completo y el título
    sin subtítulo, y se queda con el mejor."""
    best = 0.0
    for x in {a, main_title(a)}:
        for y in {b, main_title(b)}:
            nx, ny = norm_title(x), norm_title(y)
            if not nx or not ny:
                continue
            if nx == ny:
                return 1.0
            tx, ty = title_tokens(x), title_tokens(y)
            if not tx or not ty:
                continue
            common = len(tx & ty)
            score = 2 * common / (len(tx) + len(ty))
            # Un título contenido entero en el otro también cuenta (subtítulos)
            if common == min(len(tx), len(ty)):
                score = max(score, 0.8 if min(len(tx), len(ty)) >= 2 else 0.6)
            best = max(best, score)
    return best


def surname(author):
    if not author:
        return ''
    if ',' in author:
        return author.split(',')[0].strip()
    parts = author.split()
    return parts[-1] if parts else ''


def index_in_title(raw_title):
    """'Alas de sangre (Empíreo, #1)' -> 1.0"""
    m = re.search(r'#\s*(\d+(?:\.\d+)?)\s*[)\]]', raw_title or '')
    return float(m.group(1)) if m else None


def query_variants(title, authors):
    """Consultas de la más precisa a la más amplia."""
    full = re.sub(r'\s*[(\[][^()\[\]]*[)\]]', '', clean_title(title or '')).strip()
    short = main_title(full)
    last = surname(authors[0]) if authors else ''
    variants = []
    for q in ([f'{full} {last}', f'{short} {last}'] if last else []) + [full, short]:
        q = ' '.join(q.split())
        if q and q not in variants:
            variants.append(q)
    return variants


def autocomplete_results(raw):
    """Resultados del autocompletado de Goodreads (JSON) como
    [(url, título, autor, url_del_autor)]. Devuelve None si la respuesta no es la esperada."""
    try:
        items = json.loads(raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw)
    except Exception:
        return None
    if not isinstance(items, list):
        return None
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        book_id = str(item.get('bookId') or '')
        url = item.get('bookUrl') or (f'/book/show/{book_id}' if book_id else '')
        title = item.get('title') or item.get('bookTitleBare') or ''
        author = item.get('author') or {}
        author_url = ''
        if isinstance(author, dict):
            if author.get('id'):
                author_url = f"{GOODREADS}/author/show/{author['id']}"
            author = author.get('name', '')
        else:
            author = str(author)
        if url and title:
            results.append((format_url(url.split('?')[0]), title, author, author_url))
    return results


def search_results(html):
    """Lista de (url_del_libro, título, autor, url_del_autor) de una página de búsqueda."""
    soup = BeautifulSoup(html, 'html.parser')
    rows = soup.select('tr[itemtype*="Book"]') or soup.select('table.tableList tr')
    results = []
    for row in rows:
        link = row.select_one('a.bookTitle[href*="/book/show/"]')
        if not link:
            continue
        author = row.select_one('a.authorName span[itemprop="name"], a.authorName')
        author_link = row.select_one('a.authorName[href*="/author/show/"]')
        results.append((format_url(link['href'].split('?')[0]),
                        link.get_text(' ', strip=True),
                        author.get_text(' ', strip=True) if author else '',
                        format_url(author_link['href'].split('?')[0]) if author_link else ''))
    return results


def parse_card(card):
    t_tag = first_with_text(card, [
        'a.bookTitle', '[data-testid="bookTitle"]',
        'span[itemprop="name"]', 'a[href*="/book/show/"]'])
    title = t_tag.get_text(strip=True) if t_tag else ''
    if not title:
        return None

    link = t_tag if t_tag.name == 'a' and t_tag.get('href') else (
        t_tag.find_parent('a', href=True) or card.select_one('a[href*="/book/show/"]'))
    book_url = format_url(link['href'].split('?')[0]) if link else ''

    num_tag = first_with_text(card, [
        'h3', 'span.seriesItem__number', 'div.responsiveBookCard__seriesNum', '.bookSeries'])
    num = num_tag.get_text(strip=True) if num_tag else ''

    a_tag = first_with_text(card, [
        'span[itemprop="author"] a', 'a.authorName', 'a[href*="/author/show/"]'])
    author = a_tag.get_text(strip=True) if a_tag else ''

    rating = ''
    r_tag = first_with_text(card, [
        'span[itemprop="ratingValue"]', 'div.communityRating', 'span.minirating'])
    if r_tag:
        match = re.search(r'\d+[.,]\d+', r_tag.get_text(' ', strip=True))
        rating = match.group(0) if match else ''

    synopsis = ''
    syn_tag = card.select_one(
        'div.formattedTextWithMore, span.Formatted, span.readable, '
        'div.responsiveBookCard__description, div.description')
    if syn_tag:
        for b in syn_tag.select('button'):
            b.decompose()
        for a in syn_tag.select('a'):
            if a.get_text(strip=True).lower() in MORE_TEXTS:
                a.decompose()
        synopsis = syn_tag.get_text(separator=' ', strip=True)

    cover_url = ''
    for img in card.find_all('img'):
        src = img.get('src') or img.get('data-src') or ''
        if src and 'nophoto' not in src and any(
                k in src for k in ('gr-assets', 'amazon', 'goodreads')):
            cover_url = format_url(src)
            break

    m = re.search(r'workId(?:&quot;|")?\s*[:=]\s*(?:&quot;|")?(\d+)|/work/editions/(\d+)', str(card))
    work_id = (m.group(1) or m.group(2)) if m else None

    return {
        'work_id': work_id,
        'num': num,
        'index': parse_index(num),
        'title': clean_title(title),
        'original_title': clean_title(title),
        'author': author,
        'rating': rating,
        'synopsis': synopsis,
        'cover_url': cover_url,
        'cover_data': None,
        'gr_id': book_id_from_url(book_url),
        'book_url': book_url,
        'isbn': None,
        'spanish': TARGET_IS_ENGLISH,   # en inglés no hace falta buscar otra edición
        'foreign_title': foreign_title(title),
        'lib_id': None,
        'kind': classify(num, title)[0],
        'kind_reason': classify(num, title)[1],
        'compilation': is_compilation(num, title),
        # 'found' = hay edición en español, 'none' = no hay, 'unknown' = sin buscar
        'es_status': 'found' if TARGET_IS_ENGLISH else 'unknown',
    }


def parse_series_page(html):
    soup = BeautifulSoup(html, 'html.parser')
    series_name = _('Goodreads series')
    title_tag = soup.select_one('div.responsiveSeriesHeader__title h1, h1')
    if title_tag:
        name = re.sub(r'\s+Series$', '', title_tag.get_text(' ', strip=True), flags=re.I)
        if name:
            series_name = name

    cards = soup.select('div.listWithDividers__item')
    if not cards:
        cards = soup.select('div.seriesItem, div.responsiveBookCard, '
                            'div[itemtype*="Book"], tr[itemtype*="Book"]')
    if not cards:
        cards = [p for p in (a.find_parent(['tr', 'li', 'div'])
                             for a in soup.select('a[href*="/book/show/"]')) if p]

    books, seen = [], set()
    for card in cards:
        parsed = parse_card(card)
        if not parsed:
            continue
        key = parsed['gr_id'] or (parsed['num'].lower(), parsed['title'].lower())
        if key in seen:
            continue
        seen.add(key)
        books.append(parsed)
    return series_name, books


# --------------------------------------------- búsqueda de la edición en español

def apply_edition(book, html, require_language, log):
    info = parse_book_page(html)
    if require_language and info['language'] and not is_target_language(info['language']):
        log(f'   Esa edición está en {info["language"]}, no en {TARGET_NAME}.')
        return False
    if not info['title']:
        return False
    book['title'] = clean_title(info['title'])
    if info['synopsis']:
        book['synopsis'] = info['synopsis']
    if info['cover_url']:
        book['cover_url'] = info['cover_url']
    if info['isbn']:
        book['isbn'] = info['isbn']
    book['spanish'] = True
    return True


def find_spanish_edition(client, book, cache_only=False):
    """Busca en la lista de ediciones del libro la más popular en español y aplica
    sus datos. Devuelve 'found', 'none' (no hay edición en español) o 'unknown'
    (no se pudo averiguar, por ejemplo porque no estaba en la caché)."""
    log = client.log
    if TARGET_IS_ENGLISH:
        # Goodreads ya muestra los datos en inglés: no hace falta buscar otra edición
        book['spanish'] = True
        return 'found'
    if not book['book_url']:
        return 'none'
    html = client.try_html(book['book_url'], cache_only=cache_only)
    if not html:
        return 'unknown'
    work_url = parse_book_page(html)['work_url']
    if not work_url:
        log('   No se encontró el enlace a la lista de ediciones.')
        return 'none'

    params = urllib.parse.urlencode({
        'utf8': '✓', 'sort': 'num_ratings', 'per_page': 100,
        'filter_by_format': '', 'filter_by_language': _lang.goodreads_code(TARGET_CODE),
    })
    html = client.try_html(f'{work_url}?{params}', cache_only=cache_only)
    if not html:
        return 'unknown'

    soup = BeautifulSoup(html, 'html.parser')
    editions = soup.select('div.elementList')
    languages = []
    for edition in editions:
        language = ''
        for row in edition.select('div.dataRow'):
            label = row.select_one('div.dataTitle')
            value = row.select_one('div.dataValue')
            if label and value and 'language' in label.get_text(strip=True).lower():
                language = value.get_text(strip=True)
                break
        languages.append(language or '?')
        if not is_target_language(language):
            continue
        link = edition.select_one('a.bookTitle[href*="/book/show/"]')
        if not link:
            continue
        url = format_url(link['href'].split('?')[0])
        log(f'   Edición en {TARGET_NAME}: "{link.get_text(strip=True)}"')
        page = client.try_html(url, cache_only=cache_only)
        if not page:
            return 'unknown'
        if apply_edition(book, page, False, log):
            book['edition_gr_id'] = book_id_from_url(url)
            return 'found'
        return 'none'

    if editions:
        log(f'   {len(editions)} ediciones en la lista, ninguna en {TARGET_NAME} '
            f'(idiomas vistos: {", ".join(sorted(set(languages)))}).')
        return 'none'
    log('   La lista de ediciones vino vacía o con otro formato '
        '(puede que Goodreads pida iniciar sesión).')
    return 'unknown'


def load_cover(client, book, cache_only=False):
    book['cover_data'] = (client.image(book['cover_url'], cache_only=cache_only)
                          or client.open_library_cover(book['isbn'], book.get('edition_gr_id'),
                                                       cache_only=cache_only))


# ------------------------------------------- tus ediciones en Goodreads

# Fichas nuevas (no guardadas en la caché) que se leen por apertura para conocer
# la obra y la serie de tus libros; el resto se completa en las siguientes
MAX_LIBRARY_PAGES = 12


def read_library_editions(client, library_books, log, aborted=lambda: False):
    """Para cada libro tuyo con ID de Goodreads, lee su ficha (desde la caché si
    está) y anota la obra, la serie y el número que tiene en Goodreads.
    Devuelve cuántos quedaron sin leer por el tope de consultas."""
    new_pages = 0
    pending = 0
    max_pages = int(client.settings.get('max_new_pages', MAX_LIBRARY_PAGES))
    for lb in library_books:
        if lb.get('gr_checked') or not lb.get('gr_id'):
            continue
        if aborted():
            break
        url = f"{GOODREADS}/book/show/{lb['gr_id']}"
        html = client.try_html(url, cache_only=True, quiet=True)
        if html is None:
            if new_pages >= max_pages:
                pending += 1
                continue
            new_pages += 1
            html = client.try_html(url, quiet=True)   # un bloqueo se propaga
        if not html:
            continue
        info = parse_book_page(html)
        sid, sname, sidx = series_details(html)
        lb['work_id'] = info.get('work_id')
        lb['gr_series_id'] = sid
        lb['gr_series_name'] = sname
        lb['gr_series_index'] = sidx
        lb['gr_checked'] = True
    known = sum(1 for lb in library_books if lb.get('gr_checked'))
    with_id = sum(1 for lb in library_books if lb.get('gr_id'))
    log(f'Tus ediciones en Goodreads: {known} de {with_id} leídas'
        f' ({new_pages} consultas nuevas{f", {pending} quedan para la próxima" if pending else ""}).')
    return pending


MAX_WORK_LOOKUPS = 15


def match_by_work(client, books, library_books, used, log, aborted=lambda: False):
    """Segundo paso: si quedan libros tuyos sin ubicar que tienen obra conocida,
    se lee la ficha de los libros faltantes para conocer su obra. Es la misma
    ficha que usa la búsqueda en español, así que no suma consultas."""
    pending_works = {lb['work_id']: lb for lb in library_books
                     if lb.get('work_id') and lb['id'] not in used}
    if not pending_works:
        return
    lookups = 0
    for b in books:
        if not pending_works or aborted() or lookups >= MAX_WORK_LOOKUPS:
            break
        if b.get('lib_id') or b.get('kind') != 'single' or not b.get('book_url'):
            continue
        if not b.get('work_id'):
            html = client.try_html(b['book_url'], quiet=True)
            lookups += 1
            if not html:
                continue
            b['work_id'] = parse_book_page(html).get('work_id')
        lb = pending_works.pop(b.get('work_id'), None)
        if lb:
            used.add(lb['id'])
            b['lib_id'] = lb['id']
            log(f'   ✓ "{b["original_title"]}" = tu "{lb["title"]}" (misma obra en Goodreads)')


def match_owned(book, library_books, series_id_=None, series_names=(), used=None):
    """Busca el libro de Goodreads entre los tuyos. Devuelve (libro_tuyo, motivo).
    Orden: mismo ID, misma obra, tu edición figura con ese número en esa serie,
    serie y número de calibre, título parecido."""
    used = used if used is not None else set()
    candidates = [lb for lb in library_books if lb['id'] not in used]
    if book.get('gr_id'):
        for lb in candidates:
            if lb.get('gr_id') == book['gr_id']:
                return lb, 'mismo ID de Goodreads'
    if book.get('work_id'):
        for lb in candidates:
            if lb.get('work_id') and lb['work_id'] == book['work_id']:
                return lb, 'misma obra en Goodreads'
    idx = book.get('index')
    if idx is not None:
        names = {norm_series(n) for n in series_names if n}
        names.discard('')
        for lb in candidates:
            same_series = (series_id_ and lb.get('gr_series_id') == series_id_) or (
                lb.get('gr_series_name') and norm_series(lb['gr_series_name']) in names)
            if same_series and same_index(lb.get('gr_series_index'), idx):
                return lb, f'tu edición figura en Goodreads como #{idx:g} de la serie'
        for lb in candidates:
            if norm_series(lb.get('series')) in names and same_index(lb.get('series_index'), idx):
                return lb, f'serie "{lb.get("series")}" #{idx:g} en calibre'
    for title in {book.get('title'), book.get('original_title')}:
        key = norm_title(title)
        if not key:
            continue
        for lb in candidates:
            if norm_title(lb.get('title')) == key:
                return lb, 'mismo título'
    return None, None


# =================================================== hilo: la serie completa

class FetchSeriesWorker(QThread):
    data_loaded = pyqtSignal(list, str, str)   # libros, nombre de la serie, aviso
    match_found = pyqtSignal(str, str)         # ID de Goodreads encontrado por búsqueda, título
    not_found = pyqtSignal(str)                # sin serie: URL del autor (o vacío)
    author_found = pyqtSignal(str)             # URL del autor en Goodreads
    progress = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    diagnostics = pyqtSignal(str)

    def __init__(self, query_book, library_books):
        """query_book: dict con id, title, authors, identifiers, series, series_index.
        library_books: libros del mismo autor que ya están en la biblioteca."""
        super().__init__()
        self.query = dict(query_book)
        self.identifiers = dict(self.query.get('identifiers') or {})
        self.library_books = list(library_books or [])
        self._aborted = False
        self._log = []
        self.client = GoodreadsClient(self.log)
        self.client.aborted = lambda: self._aborted
        # Ficha del libro consultado, si se encontró al buscar la serie
        self.query_edition_url = None
        # (ID de Goodreads, título) si la edición se encontró por búsqueda o ISBN,
        # para ofrecer guardarlo en calibre
        self.search_match = None
        self.autocomplete_ok = True
        # Página del autor en Goodreads, para la vista por autor
        self.author_url = None

    def abort(self):
        self._aborted = True

    def log(self, message):
        self._log.append(f'[{time.strftime("%H:%M:%S")}] {message}')

    def _get_goodreads_id(self):
        ids = self.identifiers
        for key in ('goodreads', 'goodreads_id', 'gr'):
            if key in ids:
                match = re.search(r'\d+', str(ids[key]))
                if match:
                    return match.group(0)
        for k, v in ids.items():
            if 'goodreads' in k.lower():
                match = re.search(r'\d+', str(v))
                if match:
                    return match.group(0)
        return None

    # -------------------------------------------------- búsqueda de la serie

    def _score_candidate(self, r_title, r_author, position):
        """Puntaje de un resultado de búsqueda antes de abrir su ficha."""
        title = self.query.get('title') or ''
        authors = [a for a in (self.query.get('authors') or []) if a not in ('Unknown', 'Desconocido')]
        sim = title_similarity(title, r_title)
        author_ok = None
        if authors and r_author:
            author_ok = authors_match(authors, r_author)
        score = sim * 60
        if author_ok:
            score += 30
        elif author_ok is False:
            score -= 100
        own_index = self.query.get('series_index') if self.query.get('series') else None
        idx = index_in_title(r_title)
        if own_index is not None and idx is not None:
            score += 10 if same_index(own_index, idx) else -40
        score += max(0, 5 - position)
        return score, sim, author_ok

    def _check_book_page(self, html, source, url):
        """Verifica la ficha de un candidato. Devuelve la URL de la serie o None."""
        info = parse_book_page(html)
        authors = self.query.get('authors') or []
        if info['author'] and authors and not authors_match(authors, info['author']):
            self.log(f'   Descartado ({source}): el autor "{info["author"]}" no coincide')
            return None
        if info.get('author_url') and not self.author_url:
            self.author_url = info['author_url']
        title = self.query.get('title') or ''
        sim = max(title_similarity(title, info['title']),
                  title_similarity(title, info.get('original_title') or ''))
        if info["title"] and sim < 0.5:
            self.log(f'   Descartado ({source}): el título "{info["title"]}" no se parece '
                     f'(parecido {sim:.2f})')
            return None
        series_url, index = series_info(html, strict=True)
        if not series_url:
            self.log(f'   Descartado ({source}): "{info["title"]}" no pertenece a ninguna serie')
            return None
        own_index = self.query.get('series_index') if self.query.get('series') else None
        if own_index is not None and index is not None and not same_index(own_index, index):
            self.log(f'   Descartado ({source}): es el #{index:g} y en calibre es el #{float(own_index):g}')
            return None
        self.query_edition_url = url
        found_id = book_id_from_url(url) or info.get('canonical_id')
        if found_id:
            self.search_match = (found_id, info['title'])
            if url is None:
                self.query_edition_url = f'{GOODREADS}/book/show/{found_id}'
        self.log(f'   Aceptado ({source}): "{info["title"]}" -> {series_url}')
        return series_url

    def _search_candidates(self, query):
        """Candidatos para una consulta: primero el autocompletado; si no responde
        o no trae nada útil, la página de búsqueda. Devuelve (lista, html_si_ficha)."""
        q = urllib.parse.quote(query)
        if self.autocomplete_ok:
            try:
                raw = self.client.fetch(f'{GOODREADS}/book/auto_complete?format=json&q={q}')
                results = autocomplete_results(raw) if raw else None
            except (HttpError, NotCached):
                results = None
            if results is None:
                self.autocomplete_ok = False
                self.log('   El autocompletado no respondió como se esperaba; '
                         'se usa la página de búsqueda.')
            elif results:
                return results, None
        html = self.client.try_html(f'{GOODREADS}/search?q={q}')
        if not html:
            return [], None
        results = search_results(html)
        if results:
            return results, None
        # Sin lista: puede que Goodreads haya abierto directamente la ficha del libro
        info = parse_book_page(html)
        is_book_page = bool(info.get('canonical_id')) or bool(
            BeautifulSoup(html, 'html.parser').select_one('h1[data-testid="bookTitle"], h1#bookTitle'))
        return [], (html if is_book_page else None)

    def _find_series_url(self):
        client = self.client
        candidates = []
        gr_id = self._get_goodreads_id()
        if gr_id:
            candidates.append(('ID de Goodreads', f'{GOODREADS}/book/show/{gr_id}'))
        isbn = clean_isbn(self.identifiers.get('isbn'))
        if isbn:
            candidates.append(('ISBN', f'{GOODREADS}/book/isbn/{isbn}'))
        if not candidates:
            self.log('El libro no tiene ID de Goodreads ni ISBN.')

        for source, url in candidates:
            if self._aborted:
                return None
            self.log(f'Buscando la serie por {source}...')
            html = client.try_html(url)
            if not html:
                continue
            info = parse_book_page(html)
            if info.get('author_url') and not self.author_url:
                self.author_url = info['author_url']
            series_url, _ = series_info(html, strict=True)
            if series_url:
                self.query_edition_url = url
                if source == 'ISBN' and not gr_id:
                    found_id = parse_book_page(html).get('canonical_id')
                    if found_id:
                        self.search_match = (found_id, parse_book_page(html)['title'])
                self.log(f'   Serie encontrada: {series_url}')
                return series_url
            self.log(f'   La ficha encontrada por {source} no muestra ninguna serie.')

        title = self.query.get('title') or ''
        if not title.strip():
            return None
        authors = [a for a in (self.query.get('authors') or [])
                   if a not in ('Unknown', 'Desconocido')]

        checked_pages = set()
        for query in query_variants(title, authors):
            if self._aborted or len(checked_pages) >= MAX_PAGE_CHECKS:
                break
            self.log(f'Buscando: "{query}"')
            results, direct_html = self._search_candidates(query)
            if direct_html:
                self.log('   Goodreads abrió directamente una ficha; se verifica.')
                found = self._check_book_page(direct_html, 'redirección', None)
                if found:
                    return found
                continue
            if not results:
                self.log('   Sin resultados.')
                continue

            scored = []
            for pos, (book_url, r_title, r_author, r_author_url) in enumerate(results[:15]):
                score, sim, author_ok = self._score_candidate(r_title, r_author, pos)
                scored.append((score, sim, author_ok, book_url, r_title, r_author))
                if author_ok and r_author_url and not self.author_url:
                    self.author_url = r_author_url
            scored.sort(key=lambda x: -x[0])

            self.log(f'   {len(results)} resultados; los mejores:')
            for score, sim, author_ok, _, r_title, r_author in scored[:5]:
                mark = {True: 'autor ✓', False: 'otro autor', None: 'autor ?'}[author_ok]
                self.log(f'     {score:5.1f}  "{r_title}" de {r_author or "?"} '
                         f'[título {sim:.2f}, {mark}]')

            opened = 0
            for score, sim, author_ok, book_url, r_title, _ in scored:
                if opened >= 2 or len(checked_pages) >= MAX_PAGE_CHECKS:
                    break
                if sim < MIN_TITLE_SIMILARITY or author_ok is False:
                    break
                if book_url in checked_pages:
                    continue
                checked_pages.add(book_url)
                opened += 1
                book_html = client.try_html(book_url)
                if book_html:
                    found = self._check_book_page(book_html, f'"{r_title}"', book_url)
                    if found:
                        return found
            if not opened:
                self.log(f'   Ningún resultado se parece lo suficiente '
                         f'(mínimo de parecido de título: {MIN_TITLE_SIMILARITY}).')
        return None

    # --------------------------------------------- coincidencia con biblioteca

    def _match_library(self, book, series_name, series_url, used):
        return match_owned(book, self.library_books, series_id(series_url),
                           (series_name, self.query.get('series')), used)

    def _localize_owned(self, book, lib_book):
        """Libro que ya tenés: se usan tus identificadores (un solo pedido)."""
        urls = []
        if lib_book.get('gr_id'):
            urls.append(f"{GOODREADS}/book/show/{lib_book['gr_id']}")
        if lib_book.get('isbn'):
            urls.append(f"{GOODREADS}/book/isbn/{lib_book['isbn']}")
        if (lib_book.get('id') == self.query.get('id') and self.query_edition_url
                and self.query_edition_url not in urls):
            urls.append(self.query_edition_url)
        if not urls:
            self.log('   Tu ejemplar no tiene ID de Goodreads ni ISBN.')
        for url in urls:
            html = self.client.try_html(url)
            if html and apply_edition(book, html, True, self.log):
                book['edition_gr_id'] = book_id_from_url(url) or lib_book.get('gr_id')
                self.log(f'   Datos en español de tu edición: "{book["title"]}"')
                return True
        return False

    # ----------------------------------------------------------- principal

    def run(self):
        q = self.query
        self.log(f'Libro consultado: "{q.get("title")}" de {" & ".join(q.get("authors") or [])}')
        self.log(f'Identificadores: {self.identifiers or "ninguno"}')
        if q.get('series'):
            self.log(f'Serie en calibre: {q.get("series")} #{float(q.get("series_index") or 0):g}')
        self.log(f'Libros del mismo autor en la biblioteca: {len(self.library_books)}')
        try:
            self.progress.emit(_('Looking for the series on Goodreads...'))
            series_url = self._find_series_url()
            if self._aborted:
                return
            if not series_url:
                self.log('RESULTADO: no se encontró la serie; se pasa a la vista por autor.')
                self.not_found.emit(self.author_url or '')
                return

            if self.search_match and self._get_goodreads_id():
                # Ya tenés un ID (lo usás en otros complementos): no se ofrece reemplazarlo
                self.log(f'La serie se encontró con otra edición ({self.search_match[0]}); '
                         f'tu ID de Goodreads no se modifica.')
            elif self.search_match:
                self.log(f'Edición encontrada sin ID guardado: {self.search_match[0]} '
                         f'("{self.search_match[1]}"). Se ofrece guardarla en calibre.')
                self.match_found.emit(*self.search_match)

            self.log(f'Leyendo la página de la serie: {series_url}')
            html = self.client.html(series_url)
            if self._aborted or not html:
                return
            series_name, books = parse_series_page(html)
            singles = sum(1 for b in books if b['kind'] == 'single')
            self.log(f'Serie "{series_name}": {singles} libros individuales y '
                     f'{len(books) - singles} packs, ediciones extranjeras o complementos.')
            if not books:
                self.error_occurred.emit(_('The books of the series could not be extracted.'))
                return

            warning = ''
            limited = False
            try:
                self.progress.emit(_('Recognizing your books...'))
                read_library_editions(self.client, self.library_books, self.log,
                                      lambda: self._aborted)
            except RateLimited:
                limited = True
                warning = _('Goodreads limited the requests; some of your books may show '
                            'as missing. Try again in a few minutes.')
            used = set()
            for book in books:
                if book['kind'] == 'single':
                    lb, reason = self._match_library(book, series_name, series_url, used)
                    if lb:
                        used.add(lb['id'])
                        book['lib_id'] = lb['id']
                        book['match_reason'] = reason
            if not limited:
                try:
                    match_by_work(self.client, books, self.library_books, used, self.log,
                                  lambda: self._aborted)
                except RateLimited:
                    limited = True
                    warning = _('Goodreads limited the requests; some of your books may show '
                                'as missing. Try again in a few minutes.')
            by_id = {lb['id']: lb for lb in self.library_books}
            total = len(books)
            for i, book in enumerate(books, 1):
                if self._aborted:
                    return
                self.log(f'--- {book["num"] or "?"} "{book["original_title"]}" ---')
                if book['kind'] != 'single':
                    # Packs, ediciones extranjeras y complementos: no se consulta nada
                    self.log(f'   Se omite: {book["kind_reason"]}.')
                    load_cover(self.client, book, cache_only=True)
                    continue
                lib_book = by_id.get(book['lib_id'])
                reason = book.get('match_reason', 'misma obra en Goodreads')
                if lib_book:
                    self.log(f'   En tu biblioteca (ID {lib_book["id"]}, "{lib_book["title"]}") por {reason}.')
                    if not limited:
                        self.progress.emit(_('Reading your editions ({0} of {1}): {2}').format(i, total, book["original_title"]))
                        try:
                            if self._localize_owned(book, lib_book):
                                book['es_status'] = 'found'
                        except RateLimited:
                            limited = True
                            warning = _('Goodreads limited the requests. The rest is shown with the '
                                        'data of the series; try again in a few minutes.')
                            self.log('   Goodreads limitó las consultas: no se piden más páginas.')
                else:
                    self.log('   No está en tu biblioteca.')
                    # Solo si ya se buscó antes y quedó en la caché: no gasta pedidos
                    book['es_status'] = find_spanish_edition(self.client, book, cache_only=True)
                    if book['es_status'] == 'found':
                        self.log('   Edición en español tomada de la caché.')
                    elif book['es_status'] == 'unknown':
                        self.log('   Edición en español: se busca a continuación.')

                load_cover(self.client, book, cache_only=limited)

            self.log(f'RESULTADO: terminado. Pedidos a Goodreads: {self.client.network_requests}; '
                     f'desde la caché: {self.client.cache_hits}.')
            if not self._aborted:
                self.data_loaded.emit(books, series_name, warning)

        except RateLimited:
            self.log('RESULTADO: Goodreads limitó las consultas.')
            if not self._aborted:
                self.error_occurred.emit(
                    _('Goodreads limited the requests because of the number of recent requests.') + '\n'
                    + _('Wait a few minutes (sometimes up to an hour) and try again.'))
        except HttpError as e:
            self.log(f'RESULTADO: error HTTP {e.code}.')
            if not self._aborted:
                self.error_occurred.emit(
                    _('Goodreads answered with code {0}. Try again in a few minutes.').format(e.code))
        except Exception as e:
            self.log(f'RESULTADO: error inesperado: {e!r}')
            if not self._aborted:
                self.error_occurred.emit(_('Unexpected error: {0}').format(e))
        finally:
            if not self._aborted:
                if self.author_url:
                    self.author_found.emit(self.author_url)
                self.diagnostics.emit('\n'.join(self._log))


# ============================================ hilo: un libro, a pedido

class SpanishEditionWorker(QThread):
    """Busca la edición en español de un solo libro (botón de la tarjeta)."""
    finished_book = pyqtSignal(object, str, str)   # libro, estado, mensaje

    def __init__(self, book):
        super().__init__()
        self.book = book
        self._aborted = False
        self.lines = []
        self.client = GoodreadsClient(self.log)
        self.client.aborted = lambda: self._aborted

    def abort(self):
        self._aborted = True

    def log(self, message):
        self.lines.append(f'[{time.strftime("%H:%M:%S")}] {message}')

    def run(self):
        book = self.book
        self.log(f'--- Buscar en español: "{book["original_title"]}" ---')
        try:
            status = find_spanish_edition(self.client, book)
            book['es_status'] = status
            if status == 'found':
                load_cover(self.client, book)
                self.finished_book.emit(book, status, '')
            elif status == 'none':
                self.log('   Sin edición en español.')
                self.finished_book.emit(book, status, _('No edition in {0}.').format(_lang.display_name(TARGET_CODE)))
            else:
                self.finished_book.emit(book, status, _('Could not be checked; try again.'))
        except RateLimited:
            self.log('   Goodreads limitó las consultas.')
            self.finished_book.emit(book, 'limited', _('Goodreads limited the requests; try in a few minutes.'))
        except Exception as e:
            self.log(f'   Error: {e!r}')
            self.finished_book.emit(book, 'unknown', _('Error: {0}').format(e))


# =============================================== hilo: libros del autor

# Libros por página en la lista de un autor y páginas que se leen como máximo
AUTHOR_PER_PAGE = 100
AUTHOR_MAX_PAGES = 2

SERIES_IN_TITLE = re.compile(
    r'\s*\(([^()]*?),?\s*#\s*(\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?)\)\s*$')


def split_series_title(raw_title):
    """'Peón (El Tablero de las Sombras, #1)' -> ('Peón', 'El Tablero de las Sombras', '1')."""
    m = SERIES_IN_TITLE.search(raw_title or '')
    if not m:
        return clean_title(raw_title), '', ''
    return clean_title(raw_title[:m.start()]), m.group(1).strip(' ,'), m.group(2).replace(' ', '')


def parse_author_list(html, authors=None):
    """Libros de la lista de un autor (/author/list/ID). Devuelve (nombre, libros, hay_más).
    authors: los autores del libro en calibre, para separar los libros firmados con
    otro nombre (seudónimo) o como coautor."""
    soup = BeautifulSoup(html, 'html.parser')
    name = ''
    tag = soup.select_one('a.authorName span[itemprop="name"]') or soup.select_one('h1')
    if tag:
        name = re.sub(r'^Books by\s+', '', tag.get_text(' ', strip=True), flags=re.I)

    books = []
    for row in soup.select('tr[itemtype*="Book"]'):
        link = row.select_one('a.bookTitle[href*="/book/show/"]')
        if not link:
            continue
        raw = link.get_text(' ', strip=True)
        title, series_name, num = split_series_title(raw)
        url = format_url(link['href'].split('?')[0])
        author = row.select_one('a.authorName span[itemprop="name"], a.authorName')
        rating = ''
        mini = row.select_one('span.minirating')
        if mini:
            m = re.search(r'\d+[.,]\d+', mini.get_text(' ', strip=True))
            rating = m.group(0) if m else ''
        work = row.select_one('a[href*="/work/editions/"]')
        m = re.search(r'/work/editions/(\d+)', work['href']) if work else None
        cover = row.select_one('img.bookCover, img')
        cover_url = cover.get('src') if cover else ''
        if cover_url and 'nophoto' in cover_url:
            cover_url = ''
        num_text = f'#{num}' if num else ''
        credited = author.get_text(' ', strip=True) if author else ''
        if is_compilation(num_text, raw):
            kind, reason = 'pack', _('box set or collection')
        elif latin_ratio(title) < 0.5:
            kind, reason = 'extra', _('edition in another script')
        elif credited and (authors or name) and not authors_match(list(authors or [name]), credited):
            # Goodreads incluye en la página del autor los libros que firmó con
            # otro nombre (seudónimo) o como coautor: se muestran aparte
            kind, reason = 'extra', _('published as {0} (pen name or co-author)').format(credited)
        else:
            kind, reason = 'single', ''
        books.append({
            'work_id': m.group(1) if m else None,
            'num': num_text,
            'index': parse_index(num_text),
            'title': title,
            'original_title': title,
            'series_name': series_name,
            'author': credited,
            'rating': rating,
            'synopsis': '',
            'cover_url': format_url(cover_url) if cover_url else '',
            'cover_data': None,
            'gr_id': book_id_from_url(url),
            'book_url': url,
            'isbn': None,
            'spanish': TARGET_IS_ENGLISH,   # en inglés no hace falta buscar otra edición
            'foreign_title': foreign_title(title),
            'lib_id': None,
            'kind': kind,
            'kind_reason': reason,
            'compilation': kind == 'pack',
            'es_status': 'found' if TARGET_IS_ENGLISH else 'unknown',
        })
    more = bool(soup.select_one('a.next_page[href]'))
    return name, books, more


class AuthorWorker(QThread):
    """Lista los libros del autor en Goodreads, agrupados por serie, y marca
    cuáles tenés."""
    data_loaded = pyqtSignal(object)   # dict con author, author_url, books, warning
    progress = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    diagnostics = pyqtSignal(str)

    def __init__(self, authors, author_url, library_books):
        super().__init__()
        self.authors = [a for a in (authors or []) if a not in ('Unknown', 'Desconocido')]
        self.author_url = author_url or ''
        self.library_books = library_books
        self._aborted = False
        self.lines = []
        self.client = GoodreadsClient(self.log)
        self.client.aborted = lambda: self._aborted

    def abort(self):
        self._aborted = True

    def log(self, message):
        self.lines.append(f'[{time.strftime("%H:%M:%S")}] {message}')

    def _find_author_url(self):
        name = self.authors[0]
        q = urllib.parse.quote(name)
        self.log(f'Buscando al autor "{name}" en Goodreads...')
        results = None
        try:
            raw = self.client.fetch(f'{GOODREADS}/book/auto_complete?format=json&q={q}')
            results = autocomplete_results(raw) if raw else None
        except (HttpError, NotCached):
            results = None
        if not results:
            html = self.client.try_html(f'{GOODREADS}/search?q={q}&search_type=books&search%5Bfield%5D=author')
            results = search_results(html) if html else []
        for _, _, r_author, r_author_url in results:
            if r_author_url and authors_match(self.authors, r_author):
                self.log(f'   Autor encontrado: {r_author} ({r_author_url})')
                return r_author_url
        self.log('   No se encontró al autor.')
        return ''

    def run(self):
        self.log('=== Vista por autor ===')
        try:
            if not self.authors and not self.author_url:
                self.error_occurred.emit(_('The book has no author set.'))
                return
            self.progress.emit(_('Looking for the author\'s books on Goodreads...'))
            url = self.author_url or self._find_author_url()
            m = re.search(r'/author/(?:show|list)/(\d+)', url or '')
            if not m:
                self.error_occurred.emit(_('The author was not found on Goodreads.'))
                return
            author_id = m.group(1)

            books, name, seen = [], '', set()
            for page in range(1, AUTHOR_MAX_PAGES + 1):
                if self._aborted:
                    return
                html = self.client.html(
                    f'{GOODREADS}/author/list/{author_id}?page={page}&per_page={AUTHOR_PER_PAGE}')
                if not html:
                    break
                page_name, page_books, more = parse_author_list(html, self.authors)
                if page_name and not authors_match(self.authors, page_name):
                    page_name = ''   # era el nombre de un libro firmado con otro nombre
                name = name or page_name
                for b in page_books:
                    key = b['work_id'] or b['gr_id']
                    if key in seen:
                        continue
                    seen.add(key)
                    books.append(b)
                if not more:
                    break
            self.log(f'Autor "{name or self.authors[0]}": {len(books)} libros en Goodreads.')
            if not books:
                self.error_occurred.emit(_('The list of the author\'s books could not be read.'))
                return

            warning = ''
            try:
                self.progress.emit(_('Recognizing your books...'))
                read_library_editions(self.client, self.library_books, self.log,
                                      lambda: self._aborted)
            except RateLimited:
                warning = _('Goodreads limited the requests; some of your books may show '
                            'as missing. Try again in a few minutes.')

            used = set()
            # Primero los libros con serie (son los que más información tienen)
            for b in sorted(books, key=lambda x: (not x['series_name'], x['index'] is None)):
                if b['kind'] != 'single':
                    continue
                lb, reason = match_owned(b, self.library_books, None, (b['series_name'],), used)
                if lb:
                    used.add(lb['id'])
                    b['lib_id'] = lb['id']
                    # Se muestra tu título (normalmente en español)
                    if lb.get('title') and norm_title(lb['title']) != norm_title(b['title']):
                        b['title'] = lb['title']
                    b['spanish'] = True
                    b['es_status'] = 'found'
                    b['calibre_series'] = lb.get('series') or ''
                    self.log(f'   ✓ "{b["original_title"]}" = tu "{lb["title"]}" ({reason})')

            if not warning:
                try:
                    match_by_work(self.client, books, self.library_books, used, self.log,
                                  lambda: self._aborted)
                except RateLimited:
                    warning = _('Goodreads limited the requests; some of your books may show '
                                'as missing. Try again in a few minutes.')
            by_id = {lb['id']: lb for lb in self.library_books}
            gr_series = {norm_series(b['series_name']): b['series_name'] for b in books
                         if b['series_name']}
            for b in books:
                lb = by_id.get(b['lib_id'])
                if not lb:
                    continue
                if not b.get('spanish') and lb.get('title'):
                    if norm_title(lb['title']) != norm_title(b['title']):
                        b['title'] = lb['title']
                    b['spanish'] = True
                    b['es_status'] = 'found'
                b['calibre_series'] = lb.get('series') or ''
                # Goodreads no lo ubica en ninguna serie pero en calibre sí: se usa tu dato
                if not b['series_name'] and lb.get('series'):
                    b['series_name'] = gr_series.get(norm_series(lb['series']), lb['series'])
                    b['index'] = lb.get('series_index')
                    b['num'] = f'#{b["index"]:g} (según calibre)' if b['index'] is not None else ''
                    self.log(f'   "{b["title"]}": sin serie en Goodreads; se ubica en '
                             f'"{b["series_name"]}" por tus datos de calibre.')

            # Para entradas nuevas: el nombre de serie que ya usás en calibre
            calibre_names = {}
            for b in books:
                if b.get('calibre_series') and b['series_name']:
                    calibre_names.setdefault(b['series_name'], b['calibre_series'])
            for b in books:
                b['target_series'] = calibre_names.get(b['series_name'], b['series_name'])
                load_cover(self.client, b, cache_only=bool(warning))

            owned = sum(1 for b in books if b['lib_id'])
            self.log(f'RESULTADO: {owned} de {len(books)} en tu biblioteca. '
                     f'Pedidos a Goodreads: {self.client.network_requests}; '
                     f'desde la caché: {self.client.cache_hits}.')
            if not self._aborted:
                self.data_loaded.emit({'author': name or self.authors[0], 'author_url': url,
                                       'books': books, 'warning': warning})
        except RateLimited:
            self.log('RESULTADO: Goodreads limitó las consultas.')
            if not self._aborted:
                self.error_occurred.emit(
                    _('Goodreads limited the requests because of the number of recent requests.') + '\n'
                    + _('Wait a few minutes and try again.'))
        except Exception as e:
            self.log(f'RESULTADO: error inesperado: {e!r}')
            if not self._aborted:
                self.error_occurred.emit(_('Unexpected error: {0}').format(e))
        finally:
            if not self._aborted:
                self.diagnostics.emit('\n'.join(self.lines))
