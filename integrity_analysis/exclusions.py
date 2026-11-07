# -*- coding: utf-8 -*-
"""
Gestión del archivo JSON de exclusiones de Integrity Analysis.

Formato del archivo (editable a mano):

{
  "version": 1,
  "excluded_tags": ["Sin archivo"],
  "books": [
    {
      "uuid": "b3c0...",
      "id": 123,
      "title": "Título de referencia",
      "checks": ["no_formats"],
      "note": "Registro vacío a propósito"
    }
  ]
}

- Un libro se identifica por "uuid" (preferente, sirve en cualquier biblioteca)
  o, si no hay uuid, por "id" (sólo válido en la biblioteca actual).
- "checks" admite: all, no_formats, formats, folder, opf, cover.
- "excluded_tags": los libros con cualquiera de esas etiquetas se omiten por completo.
"""

import io
import json
import os

try:
    load_translations()
except NameError:
    pass

from calibre.constants import config_dir

DEFAULT_FILE = os.path.join(config_dir, 'plugins', 'integrity_analysis_exclusions.json')

# Clave interna -> descripción mostrada
CHECKS = (
    ('all', _('All checks (skip the book entirely)')),
    ('no_formats', _('Book without formats (empty record)')),
    ('formats', _('Missing or empty format files')),
    ('folder', _('Missing book folder')),
    ('opf', _('Missing or empty metadata.opf')),
    ('cover', _('Missing cover.jpg')),
)
VALID_CHECKS = {k for k, _label in CHECKS}


def exclusions_path():
    from calibre_plugins.integrity_analysis.config import plugin_prefs
    path = (plugin_prefs.get('exclusions_file') or '').strip()
    return path or DEFAULT_FILE


def empty_data():
    return {'version': 1, 'excluded_tags': [], 'books': []}


class ExclusionsError(Exception):
    pass


def _normalize(data):
    if not isinstance(data, dict):
        raise ExclusionsError(_('The root of the JSON file must be an object {...}'))
    out = empty_data()
    tags = data.get('excluded_tags') or []
    if not isinstance(tags, list):
        raise ExclusionsError(_('"excluded_tags" must be a list'))
    out['excluded_tags'] = [str(t).strip() for t in tags if str(t).strip()]
    books = data.get('books') or []
    if not isinstance(books, list):
        raise ExclusionsError(_('"books" must be a list'))
    for i, entry in enumerate(books):
        if not isinstance(entry, dict):
            raise ExclusionsError(_('Entry #{0} in "books" is not an object').format(i + 1))
        uuid = (entry.get('uuid') or '').strip() or None
        book_id = entry.get('id')
        try:
            book_id = int(book_id) if book_id is not None else None
        except (TypeError, ValueError):
            raise ExclusionsError(_('Entry #{0}: "id" must be a number').format(i + 1))
        if uuid is None and book_id is None:
            raise ExclusionsError(_('Entry #{0} needs a "uuid" or an "id"').format(i + 1))
        checks = entry.get('checks') or ['all']
        if isinstance(checks, str):
            checks = [checks]
        checks = [str(c).strip().lower() for c in checks]
        bad = [c for c in checks if c not in VALID_CHECKS]
        if bad:
            raise ExclusionsError(_('Entry #{0}: unknown check(s): {1}').format(i + 1, ', '.join(bad)))
        out['books'].append({
            'uuid': uuid,
            'id': book_id,
            'title': entry.get('title') or '',
            'checks': sorted(set(checks)),
            'note': entry.get('note') or '',
        })
    return out


def load(path=None):
    """Devuelve los datos normalizados. Si el archivo no existe, devuelve uno vacío."""
    path = path or exclusions_path()
    if not os.path.exists(path):
        return empty_data()
    try:
        with io.open(path, 'r', encoding='utf-8-sig') as f:
            raw = json.load(f)
    except ValueError as e:
        raise ExclusionsError(_('The JSON file is not valid: {0}').format(e))
    return _normalize(raw)


def save(data, path=None):
    path = path or exclusions_path()
    folder = os.path.dirname(path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    data = _normalize(data)
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, path)
    return path


class ExclusionMatcher(object):
    """Resuelve rápidamente qué comprobaciones hay que omitir para cada libro."""

    def __init__(self, data):
        self.by_uuid = {}
        self.by_id = {}
        for e in data['books']:
            checks = set(e['checks'])
            if e['uuid']:
                self.by_uuid.setdefault(e['uuid'], set()).update(checks)
            elif e['id'] is not None:
                self.by_id.setdefault(e['id'], set()).update(checks)
        self.tags = {t.lower() for t in data['excluded_tags']}

    def skipped_checks(self, book_id, uuid, tags):
        if self.tags and tags and any(t.lower() in self.tags for t in tags):
            return {'all'}
        s = set()
        if uuid and uuid in self.by_uuid:
            s |= self.by_uuid[uuid]
        if book_id in self.by_id:
            s |= self.by_id[book_id]
        return s


def add_books(data, books, checks, note):
    """books: lista de (id, uuid, title). Fusiona con entradas existentes."""
    checks = sorted(set(checks)) or ['all']
    if 'all' in checks:
        checks = ['all']
    added = 0
    for book_id, uuid, title in books:
        found = None
        for e in data['books']:
            if (uuid and e['uuid'] == uuid) or (not e['uuid'] and e['id'] == book_id):
                found = e
                break
        if found is None:
            data['books'].append({'uuid': uuid, 'id': book_id, 'title': title or '',
                                  'checks': list(checks), 'note': note or ''})
            added += 1
        else:
            merged = set(found['checks']) | set(checks)
            found['checks'] = ['all'] if 'all' in merged else sorted(merged)
            found['id'] = book_id
            if title:
                found['title'] = title
            if note:
                found['note'] = note
    return added


def remove_books(data, books):
    uuids = {u for _i, u, _t in books if u}
    ids = {i for i, _u, _t in books}
    before = len(data['books'])
    data['books'] = [e for e in data['books']
                     if not ((e['uuid'] and e['uuid'] in uuids) or (not e['uuid'] and e['id'] in ids))]
    return before - len(data['books'])
