import html
import re

try:
    load_translations()
except NameError:
    pass

from qt.core import (
    QDialog, QHBoxLayout, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QScrollArea, QWidget, QFrame, QLabel, QPushButton, QPixmap, Qt,
    QPlainTextEdit, QApplication, QCheckBox, QToolButton, QMenu
)
from calibre.gui2 import error_dialog, info_dialog, question_dialog
from calibre.ebooks.metadata.book.base import Metadata
from calibre_plugins.goodreads_series_explorer.worker import (
    FetchSeriesWorker, SpanishEditionWorker, AuthorWorker, clear_cache, norm_title,
    load_settings
)
from calibre_plugins.goodreads_series_explorer import lang

# Mantiene vivos los hilos hasta que terminan, aunque se cierre el diálogo,
# para evitar "QThread: Destroyed while thread is still running".
_running_workers = set()


def _keep_alive(worker):
    _running_workers.add(worker)
    worker.finished.connect(lambda w=worker: _release_worker(w))


def _release_worker(worker):
    worker.wait()
    _running_workers.discard(worker)


def _disconnect(signal, slot):
    try:
        signal.disconnect(slot)
    except (TypeError, RuntimeError):
        pass


def search_quote(text):
    """Escapa barras y comillas para usar el texto dentro de una búsqueda de calibre."""
    return (text or '').replace('\\', '\\\\').replace('"', '\\"')


def fmt_index(idx):
    if idx is None:
        return ''
    return str(int(idx)) if float(idx).is_integer() else f'{idx:g}'


def _close_browser():
    """Cierra el navegador Camoufox, si se abrió (no bloquea la interfaz)."""
    try:
        from calibre_plugins.goodreads_series_explorer.worker import shutdown_browser
        shutdown_browser()
    except Exception:
        pass


