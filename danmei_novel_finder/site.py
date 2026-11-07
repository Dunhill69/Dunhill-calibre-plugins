#!/usr/bin/env python
# Lectura de danmeinovel.com (tema Madara de WordPress).
# No usa Qt: se puede llamar desde hilos de trabajo.

import re
import time
from urllib.parse import quote_plus, urljoin, urlencode, urlparse

BASE_URL = 'https://danmeinovel.com'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')


class SiteError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


# ----------------------------------------------------------------- red

def make_browser():
    from calibre import browser
    br = browser(user_agent=USER_AGENT)
    br.set_handle_robots(False)
    br.addheaders = [h for h in br.addheaders if h[0].lower() != 'referer']
    br.addheaders.append(('Referer', BASE_URL + '/'))
    return br


def fetch(br, url, data=None, ajax=False, timeout=40, retries=2):
    from mechanize import Request
    headers = {'X-Requested-With': 'XMLHttpRequest'} if ajax else {}
    last = None
    for attempt in range(retries + 1):
        try:
            if data is not None or headers:
                req = Request(url, data=data, headers=headers)
                return br.open(req, timeout=timeout).read()
            return br.open(url, timeout=timeout).read()
        except Exception as e:
            last = e
            code = getattr(e, 'code', None)
            if code in (400, 401, 403, 404, 410):
                break
            time.sleep(1.5 * (attempt + 1))
    code = getattr(last, 'code', None)
    if code == 403:
        raise SiteError('El sitio rechazó la conexión (403). Puede estar '
                        'protegido por Cloudflare o bloqueando descargas.')
    if code == 404:
        raise SiteError('No se encontró la página (404): %s' % url, 404)
    raise SiteError('No se pudo conectar con %s\n%s' % (url, last))


def parse(raw):
    from calibre.ebooks.BeautifulSoup import BeautifulSoup
    return BeautifulSoup(raw)


# ------------------------------------------------------------ utilidades

def clean(text):
    return ' '.join((text or '').split())


def node_text(node):
    return clean(node.get_text(' ')) if node is not None else ''


def img_url(img):
    if img is None:
        return None
    for attr in ('data-src', 'data-lazy-src', 'data-cfsrc', 'src'):
        v = (img.get(attr) or '').strip()
        if v and not v.startswith('data:'):
            return urljoin(BASE_URL + '/', v)
    srcset = img.get('data-srcset') or img.get('srcset') or ''
    if srcset:
        last = srcset.split(',')[-1].strip().split(' ')[0]
        if last:
            return urljoin(BASE_URL + '/', last)
    return None


def meta_content(soup, prop):
    m = soup.find('meta', attrs={'property': prop}) or soup.find('meta', attrs={'name': prop})
    return (m.get('content') or '').strip() if m is not None else ''


def is_site_url(url):
    try:
        p = urlparse(url.strip())
    except Exception:
        return False
    return p.scheme in ('http', 'https') and 'danmeinovel' in (p.netloc or '').lower()


def first_number(text):
    m = re.search(r'(\d+(?:\.\d+)?)', text or '')
    return float(m.group(1)) if m else None


# ------------------------------------------------- búsqueda y catálogo

# Órdenes del catálogo del tema Madara (m_orderby)
ORDERS = [
    ('Últimas actualizadas', 'latest'),
    ('Más populares', 'views'),
    ('Tendencia', 'trending'),
    ('Mejor puntuadas', 'rating'),
    ('Nuevas', 'new-manga'),
    ('Alfabético (A-Z)', 'alphabet'),
]


def _parse_items(soup):
    items = (soup.find_all('div', class_='c-tabs-item__content')
             or soup.find_all('div', class_='page-item-detail')
             or soup.find_all('article'))
    results, seen = [], set()
    for it in items:
        holder = it.find(class_='post-title') or it.find(class_='entry-title')
        a = holder.find('a', href=True) if holder is not None else None
        if a is None:
            a = it.find('a', href=True)
        if a is None:
            continue
        link = urljoin(BASE_URL + '/', a['href'])
        if link in seen or not is_site_url(link):
            continue
        seen.add(link)
        title = node_text(a) or a.get('title') or ''
        authors = []
        box = it.find('div', class_='mg_author') or it.find('div', class_='author-content')
        if box is not None:
            authors = [node_text(x) for x in box.find_all('a')] or [node_text(box)]
        authors = [x for x in authors if x and x.lower() not in ('updating', 'author(s)')]
        latest = ''
        ch = it.find(class_='chapter') or it.find(class_='latest-chap')
        if ch is not None:
            latest = node_text(ch.find('a') or ch)
        score = it.find(class_='score')
        results.append({
            'title': title,
            'url': link,
            'authors': authors,
            'cover': img_url(it.find('img')),
            'latest': latest,
            'score': node_text(score) if score is not None else '',
        })
    return results


