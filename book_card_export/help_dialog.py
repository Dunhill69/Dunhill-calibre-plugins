#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

from qt.core import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

try:
    load_translations()
except NameError:
    pass


def help_html():
    lang = 'en'
    try:
        from calibre.utils.localization import get_lang
        lang = (get_lang() or 'en').split('_')[0].lower()
    except Exception:
        pass
    for name in ('help/%s.html' % lang, 'help/en.html'):
        try:
            raw = get_resources(name)
        except Exception:
            raw = None
        if raw:
            return raw.decode('utf-8')
    return ''


class HelpDialog(QDialog):

    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.setWindowTitle(_('Book Card Export - Help'))
        self.setWindowIcon(get_icons('images/icon.png', 'Book Card Export'))
        l = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(help_html())
        l.addWidget(self.browser)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        l.addWidget(bb)
        self.resize(760, 640)
