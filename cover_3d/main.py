from io import BytesIO

try:
    load_translations()
except NameError:
    pass
    
from qt.core import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QProgressBar, QWidget, QMessageBox,
    Qt, QImage, QPixmap, QThread, QSizePolicy,
    pyqtSignal, QShortcut, QKeySequence, QComboBox, QColorDialog, QColor,
    QSpinBox, QTimer
)
from calibre.gui2 import error_dialog, info_dialog
from calibre.utils.config import JSONConfig

from calibre_plugins.cover3d.compositor import generate_cover, DEFAULT_ANGLE, DEFAULT_TOP

PREVIEW_W = 260
PREVIEW_H = 380

STYLE_NAV = "QPushButton { font-weight: bold; padding: 4px 8px; }"
STYLE_PREVIEW = "border: 1px solid #e0e0e0;"


prefs = JSONConfig('plugins/3d_cover')
prefs.defaults['bg_mode'] = 'grid'          # 'grid', 'details', 'custom' o 'transparent'
prefs.defaults['bg_color'] = [80, 80, 80]
prefs.defaults['size'] = 800              # ancho en px; 0 = tamaño original
prefs.defaults['angle'] = DEFAULT_ANGLE   # grados de giro del libro
prefs.defaults['top'] = DEFAULT_TOP       # canto superior visible
prefs.defaults['shadow'] = True
prefs.defaults['spine'] = 'black'        # 'black' o 'cover'
prefs.defaults['binding'] = 'soft'       # 'soft' (tapa blanda) o 'hard' (tapa dura)

SIZES = ((500, 'Normal'), (800, 'Large'), (1200, 'Extra large'), (0, 'Original'))


def grid_background_color():
    """Color de fondo de la cuadrícula de portadas de calibre (tema actual)."""
    try:
        from calibre.gui2 import resolve_grid_color, is_dark_theme
        c = resolve_grid_color(for_dark=is_dark_theme())
        return tuple(int(x) for x in c[:3])
    except Exception:
        pass
    try:  # versiones antiguas de calibre
        from calibre.gui2 import gprefs
        c = gprefs.get('cover_grid_color', None)
        if c:
            return tuple(int(x) for x in c[:3])
    except Exception:
        pass
    return (80, 80, 80)


def _png_has_alpha(data):
    # Byte 25 del PNG = tipo de color del encabezado IHDR (4 = gris+alfa, 6 = RGBA)
    return data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) > 25 and data[25] in (4, 6)


def set_cover_keep_alpha(db, bid, data):
    """Guarda la portada. Si la imagen es un PNG con transparencia, la escribe
    tal cual en cover.jpg (sin convertirla a JPEG), para que el fondo quede
    realmente transparente en el panel de detalles. calibre detecta el formato
    por el contenido, no por la extensión."""
    db.set_cover({bid: data})  # registra la portada y actualiza cachés/campos
    if not _png_has_alpha(data):
        return
    import os
    with db.write_lock:
        path = db._field_for('path', bid)
        try:
            db.backend.set_cover(bid, path, data, no_processing=True)
        except TypeError:  # calibre muy antiguo sin no_processing
            with open(os.path.join(db.backend.library_path, path, 'cover.jpg'), 'wb') as f:
                f.write(data)
        for cc in getattr(db, 'cover_caches', ()):
            try:
                cc.invalidate({bid: data})
            except Exception:
                pass


def refresh_cover_browser(gui):
    """El explorador de portadas guarda sus propias imágenes en memoria y no se
    entera de que la portada cambió: hay que pedirle que las vuelva a cargar."""
    try:
        gui.refresh_cover_browser()
        return
    except Exception:
        pass
    cf = getattr(gui, 'cover_flow', None)
    for meth in ('dataChanged', 'clearCaches'):
        try:
            getattr(cf, meth)()
            return
        except Exception:
            pass


def _most_common_color(img, points):
    from collections import Counter
    cols = []
    for x, y in points:
        if 0 <= x < img.width() and 0 <= y < img.height():
            c = img.pixelColor(x, y)
            cols.append((c.red(), c.green(), c.blue()))
    if not cols:
        return None
    return Counter(cols).most_common(1)[0][0]


