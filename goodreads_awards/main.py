# -*- coding: utf-8 -*-

try:
    load_translations()
except NameError:
    pass

from qt.core import (
    QToolButton, QMenu, QAction, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextEdit, QListWidget, QListWidgetItem,
    QFrame, QDialogButtonBox, Qt, pyqtSignal, QObject, QApplication, QCursor,
    QAbstractItemView, QIcon, QPixmap
)

from calibre.gui2 import error_dialog, info_dialog, question_dialog
from calibre.gui2.actions import InterfaceAction

from calibre_plugins.goodreads_awards.config import prefs
from calibre_plugins.goodreads_awards.worker import (search_books, FetchWorker, begin_session,
                                                     end_session, using_camoufox)


# Más libros que esto en una sola tanda puede hacer que Goodreads bloquee las descargas
MAX_RECOMMENDED = 50


def _esc(text):
    return (text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


class _Signals(QObject):
    progress = pyqtSignal(object, object, object)
    done     = pyqtSignal()


class SelectDialog(QDialog):
    def __init__(self, parent, title, author, results, exact=True):
        super().__init__(parent)
        self.setWindowTitle(_('Select book on Goodreads'))
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.selected_url = None

        layout = QVBoxLayout(self)

        text = _('<b>Book in Calibre:</b> {0}').format(_esc(title)) + (' — ' + _esc(author) if author else '')
        text += _('<br>Choose the correct result on Goodreads:')
        if not exact:
            text += '<br><i>' + _esc(_('No result has exactly the same title. These are all the results of the search:')) + '</i>'
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemDoubleClicked.connect(self.accept)

        for r in results:
            item = QListWidgetItem(r['title'] + (' — ' + r['author'] if r.get('author') else ''))
            item.setData(Qt.ItemDataRole.UserRole, r['url'])
            item.setToolTip(r['url'])
            self.list.addItem(item)

        if self.list.count() > 0:
            self.list.setCurrentRow(0)

        layout.addWidget(self.list)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        skip = btn_box.addButton(_('Skip this book'), QDialogButtonBox.ButtonRole.RejectRole)
        skip.setToolTip(_('Continue with the next book'))
        stop = btn_box.addButton(_('Cancel'), QDialogButtonBox.ButtonRole.DestructiveRole)
        stop.setToolTip(_('Do not search the remaining books'))
        stop.clicked.connect(self._cancel_all)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        self.cancel_all = False

    def _cancel_all(self):
        self.cancel_all = True
        self.reject()

    def accept(self):
        item = self.list.currentItem()
        if item:
            self.selected_url = item.data(Qt.ItemDataRole.UserRole)
        super().accept()


class ProgressDialog(QDialog):
    def __init__(self, parent, total):
        super().__init__(parent)
        self.setWindowTitle(_('Goodreads Awards — Downloading awards'))
        self.setMinimumWidth(500)
        self.total = total
        self.processed = 0
        self.ok_count = 0
        self.err_count = 0
        self.running = True

        layout = QVBoxLayout(self)
        self.label = QLabel(_('Processing 0 of {0} books…').format(total))
        layout.addWidget(self.label)

        self.bar = QProgressBar()
        self.bar.setRange(0, total)
        layout.addWidget(self.bar)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        layout.addWidget(self.log)

        btn_layout = QHBoxLayout()
        self.btn_abort = QPushButton(_('Cancel'))
        self.btn_close = QPushButton(_('Close'))
        self.btn_close.setEnabled(False)
        self.btn_abort.clicked.connect(self._on_abort)
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_abort)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        self.abort_callback = None

    def _on_abort(self):
        if self.abort_callback:
            self.abort_callback()
        self.btn_abort.setEnabled(False)
        self.log.append(_('⚠ Cancelling…'))

    def reject(self):
        # Cerrar con Esc o la X mientras trabaja también cancela
        if self.running and self.abort_callback:
            self.abort_callback()
        super().reject()

    def log_line(self, text):
        self.log.append(_esc(text))

    def update_progress(self, title, data, error):
        self.processed += 1
        self.bar.setValue(self.processed)
        self.label.setText(_('Processing {0} of {1} books…').format(self.processed, self.total))

        if error:
            self.err_count += 1
            self.log_line(_('✗ {0}: {1}').format(title, error))
        else:
            premios = data.get('premios', [])
            if premios:
                self.ok_count += 1
                self.log_line(_('✓ {0}: {1}').format(title, ' • '.join(premios)))
            else:
                self.log_line(_('○ {0}: no awards found').format(title))

    def finish(self):
        self.running = False
        self.label.setText(
            _('Completed — {0} with awards, {1} errors').format(self.ok_count, self.err_count)
        )
        self.bar.setValue(self.bar.maximum())
        self.btn_close.setEnabled(True)
        self.btn_close.setDefault(True)
        self.btn_abort.setEnabled(False)


