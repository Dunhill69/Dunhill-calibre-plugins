#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai

__license__   = 'GPL v3'
__copyright__ = '2026, Dunhill'

try:
    load_translations()
except NameError:
    pass

import os
import re

from qt.core import (QComboBox, QFileDialog, QFont, QFrame, QHBoxLayout, QIcon,
                     QInputDialog, QLabel, QLineEdit, QListWidget,
                     QListWidgetItem, QPlainTextEdit, QPushButton, QSplitter,
                     Qt, QTextBrowser, QTimer, QVBoxLayout, QWidget)

from calibre.gui2 import error_dialog, gprefs, question_dialog

from calibre_plugins.calibre_style.config import (get_assignments, get_styles,
                                                  normalize_path, unique_name)

COLOR_RE = re.compile(r'#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b')

def sample_details():
    return (
        '<html><head></head><body class="horizontal">'
        '<table><tr><td valign="top" width="40%"><table class="fields">'
        '<tr id="title"><td class="title">{t}</td><td>El misterio de la librería</td></tr>'
        '<tr id="authors"><td class="title">{a}</td><td><a href="#">Walter Dunhill</a></td></tr>'
        '<tr id="series"><td class="title">{s}</td><td>{b} <a href="#">Crónicas de Linux</a></td></tr>'
        '<tr id="formats"><td class="title">{f}</td><td><a href="#">EPUB</a>, <a href="#">AZW3</a></td></tr>'
        '<tr id="tags"><td class="title">{g}</td><td><a href="#">Ficción</a>, <a href="#">Misterio</a></td></tr>'
        '<tr id="rating"><td class="title">{r}</td><td>★★★★☆</td></tr>'
        '</table></td><td valign="top" width="60%">'
        '<div class="comments"><h3 class="comments-heading">{c}</h3><p>{x}</p></div>'
        '</td></tr></table></body></html>').format(
            t=_('Title:'), a=_('Authors:'), s=_('Series:'), b=_('Book 1 of'),
            f=_('Formats:'), g=_('Tags:'), r=_('Rating:'), c=_('Comments'),
            x=_('Example text. Select a book in calibre before opening this window '
                'to preview the style with that book.'))

SAMPLE_BOOK = '''\
<html><head><style>{css}</style></head><body>
<h1>Capítulo uno</h1>
<p>Era una noche oscura y tormentosa. La librería de la calle Florida llevaba años
cerrada, pero esa noche había luz detrás del vidrio empañado.</p>
<p>—¿Hay alguien? —preguntó Martín, empujando la puerta con dos dedos.</p>
<blockquote>«Los libros no se pierden: esperan.»</blockquote>
<h2>I</h2>
<p>Nadie contestó. Sobre el mostrador, un ejemplar abierto mostraba una dedicatoria
escrita con tinta <em>todavía fresca</em> y una firma que conocía demasiado bien.</p>
</body></html>'''


