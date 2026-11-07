#!/usr/bin/env python
# Danmei Novel Finder — tienda y ventana de descarga

from html import escape
import os
import threading
import time

from qt.core import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QIcon, QLabel, QLineEdit, QMessageBox, QPixmap, QProgressBar,
    QPushButton, QSpinBox, QStandardPaths, Qt, QThread, QVBoxLayout, pyqtSignal,
    QColor, QListView, QListWidget, QListWidgetItem,
    QPainter, QSize, QSplitter, QTextBrowser, QTimer, QWidget,
)

from calibre.gui2.store import StorePlugin
from calibre.gui2.store.search_result import SearchResult

from calibre_plugins.DanmeiStore import PLUGIN_NAME, PLUGIN_VERSION
from calibre_plugins.DanmeiStore import site, builder

KOFI_URL = 'https://ko-fi.com/dunhill69'
PAYPAL_URL = 'https://paypal.me/Dunhill69'
VERSION_STR = '.'.join(map(str, PLUGIN_VERSION))


def resource_pixmap(name):
    pm = QPixmap()
    try:
        data = get_resources(name)  # noqa: F821 (lo inyecta calibre)
        if data:
            pm.loadFromData(data)
    except Exception:
        pass
    return pm


def plugin_icon():
    pm = resource_pixmap('images/icon.png')
    return QIcon(pm) if not pm.isNull() else QIcon()


# ------------------------------------------------------------------ tienda

class DanmeiStore(StorePlugin):

    def open(self, parent=None, detail_item=None, external=False):
        d = DanmeiDialog(self.gui, parent or self.gui, detail_item)
        d.exec()

    def search(self, query, max_results=10, timeout=60):
        for r in site.search(query, max_results=max_results, timeout=timeout):
            s = SearchResult()
            s.title = r['title']
            s.author = ' & '.join(r['authors'])
            s.cover_url = r['cover']
            s.detail_item = r['url']
            s.price = '$0.00'
            s.drm = SearchResult.DRM_UNLOCKED
            s.formats = 'EPUB, TXT'
            yield s

    def get_details(self, search_result, timeout):
        return True


# ------------------------------------------------------------------ hilos

