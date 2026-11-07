# -*- coding: utf-8 -*-

import os
from collections import OrderedDict

try:
    from qt.core import (QMenu, QFileDialog, QDialog, QVBoxLayout, QTextEdit,
                         QDialogButtonBox, QFont, QLabel, QCheckBox, QLineEdit,
                         QProgressDialog, Qt, QApplication)
except ImportError:
    from PyQt5.Qt import (QMenu, QFileDialog, QDialog, QVBoxLayout, QTextEdit,
                          QDialogButtonBox, QFont, QLabel, QCheckBox, QLineEdit,
                          QProgressDialog, Qt, QApplication)

from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import info_dialog, error_dialog, question_dialog, open_local_file

try:
    load_translations()
except NameError:
    pass


def mark_label():
    # Texto con el que se marcan los libros problemáticos (búsqueda: marked:"=...")
    return _('integrity_issue')


HELP_HTML = (
    '<h3>Recommended workflow</h3>'
    '<ol>'
    '<li><b>Run Integrity Analysis</b> and read the report.</li>'
    '<li>Fix the real problems (missing files, damaged folders...). The affected books are marked so you can find them.</li>'
    '<li>For the issues that are intentional (for example, empty records you keep on purpose), select those books and use <b>Exclusions &gt; Exclude selected books</b>, or use <b>Exclude every issue in the last report</b> to add them all at once.</li>'
    '<li>Run the analysis again: the report now shows only the issues that still need attention.</li>'
    '</ol>'
    '<h3>Menu options</h3>'
    '<p><b>Run Integrity Analysis</b>: scans every book of the current library. The progress window lets you cancel; in that case the report is partial.</p>'
    '<p><b>View Last Integrity Report</b>: shows the last report again, grouped by book. Each issue shows its check type in brackets: [no_formats], [formats], [folder], [opf], [cover] or [io].</p>'
    '<p><b>Export Report to .txt</b>: saves the report to a text file.</p>'
    '<p><b>Mark problematic books</b>: marks the books of the last report with the text <i>{mark}</i> and shows them. You can also find them by typing <code>marked:"={mark}"</code> in the search bar.</p>'
    '<p><b>Show marked problematic books</b>: shows only the marked books again. Clear the search bar to see the whole library.</p>'
    '<p><b>Clear integrity marks</b>: removes only the marks added by this plugin.</p>'
    '<h3>Exclusions submenu</h3>'
    '<p><b>Exclude selected books</b>: select books first. You choose which checks to ignore for them:</p>'
    '<ul>'
    '<li><i>All checks</i>: the book is skipped entirely.</li>'
    '<li><i>Book without formats (empty record)</i>: for records that only hold metadata.</li>'
    '<li><i>Missing or empty format files</i>, <i>Missing book folder</i>, <i>Missing or empty metadata.opf</i>, <i>Missing cover.jpg</i>.</li>'
    '</ul>'
    '<p>If the books appear in the last report, the checks they failed are already ticked.</p>'
    '<p><b>Exclude every issue in the last report</b>: adds all the books of the report, each one only with the checks it failed. If a new, different problem appears later in one of them, it will still be reported.</p>'
    '<p><b>Remove selected books from exclusions</b>: those books will be checked again.</p>'
    '<p><b>Show excluded books in the library</b>: filters the library to the excluded books.</p>'
    '<p><b>Open exclusions file</b>: opens the JSON with your editor. Besides the books, you can fill the <code>excluded_tags</code> list: any book with one of those tags is skipped entirely.</p>'
    '<p><b>Import / Export exclusions</b>: merge another JSON into yours, or save a copy (backup or another computer). Books are identified by their uuid, so exclusions keep working even if the id changes.</p>'
    '<h3>Configure Plugin</h3>'
    '<p>Turn each check on or off. If you never want empty records to be reported, uncheck <i>Report books without any format</i>. You can also turn off automatic marking and choose where the exclusions file is stored.</p>'
)