def details_background_color(gui):
    """Color real del fondo del panel de detalles del libro, tal como se ve
    en pantalla (respeta temas y hojas de estilo personalizadas)."""
    bd = getattr(gui, 'book_details', None)
    if bd is None:
        return None
    # 1) El área de texto del panel: sus esquinas son siempre fondo.
    try:
        bi = bd.book_info
        img = bi.grab().toImage()
        w, h = img.width(), img.height()
        if w > 40 and h > 20:
            pts = [(3, 3), (4, 6), (w // 2, 2), (w - 30, 3), (3, h - 4), (w - 30, h - 4)]
            c = _most_common_color(img, pts)
            if c:
                return c
    except Exception:
        pass
    # 2) Paleta del panel.
    try:
        from qt.core import QPalette
        c = bd.palette().color(QPalette.ColorRole.Window)
        return (c.red(), c.green(), c.blue())
    except Exception:
        return None


def _pixmap_from_bytes(data):
    img = QImage()
    img.loadFromData(data)
    return QPixmap.fromImage(img)


class LibraryLoadWorker(QThread):
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(list, set)  # all_book_ids, books_with_originals

    def __init__(self, model, db):
        super().__init__()
        self.model = model
        self.db = db

    def run(self):
        try:
            try:
                row_count = self.model.rowCount()
            except TypeError:
                from PyQt5.QtCore import QModelIndex
                row_count = self.model.rowCount(QModelIndex())

            all_book_ids = [self.model.id(row) for row in range(row_count)]

            books_with_originals = set()
            total = len(all_book_ids)
            for i, bid in enumerate(all_book_ids):
                try:
                    files = self.db.list_extra_files(bid, pattern="data/original_cover.*")
                    if files:
                        books_with_originals.add(bid)
                except Exception:
                    pass
                self.progress.emit(i + 1, total)

            self.finished.emit(all_book_ids, books_with_originals)
        except Exception:
            self.finished.emit([], set())


class GenerateWorker(QThread):
    finished = pyqtSignal(bytes)
    error = pyqtSignal(str)

    def __init__(self, cover_bytes, pixel_ratio, rtl, fmt, background=None, width=None, style=None):
        super().__init__()
        self.style = style or {}
        self.width = width
        self.background = background
        self.cover_bytes = cover_bytes
        self.pixel_ratio = pixel_ratio
        self.rtl = rtl
        self.fmt = fmt

    def run(self):
        try:
            result = generate_cover(
                self.cover_bytes,
                pixel_ratio=self.pixel_ratio,
                rtl=self.rtl,
                fmt=self.fmt,
                background=self.background,
                width=self.width,
                **self.style
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class HardcoverDialog(QDialog):

    def __init__(self, gui, icon, all_book_ids=None, books_with_originals=None):
        super().__init__(gui)
        self.gui = gui
        self.db = gui.current_db.new_api
        self.results = {}
        self.worker = None
        self._generated_only = False
        self._all_book_ids = []
        self._nav_book_ids = []
        self._batch_stopped = False
        self._active_batch = None  # 'generate', 'apply', or 'restore'

        self.setWindowTitle(_("3D Cover"))
        self.setMinimumSize(1100, 680)
        self.setWindowIcon(icon)

        QShortcut(QKeySequence(Qt.Key.Key_Left), self, self._prev_book)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, self._next_book)

        if all_book_ids is not None:
            all_book_ids = list(all_book_ids)
            self._books_with_originals = set(books_with_originals or set())
        else:
            model = gui.library_view.model()
            try:
                row_count = model.rowCount()
            except TypeError:
                from PyQt5.QtCore import QModelIndex
                row_count = model.rowCount(QModelIndex())
            all_book_ids = [model.id(row) for row in range(row_count)]
            self._books_with_originals = set()
            for bid in all_book_ids:
                try:
                    files = self.db.list_extra_files(bid, pattern="data/original_cover.*")
                    if files:
                        self._books_with_originals.add(bid)
                except Exception:
                    pass

        self.selected_ids = gui.library_view.get_selected_ids()

        self.multi_select = len(self.selected_ids) > 1

        if self.multi_select:
            self.book_ids = [bid for bid in self.selected_ids if bid in all_book_ids]
            self.current_book_index = 0
        else:
            self.book_ids = all_book_ids
            if self.selected_ids and self.selected_ids[0] in self.book_ids:
                self.current_book_index = self.book_ids.index(self.selected_ids[0])
            else:
                self.current_book_index = 0

        self._all_book_ids = list(self.book_ids)
        self._nav_book_ids = self._all_book_ids

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 10)
        layout.setSpacing(0)

        # Settings row (fixed position)
        opts_widget = QWidget()
        opts_widget.setFixedHeight(40)
        opts = QHBoxLayout(opts_widget)
        opts.setContentsMargins(5, 5, 5, 5)
        self.rtl_cb = QCheckBox(_("RTL Spine"))
        self.rtl_cb.setToolTip(_("Right-to-left spine for Persian, Arabic, Hebrew books"))
        self.rtl_cb.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        opts.addWidget(self.rtl_cb)

        self.save_cb = QCheckBox(_("Save original before replacing"))
        self.save_cb.setChecked(True)
        self.save_cb.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        opts.addWidget(self.save_cb)

        opts.addSpacing(12)
        opts.addWidget(QLabel(_("Size:")))
        self.size_combo = QComboBox()
        size_names = {500: _('Normal'), 800: _('Large'), 1200: _('Extra large'), 0: _('Original')}
        for w, _n in SIZES:
            label = size_names[w] + (f' ({w} px)' if w else '')
            self.size_combo.addItem(label, w)
        self.size_combo.setToolTip(_(
            "Width of the generated cover. Larger sizes look sharper\n"
            "in the cover grid and the book details panel."))
        self.size_combo.setCurrentIndex(max(0, self.size_combo.findData(prefs['size'])))
        self.size_combo.currentIndexChanged.connect(
            lambda: prefs.__setitem__('size', self.size_combo.currentData()))
        self.size_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        opts.addWidget(self.size_combo)

        opts.addSpacing(12)
        opts.addWidget(QLabel(_("Background:")))
        self.bg_combo = QComboBox()
        self.bg_combo.addItem(_("Cover grid color"), 'grid')
        self.bg_combo.addItem(_("Book details panel color"), 'details')
        self.bg_combo.addItem(_("Custom color"), 'custom')
        self.bg_combo.addItem(_("Transparent (details panel)"), 'transparent')
        self.bg_combo.setToolTip(_(
            "calibre always stores covers as JPEG, which has no transparency.\n"
            "The background is filled with this color so it blends with the cover grid.\n\n"
            "Transparent: the cover is saved as PNG so the book details panel shows\n"
            "through it. In the cover grid the background may look dark, because\n"
            "calibre caches grid thumbnails without transparency."))
        self.bg_combo.setCurrentIndex(max(0, self.bg_combo.findData(prefs['bg_mode'])))
        self.bg_combo.currentIndexChanged.connect(self._bg_mode_changed)
        self.bg_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        opts.addWidget(self.bg_combo)
        self.bg_btn = QPushButton()
        self.bg_btn.setFixedSize(28, 22)
        self.bg_btn.setToolTip(_("Choose background color"))
        self.bg_btn.clicked.connect(self._choose_bg_color)
        opts.addWidget(self.bg_btn)
        self._refresh_bg_button()

        self.unapplied_label = QLabel()
        self.unapplied_label.setStyleSheet("color: #666; font-size: 11px;")

        self.show_generated_btn = QPushButton(_("Show me"))
        self.show_generated_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.show_generated_btn.setMinimumHeight(30)
        self.show_generated_btn.setVisible(False)
        self.show_generated_btn.clicked.connect(self._toggle_generated_only)

        opts.addStretch()
        layout.addWidget(opts_widget)
        # Aviso visible del modo transparente: calibre guarda las miniaturas de la
        # cuadrícula sin transparencia (PPM), así que el fondo se ve negro allí
        self.transparent_warning = QLabel(_(
            "⚠ Transparent background: the book details panel shows through it, but in the "
            "cover grid and the cover browser the background will look BLACK, because calibre "
            "stores their thumbnails without transparency. To avoid it, choose \"Cover grid color\"."))
        self.transparent_warning.setWordWrap(True)
        self.transparent_warning.setStyleSheet("color: #b35900; padding: 2px 8px 6px 8px;")
        self.transparent_warning.setVisible(prefs['bg_mode'] == 'transparent')
        layout.addWidget(self.transparent_warning)

        # Segunda fila: forma del libro (ángulo, canto superior, sombra)
        shape_widget = QWidget()
        shape_widget.setFixedHeight(40)
        shape = QHBoxLayout(shape_widget)
        shape.setContentsMargins(5, 0, 5, 5)
        shape.addWidget(QLabel(_("Angle:")))
        self.angle_sb = QSpinBox()
        self.angle_sb.setRange(0, 60)
        self.angle_sb.setSuffix('°')
        self.angle_sb.setToolTip(_(
            "How much the book is turned. 0° = seen from the front.\n"
            "Smaller angles make the cover fill more space."))
        self.angle_sb.setValue(int(prefs['angle']))
        shape.addWidget(self.angle_sb)
        shape.addSpacing(12)
        shape.addWidget(QLabel(_("Top edge:")))
        self.top_sb = QSpinBox()
        self.top_sb.setRange(0, 40)
        self.top_sb.setToolTip(_("How much of the top of the pages is visible. 0 = none.\n"
            "It grows or shrinks together with the angle."))
        self.top_sb.setValue(int(prefs['top']))
        shape.addWidget(self.top_sb)
        shape.addSpacing(12)
        self.shadow_cb = QCheckBox(_("Shadow"))
        self.shadow_cb.setToolTip(_("Without shadow the book fills more of the image."))
        self.shadow_cb.setChecked(bool(prefs['shadow']))
        shape.addWidget(self.shadow_cb)
        shape.addSpacing(12)
        shape.addWidget(QLabel(_("Spine:")))
        self.spine_combo = QComboBox()
        self.spine_combo.addItem(_("Black"), 'black')
        self.spine_combo.addItem(_("Cover color"), 'cover')
        self.spine_combo.addItem(_("Title and author"), 'title')
        self.spine_combo.addItem(_("Stretched from cover"), 'stretch')
        self.spine_combo.setToolTip(_("Color of the book spine. 'Cover color' takes the\n"
                                      "color of the cover edge on the spine side.\n"
                                      "'Title and author': that color, with the title and the author\n"
                                      "written along the spine.\n"
                                      "'Stretched from cover': the edge of the cover stretched over\n"
                                      "the spine, so the picture seems to continue around the book.\n"
                                      "Both look best with a thick book."))
        self.spine_combo.setCurrentIndex(max(0, self.spine_combo.findData(prefs['spine'])))
        self.spine_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        shape.addWidget(self.spine_combo)
        shape.addSpacing(12)
        shape.addWidget(QLabel(_("Binding:")))
        self.binding_combo = QComboBox()
        self.binding_combo.addItem(_("Paperback"), 'soft')
        self.binding_combo.addItem(_("Hardcover"), 'hard')
        self.binding_combo.addItem(_("Thick book"), 'thick')
        self.binding_combo.setToolTip(_("Hardcover: the boards stick out past the pages and\n"
                                        "the spine is a bit thicker and rounded.\n"
                                        "Thick book: a thick paperback with a wide spine, like a\n"
                                        "printed book photographed in a shop. Try it with a small\n"
                                        "angle and the spine 'Title and author'."))
        self.binding_combo.setCurrentIndex(max(0, self.binding_combo.findData(prefs['binding'])))
        self.binding_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        shape.addWidget(self.binding_combo)
        shape.addSpacing(12)
        reset_btn = QPushButton(_("Reset"))
        reset_btn.setToolTip(_("Restore the default book shape"))
        reset_btn.clicked.connect(self._reset_shape)
        shape.addWidget(reset_btn)
        shape.addStretch()
        layout.addWidget(shape_widget)

        # Vista previa en vivo: al cambiar una opción se regenera la portada
        # del libro actual (si ya estaba generada).
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(350)
        self._preview_timer.timeout.connect(self._live_regenerate)
        self.angle_sb.valueChanged.connect(self._shape_changed)
        self.top_sb.valueChanged.connect(self._shape_changed)
        self.shadow_cb.toggled.connect(self._shape_changed)
        self.spine_combo.currentIndexChanged.connect(self._shape_changed)
        self.binding_combo.currentIndexChanged.connect(self._shape_changed)
        self.rtl_cb.toggled.connect(lambda: self._preview_timer.start())
        self.size_combo.currentIndexChanged.connect(lambda: self._preview_timer.start())
        self.bg_combo.currentIndexChanged.connect(lambda: self._preview_timer.start())

        # Preview area
        preview = QHBoxLayout()
        preview.setSpacing(20)
        preview.setContentsMargins(30, 10, 30, 10)

        left = QVBoxLayout()
        left.addWidget(QLabel(_("Original")), alignment=Qt.AlignmentFlag.AlignCenter)
        self.orig_label = QLabel()
        self.orig_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.orig_label.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.orig_label.setStyleSheet(STYLE_PREVIEW)
        left.addWidget(self.orig_label)
        preview.addLayout(left)

        right = QVBoxLayout()
        right.addWidget(QLabel(_("Generated")), alignment=Qt.AlignmentFlag.AlignCenter)
        self.gen_label = QLabel()
        self.gen_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gen_label.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.gen_label.setStyleSheet(STYLE_PREVIEW)
        right.addWidget(self.gen_label)
        preview.addLayout(right)

        layout.addLayout(preview)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        layout.addSpacing(24)

        # Navigation row
        nav = QHBoxLayout()
        nav.setSpacing(4)

        self.first_btn = QPushButton("|<")
        self.first_btn.setFixedWidth(36)
        self.first_btn.setStyleSheet(STYLE_NAV)
        self.first_btn.setToolTip(_("First Book"))
        self.first_btn.clicked.connect(self._first_book)
        nav.addWidget(self.first_btn)

        self.prev_btn = QPushButton("<")
        self.prev_btn.setFixedWidth(36)
        self.prev_btn.setStyleSheet(STYLE_NAV)
        self.prev_btn.setToolTip(_("Previous Book"))
        self.prev_btn.clicked.connect(self._prev_book)
        nav.addWidget(self.prev_btn)

        nav_center = QVBoxLayout()
        self.book_label = QLabel()
        self.book_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_center.addWidget(self.book_label)
        self.book_count_label = QLabel()
        self.book_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.book_count_label.setStyleSheet("color: #666; font-size: 11px;")
        nav_center.addWidget(self.book_count_label)
        nav.addLayout(nav_center, 1)

        self.next_btn = QPushButton(">")
        self.next_btn.setFixedWidth(36)
        self.next_btn.setStyleSheet(STYLE_NAV)
        self.next_btn.setToolTip(_("Next Book"))
        self.next_btn.clicked.connect(self._next_book)
        nav.addWidget(self.next_btn)

        self.last_btn = QPushButton(">|")
        self.last_btn.setFixedWidth(36)
        self.last_btn.setStyleSheet(STYLE_NAV)
        self.last_btn.setToolTip(_("Last Book"))
        self.last_btn.clicked.connect(self._last_book)
        nav.addWidget(self.last_btn)
        layout.addLayout(nav)

        # Spacing between navigation and buttons
        layout.addSpacing(16)

        # Action buttons
        btns = QHBoxLayout()
        self.gen_btn = QPushButton(_("Generate"))
        self.gen_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.gen_btn.setMinimumHeight(30)
        self.gen_btn.clicked.connect(self._generate)
        btns.addWidget(self.gen_btn)

        self.apply_btn = QPushButton(_("Apply"))
        self.apply_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.apply_btn.setMinimumHeight(30)
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        btns.addWidget(self.apply_btn)

        self.clear_btn = QPushButton(_("Clear"))
        self.clear_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.clear_btn.setMinimumHeight(30)
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self._clear)
        btns.addWidget(self.clear_btn)

        self.restore_btn = QPushButton(_("Restore"))
        self.restore_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.restore_btn.setMinimumHeight(30)
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self._restore)
        btns.addWidget(self.restore_btn)

        self.gen_all_btn = QPushButton(_("Generate All"))
        self.gen_all_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.gen_all_btn.setMinimumHeight(30)
        self.gen_all_btn.setVisible(self.multi_select)
        self.gen_all_btn.clicked.connect(self._generate_all)
        btns.addWidget(self.gen_all_btn)

        self.apply_all_btn = QPushButton(_("Apply All"))
        self.apply_all_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.apply_all_btn.setMinimumHeight(30)
        self.apply_all_btn.setVisible(False)
        self.apply_all_btn.clicked.connect(self._apply_all)
        btns.addWidget(self.apply_all_btn)

        self.clear_all_btn = QPushButton(_("Clear All"))
        self.clear_all_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.clear_all_btn.setMinimumHeight(30)
        self.clear_all_btn.setVisible(False)
        self.clear_all_btn.clicked.connect(self._clear_all)
        btns.addWidget(self.clear_all_btn)

        self.restore_all_btn = QPushButton(_("Restore All"))
        self.restore_all_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.restore_all_btn.setMinimumHeight(30)
        self.restore_all_btn.setVisible(self.multi_select)
        self.restore_all_btn.clicked.connect(self._restore_all)
        btns.addWidget(self.restore_all_btn)

        btns.addSpacing(12)
        btns.addWidget(self.unapplied_label)
        btns.addWidget(self.show_generated_btn)
        btns.addStretch()
        about_btn = QPushButton(_("About"))
        about_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        about_btn.setMinimumHeight(30)
        about_btn.clicked.connect(self._show_about)
        btns.addWidget(about_btn)
        self.stop_btn = QPushButton(_("Stop"))
        self.stop_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.stop_btn.setMinimumHeight(30)
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._stop_batch)
        btns.addWidget(self.stop_btn)
        cancel = QPushButton(_("Cancel"))
        cancel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        cancel.setMinimumHeight(30)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        layout.addLayout(btns)
        layout.addSpacing(10)

        self._update_all_buttons()
        self._load_current_book()

    def _show_about(self):
        from calibre_plugins.cover3d import Cover3DPlugin
        from calibre_plugins.cover3d.support import show_about
        show_about(self, Cover3DPlugin)

    def _book_style(self, bid):
        """Forma del libro más el título y el autor (para el lomo)."""
        style = self._style()
        try:
            style['title'] = self.db.field_for('title', bid) or ''
            style['author'] = ' & '.join(self.db.field_for('authors', bid) or ())
        except Exception:
            pass
        return style

    def _style(self):
        return {
            'angle': self.angle_sb.value(),
            'top': self.top_sb.value(),
            'shadow': self.shadow_cb.isChecked(),
            'spine': self.spine_combo.currentData(),
            'binding': self.binding_combo.currentData(),
        }

    def _shape_changed(self):
        prefs['angle'] = self.angle_sb.value()
        prefs['top'] = self.top_sb.value()
        prefs['shadow'] = self.shadow_cb.isChecked()
        prefs['spine'] = self.spine_combo.currentData()
        prefs['binding'] = self.binding_combo.currentData()
        self._preview_timer.start()

    def _reset_shape(self):
        self.angle_sb.setValue(DEFAULT_ANGLE)
        self.top_sb.setValue(DEFAULT_TOP)
        self.shadow_cb.setChecked(True)
        self.spine_combo.setCurrentIndex(0)
        self.binding_combo.setCurrentIndex(0)

    def _live_regenerate(self):
        if self._active_batch:
            return
        if self.worker is not None and self.worker.isRunning():
            self._preview_timer.start()  # reintentar cuando termine
            return
        bid = self._current_book_id()
        if bid is not None and bid in self.results:
            self._generate()

    def _background(self):
        mode = self.bg_combo.currentData()
        if mode == 'transparent':
            return None
        if mode == 'custom':
            return tuple(prefs['bg_color'][:3])
        if mode == 'details':
            c = details_background_color(self.gui)
            if c:
                return tuple(c)
        return grid_background_color()

    def _refresh_bg_button(self):
        if self.bg_combo.currentData() == 'transparent':
            self.bg_btn.setStyleSheet(
                "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                "stop:0 #fff, stop:0.49 #fff, stop:0.5 #ccc, stop:1 #ccc); border: 1px solid #888; }")
            self.bg_btn.setEnabled(False)
            return
        r, g, b = self._background()
        self.bg_btn.setStyleSheet(
            f"QPushButton {{ background-color: rgb({r},{g},{b}); border: 1px solid #888; }}")
        self.bg_btn.setEnabled(self.bg_combo.currentData() == 'custom')

    def _bg_mode_changed(self):
        prefs['bg_mode'] = self.bg_combo.currentData()
        self._refresh_bg_button()
        self.transparent_warning.setVisible(self.bg_combo.currentData() == 'transparent')

    def _choose_bg_color(self):
        c = QColorDialog.getColor(QColor(*self._background()), self, _("Background color"))
        if c.isValid():
            prefs['bg_color'] = [c.red(), c.green(), c.blue()]
            self._refresh_bg_button()

    def _current_book_id(self):
        if 0 <= self.current_book_index < len(self._nav_book_ids):
            return self._nav_book_ids[self.current_book_index]
        return None

    def _update_nav(self):
        total = len(self._nav_book_ids)
        idx = self.current_book_index
        self.first_btn.setEnabled(idx > 0)
        self.prev_btn.setEnabled(idx > 0)
        self.next_btn.setEnabled(idx < total - 1)
        self.last_btn.setEnabled(idx < total - 1)

    def _toggle_generated_only(self):
        self._generated_only = not self._generated_only
        if self._generated_only:
            generated = [bid for bid in self._all_book_ids if bid in self.results]
            if not generated:
                self._generated_only = False
                return
            self._saved_index = self.current_book_index
            self._nav_book_ids = generated
            self.current_book_index = 0
            self.show_generated_btn.setText(_("Show All"))
        else:
            self._nav_book_ids = self._all_book_ids
            self.current_book_index = getattr(self, '_saved_index', 0)
            self.show_generated_btn.setText(_("Show me"))
        self._update_all_buttons()
        self._load_current_book()

    def _update_all_buttons(self):
        need_generate = [
            bid for bid in self._all_book_ids
            if bid not in self._books_with_originals and bid not in self.results
        ]
        restore_count = len([b for b in self._all_book_ids if b in self._books_with_originals])
        has_results = len(self.results) > 0
        need_count = len(need_generate)

        self.gen_all_btn.setEnabled(self.multi_select and need_count > 0 and not self._generated_only)
        self.gen_all_btn.setVisible(self.multi_select and not self._generated_only)
        self.gen_all_btn.setText(_("Generate {need_count} Covers").format(need_count=need_count))

        self.restore_all_btn.setEnabled(self.multi_select and restore_count > 0)
        self.restore_all_btn.setVisible(self.multi_select and restore_count > 0)
        self.restore_all_btn.setText(_("Restore {restore_count} Covers").format(restore_count=restore_count))

        show_batch = self.multi_select or (self._generated_only and len(self.results) > 1)

        self.apply_all_btn.setEnabled(show_batch and has_results)
        self.apply_all_btn.setVisible(show_batch and has_results)
        self.apply_all_btn.setText(_("Apply {count} Covers").format(count=len(self.results)))

        self.clear_all_btn.setEnabled(show_batch and has_results)
        self.clear_all_btn.setVisible(show_batch and has_results)

        unapplied = len(self.results)
        if unapplied > 0:
            self.unapplied_label.setText(_("There are {unapplied} unapplied cover(s)").format(unapplied=unapplied))
            self.show_generated_btn.setVisible(True)
        else:
            self.unapplied_label.setText("")
            self.show_generated_btn.setVisible(False)
            self.show_generated_btn.setText(_("Show me"))
            if self._generated_only:
                self._generated_only = False
                self._nav_book_ids = self._all_book_ids
                self.current_book_index = getattr(self, '_saved_index', 0)
                self._load_current_book()

    def _first_book(self):
        if self._nav_book_ids:
            self.current_book_index = 0
            self._load_current_book()

    def _prev_book(self):
        if self.current_book_index > 0:
            self.current_book_index -= 1
            self._load_current_book()

    def _next_book(self):
        if self.current_book_index < len(self._nav_book_ids) - 1:
            self.current_book_index += 1
            self._load_current_book()

    def _last_book(self):
        if self._nav_book_ids:
            self.current_book_index = len(self._nav_book_ids) - 1
            self._load_current_book()

    def _load_current_book(self):
        bid = self._current_book_id()
        if bid is None:
            return

        self.gen_label.clear()
        self.gen_btn.setEnabled(True)
        self.apply_btn.setEnabled(bid in self.results)
        self.clear_btn.setEnabled(bid in self.results)

        title = self.db.field_for("title", bid) or _("Unknown")
        self.book_label.setText(title)

        total = len(self._nav_book_ids)
        idx = self.current_book_index
        if self._generated_only:
            self.book_count_label.setText(_("{current} of {total} generated").format(current=idx + 1, total=total))
        else:
            self.book_count_label.setText(_("{current} of {total} books").format(current=idx + 1, total=total))

        cover = self.db.cover(bid)
        if cover:
            pm = _pixmap_from_bytes(cover)
            self.orig_label.setPixmap(pm.scaled(
                PREVIEW_W - 20, PREVIEW_H - 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self.orig_label.setText(_("No cover"))

        if bid in self.results:
            pm = _pixmap_from_bytes(self.results[bid])
            self.gen_label.setPixmap(pm.scaled(
                PREVIEW_W - 20, PREVIEW_H - 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            self.apply_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)

        has_original = bid in self._books_with_originals
        self.restore_btn.setEnabled(has_original)
        self.restore_btn.setVisible(has_original)

        self._update_all_buttons()
        self._update_nav()

    def _generate(self):
        bid = self._current_book_id()
        if bid is None:
            return

        cover = self.db.cover(bid)
        if not cover:
            return error_dialog(self, _("No Cover"), _("This book has no cover."), show=True)

        self.gen_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)

        self.worker = GenerateWorker(
            cover,
            pixel_ratio=1,
            rtl=self.rtl_cb.isChecked(),
            fmt='jpg',
            background=self._background(),
            width=self.size_combo.currentData(),
            style=self._book_style(bid),
        )
        self.worker.finished.connect(self._on_generated)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_generated(self, result):
        bid = self._current_book_id()
        if bid is None:
            return

        self.results[bid] = result
        pm = _pixmap_from_bytes(result)
        self.gen_label.setPixmap(pm.scaled(
            PREVIEW_W - 20, PREVIEW_H - 20,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        self.gen_btn.setEnabled(True)
        self.apply_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        if self._generated_only and bid not in self._nav_book_ids:
            self._nav_book_ids.append(bid)
        self._update_all_buttons()
        self.progress.setVisible(False)

    def _on_error(self, msg):
        self.progress.setVisible(False)
        self.gen_btn.setEnabled(True)
        error_dialog(self, _("Error"), msg, show=True)

    def _clear(self):
        bid = self._current_book_id()
        if bid is None:
            return
        self.results.pop(bid, None)
        self.gen_label.clear()
        self.apply_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        if self._generated_only:
            self._nav_book_ids = [b for b in self._nav_book_ids if b != bid]
            if not self._nav_book_ids:
                self._generated_only = False
                self._nav_book_ids = self._all_book_ids
                self.current_book_index = getattr(self, '_saved_index', 0)
            elif self.current_book_index >= len(self._nav_book_ids):
                self.current_book_index = len(self._nav_book_ids) - 1
        self._update_all_buttons()
        self._load_current_book()

    def _clear_all(self):
        self.results.clear()
        self.gen_label.clear()
        self.apply_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        if self._generated_only:
            self._generated_only = False
            self._nav_book_ids = self._all_book_ids
            self.current_book_index = getattr(self, '_saved_index', 0)
        self._update_all_buttons()
        self._load_current_book()

    def _apply(self):
        bid = self._current_book_id()
        if bid is None or bid not in self.results:
            return

        if self.save_cb.isChecked():
            try:
                cover = self.db.cover(bid)
                if cover:
                    self.db.add_extra_files(bid, {
                        "data/original_cover.jpg": BytesIO(cover),
                    }, replace=True)
                    self._books_with_originals.add(bid)
            except Exception:
                pass

        try:
            set_cover_keep_alpha(self.db, bid, self.results[bid])
            self.gui.library_view.model().refresh_ids([bid])
            refresh_cover_browser(self.gui)
        except Exception as e:
            return error_dialog(self, _("Error"), str(e), show=True)

        info_dialog(self, _("Done"), _("Cover applied."), show=True)
        self.apply_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.results.pop(bid, None)
        self._load_current_book()

    def _apply_all(self):
        if not self.results:
            return

        batch = [bid for bid in self._all_book_ids if bid in self.results]
        if not batch:
            return info_dialog(self, _("Nothing to apply"), _("No generated covers for selected books."), show=True)

        self._batch_stopped = False
        self._active_batch = 'apply'
        self.stop_btn.setVisible(True)
        self.apply_all_btn.setEnabled(False)
        self.restore_all_btn.setEnabled(False)
        self.clear_all_btn.setEnabled(False)

        self.progress.setVisible(True)
        self.progress.setRange(0, len(batch))
        self.progress.setValue(0)

        from qt.core import QApplication
        applied = 0
        for i, bid in enumerate(batch):
            if self._batch_stopped:
                break
            self.progress.setValue(i)
            QApplication.processEvents()

            if self.save_cb.isChecked():
                try:
                    cover = self.db.cover(bid)
                    if cover:
                        self.db.add_extra_files(bid, {
                            "data/original_cover.jpg": BytesIO(cover),
                        }, replace=True)
                        self._books_with_originals.add(bid)
                except Exception:
                    pass

            try:
                set_cover_keep_alpha(self.db, bid, self.results[bid])
                applied += 1
            except Exception:
                continue

        self.progress.setValue(len(batch))
        QApplication.processEvents()

        for bid in batch:
            self.results.pop(bid, None)

        self.gui.library_view.model().refresh_ids(batch)
        refresh_cover_browser(self.gui)
        self.progress.setVisible(False)
        self.stop_btn.setVisible(False)
        self._active_batch = None
        self._update_all_buttons()
        self._load_current_book()
        if self._batch_stopped:
            info_dialog(self, _("Stopped"), _("Applied {applied}/{total} covers.").format(applied=applied, total=len(batch)), show=True)
        else:
            info_dialog(self, _("Done"), _("Applied {applied}/{total} covers.").format(applied=applied, total=len(batch)), show=True)

    def _generate_all(self):
        self._batch_queue = [
            bid for bid in self._all_book_ids
            if bid not in self.results and bid not in self._books_with_originals
        ]
        self._batch_stopped = False
        self._active_batch = 'generate'
        self.gen_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.gen_all_btn.setEnabled(False)
        self.apply_all_btn.setEnabled(False)
        self.restore_all_btn.setEnabled(False)
        self.clear_all_btn.setEnabled(False)
        self.stop_btn.setVisible(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(self._batch_queue))
        self.progress.setValue(0)

        self._batch_index = 0
        self._batch_generate_next()

    def _stop_batch(self):
        self._batch_stopped = True
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        if self._active_batch == 'generate':
            self._batch_generate_next()

    def _batch_generate_next(self):
        if self._batch_stopped or self._batch_index >= len(self._batch_queue):
            self.progress.setVisible(False)
            self.stop_btn.setVisible(False)
            self._active_batch = None
            self.gen_btn.setEnabled(True)
            self._update_all_buttons()
            self._load_current_book()
            count = self._batch_index
            if self._batch_stopped:
                info_dialog(self, _("Stopped"), _("Generated {count} covers.").format(count=count), show=True)
            else:
                info_dialog(self, _("Done"), _("Generated {count} covers.").format(count=count), show=True)
            return

        bid = self._batch_queue[self._batch_index]
        self.progress.setValue(self._batch_index)
        title = self.db.field_for("title", bid) or _("Unknown")
        self.book_label.setText(_("Generating {current}/{total}: {title}").format(current=self._batch_index + 1, total=len(self._batch_queue), title=title))

        cover = self.db.cover(bid)
        if not cover:
            self._batch_index += 1
            self._batch_generate_next()
            return

        self.worker = GenerateWorker(
            cover,
            pixel_ratio=1,
            rtl=self.rtl_cb.isChecked(),
            fmt='jpg',
            background=self._background(),
            width=self.size_combo.currentData(),
            style=self._book_style(bid),
        )
        self.worker.finished.connect(self._on_batch_done)
        self.worker.error.connect(self._on_batch_error)
        self.worker.start()

    def _on_batch_done(self, result):
        bid = self._batch_queue[self._batch_index]
        self.results[bid] = result
        self._batch_index += 1
        self._batch_generate_next()

    def _on_batch_error(self, msg):
        self._batch_index += 1
        self._batch_generate_next()

    def _restore(self):
        bid = self._current_book_id()
        if bid is None:
            return
        try:
            files = self.db.list_extra_files(bid, pattern="data/original_cover.*")
            if not files:
                return error_dialog(self, _("No Original"), _("No saved original found."), show=True)
            with open(files[0].file_path, "rb") as f:
                original = f.read()
            self.db.set_cover({bid: original})
            self.db.remove_extra_files(bid, [files[0].relpath])
            self.gui.library_view.model().refresh_ids([bid])
            refresh_cover_browser(self.gui)
            self.results.pop(bid, None)
            self._books_with_originals.discard(bid)
            self._load_current_book()
            info_dialog(self, _("Done"), _("Original restored."), show=True)
        except Exception as e:
            error_dialog(self, _("Error"), str(e), show=True)

    def _restore_all(self):
        batch = [bid for bid in self._all_book_ids if bid in self._books_with_originals]

        self._batch_stopped = False
        self._active_batch = 'restore'
        self.stop_btn.setVisible(True)
        self.apply_all_btn.setEnabled(False)
        self.restore_all_btn.setEnabled(False)
        self.clear_all_btn.setEnabled(False)

        self.progress.setVisible(True)
        self.progress.setRange(0, len(batch))
        self.progress.setValue(0)

        from qt.core import QApplication
        restored = 0
        for i, bid in enumerate(batch):
            if self._batch_stopped:
                break
            self.progress.setValue(i)
            QApplication.processEvents()
            try:
                files = self.db.list_extra_files(bid, pattern="data/original_cover.*")
                if not files:
                    continue
                with open(files[0].file_path, "rb") as f:
                    original = f.read()
                self.db.set_cover({bid: original})
                self.db.remove_extra_files(bid, [files[0].relpath])
                self.results.pop(bid, None)
                self._books_with_originals.discard(bid)
                restored += 1
            except Exception:
                continue

        self.progress.setValue(len(batch))
        QApplication.processEvents()
        self.progress.setVisible(False)
        self.stop_btn.setVisible(False)
        self._active_batch = None
        self.gui.library_view.model().refresh_ids(batch)
        refresh_cover_browser(self.gui)
        self._update_all_buttons()
        self._load_current_book()
        if self._batch_stopped:
            info_dialog(self, _("Stopped"), _("Restored {restored}/{total} covers.").format(restored=restored, total=len(batch)), show=True)
        else:
            info_dialog(self, _("Done"), _("Restored {restored}/{total} covers.").format(restored=restored, total=len(batch)), show=True)

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
        if self.results:
            msg = QMessageBox(self)
            msg.setWindowTitle(_("Unsaved Covers"))
            msg.setText(_("You have {count} unapplied generated cover(s).\nDiscard them?").format(count=len(self.results)))
            msg.setIcon(QMessageBox.Icon.Warning)
            discard_btn = msg.addButton(_("Discard"), QMessageBox.ButtonRole.AcceptRole)
            show_btn = msg.addButton(_("Show me"), QMessageBox.ButtonRole.RejectRole)
            msg.addButton(QMessageBox.StandardButton.Cancel)
            msg.setDefaultButton(discard_btn)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == discard_btn:
                pass
            elif clicked == show_btn:
                if not self._generated_only:
                    self._toggle_generated_only()
                return
            else:
                return
        super().reject()
