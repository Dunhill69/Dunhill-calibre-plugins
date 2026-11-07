#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai

__license__   = 'GPL v3'
__copyright__ = '2026, Dunhill'

try:
    load_translations()
except NameError:
    pass

import os

from qt.core import QIcon, QMenu, QTimer

from calibre.gui2.actions import InterfaceAction


class CalibreCSSAction(InterfaceAction):
    # Internal name kept from the old "Calibre Stylist" so the button keeps
    # its place in toolbars and menus after updating
    name = 'Calibre Stylist'
    action_spec = ('Calibre CSS', None,
                   _('Set a different style for each library'), None)
    action_type = 'current'
    dont_add_to = frozenset(['context-menu-device'])

    def genesis(self):
        try:
            icon = get_icons('images/icon.png', 'Calibre CSS')
            self.qaction.setIcon(icon)
        except Exception:
            pass
        self.qaction.triggered.connect(self.show_config_dialog)
        self.menu = QMenu(self.gui)
        self.menu.addAction(self.qaction.icon(), _('Configure styles...'),
                            self.show_config_dialog)
        self.menu.addAction(QIcon.ic('edit_book.png'), _('Edit the CSS of the selected book...'),
                            lambda: self.show_config_dialog(tab=2))
        self.menu.addSeparator()
        self.menu.addAction(_('About {0}').format('Calibre CSS'), self.show_about)
        self.qaction.setMenu(self.menu)

    def _remove_old_plugin(self):
        # Before 1.5 the plugin was called "Calibre Stylist". Installing the
        # renamed version leaves the old entry behind (same import name), so
        # drop it to avoid having both installed.
        try:
            from calibre.customize.ui import config
            base = self.interface_action_base_plugin
            plugins = config['plugins']
            if base is None or base.name == 'Calibre Stylist' or 'Calibre Stylist' not in plugins:
                return
            old = plugins.pop('Calibre Stylist')
            same = bool(old) and os.path.abspath(old) == os.path.abspath(base.plugin_path or '')
            if same:
                # calibre copied the new version over the old file: keep it,
                # registered under the new name
                plugins.setdefault(base.name, old)
            config['plugins'] = plugins
            if old and not same and os.path.exists(old):
                try:
                    os.remove(old)
                except Exception:
                    pass   # file in use (Windows); calibre no longer loads it
        except Exception:
            import traceback
            traceback.print_exc()

    def initialization_complete(self):
        self._remove_old_plugin()
        # Wait until the book details panel exists and has shown a book
        QTimer.singleShot(0, self.apply_styles)

    def library_changed(self, db):
        QTimer.singleShot(0, lambda: self.apply_styles(db.library_path))

    def apply_styles(self, library_path=None):
        from calibre_plugins.calibre_style.config import apply_all
        apply_all(self.gui, library_path)

    def show_config_dialog(self, *args, tab=0):
        from calibre_plugins.calibre_style.config import ConfigDialog
        d = ConfigDialog(self.gui, self.interface_action_base_plugin, tab=tab)
        d.exec()
        d.widget.tab_book.cleanup()

    def show_about(self):
        from calibre_plugins.calibre_style.support import show_about
        show_about(self.gui, self.interface_action_base_plugin)
