#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai

__license__   = 'GPL v3'
__copyright__ = '2026, Dunhill'

try:
    load_translations()
except NameError:
    pass

import os
import shutil

from qt.core import (QApplication, QComboBox, QCursor, QHBoxLayout, QIcon,
                     QLabel, QListWidget, QListWidgetItem, QPushButton,
                     QSplitter, Qt, QTextBrowser, QTimer, QUrl, QVBoxLayout,
                     QWidget)

from calibre.gui2 import error_dialog, info_dialog, question_dialog

from calibre_plugins.calibre_style.code_editor import CodeEditor
from calibre_plugins.calibre_style.css_check import check_css

EDITABLE_FORMATS = ('EPUB', 'KEPUB', 'AZW3')


class CSSList(QListWidget):
    """List of the book's CSS files with a QComboBox-like API."""

    def __init__(self, parent):
        QListWidget.__init__(self, parent)
        self.currentIndexChanged = self.currentRowChanged

    def addItem(self, text, data=None):
        it = QListWidgetItem(text)
        it.setData(Qt.ItemDataRole.UserRole, data)
        it.setToolTip(data or text)
        QListWidget.addItem(self, it)

    def itemData(self, i):
        it = self.item(i)
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def itemText(self, i):
        it = self.item(i)
        return it.text() if it is not None else ''

    def setItemText(self, i, text):
        it = self.item(i)
        if it is not None:
            it.setText(text)

    def findData(self, data):
        for i in range(self.count()):
            if self.itemData(i) == data:
                return i
        return -1

    def currentIndex(self):
        return self.currentRow()

    def setCurrentIndex(self, i):
        self.setCurrentRow(i)


