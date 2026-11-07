# -*- coding: utf-8 -*-
"""Vista previa de archivos XTC/XTCH dentro de calibre."""

try:
    load_translations()
except NameError:
    pass

from qt.core import (Qt, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                     QSpinBox, QComboBox, QImage, QPixmap, QSize, QKeySequence,
                     QShortcut, QSizePolicy)

from calibre_plugins.epub_to_xtc_converter.xtc_format import XTCReader


class PageView(QLabel):
    """Muestra la página escalada para que entre en el espacio disponible."""

    def __init__(self, parent):
        QLabel.__init__(self, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 240)
        self.setStyleSheet('background-color: #6b6b6b;')
        self._pix = None

    def set_page(self, pixmap):
        self._pix = pixmap
        self._refresh()

    def resizeEvent(self, ev):
        QLabel.resizeEvent(self, ev)
        self._refresh()

    def _refresh(self):
        if self._pix is None:
            return
        avail = self.size() - QSize(16, 16)
        pw, ph = self._pix.width(), self._pix.height()
        if pw <= avail.width() and ph <= avail.height():
            self.setPixmap(self._pix)  # tamaño real, píxel por píxel
        else:
            self.setPixmap(self._pix.scaled(avail, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))


class PreviewDialog(QDialog):

    def __init__(self, parent, path, book_title=''):
        QDialog.__init__(self, parent)
        self.reader = XTCReader(path)
        r = self.reader
        self.setWindowTitle(_('XTC preview: {0}').format(r.title or book_title))
        lay = QVBoxLayout(self)

        kind = _('4 shades of gray') if r.grayscale else _('Black and white')
        info = QLabel('<b>%s</b>%s<br>%s' % (
            _esc(r.title or book_title), (' — ' + _esc(r.author)) if r.author else '',
            _('{0} pages · {1}×{2} · {3} · {4} chapters').format(r.page_count, r.width, r.height, kind, len(r.chapters))), self)
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setWordWrap(True)
        lay.addWidget(info)

        self.view = PageView(self)
        lay.addWidget(self.view, 1)

        bar = QHBoxLayout()
        self.first_b = QPushButton('⏮', self)
        self.prev_b = QPushButton('◀', self)
        self.next_b = QPushButton('▶', self)
        self.last_b = QPushButton('⏭', self)
        for b, tip in ((self.first_b, _('First page')), (self.prev_b, _('Previous page')),
                       (self.next_b, _('Next page')), (self.last_b, _('Last page'))):
            b.setToolTip(tip)
            b.setAutoDefault(False)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.spin = QSpinBox(self)
        self.spin.setRange(1, r.page_count)
        self.spin.setSuffix(' / %d' % r.page_count)
        self.spin.setKeyboardTracking(False)

        bar.addWidget(self.first_b)
        bar.addWidget(self.prev_b)
        bar.addWidget(self.spin)
        bar.addWidget(self.next_b)
        bar.addWidget(self.last_b)

        self.chapters = QComboBox(self)
        self.chapters.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.chapters.setMinimumContentsLength(18)
        if r.chapters:
            self.chapters.addItem(_('Chapters...'), -1)
            for name, start, end in r.chapters:
                self.chapters.addItem('%s  (%d)' % (name, start + 1), start)
            bar.addWidget(self.chapters, 1)
        else:
            self.chapters.hide()
            bar.addStretch(1)
        lay.addLayout(bar)

        self.first_b.clicked.connect(lambda: self.go(0))
        self.prev_b.clicked.connect(lambda: self.go(self.current - 1))
        self.next_b.clicked.connect(lambda: self.go(self.current + 1))
        self.last_b.clicked.connect(lambda: self.go(r.page_count - 1))
        self.spin.valueChanged.connect(lambda v: self.go(v - 1))
        self.chapters.activated.connect(self._chapter_chosen)

        for keys, func in ((('Right', 'PgDown'), lambda: self.go(self.current + 1)),
                           (('Left', 'PgUp'), lambda: self.go(self.current - 1)),
                           (('Ctrl+Home',), lambda: self.go(0)),
                           (('Ctrl+End',), lambda: self.go(r.page_count - 1))):
            for k in keys:
                sc = QShortcut(QKeySequence(k), self)
                sc.activated.connect(func)

        self.current = -1
        height = 940
        try:
            height = min(height, int(self.screen().availableGeometry().height() * 0.9))
        except Exception:
            pass
        self.resize(max(360, int(height * 0.6)), height)
        self.go(0)
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.view.setFocus()

    def _chapter_chosen(self, idx):
        start = self.chapters.itemData(idx)
        if start is not None and start >= 0:
            self.go(start)

    def go(self, index):
        r = self.reader
        index = max(0, min(index, r.page_count - 1))
        if index == self.current:
            return
        self.current = index
        w, h, gray = r.page(index)
        img = QImage(gray, w, h, w, QImage.Format.Format_Grayscale8).copy()
        self.view.set_page(QPixmap.fromImage(img))
        self.spin.blockSignals(True)
        self.spin.setValue(index + 1)
        self.spin.blockSignals(False)
        self.first_b.setEnabled(index > 0)
        self.prev_b.setEnabled(index > 0)
        self.next_b.setEnabled(index < r.page_count - 1)
        self.last_b.setEnabled(index < r.page_count - 1)
        # capítulo actual en el desplegable
        if r.chapters:
            pos = 0
            for i, (name, start, end) in enumerate(r.chapters):
                if start <= index:
                    pos = i + 1
            self.chapters.blockSignals(True)
            self.chapters.setCurrentIndex(pos)
            self.chapters.blockSignals(False)


def _esc(text):
    return (text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
