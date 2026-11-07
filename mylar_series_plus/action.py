#!/usr/bin/env python
# -*- coding: utf-8 -*-

try:
    load_translations()
except NameError:
    pass

import os
import re
import json
from html import escape
from urllib.parse import urlencode

from qt.core import QMenu, QInputDialog, QLineEdit, QIcon, QPixmap, QDialog
from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import error_dialog, info_dialog

# Importamos las preferencias y la interfaz del plugin
from calibre_plugins.mylar_series_plus.config import prefs
from calibre_plugins.mylar_series_plus.ui import ComicVineDialog, RESOURCES

API_BASE = 'https://comicvine.gamespot.com/api'
USER_AGENT = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# Campos a pedir según el tipo de ficha
FIELDS = {
    'volume': 'name,character_credits,location_credits,publisher,count_of_issues,description,deck,start_year',
    'series': 'name,characters,locations,publisher,count_of_episodes,description,deck,start_year',
}

# Firma del panel en los comentarios (sirve para reemplazarlo en vez de duplicarlo)
PANEL_RE = re.compile(r'\s*<div[^>]*border:\s*2px solid #2a7ae2.*?<hr\s*/?>', re.DOTALL | re.IGNORECASE)


class ComicVineError(Exception):
    pass


def html_to_text(html):
    if not html:
        return ''
    try:
        from calibre.utils.html2text import html2text
        return html2text(html).strip()
    except Exception:
        return re.sub(r'<[^>]+>', '', html).strip()