def _has_next(soup, n_items):
    if not n_items:
        return False
    if soup.find('link', attrs={'rel': 'next'}) is not None:
        return True
    for cls in ('nav-previous', 'next', 'nextpostslink', 'navigation-ajax'):
        if soup.find(class_=cls) is not None:
            return True
    return n_items >= 10


def _paged(path, page):
    path = path.rstrip('/') + '/'
    return path if page <= 1 else '%spage/%d/' % (path, page)


def search_page(query, page=1, timeout=40):
    url = '%s?s=%s&post_type=wp-manga' % (_paged(BASE_URL, page), quote_plus(query))
    try:
        soup = parse(fetch(make_browser(), url, timeout=timeout))
    except SiteError as e:
        if e.code == 404 and page > 1:
            return ([], False) if 'm_orderby' not in url else ([], False, [])
        raise
    items = _parse_items(soup)
    return items, _has_next(soup, len(items))


def search(query, max_results=10, timeout=40):
    items, _ = search_page(query, 1, timeout)
    return items[:max_results]


def _genres(soup):
    out, seen = [], set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        m = re.search(r'/manga-genre/([^/?#]+)', href)
        if not m or m.group(1) in seen:
            continue
        name = re.sub(r'\s*\(\d+\)\s*$', '', node_text(a))
        if not name:
            continue
        seen.add(m.group(1))
        out.append((name, m.group(1)))
    out.sort(key=lambda x: x[0].lower())
    return out


def catalog_page(order='latest', genre=None, page=1, timeout=40):
    """Devuelve (novelas, hay_más, géneros)."""
    base = '%s/manga-genre/%s' % (BASE_URL, genre) if genre else BASE_URL + '/manga'
    url = '%s?m_orderby=%s' % (_paged(base, page), order)
    try:
        soup = parse(fetch(make_browser(), url, timeout=timeout))
    except SiteError as e:
        if e.code == 404 and page > 1:
            return ([], False) if 'm_orderby' not in url else ([], False, [])
        raise
    items = _parse_items(soup)
    return items, _has_next(soup, len(items)), _genres(soup)


# ---------------------------------------------------------- ficha novela

JUNK_TAGS = re.compile(r'danmeinovel|^novela?s?$|^novel$', re.I)
SUMMARY_WORDS = re.compile(r'^(summary|synopsis|description|sinopsis|resumen|descripci[oó]n)\b', re.I)
FIELD_KEYS = (
    ('alternative', ('alternative', 'alternativ', 'other name', 'otros nombres')),
    ('author', ('author', 'autor', 'writer')),
    ('genre', ('genre', 'género', 'genero')),
    ('tag', ('tag', 'etiqueta')),
    ('status', ('status', 'estado')),
)


def _links_or_text(box):
    if box is None:
        return []
    items = [node_text(a) for a in box.find_all('a')]
    items = [i for i in items if i]
    if not items:
        items = [x.strip() for x in re.split(r'[,;]', node_text(box))]
    return [i for i in items if i]


def _detail_fields(soup):
    """Filas "Rango / Alternativa / Género(s) / Etiqueta(s) / Estado" de Madara."""
    fields = {}
    for row in soup.find_all('div', class_='post-content_item'):
        head = row.find(class_='summary-heading')
        content = row.find(class_='summary-content')
        if head is None or content is None:
            continue
        label = node_text(head).lower()
        for key, words in FIELD_KEYS:
            if key not in fields and any(label.startswith(w) for w in words):
                fields[key] = content
                break
    return fields


def _paras(box):
    for tag in box.find_all(['script', 'style', 'noscript', 'button']):
        tag.decompose()
    paras = [node_text(p) for p in box.find_all('p')]
    paras = [p for p in paras if p]
    if not paras:
        paras = [clean(x) for x in box.get_text('\n').split('\n')]
        paras = [p for p in paras if p]
    return [p for p in paras if not re.match(r'^(show more|show less|ver m[aá]s)$', p, re.I)]


def _summary(soup):
    for cls in ('summary__content', 'description-summary', 'manga-summary',
                'manga-excerpt', 'summary-text', 'novel-summary'):
        box = soup.find('div', class_=cls)
        if box is not None:
            paras = _paras(box)
            if paras:
                return paras
    # Por título de sección: "Summary", "Synopsis", "Resumen"…
    for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        if not SUMMARY_WORDS.match(node_text(h)):
            continue
        node = h
        while node.parent is not None and node.find_next_sibling() is None:
            node = node.parent
        for sib in node.find_next_siblings():
            if sib.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']) is not None and not sib.find('p'):
                break
            paras = _paras(sib)
            if paras and sum(len(p) for p in paras) > 40:
                return paras
    d = meta_content(soup, 'og:description') or meta_content(soup, 'description')
    return [d] if d else []


