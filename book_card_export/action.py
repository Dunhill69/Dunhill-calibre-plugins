#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

from calibre.gui2 import error_dialog
from calibre.gui2.actions import InterfaceAction
from qt.core import QModelIndex

try:
    load_translations()
except NameError:
    pass


class BookCardAction(InterfaceAction):

    name = 'Book Card Export'
    action_spec = (_('Book card'), None,
                   _('Export the book card as an image, or copy it for Telegram'), None)
    action_type = 'current'
    action_add_menu = True
    action_menu_clone_qaction = _('Open book card')
    dont_add_to = frozenset(['context-menu-device', 'toolbar-device', 'menubar-device'])

    def genesis(self):
        self.qaction.setIcon(get_icons('images/icon.png', 'Book Card Export'))
        self.qaction.triggered.connect(self.show_dialog)
        m = self.qaction.menu()
        m.addSeparator()
        self.create_menu_action(m, 'bce-config', _('Configure...'),
                                'config.png', triggered=self.show_config)
        self.create_menu_action(m, 'bce-help', _('Help...'),
                                'help.png', triggered=self.show_help)
        self.create_menu_action(m, 'bce-about', _('About...'),
                                'dialog_information.png', triggered=self.show_about)

    def location_selected(self, loc):
        self.qaction.setEnabled(loc == 'library')

    def show_dialog(self):
        view = self.gui.library_view
        rows = view.selectionModel().selectedRows()
        if not rows:
            return error_dialog(self.gui, _('No book selected'),
                                _('Select a book to see its card.'), show=True)
        model = view.model()
        selected = [model.id(r) for r in rows]
        if len(selected) > 1:
            ids, start, mode = selected, 0, 'selected'
        else:
            ids = [model.id(r) for r in range(model.rowCount(QModelIndex()))]
            try:
                start = ids.index(selected[0])
            except ValueError:
                ids, start = selected, 0
            try:
                total = len(self.gui.current_db.new_api.all_book_ids())
            except Exception:
                total = len(ids)
            mode = 'library' if len(ids) >= total else 'view'
        from calibre_plugins.book_card_export.dialog import CardDialog
        d = CardDialog(self.gui, self, ids, start, selected, mode)
        d.exec()

    def show_config(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def show_help(self):
        from calibre_plugins.book_card_export.help_dialog import HelpDialog
        HelpDialog(self.gui).exec()

    def show_about(self):
        from calibre_plugins.book_card_export.about import AboutDialog
        AboutDialog(self.gui, self.interface_action_base_plugin).exec()