class ExclusionDialog(QDialog):
    """Permite elegir qué comprobaciones excluir y añadir una nota."""

    def __init__(self, parent, count, preselected):
        QDialog.__init__(self, parent)
        from calibre_plugins.integrity_analysis.exclusions import CHECKS
        self.setWindowTitle(_('Add books to exclusions'))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_('Books to exclude: {0}').format(count), self))
        layout.addWidget(QLabel(_('Ignore these checks for the selected books:'), self))
        self.boxes = {}
        for key, label in CHECKS:
            cb = QCheckBox(label, self)
            cb.setChecked(key in preselected)
            self.boxes[key] = cb
            layout.addWidget(cb)
        self.boxes['all'].toggled.connect(self._all_toggled)
        self._all_toggled(self.boxes['all'].isChecked())
        layout.addWidget(QLabel(_('Note (optional):'), self))
        self.note = QLineEdit(self)
        layout.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _all_toggled(self, checked):
        for key, cb in self.boxes.items():
            if key != 'all':
                cb.setEnabled(not checked)

    def selected_checks(self):
        if self.boxes['all'].isChecked():
            return ['all']
        return [k for k, cb in self.boxes.items() if cb.isChecked()]


class IntegrityAnalysisAction(InterfaceAction):

    name = 'Integrity Analysis'
    action_spec = (_('Integrity Analysis'), 'images/icon.png',
                   _('Run integrity analysis on library and components'), None)

    def genesis(self):
        icon = get_icons('images/icon.png', 'Integrity Analysis')

        self.last_report_data = None
        self.last_issues = []          # lista de dicts {id, uuid, title, check, reason}
        self.last_library_id = None

        menu = QMenu(self.gui)
        menu.setToolTipsVisible(True)

        def add(m, text, slot, tip, ic=None):
            a = m.addAction(ic, text, slot) if ic is not None else m.addAction(text, slot)
            a.setToolTip(tip)
            a.setStatusTip(tip)
            return a

        add(menu, _('Run Integrity Analysis'), self.run_analysis,
            _('Scans every book in the current library: format files, book folder, '
              'metadata.opf and cover.jpg. Books and checks listed in the exclusions '
              'file are skipped.'), icon)
        menu.addSeparator()

        self.action_view_report = add(
            menu, _('View Last Integrity Report'), self.view_last_report,
            _('Opens the report of the last scan again, with the issues grouped by book. '
              'Available after running an analysis.'))
        self.action_export_report = add(
            menu, _('Export Report to .txt...'), self.export_report_to_txt,
            _('Saves the last report as a text file so you can keep it or review it later.'))
        menu.addSeparator()

        # Marcado de libros
        self.action_mark = add(
            menu, _('Mark problematic books'), self.mark_problem_books,
            _('Marks in calibre every book that had an issue in the last report and '
              'filters the library to show only them. Other marks you have are kept.'))
        add(menu, _('Show marked problematic books'), self.show_marked_books,
            _('Filters the library to show only the books marked by this plugin. '
              'To see all books again, clear the search bar.'))
        add(menu, _('Clear integrity marks'), self.clear_marks,
            _('Removes the marks added by this plugin. Marks made by you or other '
              'plugins are not touched.'))
        menu.addSeparator()

        # Exclusiones
        ex_menu = menu.addMenu(_('Exclusions'))
        ex_menu.setToolTipsVisible(True)
        add(ex_menu, _('Exclude selected books...'), self.exclude_selected,
            _('Select one or more books in the library first. A window lets you choose '
              'which checks to ignore for them (for example, "Book without formats" for '
              'empty records) and add a note.'))
        self.action_exclude_report = add(
            ex_menu, _('Exclude every issue in the last report...'), self.exclude_from_report,
            _('Adds all the books of the last report to the exclusions file, ignoring only '
              'the checks each one failed. Use it once you have reviewed the report and '
              'the remaining issues are intentional.'))
        add(ex_menu, _('Remove selected books from exclusions'), self.unexclude_selected,
            _('Select books in the library first. They are removed from the exclusions '
              'file and will be checked again in the next scan.'))
        ex_menu.addSeparator()
        add(ex_menu, _('Show excluded books in the library'), self.show_excluded_books,
            _('Filters the library to show the books that are excluded '
              '(by uuid, by id or by tag).'))
        add(ex_menu, _('Open exclusions file (.json)'), self.open_exclusions_file,
            _('Opens the JSON file with your default editor so you can review it or edit '
              'it by hand. It is created empty if it does not exist yet.'))
        add(ex_menu, _('Import exclusions from .json...'), self.import_exclusions,
            _('Merges the exclusions of another JSON file (for example, a backup) into '
              'the current file. Nothing already present is deleted.'))
        add(ex_menu, _('Export exclusions to .json...'), self.export_exclusions,
            _('Saves a copy of the exclusions file wherever you choose, as a backup or '
              'to use it on another computer.'))

        menu.addSeparator()
        add(menu, _('Configure Plugin...'), self.show_configuration,
            _('Choose which checks to run, whether to mark books automatically and '
              'where the exclusions file is stored.'))
        add(menu, _('Help'), self.show_help,
            _('Explains what each option of this menu does and the recommended workflow.'))
        add(menu, _('About {0}').format(_('Integrity Analysis')), self.show_about,
            _('Version, links and how to support the development of this plugin.'))

        self.qaction.setIcon(icon)
        self.qaction.setMenu(menu)
        self.qaction.triggered.connect(self.run_analysis)
        self._update_actions()

    # ------------------------------------------------------------------ util
    def _update_actions(self):
        has_report = bool(self.last_report_data)
        self.action_view_report.setEnabled(has_report)
        self.action_export_report.setEnabled(has_report)
        self.action_mark.setEnabled(bool(self.last_issues))
        self.action_exclude_report.setEnabled(bool(self.last_issues))

    def library_changed(self, db):
        # Los resultados pertenecen a otra biblioteca: se descartan.
        self.last_report_data = None
        self.last_issues = []
        self.last_library_id = None
        self._update_actions()

    def _selected_books(self):
        db = self.gui.current_db.new_api
        ids = list(self.gui.library_view.get_selected_ids())
        return [(i, db.field_for('uuid', i), db.field_for('title', i)) for i in ids]

    def _load_exclusions(self, silent_errors=False):
        from calibre_plugins.integrity_analysis import exclusions as ex
        try:
            return ex.load()
        except Exception as e:
            if not silent_errors:
                error_dialog(self.gui, _('Integrity Analysis'),
                             _('Could not read the exclusions file'),
                             det_msg='%s\n\n%s' % (ex.exclusions_path(), e), show=True)
            return None

    def _save_exclusions(self, data):
        from calibre_plugins.integrity_analysis import exclusions as ex
        try:
            return ex.save(data)
        except Exception as e:
            error_dialog(self.gui, _('Integrity Analysis'),
                         _('Could not save the exclusions file'),
                         det_msg='%s\n\n%s' % (ex.exclusions_path(), e), show=True)
            return None

    # -------------------------------------------------------------- análisis
    def run_analysis(self):
        gui = self.gui
        db = gui.current_db.new_api
        all_ids = list(db.all_book_ids())
        total_books = len(all_ids)

        if total_books == 0:
            error_dialog(gui, _('Integrity Analysis'), _('The library is empty'),
                         det_msg=_('Please add some books to your library before running the integrity analysis.'),
                         show=True)
            return

        from calibre_plugins.integrity_analysis.config import plugin_prefs
        from calibre_plugins.integrity_analysis import exclusions as ex
        check_formats = plugin_prefs.get('check_missing_formats', True)
        check_empty = plugin_prefs.get('check_empty_records', True)
        check_covers = plugin_prefs.get('check_missing_covers', True)
        cover_only_if_db = plugin_prefs.get('only_cover_if_db_has_cover', False)
        check_opf = plugin_prefs.get('check_missing_opf', True)

        matcher = None
        if plugin_prefs.get('use_exclusions', True):
            data = self._load_exclusions()
            if data is None:
                if not question_dialog(gui, _('Integrity Analysis'),
                                       _('Continue the analysis without exclusions?')):
                    return
            else:
                matcher = ex.ExclusionMatcher(data)

        library_path = gui.current_db.library_path
        issues = []
        excluded_books = 0
        excluded_issues = 0

        progress = QProgressDialog(_('Analyzing library...'), _('Cancel'), 0, total_books, gui)
        progress.setWindowTitle(_('Integrity Analysis'))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(500)
        cancelled = False

        for n, book_id in enumerate(all_ids):
            if n % 25 == 0:
                progress.setValue(n)
                QApplication.processEvents()
                if progress.wasCanceled():
                    cancelled = True
                    break

            title = db.field_for('title', book_id) or _('(untitled)')
            uuid = db.field_for('uuid', book_id)
            skipped = set()
            if matcher is not None:
                skipped = matcher.skipped_checks(book_id, uuid, db.field_for('tags', book_id))
                if 'all' in skipped:
                    excluded_books += 1
                    continue

            book_issues = []

            def add(check, reason):
                book_issues.append({'id': book_id, 'uuid': uuid, 'title': title,
                                    'check': check, 'reason': reason})

            try:
                # A. Formatos registrados
                if check_formats or check_empty:
                    formats = db.formats(book_id) or ()
                    if not formats:
                        if check_empty:
                            add('no_formats', _('No formats registered in database for this book'))
                    elif check_formats:
                        for fmt in formats:
                            file_path = db.format_abspath(book_id, fmt)
                            if file_path is None or not os.path.exists(file_path):
                                add('formats', _('Missing physical file for format: {0}').format(fmt))
                            elif os.path.getsize(file_path) == 0:
                                add('formats', _('Empty file (0 bytes) for format: {0}').format(fmt))

                # B. Carpeta, metadata.opf y cover.jpg
                if check_covers or check_opf:
                    rel_path = db.field_for('path', book_id)
                    if rel_path:
                        book_dir = os.path.join(library_path, rel_path)
                        if not os.path.isdir(book_dir):
                            add('folder', _('The book directory does not exist on disk: {0}').format(rel_path))
                        else:
                            if check_opf:
                                opf_path = os.path.join(book_dir, 'metadata.opf')
                                if not os.path.exists(opf_path):
                                    add('opf', _('Missing metadata.opf file in the book folder'))
                                elif os.path.getsize(opf_path) == 0:
                                    add('opf', _('Corrupted or empty metadata.opf file (0 bytes)'))
                            if check_covers:
                                cover_path = os.path.join(book_dir, 'cover.jpg')
                                if not os.path.exists(cover_path):
                                    has_cover = bool(db.field_for('cover', book_id))
                                    if has_cover:
                                        add('cover', _('Missing cover.jpg file (calibre says the book has a cover)'))
                                    elif not cover_only_if_db:
                                        add('cover', _('Missing cover.jpg file in the book folder'))
                    else:
                        add('folder', _('The book has no folder path registered in the database'))
            except OSError as e:
                add('io', _('I/O Error accessing disk/folder: {0}').format(e))
            except Exception as e:
                # Un registro raro no debe detener todo el análisis
                add('io', _('Unexpected error while checking this book: {0}').format(e))

            for issue in book_issues:
                if issue['check'] in skipped:
                    excluded_issues += 1
                else:
                    issues.append(issue)

        progress.setValue(total_books)
        progress.close()

        self.last_issues = issues
        self.last_library_id = db.library_id
        problem_ids = list(OrderedDict.fromkeys(i['id'] for i in issues))
        checked = n + (0 if cancelled else 1)

        # Informe agrupado por libro
        lines = ['=' * 70, _('CALIBRE LIBRARY INTEGRITY ANALYSIS REPORT'), '=' * 70]
        if cancelled:
            lines.append(_('ANALYSIS CANCELLED: the report is partial.'))
        lines.append(_('Total books checked: {}').format(checked))
        lines.append(_('Books with issues: {}').format(len(problem_ids)))
        lines.append(_('Issues found: {}').format(len(issues)))
        if matcher is not None:
            lines.append(_('Books fully excluded: {}').format(excluded_books))
            lines.append(_('Issues ignored by exclusions: {}').format(excluded_issues))
            lines.append(_('Exclusions file: {}').format(ex.exclusions_path()))
        else:
            lines.append(_('Exclusions: not applied'))
        lines.append('-' * 70)

        if issues:
            by_book = OrderedDict()
            for issue in issues:
                by_book.setdefault(issue['id'], []).append(issue)
            for book_id, book_issues in by_book.items():
                lines.append('[ID: {0}] {1}'.format(book_id, book_issues[0]['title']))
                for issue in book_issues:
                    lines.append('    - [{0}] {1}'.format(issue['check'], issue['reason']))
            lines.append('-' * 70)
            lines.append(_('Tip: problematic books can be found with the search: {0}').format(
                'marked:"=%s"' % mark_label()))
        else:
            lines.append(_('No integrity issues detected.') + '\n' + _('Your library is healthy.'))
        lines.append('=' * 70)

        self.last_report_data = '\n'.join(lines)
        self._update_actions()

        if plugin_prefs.get('auto_mark_books', True):
            self.mark_problem_books(show=bool(problem_ids), quiet=True)

        if plugin_prefs.get('auto_show_error_log', True):
            self.view_last_report()
        else:
            info_dialog(gui, _('Integrity Analysis'), _('Analysis completed'),
                        det_msg=_('Library analyzed successfully. Total books checked: {0}. '
                                  'Use the drop-down menu to view or export the report.').format(checked),
                        show=True)

    # --------------------------------------------------------------- marcado
    def _set_marks(self, ids):
        data = self.gui.current_db.data
        label = mark_label()
        current = dict(getattr(data, 'marked_ids', {}) or {})
        current = {k: v for k, v in current.items() if v != label}
        for i in ids:
            current[i] = label
        data.set_marked_ids(current)

    def mark_problem_books(self, show=True, quiet=False):
        if not self.last_issues:
            return
        if self.last_library_id != self.gui.current_db.new_api.library_id:
            return
        existing = set(self.gui.current_db.new_api.all_book_ids())
        ids = [i for i in OrderedDict.fromkeys(x['id'] for x in self.last_issues) if i in existing]
        self._set_marks(ids)
        if show:
            self.show_marked_books()
        if not quiet:
            info_dialog(self.gui, _('Integrity Analysis'),
                        _('{0} problematic books were marked.').format(len(ids)), show=True)

    def show_marked_books(self):
        self.gui.search.set_search_string('marked:"=%s"' % mark_label())

    def clear_marks(self):
        self._set_marks([])
        search = self.gui.search.currentText() or ''
        if mark_label() in search:
            self.gui.search.clear()

    # ----------------------------------------------------------- exclusiones
    def exclude_selected(self):
        books = self._selected_books()
        if not books:
            error_dialog(self.gui, _('Integrity Analysis'), _('No books selected'), show=True)
            return
        # Preseleccionar las comprobaciones que fallaron en el último informe
        sel_ids = {b[0] for b in books}
        pre = {i['check'] for i in self.last_issues if i['id'] in sel_ids and i['check'] != 'io'}
        d = ExclusionDialog(self.gui, len(books), pre or {'all'})
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        checks = d.selected_checks()
        if not checks:
            return
        from calibre_plugins.integrity_analysis import exclusions as ex
        data = self._load_exclusions()
        if data is None:
            return
        added = ex.add_books(data, books, checks, d.note.text().strip())
        path = self._save_exclusions(data)
        if path:
            info_dialog(self.gui, _('Integrity Analysis'),
                        _('Exclusions saved: {0} new, {1} updated.').format(added, len(books) - added),
                        det_msg=path, show=True)

    def exclude_from_report(self):
        if not self.last_issues:
            return
        per_book = OrderedDict()
        for i in self.last_issues:
            if i['check'] == 'io':
                continue
            per_book.setdefault((i['id'], i['uuid'], i['title']), set()).add(i['check'])
        if not per_book:
            return
        if not question_dialog(
                self.gui, _('Integrity Analysis'),
                _('Add the {0} books of the last report to the exclusions file? '
                  'Only the checks each book failed will be ignored in future scans.').format(len(per_book))):
            return
        from calibre_plugins.integrity_analysis import exclusions as ex
        data = self._load_exclusions()
        if data is None:
            return
        added = 0
        for book, checks in per_book.items():
            added += ex.add_books(data, [book], checks, _('Added from report'))
        path = self._save_exclusions(data)
        if path:
            info_dialog(self.gui, _('Integrity Analysis'),
                        _('Exclusions saved: {0} new, {1} updated.').format(added, len(per_book) - added),
                        det_msg=path, show=True)

    def unexclude_selected(self):
        books = self._selected_books()
        if not books:
            error_dialog(self.gui, _('Integrity Analysis'), _('No books selected'), show=True)
            return
        from calibre_plugins.integrity_analysis import exclusions as ex
        data = self._load_exclusions()
        if data is None:
            return
        removed = ex.remove_books(data, books)
        if removed and self._save_exclusions(data):
            info_dialog(self.gui, _('Integrity Analysis'),
                        _('{0} books removed from the exclusions.').format(removed), show=True)
        elif not removed:
            info_dialog(self.gui, _('Integrity Analysis'),
                        _('None of the selected books were excluded.'), show=True)

    def show_excluded_books(self):
        data = self._load_exclusions()
        if data is None:
            return
        db = self.gui.current_db.new_api
        uuids = {e['uuid'] for e in data['books'] if e['uuid']}
        raw_ids = {e['id'] for e in data['books'] if not e['uuid'] and e['id'] is not None}
        tags = {t.lower() for t in data['excluded_tags']}
        ids = []
        for book_id in db.all_book_ids():
            if book_id in raw_ids or db.field_for('uuid', book_id) in uuids or (
                    tags and any(t.lower() in tags for t in (db.field_for('tags', book_id) or ()))):
                ids.append(book_id)
        if not ids:
            info_dialog(self.gui, _('Integrity Analysis'),
                        _('No book in this library is excluded.'), show=True)
            return
        self.gui.search.set_search_string(' or '.join('id:=%d' % i for i in ids))

    def open_exclusions_file(self):
        from calibre_plugins.integrity_analysis import exclusions as ex
        path = ex.exclusions_path()
        if not os.path.exists(path):
            try:
                ex.save(ex.empty_data(), path)
            except Exception as e:
                error_dialog(self.gui, _('Integrity Analysis'),
                             _('Could not save the exclusions file'), det_msg=str(e), show=True)
                return
        open_local_file(path)

    def import_exclusions(self):
        path, _f = QFileDialog.getOpenFileName(self.gui, _('Import exclusions'), '',
                                               'JSON (*.json);;All Files (*)')
        if not path:
            return
        from calibre_plugins.integrity_analysis import exclusions as ex
        try:
            incoming = ex.load(path)
        except Exception as e:
            error_dialog(self.gui, _('Integrity Analysis'),
                         _('Could not read the exclusions file'), det_msg='%s\n\n%s' % (path, e), show=True)
            return
        data = self._load_exclusions()
        if data is None:
            return
        for e in incoming['books']:
            ex.add_books(data, [(e['id'], e['uuid'], e['title'])], e['checks'], e['note'])
        for t in incoming['excluded_tags']:
            if t not in data['excluded_tags']:
                data['excluded_tags'].append(t)
        if self._save_exclusions(data):
            info_dialog(self.gui, _('Integrity Analysis'),
                        _('{0} exclusions imported.').format(len(incoming['books'])), show=True)

    def export_exclusions(self):
        data = self._load_exclusions()
        if data is None:
            return
        path, _f = QFileDialog.getSaveFileName(self.gui, _('Export exclusions'),
                                               'integrity_analysis_exclusions.json',
                                               'JSON (*.json);;All Files (*)')
        if not path:
            return
        from calibre_plugins.integrity_analysis import exclusions as ex
        try:
            ex.save(data, path)
        except Exception as e:
            error_dialog(self.gui, _('Export Error'), _('Could not save the file'), det_msg=str(e), show=True)
            return
        info_dialog(self.gui, _('Export Successful'), _('Report saved successfully'),
                    det_msg=_('The report has been saved to:\n{0}').format(path), show=True)

    # ---------------------------------------------------------------- informe
    def view_last_report(self):
        if not self.last_report_data:
            return
        dialog = QDialog(self.gui)
        dialog.setWindowTitle(_('Integrity Analysis - Last Report'))
        dialog.resize(800, 550)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(_('Summary of the latest integrity scan:'), dialog))
        text_edit = QTextEdit(dialog)
        text_edit.setReadOnly(True)
        text_edit.setPlainText(self.last_report_data)
        font = QFont('Courier New' if os.name == 'nt' else 'Monospace')
        try:
            font.setStyleHint(QFont.StyleHint.Monospace)
        except AttributeError:
            pass
        text_edit.setFont(font)
        layout.addWidget(text_edit)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, dialog)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)
        dialog.exec()

    def export_report_to_txt(self):
        if not self.last_report_data:
            return
        file_path, _f = QFileDialog.getSaveFileName(
            self.gui, _('Export Integrity Report'), 'integrity_analysis_report.txt',
            'Text Files (*.txt);;All Files (*)')
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.last_report_data)
                info_dialog(self.gui, _('Export Successful'), _('Report saved successfully'),
                            det_msg=_('The report has been saved to:\n{0}').format(file_path), show=True)
            except Exception as e:
                error_dialog(self.gui, _('Export Error'), _('Could not save the file'),
                             det_msg=str(e), show=True)

    # ----------------------------------------------------------------- ayuda
    def show_about(self):
        from calibre_plugins.integrity_analysis.support import show_about
        show_about(self.gui, self.interface_action_base_plugin)

    def show_help(self):
        try:
            from qt.core import QTextBrowser
        except ImportError:
            from PyQt5.Qt import QTextBrowser
        dialog = QDialog(self.gui)
        dialog.setWindowTitle(_('Integrity Analysis - Help'))
        dialog.resize(720, 600)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser(dialog)
        browser.setOpenExternalLinks(False)
        browser.setHtml(_(HELP_HTML).replace('{mark}', mark_label()))
        layout.addWidget(browser)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, dialog)
        bb.accepted.connect(dialog.accept)
        layout.addWidget(bb)
        dialog.exec()

    def show_configuration(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def apply_settings(self):
        pass
