# -*- coding: utf-8 -*-
"""
Anna's Archive Plus - fuente de metadatos para Calibre.

Busca por identificador (annasarchive:<md5>), por ISBN o por título + autor,
guarda el md5 en el campo Identificadores (annasarchive:<md5>) y trae título,
autores, editorial, fecha, idioma, ISBN, sinopsis y portada.
"""

import json
import re
import threading
import time
from urllib.parse import urlencode

from calibre.ebooks.metadata.sources.base import Source, Option
from calibre.ebooks.metadata.book.base import Metadata

try:
    from calibre.ebooks.BeautifulSoup import BeautifulSoup
except Exception:  # pragma: no cover
    from bs4 import BeautifulSoup


ID_NAME = 'annasarchive'
MD5_RE = re.compile(r'/md5/([0-9a-fA-F]{32})')
DEFAULT_DOMAINS = 'annas-archive.gl, annas-archive.pk, annas-archive.gd'

# calibre 9.17+ trae un navegador Camoufox que pasa los controles anti-bots
# (DDoS-Guard / Cloudflare). Un solo navegador por proceso, compartido por
# todos los hilos; cada pedido usa su propia pestaña (clone_browser()).
_CAMOUFOX_LOCK = threading.Lock()
_CAMOUFOX_BROWSER = None
_CAMOUFOX_FAILED = False
# El primer pedido espera a que el navegador se descargue y arranque
_CAMOUFOX_MIN_TIMEOUT = 90
# Esperas (segundos) entre reintentos cuando DDoS-Guard devuelve 403
CHALLENGE_WAITS = (6, 8, 10, 12)
CHALLENGE_MARKERS = ('ddos-guard', 'just a moment', 'checking your browser',
                     'challenge-form', 'cf-chl', 'verifying you are human')


def camoufox_available():
    try:
        from calibre.web.automate.recipes import Browser  # noqa: F401
    except Exception:
        return False
    return True


def _get_camoufox_browser(log):
    global _CAMOUFOX_BROWSER, _CAMOUFOX_FAILED
    with _CAMOUFOX_LOCK:
        if _CAMOUFOX_BROWSER is None and not _CAMOUFOX_FAILED:
            try:
                from calibre.web.automate.recipes import Browser
                _CAMOUFOX_BROWSER = Browser(warmup=True, max_tabs=3)
                log.info("AnnasArchivePlus: usando el navegador Camoufox de calibre")
            except Exception as e:
                _CAMOUFOX_FAILED = True
                log.warn(f"AnnasArchivePlus: Camoufox no disponible ({e}); "
                         "se usa la conexión simple (requiere calibre 9.17 o posterior)")
        return _CAMOUFOX_BROWSER


def is_challenge(text):
    head = (text or '')[:6000].lower()
    return any(m in head for m in CHALLENGE_MARKERS)

# Claves de identifiers_unified de Anna's Archive -> identificador de Calibre
ID_MAP = {
    'goodreads': 'goodreads',
    'amazon': 'amazon',
    'asin': 'amazon',
    'google_books': 'google',
    'gbooks': 'google',
    'openlib': 'openlibrary',
    'ol': 'openlibrary',
    'oclc': 'oclc',
    'doi': 'doi',
}


def _first(v):
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    return v


def _clean(s):
    if not s:
        return ''
    return re.sub(r'\s+', ' ', str(s)).strip()


def split_authors(raw):
    """'Herbert, Frank; Anderson, Kevin J.' -> ['Frank Herbert', 'Kevin J. Anderson']"""
    raw = _clean(raw)
    if not raw:
        return []
    parts = re.split(r'\s*(?:;|&|\|)\s*', raw)
    out = []
    for p in parts:
        p = p.strip(' ,')
        if not p:
            continue
        # "Apellido, Nombre" -> "Nombre Apellido" (solo si hay una única coma)
        if p.count(',') == 1:
            last, first = [x.strip() for x in p.split(',')]
            if first and last and len(first.split()) <= 3:
                p = f'{first} {last}'
        if p not in out:
            out.append(p)
    return out


def normalize_isbn(raw):
    s = re.sub(r'[^0-9Xx]', '', raw or '')
    return s.upper() if len(s) in (10, 13) else None


