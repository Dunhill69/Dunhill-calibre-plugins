"""Idioma de las ediciones que se buscan en Goodreads (sin Qt, para los hilos).

Por defecto es el idioma de la interfaz de calibre; en la configuración se
puede elegir otro. Los códigos son ISO 639-2 de tres letras, como los usa
calibre ('spa', 'por', 'fra'...)."""

import re
import unicodedata

# Cómo se llama cada idioma en su propio idioma (Goodreads a veces lo escribe así)
NATIVE = {
    'spa': ['español', 'castellano', 'castilian'],
    'por': ['português'],
    'fra': ['français', 'française'],
    'deu': ['deutsch'],
    'ita': ['italiano'],
    'nld': ['nederlands', 'flemish'],
    'cat': ['català'],
    'glg': ['galego'],
    'eus': ['euskara'],
    'pol': ['polski'],
    'rus': ['русский'],
    'ukr': ['українська'],
    'ces': ['čeština'],
    'slk': ['slovenčina'],
    'ron': ['română'],
    'hun': ['magyar'],
    'tur': ['türkçe'],
    'swe': ['svenska'],
    'dan': ['dansk'],
    'nor': ['norsk', 'norwegian bokmål', 'bokmål'],
    'fin': ['suomi'],
    'ell': ['ελληνικά'],
    'jpn': ['日本語'],
    'zho': ['中文'],
    'kor': ['한국어'],
    'ara': ['العربية'],
    'heb': ['עברית'],
}

# Goodreads filtra las ediciones con los códigos bibliográficos (ISO 639-2/B),
# que para algunos idiomas son distintos de los de calibre
T_TO_B = {
    'fra': 'fre', 'deu': 'ger', 'nld': 'dut', 'zho': 'chi', 'ces': 'cze', 'ell': 'gre',
    'fas': 'per', 'sqi': 'alb', 'hye': 'arm', 'eus': 'baq', 'mya': 'bur', 'kat': 'geo',
    'isl': 'ice', 'mkd': 'mac', 'msa': 'may', 'mri': 'mao', 'ron': 'rum', 'slk': 'slo',
    'bod': 'tib', 'cym': 'wel',
}

# Nombres en inglés de respaldo, por si calibre no los puede dar
ENGLISH = {
    'spa': 'Spanish; Castilian', 'eng': 'English', 'por': 'Portuguese', 'fra': 'French',
    'deu': 'German', 'ita': 'Italian', 'nld': 'Dutch; Flemish', 'cat': 'Catalan; Valencian',
    'glg': 'Galician', 'eus': 'Basque', 'pol': 'Polish', 'rus': 'Russian', 'ukr': 'Ukrainian',
    'ces': 'Czech', 'slk': 'Slovak', 'ron': 'Romanian', 'hun': 'Hungarian', 'tur': 'Turkish',
    'swe': 'Swedish', 'dan': 'Danish', 'nor': 'Norwegian', 'fin': 'Finnish', 'ell': 'Greek',
    'jpn': 'Japanese', 'zho': 'Chinese', 'kor': 'Korean', 'ara': 'Arabic', 'heb': 'Hebrew',
}

# Idiomas que se ofrecen en la configuración (además de "igual que calibre")
CHOICES = ('spa', 'eng', 'por', 'fra', 'deu', 'ita', 'cat', 'glg', 'eus', 'nld', 'pol', 'rus',
           'ukr', 'ces', 'ron', 'hun', 'tur', 'swe', 'dan', 'nor', 'fin', 'ell', 'jpn', 'zho', 'kor')


def strip_accents(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text or '')
                   if not unicodedata.combining(c))


def calibre_language():
    """Idioma de la interfaz de calibre como código de tres letras."""
    try:
        from calibre.utils.localization import canonicalize_lang, get_lang
        return canonicalize_lang(get_lang()) or 'eng'
    except Exception:
        return 'eng'


