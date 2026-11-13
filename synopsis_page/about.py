#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

from qt.core import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                     QPixmap, Qt, QUrl, QDialogButtonBox, QFrame)

from calibre.gui2 import open_url

try:
    load_translations()
except NameError:
    pass

KOFI_URL = 'https://ko-fi.com/dunhill69'
PAYPAL_URL = 'https://paypal.me/Dunhill69'
REPO_URL = 'https://github.com/Dunhill69/Dunhill-calibre-plugins'


class AboutDialog(QDialog):

    def __init__(self, parent, icon, version):
        QDialog.__init__(self, parent)
        self.setWindowTitle(_('About Synopsis Page'))
        self.setWindowIcon(icon)
        lay = QVBoxLayout(self)

        # Header
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icon.pixmap(72, 72))
        top.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        ver = '.'.join(map(str, version))
        head = QLabel(
            '<h2 style="margin:0">Synopsis Page</h2>'
            '<p style="margin:2px 0">%s</p><p>%s</p><p><a href="%s">%s</a></p>' % (
                _('Version %s · by <b>Dunhill</b>') % ver,
                _('Adds a page with the book cover and its synopsis, taken from '
                  'the calibre Comments field, to EPUB and AZW3 books.'),
                REPO_URL, _('GitHub repository')))
        head.setWordWrap(True)
        head.setOpenExternalLinks(True)
        top.addWidget(head, 1)
        lay.addLayout(top)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        lay.addWidget(line)

        # Donation
        don = QHBoxLayout()
        qr = QLabel()
        pix = QPixmap()
        pix.loadFromData(get_resources('images/donate_qr.png'))
        qr.setPixmap(pix.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation))
        qr.setToolTip(KOFI_URL)
        don.addWidget(qr)
        right = QVBoxLayout()
        txt = QLabel('<b>%s</b><br>%s' % (
            _('Do you find it useful?'),
            _('If you want to support the development of my plugins, you can '
              'buy me a coffee by scanning the code or with the buttons below. '
              'Thank you!')))
        txt.setWordWrap(True)
        right.addWidget(txt)
        b1 = QPushButton('☕  Ko-fi')
        b1.clicked.connect(lambda: open_url(QUrl(KOFI_URL)))
        b2 = QPushButton('PayPal')
        b2.clicked.connect(lambda: open_url(QUrl(PAYPAL_URL)))
        right.addWidget(b1)
        right.addWidget(b2)
        right.addStretch(1)
        don.addLayout(right, 1)
        lay.addLayout(don)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(480, 360)
