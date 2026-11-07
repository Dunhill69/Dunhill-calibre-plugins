from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import error_dialog
from qt.core import QMenu, QDialog, QVBoxLayout, QLabel, QProgressBar, Qt

try:
    load_translations()
except NameError:
    pass

class LoadingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("3D Cover"))
        self.setFixedSize(320, 90)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        layout = QVBoxLayout(self)
        self.label = QLabel(_("Loading library..."))
        layout.addWidget(self.label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)


class Cover3DAction(InterfaceAction):

    name = '3D Cover'
    # Nota: El segundo elemento de action_spec (tooltip) y el cuarto (shortcut) se marcan según la convención de Calibre
    action_spec = (_('3D Cover'), None, _('Turn flat covers into 3D books'), None)

    def genesis(self):
        self.icon = get_icons('images/icon.png', '3D Cover')
        self.qaction.setIcon(self.icon)
        self.qaction.triggered.connect(self.show_dialog)

        menu = QMenu()
        menu.addAction(_('Open 3D Cover'), self.show_dialog)
        menu.addSeparator()
        menu.addAction(_('Show books with generated covers'), self._filter_with_covers)
        menu.addAction(_('Show books without generated covers'), self._filter_without_covers)
        menu.addSeparator()
        menu.addAction(_('About {0}').format(_('3D Cover')), self._show_about)
        self.qaction.setMenu(menu)

    def _show_about(self):
        from calibre_plugins.cover3d.support import show_about
        show_about(self.gui, self.interface_action_base_plugin)

    def location_selected(self, loc):
        self.qaction.setEnabled(loc == 'library')

    def _get_book_ids_with_covers(self):
        db = self.gui.current_db.new_api
        with_covers = set()
        for bid in db.all_book_ids():
            try:
                files = db.list_extra_files(bid, pattern="data/original_cover.*")
                if files:
                    with_covers.add(bid)
            except Exception:
                pass
        return with_covers

    def _build_id_search(self, ids):
        return ' or '.join(f'id:{bid}' for bid in sorted(ids))

    def _filter_with_covers(self):
        with_covers = self._get_book_ids_with_covers()
        if not with_covers:
            return error_dialog(self.gui, _('No books'), _('No books with generated covers found.'), show=True)
        self.gui.library_view.search_proxy(self._build_id_search(with_covers))

    def _filter_without_covers(self):
        with_covers = self._get_book_ids_with_covers()
        db = self.gui.current_db.new_api
        without = sorted(bid for bid in db.all_book_ids() if bid not in with_covers)
        if not without:
            return error_dialog(self.gui, _('No books'), _('All books have generated covers.'), show=True)
        self.gui.library_view.search_proxy(self._build_id_search(without))

    def show_dialog(self):
        from calibre_plugins.cover3d.main import HardcoverDialog, LibraryLoadWorker

        loading = LoadingDialog(self.gui)
        loading.show()

        db = self.gui.current_db.new_api
        model = self.gui.library_view.model()
        self._load_worker = LibraryLoadWorker(model, db)
        
        # Aquí usamos .format() externo para que la plantilla de traducción quede limpia como "Loading library... {cur}/{total}"
        self._load_worker.progress.connect(
            lambda cur, total: loading.label.setText(_("Loading library... {cur}/{total}").format(cur=cur, total=total))
        )
        self._load_worker.finished.connect(lambda ids, originals: self._on_library_loaded(ids, originals, loading))
        self._load_worker.start()

    def _on_library_loaded(self, all_book_ids, books_with_originals, loading):
        loading.close()
        from calibre_plugins.cover3d.main import HardcoverDialog
        d = HardcoverDialog(self.gui, self.icon, all_book_ids, books_with_originals)
        d.exec()
