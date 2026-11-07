# -*- coding: utf-8 -*-

from qt.core import QIcon, QPixmap, QMenu, QToolButton
from calibre.gui2.actions import InterfaceAction

class CompareLibrariesAction(InterfaceAction):
    name = 'Compare Libraries'

    # Declaración del ícono para que Calibre lo extraiga del ZIP
    PLUGIN_ICONS = ['images/icon.png']
    action_spec = ('Libros Faltantes', None, 'Compara la biblioteca actual con otra y muestra los faltantes', None)
    # Clic en el botón = comparar; flechita = menú (como en Calibre Updater)
    popup_type = QToolButton.ToolButtonPopupMode.MenuButtonPopup

    def genesis(self):
        # Carga del ícono desde los recursos internos del paquete
        icon_resources = self.load_resources(self.PLUGIN_ICONS)
        self.icon_pix = QPixmap()
        self.icon = QIcon()
        if 'images/icon.png' in icon_resources:
            self.icon_pix.loadFromData(icon_resources['images/icon.png'])
            self.icon = QIcon(self.icon_pix)
            self.qaction.setIcon(self.icon)

        # Conexión directa del botón con la ejecución del diálogo
        self.qaction.triggered.connect(self.lanzar_comparacion)

        self.menu = QMenu(self.gui)
        self.menu.addAction(self.icon, 'Comparar bibliotecas', self.lanzar_comparacion)
        self.menu.addSeparator()
        self.menu.addAction('Configurar complemento...', self.show_config_window)
        self.menu.addAction('Acerca de Compare Libraries', self.show_about)
        self.qaction.setMenu(self.menu)

    def lanzar_comparacion(self):
        from calibre_plugins.compare_libraries.ui import CompareDialog
        dialogo = CompareDialog(self.gui)
        dialogo.exec()

    def show_config_window(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def show_about(self):
        from calibre_plugins.compare_libraries.support import show_about
        show_about(self.gui, self.interface_action_base_plugin)
