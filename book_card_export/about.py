#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

from qt.core import (
    QDesktopServices, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QPixmap, QPushButton, Qt, QUrl, QVBoxLayout,
)

try:
    load_translations()
except NameError:
    pass

KOFI = 'https://ko-fi.com/dunhill69'
PAYPAL = 'https://paypal.me/Dunhill69'
REPO = 'https://github.com/Dunhill69/Dunhill-calibre-plugins'


def _pixmap(name, size):
    pm = QPixmap()
    pm.loadFromData(get_resources(name))
    return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)


class AboutDialog(QDialog):

    def __init__(self, parent, plugin):
        QDialog.__init__(self, parent)
        self.setWindowTitle(_('About %s') % plugin.name)
        self.setWindowIcon(get_icons('images/icon.png', 'Book Card Export'))
        version = '.'.join(str(x) for x in plugin.version)

        l = QVBoxLayout(self)

        # header: icon + name + version
        h = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(_pixmap('images/icon.png', 72))
        h.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        title = QLabel('<h2 style="margin:0">%s</h2><p style="margin:2px 0">%s %s<br>%s <b>Dunhill</b></p>' % (
            plugin.name, _('Version'), version, _('by')))
        h.addWidget(title, 1)
        l.addLayout(h)

        desc = QLabel(_(
            'Creates a card with the cover and the book details, like the one calibre '
            'shows, and lets you save it as an image. It also prepares the text '
            'to share the book in Telegram, with the cover as a photo and the details '
            'and synopsis as its caption.'))
        desc.setWordWrap(True)
        l.addWidget(desc)

        links = QLabel('<a href="%s">%s</a>' % (REPO, _('Source code and other plugins on GitHub')))
        links.setOpenExternalLinks(True)
        l.addWidget(links)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        l.addWidget(line)

        # donation
        d = QHBoxLayout()
        qr = QLabel()
        qr.setPixmap(_pixmap('images/qr_donate.png', 170))
        qr.setToolTip(KOFI)
        d.addWidget(qr)
        v = QVBoxLayout()
        txt = QLabel(_('If this plugin is useful to you, you can support its development '
                       'with a donation. Scan the code or use the buttons. Thank you!'))
        txt.setWordWrap(True)
        v.addWidget(txt)
        b = QPushButton('☕  Ko-fi')
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(KOFI)))
        v.addWidget(b)
        b = QPushButton('💳  PayPal')
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PAYPAL)))
        v.addWidget(b)
        v.addStretch()
        d.addLayout(v, 1)
        l.addLayout(d)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        l.addWidget(bb)
        self.setMinimumWidth(500)