class CSSTab(QWidget):

    def __init__(self, parent, gui, mode='details'):
        QWidget.__init__(self, parent)
        self.gui = gui
        self.mode = mode
        self.styles = get_styles(mode)        # name -> css
        self.assign = get_assignments(mode)   # normalized library path -> name
        self._style = None                    # style shown in the editor

        lay = QVBoxLayout(self)

        if mode == 'details':
            info = _('Style for the book details panel (on the right of the book list). '
                     'calibre draws this panel with Qt, which only understands part of CSS: '
                     'colors, fonts, sizes, margins, padding and table borders work; '
                     'things like flexbox, shadows or animations do not.')
        else:
            info = _('Style that the e-book viewer adds to the books it opens, the same as '
                     'Preferences > Styles in the viewer. It takes effect the next time you '
                     'open a book (close the viewer if it is open).')
        lbl = QLabel(info, self)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        # --- library -> style ---
        top = QHBoxLayout()
        top.addWidget(QLabel(_('Library:'), self))
        self.lib_combo = QComboBox(self)
        self.lib_combo.currentIndexChanged.connect(self._on_library_changed)
        top.addWidget(self.lib_combo, 1)
        top.addSpacing(12)
        top.addWidget(QLabel(_('Uses the style:'), self))
        self.use_combo = QComboBox(self)
        self.use_combo.setMinimumContentsLength(18)
        self.use_combo.currentIndexChanged.connect(self._on_use_changed)
        top.addWidget(self.use_combo, 1)
        self.reset_button = QPushButton(QIcon.ic('edit-undo.png'), _('Restore calibre\'s original'), self)
        self.reset_button.setToolTip(_('Use calibre\'s normal style in this library'))
        self.reset_button.clicked.connect(self._reset_to_calibre)
        top.addWidget(self.reset_button)
        lay.addLayout(top)
        # Set when the user also wants calibre's own customization removed
        self.reset_calibre_base = False

        # --- style list | editor + preview ---
        main = QSplitter(Qt.Orientation.Horizontal, self)

        left = QWidget(self)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel(_('Saved styles:'), left))
        self.style_list = QListWidget(left)
        self.style_list.currentItemChanged.connect(self._on_style_selected)
        self.style_list.itemDoubleClicked.connect(lambda *a: self._rename())
        ll.addWidget(self.style_list, 1)
        grid = [(_('New'), self._new), (_('Duplicate'), self._duplicate),
                (_('Rename'), self._rename), (_('Delete'), self._delete),
                (_('Import...'), self._import_css), (_('Export...'), self._export_css)]
        for i in range(0, len(grid), 2):
            row = QHBoxLayout()
            for text, slot in grid[i:i + 2]:
                b = QPushButton(text, left)
                b.clicked.connect(slot)
                row.addWidget(b)
            ll.addLayout(row)
        main.addWidget(left)

        right = QSplitter(Qt.Orientation.Vertical, self)
        from calibre_plugins.calibre_style.code_editor import CodeEditor
        self.editor = CodeEditor(self)
        self.editor.setPlaceholderText(_('Create or select a style on the left to edit its CSS.'))
        self.editor.textChanged.connect(self._on_text_changed)
        right.addWidget(self.editor)

        prev = QWidget(self)
        pl = QVBoxLayout(prev)
        pl.setContentsMargins(0, 0, 0, 0)
        self.preview_label = QLabel(_('Preview:'), prev)
        pl.addWidget(self.preview_label)
        self.preview = self._make_preview(prev)
        pl.addWidget(self.preview, 1)
        right.addWidget(prev)
        right.setSizes([240, 260])
        main.addWidget(right)
        main.setStretchFactor(0, 0)
        main.setStretchFactor(1, 1)
        main.setSizes([220, 640])
        lay.addWidget(main, 1)

        self.color_box = QHBoxLayout()
        self.color_box.setSpacing(4)
        lay.addLayout(self.color_box)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._update_preview)

        self._fill_style_list()
        self._populate_libraries()

    # -- preview -------------------------------------------------------------

    def _make_preview(self, parent):
        self._web = False
        if self.mode == 'viewer':
            try:
                from qt.webengine import QWebEngineView
                w = QWebEngineView(parent)
                self._web = True
                return w
            except Exception:
                pass
        w = QTextBrowser(parent)
        w.setOpenLinks(False)
        return w

    def _details_html(self):
        try:
            html = self.gui.book_details.book_info.last_set_html
        except Exception:
            html = ''
        return html or sample_details()

    def _update_preview(self):
        css = self.editor.toPlainText() if self._style else ''
        if self.mode == 'details':
            try:
                from calibre.gui2.book_details import resolve_colors
                from calibre_plugins.calibre_style.config import details_stylesheet
                sheet = resolve_colors(details_stylesheet(css))
            except Exception:
                sheet = css
            self.preview.document().setDefaultStyleSheet(sheet)
            self.preview.setHtml(self._details_html())
        elif self._web:
            self.preview.setHtml(SAMPLE_BOOK.format(css=re.sub(r'(?i)</style', r'<\\/style', css)))
        else:
            self.preview.document().setDefaultStyleSheet(css)
            self.preview.setHtml(SAMPLE_BOOK.format(css=''))
        self.preview_label.setText(
            _('Preview of "{0}":').format(self._style) if self._style else _('Preview:'))

    def _update_colors(self, text):
        while self.color_box.count():
            item = self.color_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        seen = []
        for c in COLOR_RE.findall(text):
            if c.lower() not in seen:
                seen.append(c.lower())
        for c in seen[:20]:
            sw = QFrame(self)
            sw.setFixedSize(18, 18)
            sw.setToolTip(c)
            sw.setStyleSheet('background-color: %s; border: 1px solid #777;' % c)
            self.color_box.addWidget(sw)
        self.color_box.addStretch(1)

    # -- style list ----------------------------------------------------------

    def _sorted_names(self):
        return sorted(self.styles, key=lambda n: n.lower())

    def _users_of(self, name):
        return [p for p, n in self.assign.items() if n == name]

    def _fill_style_list(self, select=None):
        self.style_list.blockSignals(True)
        self.style_list.clear()
        for name in self._sorted_names():
            n = len(self._users_of(name))
            it = QListWidgetItem(name)
            it.setData(Qt.ItemDataRole.UserRole, name)
            if n:
                it.setText('%s  (%d)' % (name, n))
                it.setToolTip(_('Used by: {0}').format(', '.join(
                    os.path.basename(p.rstrip('/')) for p in self._users_of(name))))
            self.style_list.addItem(it)
        self.style_list.blockSignals(False)
        target = select if select in self.styles else (self._style if self._style in self.styles else None)
        if target is None and self.style_list.count():
            target = self.style_list.item(0).data(Qt.ItemDataRole.UserRole)
        self._select_style(target)
        self._fill_use_combo()

    def _select_style(self, name):
        for i in range(self.style_list.count()):
            if self.style_list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                self.style_list.setCurrentRow(i)
                return
        self._on_style_selected(None)

    def _on_style_selected(self, item, prev=None):
        self._style = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        self.editor.blockSignals(True)
        self.editor.setPlainText(self.styles.get(self._style, '') if self._style else '')
        self.editor.setReadOnly(self._style is None)
        self.editor.blockSignals(False)
        self._update_colors(self.editor.toPlainText())
        self._update_preview()

    def _on_text_changed(self):
        text = self.editor.toPlainText()
        if self._style:
            self.styles[self._style] = text
        self._update_colors(text)
        self._timer.start()

    def _ask_name(self, title, default=''):
        name, ok = QInputDialog.getText(self, title, _('Style name:'),
                                        QLineEdit.EchoMode.Normal, default)
        name = (name or '').strip() if ok else ''
        return name or None

    def _add_style(self, name, css):
        name = unique_name(name, self.styles)
        self.styles[name] = css
        self._fill_style_list(select=name)
        return name

    def _new(self):
        name = self._ask_name(_('New style'))
        if name:
            self._add_style(name, '')
            self.editor.setFocus()

    def _duplicate(self):
        if self._style:
            self._add_style(_('{0} (copy)').format(self._style), self.styles[self._style])

    def _rename(self):
        old = self._style
        if not old:
            return
        new = self._ask_name(_('Rename style'), old)
        if not new or new == old:
            return
        if new in self.styles:
            return error_dialog(self, _('Rename style'),
                                _('There is already a style called "{0}".').format(new), show=True)
        self.styles[new] = self.styles.pop(old)
        for p, n in list(self.assign.items()):
            if n == old:
                self.assign[p] = new
        self._style = new
        self._fill_style_list(select=new)

    def _delete(self):
        name = self._style
        if not name:
            return
        users = self._users_of(name)
        msg = _('Delete the style "{0}"?').format(name)
        if users:
            msg += '\n\n' + _('These libraries use it and will be left without a style: {0}').format(
                ', '.join(os.path.basename(p.rstrip('/')) for p in users))
        if not question_dialog(self, _('Delete style'), msg):
            return
        del self.styles[name]
        for p in users:
            del self.assign[p]
        self._style = None
        self._fill_style_list()

    def _import_css(self):
        paths, _f = QFileDialog.getOpenFileNames(
            self, _('Import CSS'), os.path.expanduser('~'), _('CSS files') + ' (*.css);;* (*)')
        last = None
        for path in paths or ():
            with open(path, encoding='utf-8', errors='replace') as f:
                css = f.read()
            last = unique_name(os.path.splitext(os.path.basename(path))[0], self.styles)
            self.styles[last] = css
        if last:
            self._fill_style_list(select=last)

    def _export_css(self):
        if not self._style:
            return
        safe = re.sub(r'[\\/:*?"<>|]+', '_', self._style)
        path, _f = QFileDialog.getSaveFileName(
            self, _('Export CSS'), os.path.join(os.path.expanduser('~'), safe + '.css'),
            _('CSS files') + ' (*.css)')
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.styles[self._style])

    # -- libraries -----------------------------------------------------------

    def _current_lib(self):
        return self.lib_combo.itemData(self.lib_combo.currentIndex())

    def _populate_libraries(self):
        current = normalize_path(getattr(self.gui.current_db, 'library_path', '')) if self.gui else ''
        self._gui_lib = current
        paths = {}
        for p in list((gprefs.get('library_usage_stats', {}) or {}).keys()) + [current]:
            if p and os.path.isdir(p):
                paths.setdefault(normalize_path(p), p)
        for p in self.assign:
            paths.setdefault(p, p)   # libraries with a style that are not in calibre's list

        self.lib_combo.blockSignals(True)
        for norm, real in sorted(paths.items(), key=lambda x: os.path.basename(x[1]).lower()):
            self.lib_combo.addItem('', norm)
            i = self.lib_combo.count() - 1
            self.lib_combo.setItemData(i, real, Qt.ItemDataRole.ToolTipRole)
            self._refresh_label(i)
        idx = self.lib_combo.findData(current)
        self.lib_combo.setCurrentIndex(max(idx, 0))
        self.lib_combo.blockSignals(False)
        self._on_library_changed(self.lib_combo.currentIndex())

    def _refresh_label(self, idx):
        norm = self.lib_combo.itemData(idx)
        real = self.lib_combo.itemData(idx, Qt.ItemDataRole.ToolTipRole) or norm
        name = os.path.basename(real.rstrip('/\\')) or real
        if not os.path.isdir(real):
            name += ' ' + _('(not found)')
        if norm == self._gui_lib:
            name += ' ' + _('(current)')
        style = self.assign.get(norm)
        if style:
            name = '● %s  →  %s' % (name, style)
        self.lib_combo.setItemText(idx, name)

    def _fill_use_combo(self):
        lib = self._current_lib()
        chosen = self.assign.get(lib) if lib else None
        self.use_combo.blockSignals(True)
        self.use_combo.clear()
        self.use_combo.addItem(_('(none: calibre\'s normal style)'), '')
        for name in self._sorted_names():
            self.use_combo.addItem(name, name)
        i = self.use_combo.findData(chosen or '')
        self.use_combo.setCurrentIndex(max(i, 0))
        self.use_combo.setEnabled(bool(lib))
        self.use_combo.blockSignals(False)

    def _on_library_changed(self, idx):
        self._fill_use_combo()
        lib = self._current_lib()
        if lib and self.assign.get(lib) in self.styles:
            self._select_style(self.assign[lib])

    def _on_use_changed(self, idx):
        lib = self._current_lib()
        if not lib:
            return
        name = self.use_combo.itemData(idx)
        if name:
            self.assign[lib] = name
            self._select_style(name)
        else:
            self.assign.pop(lib, None)
        self._refresh_label(self.lib_combo.currentIndex())
        cur = self._style
        self._fill_style_list(select=cur)

    # -- restore calibre's original -----------------------------------------

    def calibre_base_customized(self):
        """Text of the user's own customization in calibre, if any."""
        try:
            if self.mode == 'details':
                user = P('templates/book_details.css', data=True)
                default = P('templates/book_details.css', data=True, allow_user_override=False)
                return '' if user == default else user.decode('utf-8', 'replace')
            from calibre_plugins.calibre_style.config import plugin_prefs
            if plugin_prefs['viewer_managed']:
                return plugin_prefs['viewer_original_css'] or ''
            from calibre.gui2.viewer.config import vprefs
            vprefs.refresh()
            return (vprefs['session_data'] or {}).get('user_stylesheet', '') or ''
        except Exception:
            return ''

    def _reset_to_calibre(self):
        lib = self._current_lib()
        if lib:
            self.use_combo.setCurrentIndex(0)   # (none)
        if self.calibre_base_customized().strip() and not self.reset_calibre_base:
            if self.mode == 'details':
                msg = _('The base style of the book details panel was also changed in calibre '
                        '(Preferences > Look & feel > Book details). Restore it to calibre\'s '
                        'original as well? This affects all libraries.')
            else:
                msg = _('The viewer also has its own style set in its preferences '
                        '(Preferences > Styles in the viewer). Remove it too, so the viewer '
                        'looks like calibre\'s original? This affects all libraries.')
            if question_dialog(self, _('Restore calibre\'s original'), msg):
                self.reset_calibre_base = True
        self.status_reset()

    def status_reset(self):
        if self.reset_calibre_base:
            self.reset_button.setText(_('Restored (applied on OK)'))
            self.reset_button.setEnabled(False)

    def get_settings(self):
        return dict(self.styles), dict(self.assign)