def resolve(setting):
    """'auto' (o vacío) = el idioma de calibre; si no, el código elegido."""
    if not setting or setting == 'auto':
        return calibre_language()
    return setting


def english_name(code):
    try:
        from calibre.utils.localization import calibre_langcode_to_name
        name = calibre_langcode_to_name(code, localize=False)
        if name and name != code:
            return name
    except Exception:
        pass
    return ENGLISH.get(code, code)


def display_name(code):
    """Nombre del idioma en el idioma de la interfaz de calibre, para mostrar
    ('español', 'Spanish', 'portugués'...). Solo la primera parte del nombre."""
    name = ''
    try:
        from calibre.utils.localization import calibre_langcode_to_name
        name = calibre_langcode_to_name(code, localize=True)
    except Exception:
        pass
    if not name or name == code:
        name = ENGLISH.get(code, code)
    name = name.split(';')[0].strip()
    # En inglés y alemán los idiomas van con mayúscula; en el resto, en minúscula
    if calibre_language() not in ('eng', 'deu'):
        name = name[:1].lower() + name[1:]
    return name


def raw_names(code):
    """Formas en que puede aparecer el nombre del idioma (con y sin acentos)."""
    names = {p.strip() for p in english_name(code).split(';') if p.strip()}
    names |= set(NATIVE.get(code, ()))
    out = set()
    for n in names:
        out.add(n.lower())
        out.add(strip_accents(n).lower())
    return sorted(out, key=len, reverse=True)


def match_names(code):
    """Nombres sin acentos y en minúscula, para comparar con lo que muestra Goodreads."""
    return {strip_accents(n).lower() for n in raw_names(code)}


def goodreads_code(code):
    return T_TO_B.get(code, code)


def accept_language(code):
    two = ''
    try:
        from calibre.utils.localization import lang_as_iso639_1
        two = lang_as_iso639_1(code) or ''
    except Exception:
        pass
    if not two:
        two = {'spa': 'es', 'por': 'pt', 'fra': 'fr', 'deu': 'de', 'ita': 'it', 'cat': 'ca',
               'glg': 'gl', 'nld': 'nl', 'pol': 'pl', 'rus': 'ru'}.get(code, '')
    if not two or two == 'en':
        return 'en-US,en;q=0.9'
    return f'{two},en-US;q=0.8,en;q=0.7'


# Agregados de idioma en los títulos: "(Spanish Edition)", "(Edición en español)",
# "(Édition française)", "[German]"... de cualquier idioma común
_LANG_WORDS = sorted({w for c in ENGLISH for w in raw_names(c)} | {
    'english', 'spanish', 'french', 'german', 'italian', 'portuguese', 'dutch', 'catalan',
    'galician', 'basque', 'polish', 'russian', 'japanese', 'chinese', 'korean', 'turkish',
    'española', 'espanola', 'francesa', 'portuguesa', 'italiana', 'alemana', 'inglesa', 'deutsche',
    'française', 'francaise', 'inglés', 'ingles', 'francés', 'frances', 'alemán', 'aleman',
    'portugués', 'portugues', 'italiano'}, key=len, reverse=True)
_LANG_RE = '(?:' + '|'.join(re.escape(w) for w in _LANG_WORDS if not re.search(r'[;]', w)) + ')'
_EDITION_WORDS = (r'(?:edici[oó]n|versi[oó]n|traducci[oó]n|edi[cç][aã]o|vers[aã]o|tradu[cç][aã]o|'
                  r'[ée]dition|edizione|traduzione|ausgabe|uitgave)')
LANGUAGE_TAG = re.compile(
    r'\s*[(\[]\s*(?:'
    + _LANG_RE + r'(?:\s+(?:edition|version|language|ed\.?|text|ausgabe))?'
    + r'|' + _EDITION_WORDS + r'\s+(?:(?:en|em|in|al|à|a|au|del|de)\s+)?' + _LANG_RE
    + r')\s*[)\]]', re.I)