class GoodreadsAwardsAction(InterfaceAction):
    name = 'Goodreads Awards'
    action_spec = ('Goodreads Awards', None, _('Get literary awards from goodreads.com'), None)
    action_type = 'current'
    popup_type  = QToolButton.ToolButtonPopupMode.MenuButtonPopup

    def genesis(self):
        try:
            icon_data = self.load_resources(['images/icon.png'])['images/icon.png']
            pixmap = QPixmap()
            pixmap.loadFromData(icon_data)
            if not pixmap.isNull():
                self.qaction.setIcon(QIcon(pixmap))
        except Exception:
            pass

        menu = QMenu(self.gui)
        act_fetch = QAction(_('Get awards'), self.gui)
        act_fetch.setIcon(self.qaction.icon())
        act_fetch.triggered.connect(self.run_fetch)
        menu.addAction(act_fetch)

        menu.addSeparator()
        act_config = QAction(_('Configuration…'), self.gui)
        act_config.triggered.connect(self.show_config)
        menu.addAction(act_config)
        act_about = QAction(_('About {0}').format(_('Goodreads Awards')), self.gui)
        act_about.triggered.connect(self.show_about)
        menu.addAction(act_about)

        self.menu = menu
        self.qaction.setMenu(menu)
        self.qaction.triggered.connect(self.run_fetch)

    def run_fetch(self):
        book_ids = list(self.gui.library_view.get_selected_ids())
        if not book_ids:
            return error_dialog(self.gui, _('No selection'), _('Select at least one book to continue.'), show=True)
        if getattr(self, '_running', False):
            return
        if len(book_ids) > MAX_RECOMMENDED:
            if not question_dialog(
                    self.gui, _('Many books selected'),
                    '<p>' + _('You selected {0} books.').format(len(book_ids)) + '</p><p>' +
                    _('Goodreads limits automated downloads: searching hundreds of books at once can get your '
                      'connection temporarily blocked, and every book takes a few seconds. '
                      'It is better to do it in batches of up to {0} books.').format(MAX_RECOMMENDED) +
                    '</p><p>' + _('Continue anyway?') + '</p>',
                    yes_text=_('Continue'), no_text=_('Cancel')):
                return
        self._running = True
        begin_session()
        try:
            self._run_fetch(book_ids)
        finally:
            end_session()
            self._running = False

    def _run_fetch(self, book_ids):
        if using_camoufox():
            self.gui.status_bar.show_message(
                _('Starting the browser for Goodreads, the first time it can take a while…'), 0)

        db = self.gui.current_db.new_api
        confirmed, not_found, failed = [], [], []

        for book_id in book_ids:
            title = db.field_for('title', book_id) or ''
            authors = list(db.field_for('authors', book_id) or ())
            identifiers = db.field_for('identifiers', book_id) or {}
            gr_id = identifiers.get('goodreads')
            if gr_id:
                confirmed.append((book_id, 'https://www.goodreads.com/book/show/{0}'.format(gr_id), title))
                continue

            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
            if not using_camoufox() or confirmed or not_found or failed:
                self.gui.status_bar.show_message(_('Searching Goodreads: {0}').format(title), 0)
            QApplication.processEvents()
            try:
                matches, results = search_books(title, authors)
            except Exception as e:
                failed.append(_('{0}: {1}').format(title, e))
                continue
            finally:
                QApplication.restoreOverrideCursor()
                self.gui.status_bar.clearMessage()

            if len(matches) == 1:
                confirmed.append((book_id, matches[0]['url'], title))
                continue
            if not results:
                not_found.append(title)
                continue
            dlg = SelectDialog(self.gui, title, ', '.join(authors), matches or results, exact=bool(matches))
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_url:
                confirmed.append((book_id, dlg.selected_url, title))
            elif dlg.cancel_all:
                return

        if failed or not_found:
            det = failed + [_('{0}: not found on Goodreads').format(t) for t in not_found]
            info_dialog(self.gui, _('Warning'),
                        _('{0} of the selected books could not be searched on Goodreads.').format(len(det)),
                        det_msg='\n'.join(det), show=True)

        if confirmed:
            self._launch_worker(confirmed)

    def _target_column(self):
        """Columna donde guardar, o None si no hay que guardar."""
        if not prefs['guardar_premios']:
            return None
        col = prefs['col_premios']
        if not col:
            return None
        if not col.startswith('#'):
            col = '#' + col
        return col

    def _launch_worker(self, confirmed):
        dlg = ProgressDialog(self.gui, len(confirmed))
        titles = {book_id: title for book_id, url, title in confirmed}
        col = self._target_column()
        db = self.gui.current_db.new_api
        if prefs['guardar_premios'] and not col:
            dlg.log_line(_('⚠ No column selected in the configuration: the awards are shown but not saved.'))
        elif col and col not in db.field_metadata.custom_field_keys():
            dlg.log_line(_('⚠ The column {0} does not exist in this library: the awards are not saved.').format(col))
            col = None

        signals = _Signals(dlg)          # vive mientras viva el diálogo
        updated = []
        signals.progress.connect(lambda bid, d, e: self._on_progress(bid, titles.get(bid, ''), d, e, dlg, col, updated))
        signals.done.connect(dlg.finish)

        worker = FetchWorker(confirmed, signals.progress.emit, signals.done.emit)
        dlg.abort_callback = worker.abort
        worker.start()
        dlg.exec()
        if updated:
            view = self.gui.library_view
            view.model().refresh_ids(updated, current_row=view.currentIndex().row())

    def _on_progress(self, book_id, title, data, error, dlg, col, updated):
        dlg.update_progress(title, data, error)
        if error or not data or not data.get('premios') or not col:
            return

        db = self.gui.current_db.new_api
        premios = data['premios']
        try:
            meta = db.field_metadata[col]
            if meta.get('is_multiple'):
                # columna tipo etiquetas: cada premio es un elemento (sin comas internas)
                value = [p.replace(',', ';') for p in premios]
                shown = ', '.join(value)
            else:
                value = shown = prefs.get('separador_premios', ', ').join(premios)
            db.set_field(col, {book_id: value})
            updated.append(book_id)
            dlg.log_line(_('  → Saved to {0}: {1}').format(col, shown))
        except Exception as e:
            dlg.log_line(_('  ⚠ Error saving to {0}: {1}').format(col, e))

    def show_config(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def show_about(self):
        from calibre_plugins.goodreads_awards.support import show_about
        show_about(self.gui, self.interface_action_base_plugin)
