#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai

__license__   = 'GPL v3'
__copyright__ = '2026, Dunhill'

"""Small CSS checker for e-book stylesheets. It looks for the mistakes that
really break a book (unknown properties, invalid values, broken comments,
decimal commas...) and reports them with their line number."""

try:
    load_translations()
except NameError:
    if '_' not in globals():
        def _(x):
            return x

import re

HTML_TAGS = set('''
a abbr address area article aside audio b bdi bdo blockquote body br button
canvas caption cite code col colgroup data dd del details dfn dialog div dl dt
em embed fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 head header
hgroup hr html i iframe img input ins kbd label legend li link main map mark
math menu meta meter nav noscript object ol optgroup option output p param
picture pre progress q rp rt ruby s samp script section select slot small source
span strong style sub summary sup svg table tbody td template textarea tfoot th
thead time title tr track u ul var video wbr big center font strike tt acronym
image rect circle ellipse line polyline polygon path text tspan g use defs
'''.split())

# Properties css_parser may not know but that are valid in e-books
EXTRA_PROPS = set('''
hyphens widows orphans page-break-before page-break-after page-break-inside
break-before break-after break-inside box-sizing box-shadow border-radius
border-top-left-radius border-top-right-radius border-bottom-left-radius
border-bottom-right-radius column-count column-gap columns column-rule
column-width column-span opacity text-shadow text-overflow overflow-wrap
word-wrap word-break transform transform-origin transition object-fit
object-position font-variant-ligatures font-variant-numeric
font-variant-caps font-variant-east-asian font-variant-position
font-feature-settings font-kerning font-variant-alternates text-rendering
text-decoration-line text-decoration-style text-decoration-color
text-decoration-thickness text-underline-offset text-underline-position
text-align-last text-justify hanging-punctuation line-break tab-size
writing-mode text-orientation text-combine-upright unicode-range src
font-display flex flex-direction flex-wrap flex-flow flex-grow flex-shrink
flex-basis justify-content align-items align-content align-self order gap
row-gap grid grid-template-columns grid-template-rows grid-area grid-column
grid-row filter mix-blend-mode isolation resize user-select pointer-events
caret-color appearance outline-offset image-rendering adobe-hyphenate
adobe-text-layout prince-hyphens size marks bleed
'''.split())

_known = None
_suspicious = []


def known_properties():
    global _known
    if _known is None:
        names = set(EXTRA_PROPS)
        try:
            from css_parser import profile
            names |= set(profile.knownNames)
        except Exception:
            pass
        _known = names
    return _known


def _validate(name, value):
    """True/False when css_parser can judge the value, None otherwise."""
    if name in EXTRA_PROPS or '!' in value or 'var(' in value or 'calc(' in value:
        return None
    try:
        from css_parser import profile
        if name not in profile.knownNames:
            return None
        return bool(profile.validate(name, value))
    except Exception:
        return None


def _blank_comments(css):
    """Replace comments with spaces (keeping newlines, so line numbers stay
    right) and report broken comment markers."""
    issues = []
    out = []
    i, n = 0, len(css)
    while i < n:
        if css.startswith('/*', i):
            j = css.find('*/', i + 2)
            if j < 0:
                issues.append((css.count('\n', 0, i) + 1, 'error',
                               _('A comment opened with /* is never closed with */: '
                                 'everything after it is ignored')))
                j = n - 2
            chunk = css[i:j + 2]
            out.append(re.sub(r'[^\n]', ' ', chunk))
            i = j + 2
            continue
        if css.startswith('*/', i):
            issues.append((css.count('\n', 0, i) + 1, 'error',
                           _('There is a */ that closes a comment that was never opened with /*. '
                             'The text before it is read as CSS and the next rule is lost')))
        out.append(css[i])
        i += 1
    return ''.join(out), issues


def _line_at(text, pos):
    return text.count('\n', 0, pos) + 1


def _check_selector(sel, line, issues):
    sel = sel.strip()
    if not sel:
        return
    stripped = re.sub(r'\[[^\]]*\]|\([^)]*\)|"[^"]*"|\'[^\']*\'', ' ', sel)
    for part in stripped.split(','):
        part = part.strip()
        if not part:
            issues.append((line, 'error', _('Empty selector in "{0}" (extra comma?)').format(sel)))
            continue
        for m in re.finditer(r'(?:^|[\s>+~])([a-zA-Z][a-zA-Z0-9-]*)', part):
            tag = m.group(1).lower()
            if tag not in HTML_TAGS and not re.match(r'^(epub|svg|m|xml)', tag):
                issues.append((line, 'warning',
                               _('"{0}" is not an HTML element, so the rule "{1}" never applies').format(
                                   m.group(1), part)))
                break