class BookCSSTab(QWidget):
    """Edit the stylesheets inside a book, check them for errors and preview
    a chapter of the book with the changes."""

    def __init__(self, parent, gui):
        QWidget.__init__(self, parent)
        self.gui = gui
        self.container = None
        self.book_id = None
        self.fmt = None
        self.tmp_path = None
        self.original = {}   # css name -> text as it is in the book
        self.texts = {}      # css name -> current text
        self._css = None
        self._counts = {}    # css name -> number of problems
        self._loaded_once = False

        lay = QVBoxLayout(self)
        info = QLabel(_('Stylesheets inside the selected book (EPUB, KEPUB or AZW3). Fix them '
                        'here, see the errors and how a chapter looks, and save the changes '
                        'into the book. The first time, a copy of the book is kept as '
                        'ORIGINAL_EPUB (or ORIGINAL_AZW3...) so it can be restored.'), self)
        info.setWordWrap(True)
        lay.addWidget(info)

        top = QHBoxLayout()
        self.book_label = QLabel(_('No book loaded'), self)
        f = self.book_label.font()
        f.setBold(True)
        self.book_label.setFont(f)
        top.addWidget(self.book_label, 1)
        self.load_button = QPushButton(QIcon.ic('book.png'), _('Load selected book'), self)
        self.load_button.clicked.connect(self.load_selected)
        top.addWidget(self.load_button)
        lay.addLayout(top)

        self.chapter_combo = QComboBox(self)
        self.chapter_combo.currentIndexChanged.connect(self._load_chapter)

        main = QSplitter(Qt.Orientation.Horizontal, self)
        files = QWidget(self)
        fl = QVBoxLayout(files)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(QLabel(_('CSS files:'), files))
        self.css_combo = CSSList(files)
        self.css_combo.currentIndexChanged.connect(self._on_css_changed)
        fl.addWidget(self.css_combo, 1)
        main.addWidget(files)
        left = QSplitter(Qt.Orientation.Vertical, self)
        self.editor = CodeEditor(self)
        self.editor.setReadOnly(True)
        self.editor.textChanged.connect(self._on_text_changed)
        left.addWidget(self.editor)

        problems = QWidget(self)
        pl = QVBoxLayout(problems)
        pl.setContentsMargins(0, 0, 0, 0)
        self.problems_label = QLabel('', problems)
        pl.addWidget(self.problems_label)
        self.problems = QListWidget(problems)
        self.problems.setWordWrap(True)
        self.problems.itemActivated.connect(self._jump)
        self.problems.itemDoubleClicked.connect(self._jump)
        pl.addWidget(self.problems, 1)
        left.addWidget(problems)
        left.setSizes([330, 150])
        main.addWidget(left)

        prev = QWidget(self)
        vl = QVBoxLayout(prev)
        vl.setContentsMargins(0, 0, 0, 0)
        ph = QHBoxLayout()
        ph.addWidget(QLabel(_('Preview of the chapter:'), prev))
        ph.addWidget(self.chapter_combo, 1)
        vl.addLayout(ph)
        self.preview = self._make_preview(prev)
        vl.addWidget(self.preview, 1)
        main.addWidget(prev)
        main.setSizes([200, 450, 400])
        main.setStretchFactor(0, 0)
        lay.addWidget(main, 1)

        bottom = QHBoxLayout()
        self.status = QLabel('', self)
        bottom.addWidget(self.status, 1)
        self.revert_button = QPushButton(_('Undo changes'), self)
        self.revert_button.clicked.connect(self._revert)
        bottom.addWidget(self.revert_button)
        self.save_button = QPushButton(QIcon.ic('save.png'), _('Save into the book'), self)
        self.save_button.clicked.connect(self.save)
        bottom.addWidget(self.save_button)
        lay.addLayout(bottom)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._refresh)
        self._update_buttons()

    # -- helpers -------------------------------------------------------------

    def _make_preview(self, parent):
        self._web = False
        try:
            from qt.webengine import QWebEngineSettings, QWebEngineView
            w = QWebEngineView(parent)
            s = w.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            self._web = True
            return w
        except Exception:
            w = QTextBrowser(parent)
            w.setOpenLinks(False)
            return w

    def showEvent(self, ev):
        QWidget.showEvent(self, ev)
        if not self._loaded_once:
            self._loaded_once = True
            QTimer.singleShot(0, self.load_selected)

    def is_dirty(self):
        return any(self.texts.get(n) != t for n, t in self.original.items())

    def _update_buttons(self):
        dirty = self.is_dirty()
        self.save_button.setEnabled(dirty)
        self.revert_button.setEnabled(dirty)
        changed = [n for n, t in self.original.items() if self.texts.get(n) != t]
        self.status.setText(_('Unsaved changes in: {0}').format(', '.join(
            os.path.basename(n) for n in changed)) if changed else '')
        for i in range(self.css_combo.count()):
            name = self.css_combo.itemData(i)
            label = os.path.basename(name) + (' *' if name in changed else '')
            n = self._counts.get(name, 0)
            if n:
                label += '   ⚠ %d' % n
            if self.css_combo.itemText(i) != label:
                self.css_combo.setItemText(i, label)

    def _busy(self, on):
        if on:
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        else:
            QApplication.restoreOverrideCursor()

    # -- loading -------------------------------------------------------------

    def _selected_book(self):
        try:
            ids = list(self.gui.library_view.get_selected_ids())
        except Exception:
            ids = []
        return ids[0] if ids else None

    def load_selected(self):
        if self.is_dirty() and not question_dialog(
                self, _('Unsaved changes'),
                _('The CSS of the current book has unsaved changes. Discard them and load '
                  'the selected book?')):
            return
        book_id = self._selected_book()
        if book_id is None:
            self.book_label.setText(_('Select a book in calibre and press "Load selected book"'))
            return
        db = self.gui.current_db.new_api
        fmts = [f.upper() for f in (db.formats(book_id) or ())]
        fmt = next((f for f in EDITABLE_FORMATS if f in fmts), None)
        title = db.field_for('title', book_id)
        if fmt is None:
            self._close_container()
            self.book_label.setText(_('"{0}" has no EPUB, KEPUB or AZW3 format').format(title))
            self._fill_combos()
            return
        self._busy(True)
        try:
            self._close_container()
            from calibre.ptempfile import PersistentTemporaryFile
            from calibre.ebooks.oeb.polish.container import get_container
            pt = PersistentTemporaryFile('.' + fmt.lower(), prefix='calibre_css_')
            pt.close()
            db.copy_format_to(book_id, fmt, pt.name)
            self.tmp_path = pt.name
            c = get_container(pt.name, tweak_mode=True)
        except Exception as e:
            self._busy(False)
            import traceback
            msg = str(e)
            if 'DRM' in type(e).__name__ or 'drm' in msg.lower():
                msg = _('This book is protected with DRM and cannot be edited.')
            return error_dialog(self, _('Could not open the book'), msg,
                                det_msg=traceback.format_exc(), show=True)
        self.container = c
        self.book_id, self.fmt = book_id, fmt
        from calibre.ebooks.oeb.base import OEB_STYLES
        names = sorted((n for n, mt in c.mime_map.items() if mt in OEB_STYLES), key=str.lower)
        self.original = {}
        for n in names:
            try:
                self.original[n] = c.raw_data(n, decode=True)
            except Exception:
                pass
        self.texts = dict(self.original)
        self.book_label.setText('{0}  ({1})'.format(title, fmt))
        self._fill_combos()
        self._busy(False)

    def _fill_combos(self):
        self.css_combo.blockSignals(True)
        self.chapter_combo.blockSignals(True)
        self.css_combo.clear()
        self.chapter_combo.clear()
        if self.container is not None:
            for n in self.original:
                self.css_combo.addItem(n, n)
                self._counts[n] = len(check_css(self.original[n]))
            if self.original:
                # Start on the biggest stylesheet, usually the main one
                big = max(self.original, key=lambda n: len(self.original[n]))
                self.css_combo.setCurrentIndex(self.css_combo.findData(big))
            from calibre.ebooks.oeb.base import OEB_DOCS
            for n, linear in self.container.spine_names:
                if self.container.mime_map.get(n) in OEB_DOCS:
                    self.chapter_combo.addItem(n, n)
            # Start on the first chapter with real text, not the cover
            best = 0
            for i in range(self.chapter_combo.count()):
                try:
                    if len(self.container.raw_data(self.chapter_combo.itemData(i))) > 3000:
                        best = i
                        break
                except Exception:
                    pass
            self.chapter_combo.setCurrentIndex(best)
        self.css_combo.blockSignals(False)
        self.chapter_combo.blockSignals(False)
        if self.container is not None and not self.original:
            self.editor.blockSignals(True)
            self.editor.setPlainText('')
            self.editor.blockSignals(False)
            self.problems.clear()
            self.problems_label.setText(_('This book has no CSS files.'))
        self._on_css_changed(self.css_combo.currentIndex())
        self._load_chapter()
        self._update_buttons()

    # -- editing -------------------------------------------------------------

    def _on_css_changed(self, idx):
        name = self.css_combo.itemData(idx) if idx >= 0 else None
        self._css = name
        self.editor.blockSignals(True)
        self.editor.setPlainText(self.texts.get(name, '') if name else '')
        self.editor.setExtraSelections([])
        self.editor.setReadOnly(name is None)
        self.editor.blockSignals(False)
        self._check()

    def _on_text_changed(self):
        if self._css:
            self.texts[self._css] = self.editor.toPlainText()
            self.editor.setExtraSelections([])
            self._update_buttons()
            self._timer.start()

    def _refresh(self):
        self._check()
        self._write_css(self._css)
        if self._web:
            self.preview.reload()
        else:
            self._load_chapter()

    def _check(self):
        self.problems.clear()
        if not self._css:
            if self.container is None:
                self.problems_label.setText('')
            return
        issues = check_css(self.texts.get(self._css, ''))
        if self._counts.get(self._css) != len(issues):
            self._counts[self._css] = len(issues)
            self._update_buttons()
        errors = sum(1 for i in issues if i[1] == 'error')
        warnings = len(issues) - errors
        if not issues:
            self.problems_label.setText('✔ ' + _('No problems found'))
        else:
            self.problems_label.setText(_('Errors: {0}   Warnings: {1}   (double click to go to the line)').format(errors, warnings))
        err_icon, warn_icon = QIcon.ic('dialog_error.png'), QIcon.ic('dialog_warning.png')
        for line, level, msg in issues:
            text = (_('Line {0}: ').format(line) if line else '') + msg
            it = QListWidgetItem(err_icon if level == 'error' else warn_icon, text)
            it.setData(Qt.ItemDataRole.UserRole, line)
            self.problems.addItem(it)

    def _jump(self, item):
        line = item.data(Qt.ItemDataRole.UserRole)
        if line:
            self.editor.go_to_line(line)

    def _write_css(self, name):
        if self.container is None or not name:
            return
        with self.container.open(name, 'wb') as f:
            f.write(self.texts.get(name, '').encode('utf-8'))

    def _load_chapter(self, *a):
        if self.container is None or self.chapter_combo.currentIndex() < 0:
            if self._web:
                self.preview.setHtml('')
            else:
                self.preview.clear()
            return
        name = self.chapter_combo.currentData()
        path = self.container.name_to_abspath(name)
        if self._web:
            self.preview.load(QUrl.fromLocalFile(path))
        else:
            css = '\n'.join(self.texts.values())
            self.preview.document().setDefaultStyleSheet(css)
            with open(path, 'rb') as f:
                self.preview.setHtml(f.read().decode('utf-8', 'replace'))

    def _revert(self):
        if not self.is_dirty():
            return
        if not question_dialog(self, _('Undo changes'),
                               _('Discard all the changes made to the CSS of this book?')):
            return
        for n, t in self.original.items():
            if self.texts.get(n) != t:
                self.texts[n] = t
                self._write_css(n)
        self._on_css_changed(self.css_combo.currentIndex())
        self._update_buttons()
        self._load_chapter()

    # -- saving --------------------------------------------------------------

    def save(self):
        if self.container is None or not self.is_dirty():
            return True
        db = self.gui.current_db.new_api
        self._busy(True)
        try:
            for n in self.original:
                if self.texts.get(n) != self.original[n]:
                    self._write_css(n)
            orig_fmt = 'ORIGINAL_' + self.fmt
            if not db.has_format(self.book_id, orig_fmt):
                db.save_original_format(self.book_id, self.fmt)
            self.container.commit()
            with open(self.tmp_path, 'rb') as f:
                db.add_format(self.book_id, self.fmt, f, run_hooks=False)
            self.original = dict(self.texts)
            try:
                self.gui.library_view.model().refresh_ids([self.book_id])
            except Exception:
                pass
        except Exception as e:
            self._busy(False)
            import traceback
            error_dialog(self, _('Could not save'), str(e), det_msg=traceback.format_exc(), show=True)
            return False
        self._busy(False)
        self._update_buttons()
        info_dialog(self, _('Saved'),
                    _('The CSS was saved into the book. The previous version was kept as {0}; '
                      'it can be restored by right clicking on that format in the book details '
                      'panel.').format('ORIGINAL_' + self.fmt), show=True, show_copy_button=False)
        return True

    def maybe_save(self):
        """Called when the dialog closes. Returns False to keep it open."""
        if not self.is_dirty():
            return True
        from qt.core import QMessageBox
        r = QMessageBox.question(
            self, _('Unsaved changes'),
            _('The CSS of the book "{0}" has unsaved changes. Save them into the book?').format(
                self.book_label.text()),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def _close_container(self):
        c, self.container = self.container, None
        self.original, self.texts, self._css, self._counts = {}, {}, None, {}
        if c is not None:
            try:
                shutil.rmtree(c.root, ignore_errors=True)
            except Exception:
                pass
        if self.tmp_path:
            try:
                os.remove(self.tmp_path)
            except Exception:
                pass
            self.tmp_path = None

    def cleanup(self):
        self._close_container()