class SeriesViewerDialog(QDialog):
    def __init__(self, gui, book_id, parent=None, plugin=None):
        super().__init__(parent or gui)
        self.gui = gui
        self.plugin = plugin
        self.settings = load_settings()
        # Idioma de las ediciones buscadas (el de calibre o el elegido) y su nombre para mostrar
        self.lang_code = lang.resolve(self.settings.get('edition_language', 'auto'))
        self.lang_name = lang.display_name(self.lang_code)
        # Etiqueta de las entradas vacías (lista de deseos); vacía = sin etiqueta
        tag = self.settings.get('wishlist_tag')
        self.wish_tag = (_('To get') if tag is None else tag).strip()
        self.legacy_db = gui.current_db
        self.db = gui.current_db.new_api
        self.book_id = book_id
        self.worker = None
        self.author_worker = None
        self.diagnostics_text = ''
        self.mi = self.db.get_metadata(book_id)
        # 'series' = libros de la serie; 'author' = libros del autor
        self.mode = 'series'
        self.series_name = ''
        self.series_books = None
        self.series_state = 'loading'      # loading | ok | not_found | error
        self.author_data = None
        self.author_url = ''
        self.warnings = {'series': '', 'author': ''}
        self.cards = []
        self.groups = []                   # (encabezado, [tarjetas]) en la vista por autor
        # Cola de búsquedas en español: se hacen de a una para no saturar Goodreads
        self.es_queue = []
        self.es_worker = None
        self.es_card = None
        self.library = self._library_books()
        self._titles = None

        self.setWindowTitle(_('Explore series - Goodreads'))
        self.resize(1050, 720)

        self.init_ui()
        self.build_tree()
        self.start_loading()

    # ---------------------------------------------------------------- UI

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabel(_('Sources'))
        self.tree.setMaximumWidth(260)
        self.tree.itemClicked.connect(self.on_tree_clicked)
        main_layout.addWidget(self.tree)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(5, 5, 5, 5)

        self.header_label = QLabel(self._header_html())
        self.header_label.setWordWrap(True)
        self.header_label.setStyleSheet(
            'font-size: 12px; padding: 6px; background-color: #f0f0f0; '
            'border: 1px solid #d0d0d0; border-radius: 4px; color: #222;')
        right_layout.addWidget(self.header_label)

        # Aviso para guardar el ID de Goodreads encontrado por búsqueda
        self.save_id_row = QWidget()
        save_layout = QHBoxLayout(self.save_id_row)
        save_layout.setContentsMargins(6, 2, 6, 2)
        self.save_id_label = QLabel()
        self.save_id_label.setWordWrap(True)
        self.save_id_label.setStyleSheet('color: #1f5f99;')
        save_layout.addWidget(self.save_id_label, stretch=1)
        self.save_id_btn = QPushButton('💾 ' + _('Save Goodreads ID in calibre'))
        self.save_id_btn.clicked.connect(self.save_goodreads_id)
        save_layout.addWidget(self.save_id_btn)
        self.save_id_row.setVisible(False)
        self.found_match = None
        right_layout.addWidget(self.save_id_row)

        self.status_label = QLabel(_('Loading data from Goodreads...'))
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet('color: #555; padding: 2px 6px;')
        right_layout.addWidget(self.status_label)

        controls = QHBoxLayout()
        self.only_missing = QCheckBox(_('Show only the ones I am missing'))
        self.only_missing.toggled.connect(self.apply_filter)
        controls.addWidget(self.only_missing)
        self.show_all = QCheckBox(_('Show everything from Goodreads'))
        self.show_all.setToolTip(_('Includes the books without an edition in {0}, box sets, '
                                   'foreign editions and companion books.').format(self.lang_name))
        self.show_all.toggled.connect(self.apply_filter)
        controls.addWidget(self.show_all)
        controls.addStretch()
        self.view_btn = QPushButton('👤 ' + _('Books by the author'))
        self.view_btn.clicked.connect(self.toggle_view)
        controls.addWidget(self.view_btn)
        self.diag_btn = QPushButton(_('Show diagnostics'))
        self.diag_btn.setEnabled(False)
        self.diag_btn.clicked.connect(self.show_diagnostics)
        controls.addWidget(self.diag_btn)
        if self.plugin is not None:
            cfg_btn = QPushButton('⚙ ' + _('Settings'))
            cfg_btn.clicked.connect(self.open_settings)
            controls.addWidget(cfg_btn)
        right_layout.addLayout(controls)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.cards_layout = QVBoxLayout(self.scroll_content)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.scroll_content)
        right_layout.addWidget(self.scroll)

        bottom = QHBoxLayout()
        bottom.addStretch()
        close_btn = QPushButton(_('Close'))
        close_btn.clicked.connect(self.close)
        bottom.addWidget(close_btn)
        right_layout.addLayout(bottom)

        main_layout.addWidget(right_container)

    def _header_html(self):
        mi = self.mi
        e = html.escape
        authors = ' & '.join(mi.authors) if mi.authors else _('Unknown')
        parts = [
            f'<b>{_("Book")}:</b> {e(mi.title or _("Unknown"))}',
            f'<b>{_("Author")}:</b> {e(authors)}',
            f'<b>{_("calibre ID")}:</b> {self.book_id}',
        ]
        if mi.series:
            parts.append(f'<b>{_("Current series")}:</b> {e(mi.series)} [{fmt_index(mi.series_index)}]')
        return ' | '.join(parts)

    def build_tree(self):
        self.tree.clear()
        gr = QTreeWidgetItem(self.tree, ['Goodreads'])
        series_text = {
            'loading': _('Series: searching...'),
            'not_found': _('Series: not found'),
            'error': _('Series: error while loading'),
        }.get(self.series_state, _('Series: {0}').format(self.series_name))
        self.series_item = QTreeWidgetItem(gr, [series_text])
        self.series_item.setData(0, Qt.ItemDataRole.UserRole, 'series')
        author = (self.author_data or {}).get('author') or ' & '.join(self.mi.authors or []) or '?'
        self.author_item = QTreeWidgetItem(gr, [_('Author: {0}').format(author)])
        self.author_item.setData(0, Qt.ItemDataRole.UserRole, 'author')
        gr.setExpanded(True)

        own = self.calibre_series()
        if own:
            cal = QTreeWidgetItem(self.tree, [_('Your series in calibre')])
            for name, (have, missing) in sorted(own.items()):
                text = name + ('  ' + _('({0} missing)').format(len(missing)) if missing else '')
                item = QTreeWidgetItem(cal, [text])
                item.setData(0, Qt.ItemDataRole.UserRole, 'author')
            cal.setExpanded(True)
        self.tree.setCurrentItem(self.series_item if self.mode == 'series' else self.author_item)

    # ------------------------------------------------------------- datos

    def _library_books(self):
        """Libros del mismo autor que ya están en la biblioteca (solo consulta
        local, sin Goodreads)."""
        ids = set()
        for author in (self.mi.authors or [])[:3]:
            try:
                ids |= self.db.search(f'authors:"={search_quote(author)}"')
            except Exception:
                pass
        ids.add(self.book_id)

        books = []
        for book_id in ids:
            identifiers = self.db.field_for('identifiers', book_id) or {}
            gr_id = None
            for k, v in identifiers.items():
                if 'goodreads' in k.lower() or k.lower() == 'gr':
                    m = re.search(r'\d+', str(v))
                    if m:
                        gr_id = m.group(0)
                        break
            isbn = re.sub(r'[^0-9Xx]', '', str(identifiers.get('isbn', ''))).upper()
            books.append({
                'id': book_id,
                'title': self.db.field_for('title', book_id),
                'series': self.db.field_for('series', book_id),
                'series_index': self.db.field_for('series_index', book_id),
                'gr_id': gr_id,
                'isbn': isbn if len(isbn) in (10, 13) else None,
            })
        return books

    def calibre_series(self):
        """Series de calibre de este autor: {serie: ([(número, título)], [números faltantes])}."""
        series = {}
        for b in self.library:
            if b.get('series'):
                series.setdefault(b['series'], []).append((b.get('series_index') or 0, b['title']))
        result = {}
        for name, items in series.items():
            items.sort()
            have = {int(i) for i, _ in items if float(i).is_integer()}
            top = max((int(i) for i, _ in items), default=0)
            missing = [n for n in range(1, top + 1) if n not in have]
            result[name] = (items, missing)
        return result

    def titles_index(self):
        """Títulos normalizados de los libros del autor que ya tenés -> ID de calibre."""
        if self._titles is None:
            self._titles = {}
            for b in self.library:
                key = norm_title(b.get('title'))
                if key:
                    self._titles.setdefault(key, b['id'])
        return self._titles

    def start_loading(self):
        query = {
            'id': self.book_id,
            'title': self.mi.title,
            'authors': list(self.mi.authors or []),
            'identifiers': dict(self.mi.identifiers or {}),
            'series': self.mi.series,
            'series_index': self.mi.series_index if self.mi.series else None,
        }
        worker = FetchSeriesWorker(query, self.library)
        worker.data_loaded.connect(self.on_data_loaded)
        worker.progress.connect(self.on_progress)
        worker.error_occurred.connect(self.on_error)
        worker.diagnostics.connect(self.on_diagnostics)
        worker.match_found.connect(self.on_match_found)
        worker.not_found.connect(self.on_series_not_found)
        worker.author_found.connect(self.on_author_found)
        _keep_alive(worker)
        self.worker = worker
        worker.start()

    def start_author(self):
        if self.author_worker is not None:
            return
        self.status_label.setText(_('Looking for the author\'s books on Goodreads...'))
        worker = AuthorWorker(list(self.mi.authors or []), self.author_url, self.library)
        worker.data_loaded.connect(self.on_author_loaded)
        worker.progress.connect(self.on_progress)
        worker.error_occurred.connect(self.on_author_error)
        worker.diagnostics.connect(self.append_diagnostics_text)
        _keep_alive(worker)
        self.author_worker = worker
        worker.start()

    def _stop_workers(self):
        w, self.worker = self.worker, None
        if w is not None:
            w.abort()
            _disconnect(w.data_loaded, self.on_data_loaded)
            _disconnect(w.progress, self.on_progress)
            _disconnect(w.error_occurred, self.on_error)
            _disconnect(w.diagnostics, self.on_diagnostics)
            _disconnect(w.match_found, self.on_match_found)
            _disconnect(w.not_found, self.on_series_not_found)
            _disconnect(w.author_found, self.on_author_found)
        a, self.author_worker = self.author_worker, None
        if a is not None:
            a.abort()
            _disconnect(a.data_loaded, self.on_author_loaded)
            _disconnect(a.progress, self.on_progress)
            _disconnect(a.error_occurred, self.on_author_error)
            _disconnect(a.diagnostics, self.append_diagnostics_text)
        self.es_queue.clear()
        es, self.es_worker = self.es_worker, None
        if es is not None:
            es.abort()
            _disconnect(es.finished_book, self.on_spanish_done)

    def done(self, result):
        self._stop_workers()
        _close_browser()
        super().done(result)

    def closeEvent(self, ev):
        self._stop_workers()
        _close_browser()
        super().closeEvent(ev)

    # ------------------------------------------------------- cambio de vista

    def on_tree_clicked(self, item, column):
        kind = item.data(0, Qt.ItemDataRole.UserRole)
        if kind:
            self.show_view(kind)

    def toggle_view(self):
        self.show_view('author' if self.mode == 'series' else 'series')

    def show_view(self, mode):
        self.mode = mode
        self.view_btn.setText('📚 ' + _('Back to the series') if mode == 'author' else '👤 ' + _('Books by the author'))
        self.view_btn.setEnabled(mode == 'series' or self.series_state != 'not_found')
        self.tree.setCurrentItem(self.series_item if mode == 'series' else self.author_item)
        if mode == 'author' and self.author_data is None:
            self.clear_cards()
            self.cards_layout.addWidget(self._calibre_summary_label())
            self.start_author()
            return
        self.render()

    def clear_cards(self):
        # Las búsquedas en cola son de la vista anterior
        self.es_queue.clear()
        while self.cards_layout.count():
            child = self.cards_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.cards = []
        self.groups = []

    def card_series(self, book):
        """Serie para una entrada nueva: la que ya usás en calibre si se conoce."""
        if 'target_series' in book:
            return book.get('target_series') or ''
        return self.mi.series or self.series_name

    def render(self):
        self.clear_cards()
        if self.mode == 'series':
            if self.series_books is None:
                self.status_label.setText({
                    'loading': _('Loading the series from Goodreads...'),
                    'not_found': _('Goodreads has no series for this book. '
                                   'See the view by author.'),
                }.get(self.series_state, _('The series could not be loaded.')))
                return
            for b in self.series_books:
                card = BookCardFrame(b, self, self.card_series(b))
                self.cards.append(card)
                self.cards_layout.addWidget(card)
            self.apply_filter()
            # Los libros que te faltan y todavía no se sabe si tienen edición en
            # español se consultan de a uno; aparecen a medida que se confirman
            if not self.warnings['series'] and self.settings.get('auto_spanish', True):
                for card in self.cards:
                    if card.needs_spanish_check():
                        self.request_spanish(card)
            self.update_status()
            return

        # Vista por autor
        self.cards_layout.addWidget(self._calibre_summary_label())
        books = self.author_data['books']
        groups = {}
        for b in books:
            groups.setdefault(b.get('series_name') or '', []).append(b)
        order = sorted((k for k in groups if k), key=lambda k: norm_title(k))
        if '' in groups:
            order.append('')
        for name in order:
            items = sorted(groups[name], key=lambda b: (b['index'] is None, b['index'] or 0))
            singles = [b for b in items if b.get('kind') == 'single']
            owned = sum(1 for b in singles if b.get('lib_id'))
            if name:
                text = '📚 ' + html.escape(name) + ' — ' + _('you have {0} of {1}').format(owned, len(singles))
            else:
                text = _('No series on Goodreads') + ' — ' + _('you have {0} of {1}').format(owned, len(singles))
            header = QLabel(f'<b>{text}</b>')
            header.setStyleSheet('font-size: 13px; padding: 8px 2px 2px 2px; color: #333;')
            self.cards_layout.addWidget(header)
            group_cards = []
            for b in items:
                card = BookCardFrame(b, self, self.card_series(b))
                self.cards.append(card)
                group_cards.append(card)
                self.cards_layout.addWidget(card)
            self.groups.append((header, group_cards))
        self.apply_filter()

    def _calibre_summary_label(self):
        own = self.calibre_series()
        e = html.escape
        if not own:
            text = '<b>' + _('Your series in calibre:') + '</b> ' + _('none of your books by this author has a series set.')
        else:
            lines = ['<b>' + _('Your series in calibre by this author') + '</b>']
            for name, (items, missing) in sorted(own.items()):
                have = ', '.join(f'#{fmt_index(i)}' for i, _ in items)
                line = e(name) + ': ' + _('you have {0}').format(have)
                if missing:
                    line += (' · <span style="color:#b26a00;"><b>'
                             + _('missing {0}').format(', '.join(f'#{n}' for n in missing)) + '</b></span>')
                lines.append(line)
            lines.append('<span style="color:#888; font-size:11px;">'
                         + _('The missing ones are worked out from your numbers; there may be '
                             'more books after the last one.') + '</span>')
            text = '<br>'.join(lines)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet('padding: 6px; background-color: #f7f3e8; border: 1px solid #e0d6b8; '
                            'border-radius: 4px; color: #222;')
        return label

    # -------------------------------------------------------- resultados

    def on_progress(self, message):
        self.status_label.setText(message)

    def on_data_loaded(self, books, series_name, warning):
        self.series_name = series_name
        self.series_books = books
        self.series_state = 'ok'
        self.warnings['series'] = warning
        self.build_tree()
        if self.mode == 'series':
            self.render()

    def on_series_not_found(self, author_url):
        self.series_state = 'not_found'
        self.author_url = author_url or ''
        self.build_tree()
        if self.mode == 'series':
            self.show_view('author')

    def on_author_found(self, url):
        if url and not self.author_url:
            self.author_url = url

    def on_author_loaded(self, data):
        self.author_worker = None
        self.author_data = data
        self.author_url = data.get('author_url') or self.author_url
        self.warnings['author'] = data.get('warning') or ''
        self.build_tree()
        if self.mode == 'author':
            self.render()

    def on_author_error(self, message):
        self.author_worker = None
        if self.mode == 'author':
            self.status_label.setText(message)
        error_dialog(self, _('Books by the author'), message, show=True)

    def update_status(self):
        if self.mode == 'author':
            return self._update_author_status()
        warning = self.warnings['series']
        singles = [c for c in self.cards if c.book_data.get('kind') == 'single']
        others = len(self.cards) - len(singles)
        owned = sum(1 for c in singles if c.lib_id and not c.is_wish)
        wished = sum(1 for c in singles if c.is_wish)
        missing = [c for c in singles if not c.lib_id]
        es_missing = sum(1 for c in missing if c.book_data.get('es_status') == 'found')
        no_es = sum(1 for c in missing if c.book_data.get('es_status') == 'none')
        pending = len(self.es_queue) + (1 if self.es_card is not None else 0)

        parts = [_('{0} in your library').format(owned),
                 _('{0} missing (with an edition in {1})').format(es_missing, self.lang_name)]
        if wished:
            parts.append(_('{0} marked "{1}"').format(wished, self.wish_tag))
        if pending:
            parts.append(_('looking up the edition in {0} of {1} more...').format(self.lang_name, pending))
        status = ' · '.join(parts)
        unchecked = sum(1 for c in missing if c.book_data.get('es_status') == 'unknown'
                        and c is not self.es_card and c not in self.es_queue)
        hidden = []
        not_checked = _('{0} not checked').format(unchecked)
        if unchecked:
            hidden.append(not_checked)
        if no_es:
            hidden.append(_('{0} without an edition in {1}').format(no_es, self.lang_name))
        if others:
            hidden.append(_('{0} box sets, foreign editions or companion books').format(others))
        if unchecked and not self.settings.get('auto_spanish', True):
            # Con la búsqueda automática apagada, los no revisados se muestran
            hidden.remove(not_checked)
            status += '\n' + _('{0} not checked in {1} (use 🌐 on each one)').format(unchecked, self.lang_name)
        if hidden:
            word = _('shown') if self.show_all.isChecked() else _('hidden')
            status += '\n' + (' ' + _('and') + ' ').join(hidden) + f' ({word})'
        if warning:
            status += f'\n⚠ {warning}'
        self.status_label.setText(status)

    def open_settings(self):
        try:
            self.plugin.do_user_config(self)
        except Exception as e:
            error_dialog(self, _('Settings'), _('Could not open the settings: {0}').format(e), show=True)
            return
        self.settings = load_settings()
        new_code = lang.resolve(self.settings.get('edition_language', 'auto'))
        if new_code != self.lang_code:
            info_dialog(self, _('Settings'), _('The new language of the editions is used the next time '
                                               'you open the explorer.'), show=True)
        self.apply_filter()

    def _update_author_status(self):
        data = self.author_data or {}
        singles = [c for c in self.cards if c.book_data.get('kind') == 'single']
        others = len(self.cards) - len(singles)
        owned = sum(1 for c in singles if c.lib_id and not c.is_wish)
        status = (f'{data.get("author", "")}: ' + _('{0} books on Goodreads').format(len(singles)) + ' · '
                  + _('{0} in your library').format(owned) + ' · '
                  + _('{0} missing').format(len(singles) - owned))
        if others:
            word = _('shown') if self.show_all.isChecked() else _('hidden')
            status += '\n' + _('{0} box sets, editions in another script or books under another name').format(others) + f' ({word})'
        if self.series_state == 'not_found':
            status += '\n' + _('Goodreads has no series for this book; the author\'s books are shown.')
        if self.warnings['author']:
            status += f'\n⚠ {self.warnings["author"]}'
        self.status_label.setText(status)

    def apply_filter(self, *_):
        only = self.only_missing.isChecked()
        show_all = self.show_all.isChecked()
        for card in self.cards:
            hidden = (only and card.lib_id and not card.is_wish) or (not show_all and not card.in_main_view())
            card.setVisible(not hidden)
        for header, cards in self.groups:
            header.setVisible(any(not c.isHidden() for c in cards))
        if self.cards:
            self.update_status()

    def on_match_found(self, gr_id, title):
        self.found_match = (gr_id, title)
        self.save_id_label.setText(
            _('This book had no Goodreads ID; it was found by searching as "{0}" (ID {1}). '
              'If it is correct, save it so that next time the search is direct.').format(title, gr_id))
        self.save_id_row.setVisible(True)

    def save_goodreads_id(self):
        if not self.found_match:
            return
        gr_id, title = self.found_match
        if not question_dialog(
                self, _('Save Goodreads ID'),
                _('Save the Goodreads ID {0} ("{1}") in "{2}"?').format(gr_id, title, self.mi.title)
                + '\n\n' + _('Check that it is the same book before accepting.')):
            return
        try:
            identifiers = dict(self.db.field_for('identifiers', self.book_id) or {})
            if identifiers.get('goodreads'):
                error_dialog(self, _('Save Goodreads ID'), _('This book already has a Goodreads ID; '
                                                             'it is not replaced.'), show=True)
                return
            identifiers['goodreads'] = gr_id
            self.db.set_field('identifiers', {self.book_id: identifiers})
            self.gui.library_view.model().refresh_ids([self.book_id])
        except Exception as e:
            error_dialog(self, _('Error'), _('Could not save the ID: {0}').format(e), show=True)
            return
        self.save_id_label.setText('✓ ' + _('Goodreads ID {0} saved in "{1}".').format(gr_id, self.mi.title))
        self.save_id_btn.setVisible(False)

    def on_diagnostics(self, text):
        self.diagnostics_text = text
        self.diag_btn.setEnabled(True)

    def append_diagnostics_text(self, text):
        self.append_diagnostics(text.splitlines())

    def append_diagnostics(self, lines):
        if lines:
            self.diagnostics_text = '\n'.join(filter(None, [self.diagnostics_text] + list(lines)))
            self.diag_btn.setEnabled(True)

    def show_diagnostics(self):
        DiagnosticsDialog(self.diagnostics_text, self).exec()

    def on_error(self, message):
        self.series_state = 'error'
        self.build_tree()
        self.status_label.setText(_('Error while getting the data'))
        error_dialog(self, _('Loading error'), message, show=True)

    # ------------------------------------------- búsqueda en español a pedido

    def request_spanish(self, card):
        if card is self.es_card or card in self.es_queue:
            return
        self.es_queue.append(card)
        card.set_spanish_state(_('Queued...'))
        self._next_spanish()

    def _next_spanish(self):
        if self.es_worker is not None or not self.es_queue:
            return
        card = self.es_queue.pop(0)
        self.es_card = card
        card.set_spanish_state(_('Searching...'))
        worker = SpanishEditionWorker(card.book_data)
        worker.finished_book.connect(self.on_spanish_done)
        _keep_alive(worker)
        self.es_worker = worker
        worker.start()

    def on_spanish_done(self, book, status, message):
        worker, self.es_worker = self.es_worker, None
        card, self.es_card = self.es_card, None
        if worker is not None:
            self.append_diagnostics(worker.lines)

        if card is not None and card in self.cards:
            if status == 'found':
                new_card = BookCardFrame(book, self, self.card_series(book))
                idx = self.cards_layout.indexOf(card)
                self.cards_layout.insertWidget(idx, new_card)
                self.cards[self.cards.index(card)] = new_card
                for _, group_cards in self.groups:
                    if card in group_cards:
                        group_cards[group_cards.index(card)] = new_card
                card.hide()
                card.deleteLater()
            else:
                card.set_spanish_state(message, failed=True)

        if status == 'limited':
            # Goodreads frenó las consultas: se cancela el resto de la cola
            for pending in self.es_queue:
                pending.set_spanish_state(_('Cancelled: Goodreads limited the requests'), failed=True)
            self.es_queue.clear()
            self.warnings[self.mode] = _('Goodreads limited the requests; some books were not '
                                         'checked. Open it again in a few minutes.')

        self.apply_filter()
        self.update_status()
        self._next_spanish()