class InfoWorker(QThread):
    done = pyqtSignal(object, object)   # info, bytes de portada
    failed = pyqtSignal(str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            info = site.novel_info(self.url)
            cover = None
            if info.get('cover_url'):
                try:
                    cover = site.download_bytes(info['cover_url'])
                except Exception:
                    cover = None
            self.done.emit(info, cover)
        except Exception as e:
            self.failed.emit(str(e))


class DownloadWorker(QThread):
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(str, object)      # ruta, capítulos que fallaron
    failed = pyqtSignal(str)

    def __init__(self, info, chapters, cover, out_path, fmt, parent=None):
        super().__init__(parent)
        self.info, self.chapters, self.cover = info, chapters, cover
        self.out_path, self.fmt = out_path, fmt
        self.cancelled = False

    def run(self):
        try:
            br = site.make_browser()
            result, missing = [], []
            total = len(self.chapters)
            for i, (title, url) in enumerate(self.chapters, 1):
                if self.cancelled:
                    return
                self.progress.emit(i - 1, total, title)
                try:
                    paras = site.chapter_paragraphs(br, url)
                except Exception:
                    paras = []
                if paras:
                    result.append((title, paras))
                else:
                    missing.append(title)
                time.sleep(0.4)  # no saturar el sitio
            if self.cancelled:
                return
            if not result:
                self.failed.emit('No se pudo leer el texto de ningún capítulo.')
                return
            self.progress.emit(total, total, 'Armando el archivo…')
            if self.fmt == 'TXT':
                builder.build_txt(self.out_path, self.info, result)
            else:
                builder.build_epub(self.out_path, self.info, result, self.cover)
            self.done.emit(self.out_path, missing)
        except Exception as e:
            self.failed.emit(str(e))


class CatalogWorker(QThread):
    done = pyqtSignal(int, object, bool, object)   # pedido, novelas, hay_más, géneros
    failed = pyqtSignal(int, str)

    def __init__(self, req_id, mode, arg, order, page, parent=None):
        super().__init__(parent)
        self.req_id, self.mode, self.arg = req_id, mode, arg
        self.order, self.page = order, page

    def run(self):
        try:
            if self.mode == 'search':
                items, more = site.search_page(self.arg, self.page)
                genres = None
            else:
                items, more, genres = site.catalog_page(self.order, self.arg, self.page)
            self.done.emit(self.req_id, items, more, genres)
        except Exception as e:
            self.failed.emit(self.req_id, str(e))


class CoverLoader(QThread):
    """Baja las miniaturas de a una, en segundo plano."""
    loaded = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue = []
        self.stop = False
        self.mutex = threading.Lock()

    def add(self, urls):
        with self.mutex:
            self.queue.extend(urls)
        if not self.isRunning():
            self.start()

    def clear(self):
        with self.mutex:
            self.queue = []

    def run(self):
        br = site.make_browser()
        while not self.stop:
            with self.mutex:
                if not self.queue:
                    return
                url = self.queue.pop(0)
            try:
                data = site.fetch(br, url, timeout=20, retries=0)
            except Exception:
                data = None
            if data and not self.stop:
                self.loaded.emit(url, data)


THUMB_W, THUMB_H = 96, 140


class CatalogPanel(QWidget):
    chosen = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.req_id = 0
        self.page = 1
        self.mode = 'catalog'
        self.arg = None
        self.worker = None
        self.genres_loaded = False
        self.icons = {}          # url de portada -> QIcon
        self.waiting = {}        # url de portada -> [items]
        self.placeholder = self.make_placeholder()
        self.covers = CoverLoader(self)
        self.covers.loaded.connect(self.cover_loaded)

        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('Buscar por título…')
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.do_search)
        row.addWidget(self.search_edit, 1)
        b = QPushButton('Buscar')
        b.clicked.connect(self.do_search)
        row.addWidget(b)
        l.addLayout(row)

        row = QHBoxLayout()
        self.order_combo = QComboBox()
        for name, key in site.ORDERS:
            self.order_combo.addItem(name, key)
        self.order_combo.currentIndexChanged.connect(self.browse)
        row.addWidget(self.order_combo, 1)
        self.genre_combo = QComboBox()
        self.genre_combo.addItem('Todos los géneros', None)
        self.genre_combo.currentIndexChanged.connect(self.browse)
        row.addWidget(self.genre_combo, 1)
        l.addLayout(row)

        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(QSize(THUMB_W, THUMB_H))
        self.list.setGridSize(QSize(THUMB_W + 34, THUMB_H + 58))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(4)
        self.list.itemActivated.connect(self.item_chosen)
        self.list.verticalScrollBar().valueChanged.connect(self.maybe_more)
        l.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.info_lbl = QLabel('')
        row.addWidget(self.info_lbl, 1)
        self.more_btn = QPushButton('Cargar más')
        self.more_btn.clicked.connect(self.load_more)
        self.more_btn.setEnabled(False)
        row.addWidget(self.more_btn)
        l.addLayout(row)
        hint = QLabel('<small>Doble clic en una novela para cargarla.</small>')
        l.addWidget(hint)

    def make_placeholder(self):
        pm = QPixmap(THUMB_W, THUMB_H)
        pm.fill(QColor(200, 200, 200))
        icon = resource_pixmap('images/icon.png')
        if not icon.isNull():
            p = QPainter(pm)
            s = 48
            p.drawPixmap((THUMB_W - s) // 2, (THUMB_H - s) // 2,
                         icon.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
            p.end()
        return QIcon(pm)

    # ------------------------------------------------------ pedidos

    def start(self):
        if not self.list.count() and self.worker is None:
            self.browse()

    def browse(self):
        self.mode = 'catalog'
        self.arg = self.genre_combo.currentData()
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.reload()

    def do_search(self):
        q = self.search_edit.text().strip()
        if not q:
            self.browse()
            return
        self.mode, self.arg = 'search', q
        self.reload()

    def reload(self):
        self.page = 1
        self.list.clear()
        self.waiting.clear()
        self.covers.clear()
        self.request()

    def load_more(self):
        if self.worker is None and self.more_btn.isEnabled():
            self.page += 1
            self.request()

    def maybe_more(self, value):
        sb = self.list.verticalScrollBar()
        if value >= sb.maximum() - 20:
            self.load_more()

    def request(self):
        self.req_id += 1
        self.more_btn.setEnabled(False)
        self.info_lbl.setText('Cargando…')
        w = CatalogWorker(self.req_id, self.mode, self.arg,
                          self.order_combo.currentData(), self.page, self)
        w.done.connect(self.loaded)
        w.failed.connect(self.failed)
        w.finished.connect(w.deleteLater)
        self.worker = w
        w.start()

    def loaded(self, req_id, items, more, genres):
        if req_id != self.req_id:
            return  # respuesta de un pedido viejo
        self.worker = None
        if genres and not self.genres_loaded:
            self.genres_loaded = True
            self.genre_combo.blockSignals(True)
            for name, slug in genres:
                self.genre_combo.addItem(name, slug)
            self.genre_combo.blockSignals(False)
        existing = {self.list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.list.count())}
        new_covers = []
        for it in items:
            if it['url'] in existing:
                continue
            item = QListWidgetItem(self.placeholder, it['title'])
            item.setData(Qt.ItemDataRole.UserRole, it['url'])
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            tip = ['<b>%s</b>' % it['title']]
            if it.get('authors'):
                tip.append(' & '.join(it['authors']))
            if it.get('latest'):
                tip.append('Último: %s' % it['latest'])
            if it.get('score'):
                tip.append('Puntuación: %s' % it['score'])
            item.setToolTip('<br>'.join(tip))
            self.list.addItem(item)
            c = it.get('cover')
            if c:
                if c in self.icons:
                    item.setIcon(self.icons[c])
                else:
                    if c not in self.waiting:
                        new_covers.append(c)
                    self.waiting.setdefault(c, []).append(item)
        if new_covers:
            self.covers.add(new_covers)
        n = self.list.count()
        self.info_lbl.setToolTip('')
        if not n:
            self.info_lbl.setText('No se encontraron novelas.')
        elif more:
            self.info_lbl.setText('%d novelas' % n)
        else:
            self.info_lbl.setText('%d novelas · fin del catálogo' % n)
        self.more_btn.setEnabled(bool(more))

    def failed(self, req_id, msg):
        if req_id != self.req_id:
            return
        self.worker = None
        if self.page > 1:
            self.page -= 1
            self.more_btn.setEnabled(True)
        self.info_lbl.setText('❌ ' + msg.splitlines()[0])
        self.info_lbl.setToolTip(msg)

    def cover_loaded(self, url, data):
        pm = QPixmap()
        if not pm.loadFromData(data):
            return
        pm = pm.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        icon = QIcon(pm)
        self.icons[url] = icon
        for item in self.waiting.pop(url, []):
            try:
                item.setIcon(icon)
            except RuntimeError:
                pass  # el ítem ya no existe (se limpió la lista)

    def item_chosen(self, item):
        self.chosen.emit(item.data(Qt.ItemDataRole.UserRole))

    def shutdown(self):
        self.covers.stop = True
        self.covers.clear()
        self.covers.wait(5000)
        if self.worker is not None:
            self.worker.wait(5000)