def _check_declarations(body, body_start, text, issues, at_rule=None, selector=''):
    pos = 0
    for raw in body.split(';'):
        start = body_start + pos
        pos += len(raw) + 1
        decl = raw.strip()
        if not decl:
            continue
        line = _line_at(text, start + (len(raw) - len(raw.lstrip())))
        if ':' not in decl:
            issues.append((line, 'error', _('"{0}" is not a valid declaration (missing ":")').format(decl)))
            continue
        name, value = decl.split(':', 1)
        name, value = name.strip(), value.strip()
        lname = name.lower()
        if not re.match(r'^-?[a-zA-Z][a-zA-Z0-9-]*$', name):
            if re.search(r'\s|[^\x00-\x7f]', name):
                _suspicious.append(name)
            issues.append((line, 'error', _('"{0}" is not a valid property name').format(name)))
            continue
        if lname.startswith('-') and re.match(r'^-(webkit|moz|epub|ms|o|adobe|apple|kindle|amzn|ibooks|readium|prince|calibre)-', lname):
            continue
        if not value:
            issues.append((line, 'error', _('The property "{0}" has no value').format(name)))
            continue
        if re.search(r'\d,\d+\s*(em|rem|px|pt|%|ex|ch|vw|vh|mm|cm|in)\b', value) and lname not in ('font-family', 'src'):
            issues.append((line, 'error',
                           _('"{0}: {1}" uses a decimal comma; CSS needs a point (1.5em, not 1,5em)').format(name, value)))
            continue
        if at_rule == 'font-face':
            continue
        if lname not in known_properties():
            issues.append((line, 'error', _('Unknown property "{0}"').format(name)))
            continue
        if lname == 'width' and value.replace(' ', '') == '100%' and \
                re.search(r'(^|,)\s*img\s*(,|$)', selector or ''):
            issues.append((line, 'warning', _('"img { width: 100% }" stretches every image, even small '
                                              'or inline ones, to the full width; '
                                              'max-width: 100% is usually what is wanted')))
        ok = _validate(lname, value)
        if ok is False:
            issues.append((line, 'warning', _('Possibly invalid value for {0}: {1}').format(name, value)))


def check_css(css):
    """Return a sorted list of (line, level, message); level is 'error' or 'warning'."""
    text, issues = _blank_comments(css)
    del _suspicious[:]
    i, n = 0, len(text)
    depth_stack = []   # for @media / @supports blocks

    while i < n:
        j = text.find('{', i)
        k = text.find('}', i)
        if j < 0 and k < 0:
            rest = text[i:].strip()
            if rest and not rest.startswith('@'):
                issues.append((_line_at(text, i + text[i:].find(rest[0])), 'error',
                               _('Text outside any rule: "{0}"').format(rest[:40])))
            break
        if k >= 0 and (j < 0 or k < j):
            # closing an @media block (or a stray brace)
            if depth_stack:
                depth_stack.pop()
            else:
                issues.append((_line_at(text, k), 'error', _('Extra closing brace "}"')))
            i = k + 1
            continue
        prelude = text[i:j]
        pstrip = prelude.strip()
        # statements ending in ; before the block (e.g. @import, @charset)
        while pstrip.startswith('@') and ';' in pstrip:
            semi = prelude.find(';')
            i += semi + 1
            prelude = text[i:j]
            pstrip = prelude.strip()
        pline = _line_at(text, i + (len(prelude) - len(prelude.lstrip())))
        if pstrip.lower().startswith(('@media', '@supports', '@document', '@layer')):
            depth_stack.append(pstrip)
            i = j + 1
            continue
        end = text.find('}', j + 1)
        nested = text.find('{', j + 1)
        if end < 0:
            issues.append((pline, 'error', _('The rule "{0}" is never closed with "}}"').format(pstrip[:40])))
            break
        if 0 <= nested < end:
            issues.append((_line_at(text, nested), 'error',
                           _('A "{{" opens inside the rule "{0}" (a missing "}}" before it?)').format(pstrip[:40])))
        body = text[j + 1:end]
        at = None
        if pstrip.startswith('@'):
            at = pstrip[1:].split()[0].lower() if len(pstrip) > 1 else ''
            if at not in ('font-face', 'page', 'top-left', 'bottom-center'):
                issues.append((pline, 'warning', _('Unusual at-rule "@{0}"').format(at)))
        else:
            if not pstrip:
                issues.append((pline, 'error', _('A rule without a selector')))
            elif re.search(r'[^\w\s.#,>+~*:\[\]=\'"()^$|!-]', pstrip, re.UNICODE):
                short = ' '.join(pstrip.split())
                short = short[:50] + ('...' if len(short) > 50 else '')
                issues.append((pline, 'error', _('The selector "{0}" has invalid characters; '
                                                 'the whole rule is ignored').format(short)))
            else:
                _check_selector(pstrip, pline, issues)
        _check_declarations(body, j + 1, text, issues, at, '' if at else pstrip)
        i = end + 1

    if depth_stack:
        issues.append((_line_at(text, n), 'error', _('An @media block is never closed with "}"')))

    # Lots of property names with spaces or accents: machine-translated CSS
    if len(_suspicious) >= 5:
        issues.append((0, 'error', _('This CSS looks machine translated: property names such as '
                                     '"{0}" must be in English (margin, text-align, font-size...). '
                                     'Copy the original stylesheet from the book instead.').format(_suspicious[0])))
    seen = set()
    ans = []
    for line, level, msg in sorted(issues, key=lambda x: (x[0], x[1] != 'error')):
        if (line, msg) not in seen:
            seen.add((line, msg))
            ans.append((line, level, msg))
    return ans