def _chapters_from(soup):
    links = []
    lis = soup.find_all('li', class_='wp-manga-chapter')
    if lis:
        for li in lis:
            a = li.find('a', href=True)
            if a is not None:
                links.append(a)
    else:
        ul = soup.find('ul', class_='main') or soup.find('ul', class_='version-chap')
        if ul is not None:
            links = ul.find_all('a', href=True)
    out, seen = [], set()
    for a in links:
        href = urljoin(BASE_URL + '/', a['href'].strip())
        if href in seen or href.endswith('#'):
            continue
        seen.add(href)
        out.append((node_text(a) or 'Capítulo', href))
    return out


def _post_id(soup):
    holder = soup.find(id='manga-chapters-holder')
    if holder is not None and holder.get('data-id'):
        return holder['data-id']
    inp = soup.find('input', class_='rating-post-id')
    if inp is not None and inp.get('value'):
        return inp['value']
    link = soup.find('link', attrs={'rel': 'shortlink'})
    if link is not None:
        m = re.search(r'[?&]p=(\d+)', link.get('href') or '')
        if m:
            return m.group(1)
    return None


def novel_info(url, timeout=40):
    br = make_browser()
    soup = parse(fetch(br, url, timeout=timeout))

    # Título
    title = ''
    box = soup.find('div', class_='post-title')
    h = box.find(['h1', 'h2', 'h3']) if box is not None else soup.find('h1')
    if h is not None:
        for span in h.find_all('span'):
            span.decompose()  # etiquetas "HOT", "NEW"…
        title = node_text(h)
    if not title:
        title = meta_content(soup, 'og:title').split(' - ')[0].strip()
    if not title:
        title = urlparse(url).path.rstrip('/').split('/')[-1].replace('-', ' ').title()

    fields = _detail_fields(soup)

    # Autor/es
    authors = []
    box = soup.find('div', class_='author-content') or fields.get('author')
    if box is not None:
        authors = _links_or_text(box)
    authors = [a for a in authors if a.lower() not in ('updating', 'n/a', '-')] or ['Desconocido']

    # Sinopsis
    summary_paras = _summary(soup)

    # Portada
    cover = None
    box = soup.find('div', class_='summary_image')
    if box is not None:
        cover = img_url(box.find('img'))
    if not cover:
        cover = meta_content(soup, 'og:image') or None

    # Géneros y etiquetas
    genres = _links_or_text(soup.find('div', class_='genres-content') or fields.get('genre'))
    extra = _links_or_text(soup.find('div', class_='tags-content') or fields.get('tag'))
    tags, seen = [], set()
    for t in genres + extra:
        key = t.lower()
        if key in seen or key == title.lower() or JUNK_TAGS.search(t):
            continue
        seen.add(key)
        tags.append(t)

    alternative = node_text(fields['alternative']) if 'alternative' in fields else ''
    status = node_text(fields['status']) if 'status' in fields else ''

    # Capítulos: en la página, o por AJAX (versiones nuevas de Madara)
    chapters = _chapters_from(soup)
    if not chapters:
        try:
            raw = fetch(br, url.rstrip('/') + '/ajax/chapters/', data=b'', ajax=True,
                        timeout=timeout, retries=1)
            chapters = _chapters_from(parse(raw))
        except SiteError:
            pass
    if not chapters:
        pid = _post_id(soup)
        if pid:
            try:
                data = urlencode({'action': 'manga_get_chapters', 'manga': pid}).encode()
                raw = fetch(br, BASE_URL + '/wp-admin/admin-ajax.php', data=data,
                            ajax=True, timeout=timeout, retries=1)
                chapters = _chapters_from(parse(raw))
            except SiteError:
                pass

    # Madara los lista del más nuevo al más viejo: los dejamos en orden de lectura.
    if len(chapters) > 1:
        a, b = first_number(chapters[0][0]), first_number(chapters[-1][0])
        if a is None or b is None or a > b:
            chapters.reverse()

    return {
        'url': url,
        'title': title,
        'authors': authors,
        'summary': summary_paras,
        'cover_url': cover,
        'tags': tags,
        'genres': genres,
        'alternative': '' if alternative.lower() in ('updating', 'n/a') else alternative,
        'status': status,
        'chapters': chapters,
    }


def download_bytes(url, timeout=40):
    return fetch(make_browser(), url, timeout=timeout, retries=1)


# --------------------------------------------------------------- capítulo

JUNK = re.compile(r'danmeinovel\.com|^\s*(previous|next)\s*(chapter)?\s*$', re.I)


def chapter_paragraphs(br, url, timeout=40):
    soup = parse(fetch(br, url, timeout=timeout))
    box = (soup.find('div', class_='reading-content')
           or soup.find('div', class_='text-left')
           or soup.find('div', class_='entry-content'))
    if box is None:
        return []
    for tag in box.find_all(['script', 'style', 'noscript', 'iframe', 'ins', 'button']):
        tag.decompose()
    paras = [node_text(p) for p in box.find_all('p')]
    if not any(paras):
        paras = [clean(line) for line in box.get_text('\n').split('\n')]
    return [p for p in paras if p and not JUNK.search(p)]