# --------------------------------------------------------------- ventanas

class AboutDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Acerca de %s' % PLUGIN_NAME)
        self.setWindowIcon(plugin_icon())
        l = QVBoxLayout(self)

        top = QHBoxLayout()
        icon = QLabel()
        pm = resource_pixmap('images/icon.png')
        if not pm.isNull():
            icon.setPixmap(pm.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
        top.addWidget(icon)
        head = QLabel('<h2 style="margin:0">%s</h2>'
                      '<div>Versión %s · por <b>Dunhill</b></div>' % (PLUGIN_NAME, VERSION_STR))
        top.addWidget(head, 1)
        l.addLayout(top)

        desc = QLabel(
            'Explora el catálogo de <b>danmeinovel.com</b> (por orden, género o título) '
            'y las descarga completas o por rango de capítulos, como EPUB '
            '(directo a la biblioteca, con portada, autor, sinopsis y géneros) o como TXT.')
        desc.setWordWrap(True)
        l.addWidget(desc)

        box = QGroupBox('¿Te resulta útil? Invitame un café ☕')
        bl = QVBoxLayout(box)
        qr = QLabel()
        qpm = resource_pixmap('images/donate_qr.png')
        if not qpm.isNull():
            qr.setPixmap(qpm.scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(qr)
        links = QLabel('<a href="%s">Ko-fi</a> &nbsp;·&nbsp; <a href="%s">PayPal</a>'
                       % (KOFI_URL, PAYPAL_URL))
        links.setOpenExternalLinks(True)
        links.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(links)
        l.addWidget(box)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)


class DanmeiDialog(QDialog):

    def __init__(self, gui, parent=None, url=None):
        super().__init__(parent)
        self.gui = gui
        self.info = None
        self.cover = None
        self.info_worker = None
        self.dl_worker = None
        self.temp_dir = None

        self.setWindowTitle(PLUGIN_NAME)
        self.setWindowIcon(plugin_icon())
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        # Catálogo (izquierda)
        cat_box = QGroupBox('Catálogo de danmeinovel.com')
        cl = QVBoxLayout(cat_box)
        self.catalog = CatalogPanel(self)
        self.catalog.chosen.connect(self.load_from_catalog)
        cl.addWidget(self.catalog)
        splitter.addWidget(cat_box)

        # Descarga (derecha)
        right = QWidget()
        right.setMinimumWidth(480)
        l = QVBoxLayout(right)
        l.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.resize(1100, 680)

        # Enlace
        row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText('https://danmeinovel.com/manga/…')
        self.url_edit.returnPressed.connect(self.load_info)
        row.addWidget(self.url_edit, 1)
        self.load_btn = QPushButton('Cargar')
        self.load_btn.clicked.connect(self.load_info)
        row.addWidget(self.load_btn)
        l.addWidget(QLabel('Elegí una novela del catálogo o pegá su enlace:'))
        l.addLayout(row)

        # Ficha
        card = QGroupBox('Novela')
        g = QGridLayout(card)
        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(110, 160)
        self.cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_lbl.setStyleSheet('border: 1px solid palette(mid);')
        g.addWidget(self.cover_lbl, 0, 0, 5, 1)
        self.title_lbl = QLabel('—')
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setStyleSheet('font-weight: bold; font-size: 13pt;')
        g.addWidget(self.title_lbl, 0, 1)
        self.author_lbl = QLabel('')
        g.addWidget(self.author_lbl, 1, 1)
        self.chap_lbl = QLabel('')
        g.addWidget(self.chap_lbl, 2, 1)
        self.tags_lbl = QLabel('')
        self.tags_lbl.setWordWrap(True)
        g.addWidget(self.tags_lbl, 3, 1)
        g.setRowStretch(4, 1)
        self.summary_box = QTextBrowser()
        self.summary_box.setOpenLinks(False)
        self.summary_box.setPlaceholderText('Sinopsis')
        self.summary_box.setMinimumHeight(110)
        g.addWidget(self.summary_box, 5, 0, 1, 2)
        g.setColumnStretch(1, 1)
        l.addWidget(card)

        # Rango y formato
        opts = QGroupBox('Descarga')
        og = QGridLayout(opts)
        og.addWidget(QLabel('Desde el capítulo:'), 0, 0)
        self.from_spin = QSpinBox()
        og.addWidget(self.from_spin, 0, 1)
        self.from_name = QLabel('')
        og.addWidget(self.from_name, 0, 2)
        og.addWidget(QLabel('Hasta el capítulo:'), 1, 0)
        self.to_spin = QSpinBox()
        og.addWidget(self.to_spin, 1, 1)
        self.to_name = QLabel('')
        og.addWidget(self.to_name, 1, 2)
        og.setColumnStretch(2, 1)
        for sp in (self.from_spin, self.to_spin):
            sp.setRange(0, 0)
            sp.valueChanged.connect(self.range_changed)
        og.addWidget(QLabel('Formato:'), 2, 0)
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItem('EPUB — agregar a la biblioteca', ('EPUB', True))
        self.fmt_combo.addItem('EPUB — guardar como archivo', ('EPUB', False))
        self.fmt_combo.addItem('TXT — guardar como archivo', ('TXT', False))
        og.addWidget(self.fmt_combo, 2, 1, 1, 2)
        l.addWidget(opts)

        # Progreso
        self.progress = QProgressBar()
        self.progress.setValue(0)
        l.addWidget(self.progress)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        l.addWidget(self.status)

        # Botones
        bottom = QHBoxLayout()
        about = QPushButton('Acerca de')
        about.clicked.connect(lambda: AboutDialog(self).exec())
        bottom.addWidget(about)
        bottom.addStretch(1)
        self.dl_btn = QPushButton('Descargar')
        self.dl_btn.setDefault(False)
        self.dl_btn.clicked.connect(self.start_download)
        bottom.addWidget(self.dl_btn)
        self.cancel_btn = QPushButton('Cancelar descarga')
        self.cancel_btn.clicked.connect(self.cancel_download)
        self.cancel_btn.setVisible(False)
        bottom.addWidget(self.cancel_btn)
        close = QPushButton('Cerrar')
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        l.addLayout(bottom)

        self.set_busy(False)
        if url:
            self.url_edit.setText(url)
            self.load_info()
        QTimer.singleShot(0, self.catalog.start)

    def load_from_catalog(self, url):
        if not self.load_btn.isEnabled():
            self.status.setText('Esperá a que termine la operación en curso.')
            return
        self.url_edit.setText(url)
        self.load_info()

    # ---------------------------------------------------------- estado

    def set_busy(self, busy, downloading=False):
        self.url_edit.setEnabled(not busy)
        self.load_btn.setEnabled(not busy)
        ready = bool(self.info and self.info['chapters'])
        for w in (self.from_spin, self.to_spin, self.fmt_combo):
            w.setEnabled(not busy and ready)
        self.dl_btn.setEnabled(not busy and ready)
        self.dl_btn.setVisible(not downloading)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setVisible(downloading)

    def chapter_title(self, n):
        if self.info and 1 <= n <= len(self.info['chapters']):
            t = self.info['chapters'][n - 1][0]
            return t if len(t) < 60 else t[:57] + '…'
        return ''

    def range_changed(self):
        if self.from_spin.value() > self.to_spin.value():
            if self.sender() is self.from_spin:
                self.to_spin.setValue(self.from_spin.value())
            else:
                self.from_spin.setValue(self.to_spin.value())
        self.from_name.setText(self.chapter_title(self.from_spin.value()))
        self.to_name.setText(self.chapter_title(self.to_spin.value()))

    # ---------------------------------------------------------- ficha

    def load_info(self):
        url = self.url_edit.text().strip()
        if not site.is_site_url(url):
            self.status.setText('⚠️ El enlace tiene que ser de danmeinovel.com.')
            return
        self.info = None
        self.title_lbl.setText('Cargando…')
        self.author_lbl.setText('')
        self.chap_lbl.setText('')
        self.tags_lbl.setText('')
        self.summary_box.clear()
        self.cover_lbl.clear()
        self.status.setText('Leyendo la ficha de la novela…')
        self.progress.setRange(0, 0)
        self.set_busy(True)
        self.info_worker = InfoWorker(url, self)
        self.info_worker.done.connect(self.info_loaded)
        self.info_worker.failed.connect(self.info_failed)
        self.info_worker.start()

    def info_loaded(self, info, cover):
        self.info, self.cover = info, cover
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.title_lbl.setText(info['title'])
        self.author_lbl.setText('Autor: ' + ' & '.join(info['authors']))
        n = len(info['chapters'])
        status = (' · ' + info['status']) if info.get('status') else ''
        self.chap_lbl.setText('Capítulos disponibles: %d%s' % (n, status))
        self.tags_lbl.setText('<small>%s</small>' % escape(', '.join(info.get('tags', []))))
        self.tags_lbl.setToolTip(info.get('alternative', ''))
        html = ''
        if info.get('alternative'):
            html += '<p><i>%s</i></p>' % escape(info['alternative'])
        html += ''.join('<p>%s</p>' % escape(p) for p in info.get('summary', []))
        self.summary_box.setHtml(html or '<p><i>Sin sinopsis.</i></p>')
        if cover:
            pm = QPixmap()
            if pm.loadFromData(cover):
                self.cover_lbl.setPixmap(pm.scaled(
                    self.cover_lbl.size(), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        lo = 1 if n else 0
        for sp in (self.from_spin, self.to_spin):
            sp.blockSignals(True)
            sp.setRange(lo, n)
            sp.blockSignals(False)
        self.from_spin.setValue(lo)
        self.to_spin.setValue(n)
        self.range_changed()
        self.status.setText('' if n else '⚠️ No se encontraron capítulos en esa página.')
        self.set_busy(False)

    def info_failed(self, msg):
        self.progress.setRange(0, 1)
        self.title_lbl.setText('—')
        self.status.setText('❌ ' + msg)
        self.set_busy(False)

    # ---------------------------------------------------------- descarga

    def start_download(self):
        if not self.info:
            return
        a, b = self.from_spin.value(), self.to_spin.value()
        chapters = self.info['chapters'][a - 1:b]
        fmt, to_library = self.fmt_combo.currentData()
        from calibre import sanitize_file_name
        base = sanitize_file_name(self.info['title']) or 'novela'
        if a != 1 or b != len(self.info['chapters']):
            base += ' (cap %d-%d)' % (a, b)
        filename = '%s.%s' % (base, fmt.lower())

        if to_library:
            from calibre.ptempfile import PersistentTemporaryDirectory
            self.temp_dir = PersistentTemporaryDirectory('_danmei')
            out = os.path.join(self.temp_dir, filename)
        else:
            start = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DownloadLocation) or os.path.expanduser('~')
            out, _ = QFileDialog.getSaveFileName(
                self, 'Guardar novela', os.path.join(start, filename),
                '%s (*.%s)' % (fmt, fmt.lower()))
            if not out:
                return

        self.to_library = to_library
        self.progress.setRange(0, len(chapters))
        self.progress.setValue(0)
        self.status.setText('⏳ Descargando %d capítulos…' % len(chapters))
        self.set_busy(True, downloading=True)
        self.dl_worker = DownloadWorker(self.info, chapters, self.cover, out, fmt, self)
        self.dl_worker.progress.connect(self.dl_progress)
        self.dl_worker.done.connect(self.dl_done)
        self.dl_worker.failed.connect(self.dl_failed)
        self.dl_worker.finished.connect(self.dl_finished)
        self.dl_worker.start()

    def dl_progress(self, i, total, title):
        self.progress.setValue(i)
        self.status.setText('⏳ %d/%d — %s' % (min(i + 1, total), total, title))

    def dl_done(self, path, missing):
        self.progress.setValue(self.progress.maximum())
        extra = ''
        if missing:
            extra = '\n⚠️ No se pudo leer el texto de %d capítulo(s): %s' % (
                len(missing), ', '.join(missing[:5]) + ('…' if len(missing) > 5 else ''))
        if self.to_library:
            try:
                self.gui.iactions['Add Books'].add_filesystem_book(path)
                self.status.setText('✅ Novela agregada a la biblioteca.' + extra)
            except Exception as e:
                self.status.setText('❌ No se pudo agregar a la biblioteca: %s\n'
                                    'El archivo quedó en: %s' % (e, path))
        else:
            self.status.setText('✅ Novela guardada en:\n%s%s' % (path, extra))

    def dl_failed(self, msg):
        self.status.setText('❌ ' + msg)

    def dl_finished(self):
        if self.dl_worker is not None and self.dl_worker.cancelled:
            self.status.setText('Descarga cancelada.')
            self.progress.setValue(0)
        self.set_busy(False)

    def cancel_download(self):
        if self.dl_worker is not None and self.dl_worker.isRunning():
            self.dl_worker.cancelled = True
            self.status.setText('Cancelando…')
            self.cancel_btn.setEnabled(False)

    def reject(self):
        running = [w for w in (self.info_worker, self.dl_worker)
                   if w is not None and w.isRunning()]
        if self.dl_worker in running:
            if QMessageBox.question(
                    self, PLUGIN_NAME,
                    'Hay una descarga en curso. ¿Cancelarla y cerrar?') != \
                    QMessageBox.StandardButton.Yes:
                return
            self.dl_worker.cancelled = True
        for w in running:
            w.wait(15000)
        self.catalog.shutdown()
        super().reject()
