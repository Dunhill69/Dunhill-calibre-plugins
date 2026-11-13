#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

import os
import traceback

from qt.core import QMenu, QToolButton, QProgressDialog, Qt, QApplication, QIcon

from calibre.gui2 import error_dialog, info_dialog, question_dialog
from calibre.gui2.actions import InterfaceAction
from calibre.utils.logging import Log

from calibre_plugins.synopsis_page.prefs import prefs

try:
    load_translations()
except NameError:
    pass

PLUGIN_NAME = 'Synopsis Page'


class SynopsisPageAction(InterfaceAction):

    name = PLUGIN_NAME
    action_spec = (_('Synopsis Page'), None,
                   _('Adds a page with the cover and the synopsis to the book'), None)
    popup_type = QToolButton.ToolButtonPopupMode.MenuButtonPopup
    action_type = 'current'
    dont_add_to = frozenset(['context-menu-device', 'toolbar-device', 'menubar-device'])

    def genesis(self):
        self.plugin_icon = get_icons('images/icon.png', PLUGIN_NAME)
        self.qaction.setIcon(self.plugin_icon)
        self.menu = QMenu(self.gui)
        self.qaction.setMenu(self.menu)
        self.qaction.triggered.connect(self.add_pages)
        self.build_menu()

    def build_menu(self):
        m = self.menu
        m.clear()
        self.create_menu_action(m, 'sp-add', _('Add synopsis page'),
                                icon=self.plugin_icon, triggered=self.add_pages)
        self.create_menu_action(m, 'sp-remove', _('Remove synopsis page'),
                                icon=QIcon.ic('trash.png'), triggered=self.remove_pages)
        m.addSeparator()
        self.create_menu_action(m, 'sp-config', _('Customize plugin…'),
                                icon=QIcon.ic('config.png'), shortcut=False,
                                triggered=self.show_config)
        self.create_menu_action(m, 'sp-about', _('About…'),
                                icon=QIcon.ic('help.png'), shortcut=False,
                                triggered=self.show_about)
        self.gui.keyboard.finalize()

    # ------------------------------------------------------------------

    def show_config(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def show_about(self):
        from calibre_plugins.synopsis_page.about import AboutDialog
        AboutDialog(self.gui, self.plugin_icon,
                    self.interface_action_base_plugin.version).exec()

    def _selected_ids(self):
        ids = list(self.gui.library_view.get_selected_ids())
        if not ids:
            error_dialog(self.gui, _('Synopsis Page'), _('No books selected.'),
                         show=True)
        return ids

    def add_pages(self):
        ids = self._selected_ids()
        if ids:
            self._run(ids, 'add')

    def remove_pages(self):
        ids = self._selected_ids()
        if not ids:
            return
        if not question_dialog(
                self.gui, _('Synopsis Page'),
                _('Remove the synopsis page from %d book(s)?') % len(ids)):
            return
        self._run(ids, 'remove')

    # ------------------------------------------------------------------

    def _run(self, ids, mode):
        from calibre_plugins.synopsis_page.core import add_synopsis, remove_synopsis

        db = self.gui.current_db.new_api
        log = Log()
        done, skipped, replaced = [], [], 0

        pd = QProgressDialog('', _('Cancel'), 0, len(ids), self.gui)
        pd.setWindowTitle(_('Synopsis Page'))
        pd.setWindowModality(Qt.WindowModality.WindowModal)
        pd.setMinimumDuration(0)

        for i, book_id in enumerate(ids):
            if pd.wasCanceled():
                break
            mi = db.get_metadata(book_id, get_cover=False)
            title = mi.title or str(book_id)
            pd.setLabelText('%s\n%s' % (_('Adding page…') if mode == 'add'
                                        else _('Removing page…'), title))
            pd.setValue(i)
            QApplication.processEvents()

            fmts = db.formats(book_id)
            wanted = [f for f in prefs['formats'] if f in fmts]
            if not wanted:
                skipped.append((title, _('it has no %s format') % ' / '.join(prefs['formats'])))
                continue
            if mode == 'add' and not (mi.comments or '').strip():
                skipped.append((title, _('it has no synopsis (empty Comments)')))
                continue
            cover = None
            if mode == 'add' and prefs['include_cover']:
                cover = db.cover(book_id)

            for fmt in wanted:
                label = '%s [%s]' % (title, fmt)
                path = None
                try:
                    path = db.format(book_id, fmt, as_path=True)
                    if mode == 'add':
                        if add_synopsis(path, mi, cover, prefs, log):
                            replaced += 1
                        if prefs['backup'] and ('ORIGINAL_' + fmt) not in fmts:
                            db.save_original_format(book_id, fmt)
                    else:
                        if not remove_synopsis(path, log):
                            skipped.append((label, _('it had no synopsis page')))
                            continue
                    db.add_format(book_id, fmt, path, replace=True, run_hooks=False)
                    if book_id not in done:
                        done.append(book_id)
                except Exception as e:
                    skipped.append((label, '%s\n%s' % (e, traceback.format_exc())))
                finally:
                    if path:
                        try:
                            os.remove(path)
                        except Exception:
                            pass

        pd.setValue(len(ids))
        pd.close()

        if done:
            m = self.gui.library_view.model()
            m.refresh_ids(done)
            cur = self.gui.library_view.currentIndex()
            if cur.isValid():
                m.current_changed(cur, cur)

        self._report(mode, done, skipped, replaced)

    def _report(self, mode, done, skipped, replaced):
        if mode == 'add':
            msg = _('The synopsis page was added to %d book(s).') % len(done)
        else:
            msg = _('The synopsis page was removed from %d book(s).') % len(done)
        if replaced:
            msg += '<br>' + _('An older page was replaced in %d of them.') % replaced
        det = '\n\n'.join('• %s: %s' % s for s in skipped)
        if skipped:
            msg += '<br><br>' + _('%d item(s) were not processed. See the details.') % len(skipped)
            if not done:
                return error_dialog(self.gui, _('Synopsis Page'), msg, det_msg=det, show=True)
        info_dialog(self.gui, _('Synopsis Page'), msg, det_msg=det, show=True,
                    show_copy_button=bool(skipped))