class DiagnosticsDialog(QDialog):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Search diagnostics'))
        self.resize(900, 550)
        layout = QVBoxLayout(self)

        hint = QLabel(_('This is what the plugin did. Lines with "→" are requests to Goodreads; '
                        'lines with "·" came from the cache.'))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setPlainText(text or _('No data yet.'))
        layout.addWidget(self.text)

        buttons = QHBoxLayout()
        clear_btn = QPushButton(_('Clear cache'))
        clear_btn.setToolTip(_('Forces Goodreads to be queried again next time.'))
        clear_btn.clicked.connect(self.clear_cache)
        buttons.addWidget(clear_btn)
        buttons.addStretch()
        copy_btn = QPushButton(_('Copy to clipboard'))
        copy_btn.clicked.connect(self.copy)
        buttons.addWidget(copy_btn)
        close_btn = QPushButton(_('Close'))
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def copy(self):
        QApplication.clipboard().setText(self.text.toPlainText())

    def clear_cache(self):
        try:
            count = clear_cache()
        except Exception as e:
            error_dialog(self, _('Error'), _('Could not clear the cache: {0}').format(e), show=True)
            return
        info_dialog(self, _('Cache'), _('{0} saved pages were deleted.').format(count), show=True)


class BookCardFrame(QFrame):
    def __init__(self, book_data, dialog, series_name):
        super().__init__(dialog.scroll_content)
        self.dialog = dialog
        self.gui = dialog.gui
        self.db = dialog.db
        self.legacy_db = dialog.legacy_db
        self.book_data = book_data
        self.series_name = series_name
        self.lib_id = book_data.get('lib_id') or self._find_by_title()
        # Entrada vacía creada con la etiqueta de la lista de deseos (sin archivo)
        self.is_wish = self._is_wish()

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            BookCardFrame {
                background-color: #fcfcfc;
                border: 1px solid #cccccc;
                border-radius: 6px;
                margin-bottom: 6px;
            }
            QLabel { color: #222222; }
        """)

        e = html.escape
        layout = QHBoxLayout(self)
        info_layout = QVBoxLayout()

        # Fila superior: título y estado en la biblioteca
        top = QHBoxLayout()
        num = book_data['num']
        title_html = f'<b>{e(num + " " if num else "")}{e(book_data["title"])}</b>'
        original = book_data.get('original_title')
        if original and original != book_data['title']:
            title_html += f' <span style="color:#888; font-size:11px;">({e(original)})</span>'
        if book_data.get('kind', 'single') != 'single':
            tag = _('Box set') if book_data.get('kind') == 'pack' else _('Other edition')
            title_html = (f'<span style="color:#7a4fa0; font-size:11px;" title="'
                          f'{e(book_data.get("kind_reason", ""))}">[{tag}]</span> ' + title_html)
        title_lbl = QLabel(title_html)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet('font-size: 14px;')
        top.addWidget(title_lbl, stretch=1)

        self.status_lbl = QLabel()
        self._set_status()
        top.addWidget(self.status_lbl, alignment=Qt.AlignmentFlag.AlignTop)
        info_layout.addLayout(top)

        if book_data['author']:
            author_lbl = QLabel(f"<i>{e(book_data['author'])}</i>")
            author_lbl.setStyleSheet('color: #555555;')
            info_layout.addWidget(author_lbl)

        if book_data['rating']:
            rating_lbl = QLabel(f"★ {book_data['rating']}")
            rating_lbl.setTextFormat(Qt.TextFormat.PlainText)
            rating_lbl.setStyleSheet('color: #9a7b1c; font-size: 11px;')
            info_layout.addWidget(rating_lbl)

        if book_data['synopsis']:
            synopsis_lbl = QLabel(book_data['synopsis'])
            synopsis_lbl.setTextFormat(Qt.TextFormat.PlainText)
            synopsis_lbl.setWordWrap(True)
            synopsis_lbl.setStyleSheet('color: #333333; margin-top: 4px;')
            info_layout.addWidget(synopsis_lbl)

        self.btn_layout = QHBoxLayout()
        missing = not self.lib_id or self.is_wish
        single = book_data.get('kind', 'single') == 'single'

        # Lo principal para un libro que falta: conseguirlo
        self.btn_store = None
        if missing and self.gui.iactions.get('Store') is not None:
            self.btn_store = QPushButton('🛒 ' + _('Search in stores'))
            self.btn_store.setToolTip(_('Opens calibre\'s "Get books" with this title and author. '
                                        'What you download from there is added to the library.'))
            self.btn_store.clicked.connect(self.search_in_stores)
            self.btn_layout.addWidget(self.btn_store)

        # Libros que te faltan y siguen con datos de otro idioma: edición a pedido
        self.btn_es = None
        self.es_lbl = None
        if not book_data.get('spanish') and not self.lib_id and single:
            self.btn_es = QPushButton('🌐 ' + _('Search edition in {0}').format(dialog.lang_name))
            self.btn_es.setToolTip(_('Looks up on Goodreads the edition in {0} of this book and shows '
                                     'its title, cover and synopsis.').format(dialog.lang_name))
            self.btn_es.clicked.connect(lambda: self.dialog.request_spanish(self))
            self.btn_layout.addWidget(self.btn_es)

        # Lo secundario va en "Más"; un libro tuyo solo necesita ir a verlo en calibre
        self.more_btn = None
        if self.lib_id:
            btn_show = QPushButton('🔍 ' + _('Show in calibre'))
            btn_show.clicked.connect(self.search_in_calibre)
            self.btn_layout.addWidget(btn_show)
        else:
            self.more_btn = QToolButton()
            self.more_btn.setText('⋯ ' + _('More'))
            self.more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(self.more_btn)
            add_text = '➕ ' + _('Create empty entry')
            if dialog.wish_tag:
                add_text += ' (' + _('tag "{0}"').format(dialog.wish_tag) + ')'
            menu.addAction(add_text, self.add_empty_entry)
            menu.addAction('🔍 ' + _('Search in calibre'), self.search_in_calibre)
            self.more_btn.setMenu(menu)
            self.btn_layout.addWidget(self.more_btn)

        if not book_data.get('spanish') and not (self.lib_id and not self.is_wish):
            if book_data.get('es_status') == 'none':
                note = _('No edition in {0}').format(dialog.lang_name)
            elif book_data.get('foreign_title'):
                note = _('Title of a foreign edition')
            else:
                note = _('Data in English')
            self.es_lbl = QLabel(note)
            self.es_lbl.setStyleSheet('color: #888888; font-size: 11px; margin-left: 6px;')
            self.btn_layout.addWidget(self.es_lbl)

        self.btn_layout.addStretch()
        info_layout.addLayout(self.btn_layout)
        layout.addLayout(info_layout, stretch=1)

        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(80, 115)
        self.cover_lbl.setStyleSheet('border: 1px solid #aaa; background-color: #e0e0e0; color: #555;')
        self.cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_lbl.setText(_('No cover'))
        layout.addWidget(self.cover_lbl, alignment=Qt.AlignmentFlag.AlignTop)

        self.load_cover()

    def _is_wish(self):
        """True si el libro de calibre es una entrada vacía de la lista de deseos:
        tiene la etiqueta y todavía no tiene ningún archivo."""
        tag = self.dialog.wish_tag
        if not self.lib_id or not tag:
            return False
        try:
            tags = {t.lower() for t in (self.db.field_for('tags', self.lib_id) or ())}
            return tag.lower() in tags and not self.db.formats(self.lib_id)
        except Exception:
            return False

    def _set_status(self):
        if getattr(self, 'is_wish', False):
            self.status_lbl.setText('📋 ' + self.dialog.wish_tag)
            self.status_lbl.setStyleSheet('color: #1f5f99; font-weight: bold;')
            self.status_lbl.setToolTip(_('Empty entry in your library (wishlist): it has no file yet.'))
        elif self.lib_id:
            self.status_lbl.setText('✓ ' + _('In the library'))
            self.status_lbl.setStyleSheet('color: #2e7d32; font-weight: bold;')
        else:
            self.status_lbl.setText('• ' + _('Missing'))
            self.status_lbl.setStyleSheet('color: #b26a00; font-weight: bold;')

    def in_main_view(self):
        """Vista inicial: en la serie, los libros que tenés o con edición en español;
        en la del autor, todos los libros individuales."""
        if self.book_data.get('kind', 'single') != 'single':
            return False
        if self.dialog.mode == 'author':
            return True
        status = self.book_data.get('es_status')
        if status == 'unknown' and not self.dialog.settings.get('auto_spanish', True):
            return True
        return bool(self.lib_id) or status == 'found'

    def needs_spanish_check(self):
        return (self.book_data.get('kind', 'single') == 'single' and not self.lib_id
                and self.book_data.get('es_status') == 'unknown')

    def set_spanish_state(self, text, failed=False):
        if self.es_lbl is not None:
            self.es_lbl.setText(text)
            self.es_lbl.setStyleSheet(
                f'color: {"#a33" if failed else "#555"}; font-size: 11px; margin-left: 6px;')
        if self.btn_es is not None:
            # Se puede reintentar solo si la búsqueda terminó
            self.btn_es.setEnabled(failed)

    def _find_by_title(self):
        """Reconoce un libro tuyo por el título, ignorando mayúsculas, acentos, signos
        y agregados como "(Spanish Edition)" o "(Empíreo, #1)"."""
        titles = [t for t in (self.book_data['title'], self.book_data.get('original_title')) if t]
        # 1. Entre los libros del mismo autor, con comparación tolerante
        index = self.dialog.titles_index()
        for title in titles:
            book_id = index.get(norm_title(title))
            if book_id:
                return book_id
        # 2. En toda la biblioteca, por título exacto
        for title in titles:
            try:
                ids = self.db.search(f'title:"={search_quote(title)}"')
            except Exception:
                ids = set()
            if ids:
                return next(iter(ids))
        return None

    def load_cover(self):
        cover_data = self.book_data.get('cover_data')
        if not cover_data:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(cover_data):
            self.cover_lbl.setPixmap(pixmap.scaled(
                80, 115, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def search_in_stores(self):
        """Abre la búsqueda de tiendas de calibre («Obtener libros») con el título
        (en español si se encontró) y el apellido del autor."""
        action = self.gui.iactions.get('Store')
        if action is None:
            return
        title = re.sub(r'\s*\([^()]*#[^()]*\)\s*$', '', self.book_data['title'] or '').strip()
        title = re.split(r'\s*:\s*', title)[0] or title      # sin subtítulo: más resultados
        author = (self.book_data.get('author') or '').strip()
        surname = author.split()[-1] if author else ''
        query = f'{title} {surname}'.strip()
        try:
            action.search(query)
        except Exception as e:
            error_dialog(self, _('Stores'), _('Could not open the store search: {0}').format(e), show=True)

    def search_in_calibre(self):
        if self.lib_id:
            self.gui.search.set_search_string(f'id:{self.lib_id}')
        else:
            self.gui.search.set_search_string(f'title:"={search_quote(self.book_data["title"])}"')

    def add_empty_entry(self):
        title = self.book_data['title']
        author = self.book_data['author']

        mi = Metadata(title, [author] if author else None)
        if self.series_name:
            mi.series = self.series_name
            if self.book_data.get('index') is not None:
                mi.series_index = self.book_data['index']
        if self.book_data.get('synopsis'):
            mi.comments = '<p>' + html.escape(self.book_data['synopsis']) + '</p>'
        gr_id = self.book_data.get('edition_gr_id') or self.book_data.get('gr_id')
        if gr_id:
            mi.set_identifier('goodreads', gr_id)
        if self.dialog.wish_tag:
            # Para encontrar en el panel de etiquetas lo que falta conseguir
            mi.tags = [self.dialog.wish_tag]

        try:
            book_id = self.legacy_db.import_book(mi, [])
        except Exception as e:
            error_dialog(self, _('Error'), _('Could not create the entry: {0}').format(e), show=True)
            return

        cover_data = self.book_data.get('cover_data')
        if cover_data:
            try:
                self.db.set_cover({book_id: cover_data})
            except Exception:
                pass

        model = self.gui.library_view.model()
        model.books_added(1)
        model.refresh_ids([book_id])

        self.lib_id = book_id
        self.book_data['lib_id'] = book_id
        self.is_wish = bool(self.dialog.wish_tag)
        self._set_status()
        hide = [self.more_btn, self.btn_es] + ([] if self.is_wish else [self.btn_store])
        for w in hide:
            if w is not None:
                w.hide()
        self.more_btn = self.btn_es = None
        if not self.is_wish:
            self.btn_store = None
        self.dialog.update_status()
        self.dialog.apply_filter()

        info_dialog(self, _('Done'), _('The entry for "{0}" was created').format(title), show=True)
