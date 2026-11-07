# -*- coding: utf-8 -*-

from qt.core import QIcon, QPixmap, QMenu, QToolButton
from calibre.gui2.actions import InterfaceAction

try:
    load_translations()
except NameError:
    pass

class DeleteExtraFilesAction(InterfaceAction):
    name = 'delete-extra-files-action'  # Unique internal identifier for the toolbar
    PLUGIN_ICONS = ['images/icon.png']
    action_spec = (_('Delete Extra Files'), None, _('Deletes extra data folders across the entire library'), None)
    popup_type = QToolButton.ToolButtonPopupMode.MenuButtonPopup  # clic: abre el diálogo; flecha: menú

    def genesis(self):
        # Safe loading of the icon from packaged resources
        self.icon = QIcon()
        icon_resources = self.load_resources(self.PLUGIN_ICONS)
        if 'images/icon.png' in icon_resources:
            pixmap = QPixmap()
            pixmap.loadFromData(icon_resources['images/icon.png'])
            self.icon = QIcon(pixmap)
            self.qaction.setIcon(self.icon)

        self.qaction.triggered.connect(self.open_dialog)

        self.menu = QMenu(self.gui)
        self.menu.addAction(self.icon, _('Delete Extra Files'), self.open_dialog)
        self.menu.addSeparator()
        self.menu.addAction(_('About {0}').format(_('Delete Extra Files')), self.show_about)
        self.qaction.setMenu(self.menu)

    def open_dialog(self):
        from calibre_plugins.delete_extra_files.ui import DeleteExtraFilesDialog
        d = DeleteExtraFilesDialog(self.gui, self.gui.current_db)
        d.exec_()

    def show_about(self):
        from calibre_plugins.delete_extra_files.support import show_about
        show_about(self.gui, self.interface_action_base_plugin)