class MylarSeriesPlus(InterfaceAction):
    name = 'Mylar Series Plus'

    # action_spec: (nombre, icono_en_zip, ayuda, atajo)
    action_spec = ('Mylar Plus', None, 'Actualizar Serie desde ComicVine', 'Ctrl+Shift+M')

    def genesis(self):
        # --- LÓGICA DE ICONO INDESTRUCTIBLE (Método Walter) ---
        icon = None
        try:
            icon = get_icons('images/icon.png')  # noqa: F821 (inyectado por Calibre)
        except Exception:
            try:
                pixmap = QPixmap()
                pixmap.loadFromData(get_resources('images/icon.png'))  # noqa: F821
                icon = QIcon(pixmap)
            except Exception as e:
                print(f"Mylar Plus Debug: Falló la carga del icono -> {e}")

        if icon is not None and not icon.isNull():
            self.qaction.setIcon(icon)

        # Menú desplegable (la flecha al lado del botón)
        self.menu = QMenu(self.gui)
        self.setup_menu()
        self.qaction.setMenu(self.menu)

        # Clic principal del botón
        self.qaction.triggered.connect(self.main_flow)

    def setup_menu(self):
        """Opciones del menú de la flecha"""
        self.menu.addAction('Configurar API Key', self.show_config)
        self.menu.addSeparator()
        self.menu.addAction(_('About {0}').format('Mylar Series Plus'), self.about_plugin)

    def show_config(self):
        """Ventana para guardar la API Key"""
        key, ok = QInputDialog.getText(
            self.gui, 'Configuración ComicVine',
            'Introduce tu API Key de ComicVine:',
            QLineEdit.EchoMode.Normal, prefs['api_key']
        )
        if ok:
            prefs['api_key'] = key.strip()
            info_dialog(self.gui, 'Guardado', 'API Key actualizada.', show=True)

    def about_plugin(self):
        from calibre_plugins.mylar_series_plus.support import show_about
        show_about(self.gui, self.interface_action_base_plugin)

    def main_flow(self):
        """Flujo principal"""
        if not prefs['api_key']:
            return error_dialog(self.gui, 'Falta API Key',
                                'Configura tu API Key en la flecha del botón.', show=True)

        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            return error_dialog(self.gui, 'Error', 'Selecciona un libro.', show=True)

        book_id = self.gui.library_view.model().id(rows[0])
        db = self.gui.current_db.new_api

        series_name = db.field_for('series', book_id)
        if not series_name:
            return error_dialog(self.gui, 'Sin Serie', 'El libro debe tener una serie asignada.', show=True)

        d = ComicVineDialog(self.gui, series_name)
        if d.exec() != QDialog.DialogCode.Accepted or not d.result_id:
            return

        try:
            cv_data = self.fetch_comicvine_data(d.result_prefix, d.result_id)
        except ComicVineError as e:
            return error_dialog(self.gui, 'Error API', str(e), show=True)

        warnings = self.apply_all_metadata(db, book_id, cv_data, d.result_id)
        msg = f'Serie actualizada: {series_name}'
        if warnings:
            msg += '\n\n' + '\n'.join(warnings)
        info_dialog(self.gui, 'Éxito', msg, show=True)

    def fetch_comicvine_data(self, prefix, comic_id):
        resource = RESOURCES[prefix]
        params = {
            'api_key': prefs['api_key'],
            'format': 'json',
            'field_list': FIELDS[resource],
        }
        url = f"{API_BASE}/{resource}/{prefix}-{comic_id}/?{urlencode(params)}"
        print(f"Mylar Debug: Conectando a ComicVine ({resource} {prefix}-{comic_id})...")

        from calibre import browser
        br = browser(user_agent=USER_AGENT)
        try:
            raw = br.open_novisit(url, timeout=20).read()
        except Exception as e:
            code = getattr(e, 'code', None)
            if code == 401:
                raise ComicVineError('ComicVine rechazó la API Key. Revisala en la flecha del botón.')
            if code == 404:
                raise ComicVineError(f'No existe la ficha {prefix}-{comic_id} en ComicVine.')
            if code in (420, 429):
                raise ComicVineError('ComicVine limitó las consultas por exceso de pedidos. Probá de nuevo en unos minutos.')
            raise ComicVineError(f'No se pudo conectar con ComicVine:\n{e}')

        try:
            data = json.loads(raw)
        except ValueError:
            raise ComicVineError('ComicVine devolvió una respuesta que no es JSON.')

        if data.get('status_code') != 1:
            err = data.get('error') or 'Error desconocido'
            if data.get('status_code') == 100:
                err = 'API Key inválida. Revisala en la flecha del botón.'
            elif data.get('status_code') == 101:
                err = f'No existe la ficha {prefix}-{comic_id} en ComicVine.'
            raise ComicVineError(f'ComicVine respondió: {err}')

        results = data.get('results')
        if not results or not isinstance(results, dict):
            raise ComicVineError(f'ComicVine no devolvió datos para {prefix}-{comic_id}.')
        results['_resource'] = resource
        return results

    def apply_all_metadata(self, db, book_id, cv_data, comic_id):
        warnings = []
        chars_src = cv_data.get('character_credits') or cv_data.get('characters') or []
        locs_src = cv_data.get('location_credits') or cv_data.get('locations') or []
        chars = [c.get('name') for c in chars_src[:12] if c.get('name')]
        locs = [l.get('name') for l in locs_src[:6] if l.get('name')]
        pub_name = (cv_data.get('publisher') or {}).get('name') or 'Desconocido'

        total = cv_data.get('count_of_issues')
        if total is None:
            total = cv_data.get('count_of_episodes', 0)
        try:
            year = int(cv_data.get('start_year'))
        except (TypeError, ValueError):
            year = cv_data.get('start_year')

        mylar_metadata = {
            "version": "1.0.2",
            "metadata": {
                "type": "comicSeries",
                "name": cv_data.get('name') or '',
                "publisher": pub_name,
                "comicid": int(comic_id),
                "year": year,
                "total_issues": total or 0,
                "characters": chars,
                "locations": locs,
                "description_text": html_to_text(cv_data.get('description')) or (cv_data.get('deck') or ''),
            }
        }

        # Guardar series.json en la carpeta de datos del libro (<libro>/data/),
        # el lugar que calibre reserva para archivos extra: viaja con el libro
        # y no se pisa con el de otras series del mismo autor.
        try:
            from calibre.db.constants import DATA_DIR_NAME
        except Exception:
            DATA_DIR_NAME = 'data'
        book_path = db.field_for('path', book_id)
        library_path = self.gui.current_db.library_path
        data_dir = os.path.join(library_path, book_path, DATA_DIR_NAME)

        json_file = os.path.join(data_dir, 'series.json')
        try:
            os.makedirs(data_dir, exist_ok=True)
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(mylar_metadata, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error al guardar JSON: {e}")
            warnings.append(f'No se pudo guardar series.json: {e}')

        self.update_calibre_comments(db, book_id, mylar_metadata)
        return warnings

    def update_calibre_comments(self, db, book_id, data):
        m = data['metadata']
        badges = "".join([
            f'<span style="background:#f0f0f0; border:1px solid #ccc; border-radius:4px; padding:2px 6px; margin:2px; display:inline-block; color:#333; font-size:0.9em;">{escape(c)}</span>'
            for c in m['characters']
        ])
        year = escape(str(m['year'])) if m['year'] else '—'

        html_panel = f"""
        <div style="border: 2px solid #2a7ae2; border-radius: 10px; padding: 15px; background-color: rgba(42, 122, 226, 0.05); font-family: sans-serif;">
            <h2 style="color: #2a7ae2; margin-top: 0;">📚 {escape(m['name'])}</h2>
            <p><b>Editorial:</b> {escape(m['publisher'])} | <b>Año:</b> {year}</p>
            <p><b>Números:</b> {m['total_issues']}</p>
            <div style="margin: 10px 0;">
                <b>👥 Personajes:</b><br>{badges or '—'}
            </div>
            <p><b>📍 Localizaciones:</b> {escape(", ".join(m['locations'])) or '—'}</p>
        </div>
        <hr>
        """
        # Quitamos la ficha anterior (si la hay) para no acumular copias
        old_comments = PANEL_RE.sub('', db.field_for('comments', book_id) or "").lstrip()
        db.set_field('comments', {book_id: html_panel + old_comments})
        self.gui.library_view.model().refresh_ids([book_id])