class AnnasArchivePlus(Source):

    name = 'AnnasArchivePlus'
    description = ("Metadatos de Anna's Archive: busca por título, autor o ISBN, "
                   "guarda el md5 en Identificadores (annasarchive:) y trae título, autores, "
                   "editorial, fecha, idioma, ISBN, sinopsis y portada")
    author = 'Walter - Dunhill'
    version = (1, 3, 1)
    minimum_calibre_version = (6, 0, 0)
    supported_platforms = ['windows', 'osx', 'linux']
    capabilities = frozenset(['identify', 'cover'])
    touched_fields = frozenset([
        'title', 'authors', 'publisher', 'pubdate', 'languages', 'comments',
        'identifier:' + ID_NAME, 'identifier:isbn',
    ])
    has_html_comments = False
    supports_gzip_transfer_encoding = True
    cached_cover_url_is_reliable = True
    prefer_results_with_isbn = False

    options = (
        Option('domains', 'string', DEFAULT_DOMAINS,
               'Dominios de Anna\'s Archive:',
               'Lista separada por comas. Se prueban en orden hasta que uno responda.'),
        Option('language', 'string', 'es',
               'Idioma preferido en la búsqueda:',
               'Código de 2 letras (es, en, pt...). Vacío = cualquier idioma. '
               'Si no hay resultados en ese idioma se busca sin filtro.'),
        Option('max_results', 'number', 5,
               'Cantidad máxima de resultados:',
               'Cuántas fichas de Anna\'s Archive se descargan por búsqueda.'),
        Option('only_books', 'bool', True,
               'Solo libros (excluir revistas, artículos, cómics)',
               'Filtra la búsqueda a libros de ficción y no ficción.'),
        Option('use_camoufox', 'bool', True,
               'Usar el navegador Camoufox de calibre (calibre 9.17+)',
               'Carga Anna\'s Archive con el navegador Camoufox que trae calibre 9.17 y '
               'posteriores, que pasa el control anti-bots. Se descarga la primera vez '
               'que se usa. En versiones anteriores se usa la conexión simple.'),
    )

    # ------------------------------------------------------------------ util

    @property
    def domains(self):
        raw = self.prefs['domains'] or DEFAULT_DOMAINS
        doms = [d.strip().replace('https://', '').replace('http://', '').strip('/')
                for d in raw.split(',')]
        return [d for d in doms if d]

    @property
    def uses_camoufox_worker(self):
        # Hace que calibre espere más a esta fuente (el navegador tarda en arrancar).
        if not self.prefs['use_camoufox']:
            return False
        return camoufox_available()

    def _fetch_camoufox(self, url, timeout, log, as_document=True):
        """Devuelve bytes o None.

        DDoS-Guard responde 403 con una página de verificación en JavaScript.
        calibre corta apenas llega el 403, pero la pestaña sigue ejecutando la
        verificación: se deja la MISMA pestaña abierta, se espera y se reintenta.
        """
        if not self.prefs['use_camoufox']:
            return None
        br = _get_camoufox_browser(log)
        if br is None:
            return None
        tab = br.clone_browser()
        try:
            waits = (0,) + CHALLENGE_WAITS
            for i, wait in enumerate(waits):
                if wait:
                    time.sleep(wait)
                try:
                    with tab.open(url, timeout=max(timeout, _CAMOUFOX_MIN_TIMEOUT),
                                  as_document=as_document) as resp:
                        data = resp.read()
                except Exception as e:
                    code = getattr(e, 'code', None)
                    if code == 404:
                        return None
                    # NS_BINDING_ABORTED: la pestaña estaba recargando sola (la
                    # verificación de DDoS-Guard en curso), así que se sigue esperando
                    aborted = 'NS_BINDING_ABORTED' in str(e)
                    if (code in (403, 503) or aborted) and i + 1 < len(waits):
                        why = 'verificación en curso' if aborted else 'DDoS-Guard'
                        log.info(f'{why} en {url} (intento {i + 1}); '
                                 f'espero {waits[i + 1]}s')
                        continue
                    log.warn(f'Camoufox no pudo cargar {url}: {e}')
                    return None
                if as_document and is_challenge(data.decode('utf-8', 'replace')) and i + 1 < len(waits):
                    log.info(f'Página de verificación en {url} (intento {i + 1}), espero')
                    continue
                if i:
                    log.info(f'Verificación superada en el intento {i + 1}')
                return data
            return None
        finally:
            tab.release()

    def _fetch_plain(self, url, timeout, log):
        """Devuelve bytes, None si 404, o lanza la excepción."""
        try:
            return self.browser.open_novisit(url, timeout=timeout).read()
        except Exception as e:
            if getattr(e, 'code', None) == 404:
                return None
            raise

    def _fetch(self, url, timeout, log, as_document=True):
        """Camoufox primero (si está), después conexión simple. Devuelve bytes o None."""
        data = self._fetch_camoufox(url, timeout, log, as_document)
        if data is not None:
            if not as_document or not is_challenge(data.decode('utf-8', 'replace')):
                return data
        try:
            data = self._fetch_plain(url, timeout, log)
        except Exception as e:
            log.warn(f'{url}: {e}')
            return None
        if data and as_document and is_challenge(data.decode('utf-8', 'replace')):
            log.warn(f'{url}: página anti-bots')
            return None
        return data

    def _get(self, path, timeout, log, as_document=True, only=None):
        """Descarga path probando cada dominio (o solo `only`). Devuelve (texto, dominio)."""
        for dom in ([only] if only else self.domains):
            data = self._fetch(f'https://{dom}{path}', timeout, log, as_document)
            if data:
                return data.decode('utf-8', 'replace'), dom
        log.error(f"No se pudo acceder a Anna's Archive para {path}")
        return None, None

    def get_book_url(self, identifiers):
        md5 = identifiers.get(ID_NAME)
        if md5:
            return (ID_NAME, md5, f'https://{self.domains[0]}/md5/{md5}')

    def get_book_url_name(self, idtype, idval, url):
        return "Anna's Archive"

    def id_from_url(self, url):
        if 'annas-archive' in url:
            m = MD5_RE.search(url)
            if m:
                return (ID_NAME, m.group(1).lower())

    def get_cached_cover_url(self, identifiers):
        md5 = identifiers.get(ID_NAME)
        if md5:
            return self.cached_identifier_to_cover_url(md5)
        isbn = identifiers.get('isbn')
        if isbn:
            md5 = self.cached_isbn_to_identifier(isbn)
            if md5:
                return self.cached_identifier_to_cover_url(md5)

    # -------------------------------------------------------------- búsqueda

    def _search_md5s(self, query, lang, timeout, log):
        params = [('q', query)]
        if lang:
            params.append(('lang', lang))
        if self.prefs['only_books']:
            params += [('content', 'book_fiction'), ('content', 'book_nonfiction'),
                       ('content', 'book_unknown')]
        path = '/search?' + urlencode(params)
        log.info(f'Buscando: {path}')
        html, dom = self._get(path, timeout, log)
        if not html:
            return None  # problema de acceso, no "sin resultados"
        self._working_domain = dom
        return self.parse_search(html)

    @staticmethod
    def parse_search(html):
        # Anna's Archive esconde parte de los resultados dentro de comentarios HTML
        html = html.replace('<!--', '').replace('-->', '')
        seen = []
        for m in MD5_RE.finditer(html):
            md5 = m.group(1).lower()
            if md5 not in seen:
                seen.append(md5)
        return seen

    # ------------------------------------------------------------- detalles

    def _fetch_record(self, md5, timeout, log):
        """Intenta primero el JSON técnico; si falla, raspa la ficha HTML."""
        dom = getattr(self, '_working_domain', None) or self.domains[0]
        for path in (f'/db/aarecord_elasticsearch/md5:{md5}.json',
                     f'/db/aarecord/md5:{md5}.json'):
            text, _ = self._get(path, timeout, log, as_document=False, only=dom)
            if text and text.lstrip().startswith('{'):
                try:
                    rec = self.parse_json(json.loads(text))
                    if rec.get('title'):
                        return rec
                except Exception as e:
                    log.warn(f'JSON de {md5} no válido: {e}')
        html, dom2 = self._get(f'/md5/{md5}', timeout, log)
        if dom2:
            self._working_domain = dom2
        if html:
            return self.parse_html(html)
        return None

    @staticmethod
    def parse_json(data):
        fud = data.get('file_unified_data') or data.get('_source', {}).get('file_unified_data') or {}
        ids = fud.get('identifiers_unified') or {}
        rec = {
            'title': _clean(fud.get('title_best')),
            'authors': split_authors(fud.get('author_best')),
            'publisher': _clean(fud.get('publisher_best')),
            'year': _clean(fud.get('year_best')),
            'comments': (fud.get('stripped_description_best') or '').strip(),
            'languages': list(fud.get('language_codes') or fud.get('most_likely_language_codes') or []),
            'cover': fud.get('cover_url_best') or '',
            'isbns': [],
            'ids': {},
        }
        for k in ('isbn13', 'isbn10'):
            for v in ids.get(k) or []:
                n = normalize_isbn(v)
                if n and n not in rec['isbns']:
                    rec['isbns'].append(n)
        for k, cal in ID_MAP.items():
            v = _first(ids.get(k))
            if v and cal not in rec['ids']:
                rec['ids'][cal] = str(v)
        return rec

    @staticmethod
    def parse_html(html):
        soup = BeautifulSoup(html, 'html.parser')
        rec = {'title': '', 'authors': [], 'publisher': '', 'year': '', 'comments': '',
               'languages': [], 'cover': '', 'isbns': [], 'ids': {}}

        # Título
        t = soup.find('div', class_=re.compile(r'text-3xl'))
        if t:
            rec['title'] = _clean(t.get_text(' ', strip=True).replace('🔍', ''))
        if not rec['title']:
            og = soup.find('meta', attrs={'property': 'og:title'})
            if og and og.get('content'):
                rec['title'] = _clean(og['content'])
        if not rec['title'] and soup.title:
            rec['title'] = _clean(soup.title.get_text().split(' - ')[0])

        # Autor (enlace con ícono de autor, o el bloque en cursiva)
        icon = soup.find('span', class_=re.compile(r'mdi--user-edit'))
        if icon and icon.parent:
            rec['authors'] = split_authors(icon.parent.get_text(' ', strip=True))
        if not rec['authors']:
            it = soup.find('div', class_=re.compile(r'(^|\s)italic(\s|$)'))
            if it:
                rec['authors'] = split_authors(it.get_text(' ', strip=True).replace('🔍', ''))

        # Editorial y año
        pub_text = ''
        icon = soup.find('span', class_=re.compile(r'mdi--company'))
        if icon and icon.parent:
            pub_text = icon.parent.get_text(' ', strip=True)
        else:
            tm = soup.find('div', class_=re.compile(r'(^|\s)text-md(\s|$)'))
            if tm:
                pub_text = tm.get_text(' ', strip=True)
        pub_text = _clean(pub_text.replace('🔍', ''))
        if pub_text:
            y = re.search(r'\b(1[4-9]\d\d|20\d\d)\b', pub_text)
            if y:
                rec['year'] = y.group(1)
            pub = re.sub(r',?\s*\b(1[4-9]\d\d|20\d\d)\b.*$', '', pub_text).strip(' ,;')
            rec['publisher'] = pub

        # Idioma: línea gris del estilo "Spanish [es], .epub, 0.5MB, ..."
        for div in soup.find_all('div', class_=re.compile(r'text-gray-500')):
            txt = div.get_text(' ', strip=True)
            codes = re.findall(r'\[([a-z]{2,3})\]', txt)
            if codes:
                rec['languages'] = codes
                break

        # Sinopsis
        desc = soup.find('div', class_='js-md5-top-box-description')
        if desc:
            block = desc.find('div', class_='mb-1') or desc
            rec['comments'] = block.get_text('\n', strip=True)

        # ISBN (solo de la sección de códigos/identificadores si existe)
        scope = soup.find(class_=re.compile(r'js-md5-codes')) or soup
        for m in re.finditer(r'\b(97[89][\d-]{10,14}|\d{9}[\dXx])\b', scope.get_text(' ')):
            n = normalize_isbn(m.group(1))
            if n and n not in rec['isbns']:
                rec['isbns'].append(n)

        # Portada
        og = soup.find('meta', attrs={'property': 'og:image'})
        if og and og.get('content'):
            rec['cover'] = og['content']
        if not rec['cover']:
            for img in soup.find_all('img'):
                src = img.get('src') or ''
                if src.startswith('http') and ('cover' in src or 'cover' in ' '.join(img.get('class') or [])):
                    rec['cover'] = src
                    break
        return rec

    def _to_metadata(self, md5, rec, log):
        mi = Metadata(rec['title'] or 'Desconocido', rec['authors'] or ['Desconocido'])
        mi.set_identifier(ID_NAME, md5)
        if rec['isbns']:
            # prioriza ISBN-13
            isbns = sorted(rec['isbns'], key=lambda x: len(x) != 13)
            mi.isbn = isbns[0]
            self.cache_isbn_to_identifier(mi.isbn, md5)
        for k, v in rec['ids'].items():
            mi.set_identifier(k, v)
        if rec['publisher']:
            mi.publisher = rec['publisher']
        if rec['year'] and re.match(r'^\d{4}', rec['year']):
            try:
                from calibre.utils.date import parse_only_date
                mi.pubdate = parse_only_date(rec['year'][:4] + '-01-01', assume_utc=True)
            except Exception as e:
                log.warn(f'Fecha no válida {rec["year"]}: {e}')
        if rec['languages']:
            from calibre.utils.localization import canonicalize_lang
            langs = [canonicalize_lang(l) for l in rec['languages']]
            mi.languages = [l for l in langs if l]
        if rec['comments']:
            mi.comments = rec['comments']
        if rec['cover']:
            self.cache_identifier_to_cover_url(md5, rec['cover'])
            mi.has_cover = True
        return mi

    # -------------------------------------------------------------- identify

    def identify(self, log, result_queue, abort, title=None, authors=None,
                 identifiers={}, timeout=30):
        md5s = []
        md5 = identifiers.get(ID_NAME)
        if md5:
            md5s = [md5.lower()]
        else:
            lang = (self.prefs['language'] or '').strip().lower()
            queries = []
            isbn = normalize_isbn(identifiers.get('isbn'))
            if isbn:
                queries.append(isbn)
            if title:
                tokens = list(self.get_title_tokens(title, strip_joiners=False, strip_subtitle=True))
                q = ' '.join(tokens)
                if authors:
                    qa = q + ' ' + ' '.join(self.get_author_tokens(authors, only_first_author=True))
                    queries.append(qa.strip())
                # Solo título: sirve cuando el autor figura con otro nombre (p. ej. un seudónimo)
                queries.append(q.strip())
            if not queries:
                log.error('Hace falta un título, un ISBN o el identificador annasarchive')
                return
            for q in queries:
                for lg in ([lang, ''] if lang else ['']):
                    if abort.is_set():
                        return
                    md5s = self._search_md5s(q, lg, timeout, log)
                    if md5s is None:
                        log.error("No se pudo pasar la protección DDoS-Guard de Anna's Archive")
                        return
                    if md5s:
                        break
                if md5s:
                    break
            if not md5s:
                log.error('Sin resultados en Anna\'s Archive')
                return
            md5s = md5s[:int(self.prefs['max_results'] or 5)]

        for rank, md5 in enumerate(md5s):
            if abort.is_set():
                return
            rec = self._fetch_record(md5, timeout, log)
            if not rec or not rec.get('title'):
                log.warn(f'No se pudieron leer los datos de {md5}')
                continue
            mi = self._to_metadata(md5, rec, log)
            mi.source_relevance = rank
            self.clean_downloaded_metadata(mi)
            result_queue.put(mi)
        return None

    # ---------------------------------------------------------------- portada

    def download_cover(self, log, result_queue, abort, title=None, authors=None,
                       identifiers={}, timeout=30, get_best_cover=False):
        url = self.get_cached_cover_url(identifiers)
        if not url:
            log.info('Sin portada en caché, ejecuto identify primero')
            from queue import Queue, Empty
            rq = Queue()
            self.identify(log, rq, abort, title=title, authors=authors,
                          identifiers=identifiers, timeout=timeout)
            if abort.is_set():
                return
            results = []
            while True:
                try:
                    results.append(rq.get_nowait())
                except Empty:
                    break
            results.sort(key=self.identify_results_keygen(
                title=title, authors=authors, identifiers=identifiers))
            for mi in results:
                url = self.get_cached_cover_url(mi.identifiers)
                if url:
                    break
        if not url:
            log.info('No se encontró portada')
            return
        if abort.is_set():
            return
        # Las portadas suelen estar en otro servidor que no bloquea: conexión simple primero
        cdata = None
        try:
            cdata = self._fetch_plain(url, timeout, log)
        except Exception as e:
            log.info(f'Portada por conexión simple falló ({e}), pruebo con Camoufox')
        if not cdata:
            cdata = self._fetch_camoufox(url, timeout, log, as_document=False)
        if cdata:
            result_queue.put((self, cdata))
        else:
            log.error(f'No se pudo descargar la portada {url}')
