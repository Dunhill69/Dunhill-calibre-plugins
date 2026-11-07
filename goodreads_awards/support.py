# -*- coding: utf-8 -*-

try:
    load_translations()
except NameError:
    pass

# Enlace público de donación del autor
DONATE_URL = 'https://ko-fi.com/dunhill69'
# Hilo del complemento en MobileRead (si queda vacío, el enlace no se muestra)
MOBILEREAD_URL = 'https://www.mobileread.com/forums/showthread.php?t=372376'
QR_IMAGE = 'images/donate_qr.png'
COFFEE_IMAGE = 'images/coffee.png'


def _link(url, text):
    return '<a href="{0}">{1}</a>'.format(url, text)


def show_about(parent, plugin):
    """Ventana "Acerca de" con versión, enlaces y QR de donación.
    `plugin` es el InterfaceActionBase (tiene name, description y version)."""
    try:
        from qt.core import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QDialogButtonBox, QPixmap, Qt, QFont)
    except ImportError:
        from PyQt5.Qt import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QDialogButtonBox, QPixmap, Qt, QFont)
    from calibre.constants import __version__ as calibre_version

    version = '.'.join(str(x) for x in plugin.version)
    name = _(plugin.name)

    d = QDialog(parent)
    d.setWindowTitle(_('About {0}').format(name))
    lay = QVBoxLayout(d)
    lay.setSpacing(10)

    def centered(text, rich=False):
        lbl = QLabel(text, d)
        lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lbl.setWordWrap(True)
        if rich:
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setOpenExternalLinks(True)
        lay.addWidget(lbl)
        return lbl

    def muted(lbl):
        # Texto secundario: más chico y gris (como en otros complementos)
        fm = QFont(lbl.font())
        fm.setPointSizeF(fm.pointSizeF() * 0.85)
        lbl.setFont(fm)
        lbl.setStyleSheet('color: #808080;')
        return lbl

    title = centered(name)
    f = QFont(title.font())
    f.setPointSizeF(f.pointSizeF() * 1.7)
    f.setBold(True)
    title.setFont(f)

    desc = centered(_(plugin.description))
    desc.setMinimumWidth(400)

    muted(centered(_('Version: {0}').format(version)))

    if MOBILEREAD_URL:
        centered(_link(MOBILEREAD_URL, _('MobileRead forum')), rich=True)
    # Taza de café como imagen (no depende de que el sistema tenga la fuente del símbolo ☕)
    cup = None
    try:
        cup = get_resources(COFFEE_IMAGE)
    except Exception:
        pass
    link = QLabel(_link(DONATE_URL, _('Support development') if cup else '☕ ' + _('Support development')), d)
    link.setTextFormat(Qt.TextFormat.RichText)
    link.setOpenExternalLinks(True)
    row = QHBoxLayout()
    row.addStretch(1)
    if cup:
        cpm = QPixmap()
        cpm.loadFromData(cup)
        size = max(16, link.fontMetrics().height())
        cl = QLabel(d)
        cl.setPixmap(cpm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation))
        row.addWidget(cl)
    row.addWidget(link)
    row.addStretch(1)
    lay.addLayout(row)

    data = None
    try:
        data = get_resources(QR_IMAGE)
    except Exception:
        pass
    if data:
        pm = QPixmap()
        pm.loadFromData(data)
        qr = QLabel(d)
        qr.setPixmap(pm.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
        qr.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        qr.setToolTip(_('Scan the code with your phone to donate via Ko-fi.'))
        lay.addWidget(qr)
        muted(centered(_('Scan the code with your phone to donate via Ko-fi.')))

    bottom = QHBoxLayout()
    foot = QLabel('{0} {1}\ncalibre {2}'.format(name, version, calibre_version), d)
    muted(foot)
    bottom.addWidget(foot)
    bottom.addStretch(1)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, d)
    bb.rejected.connect(d.reject)
    bottom.addWidget(bb)
    lay.addLayout(bottom)

    d.exec()
