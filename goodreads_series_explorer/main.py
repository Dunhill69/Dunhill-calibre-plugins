from qt.core import QToolButton
from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import info_dialog

try:
    load_translations()
except NameError:
    pass


class GoodreadsSeriesExplorerAction(InterfaceAction):
    name = 'Goodreads Series Explorer'

    # 'G' ya lo usa calibre para "Obtener libros"; se usa otro atajo
    action_spec = (
        'Goodreads Series Explorer',
        None,
        _('Explore the whole series on Goodreads'),
        'Ctrl+Shift+G'
    )
    action_type = 'current'
    popup_type = QToolButton.ToolButtonPopupMode.MenuButtonPopup
    dont_add_to = frozenset(['context-menu-device'])

    def genesis(self):
        from qt.core import QMenu
        self.dialog = None
        # get_icons devuelve un icono vacío si falta images/icon.png (no rompe)
        icon = get_icons('images/icon.png')
        self.qaction.setIcon(icon)
        self.qaction.triggered.connect(self.show_dialog)
        self.menu = QMenu(self.gui)
        self.menu.addAction(icon, _('Explore the series'), self.show_dialog)
        self.menu.addSeparator()
        self.menu.addAction(_('Settings…'), self.show_config)
        self.menu.addAction(_('About {0}').format('Goodreads Series Explorer'), self.show_about)
        self.qaction.setMenu(self.menu)

    def show_config(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def show_about(self):
        from calibre_plugins.goodreads_series_explorer.support import show_about
        show_about(self.gui, self.interface_action_base_plugin)

    def show_dialog(self):
        from calibre_plugins.goodreads_series_explorer.dialog import SeriesViewerDialog

        gui = self.gui
        view = gui.library_view

        if gui.current_view() is not view:
            info_dialog(gui, _('Attention'),
                        _('Go back to the library view and select a book.'), show=True)
            return

        rows = view.selectionModel().selectedRows()
        if not rows:
            info_dialog(gui, _('Attention'),
                        _('Select a book to explore its series.'), show=True)
            return

        book_id = view.model().id(rows[0])

        if self.dialog is not None:
            self.dialog.close()

        # Ventana no modal: permite ver los resultados de "Buscar en Calibre"
        self.dialog = SeriesViewerDialog(gui, book_id, plugin=self.interface_action_base_plugin)
        self.dialog.show()
