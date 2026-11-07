# -*- coding: utf-8 -*-
from __future__ import (unicode_literals, division, absolute_import, print_function)

from calibre.customize import InterfaceActionBase

try:
    load_translations()
except NameError:
    pass

class EpubToXtcPlugin(InterfaceActionBase):
    name                    = 'EPUB to XTC Converter'
    description             = _('Converts books to the XTC/XTCH format of the Xteink X4 e-reader, '
                                'with the pages rendered by calibre')
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'Dunhill'
    version                 = (2, 3, 0)
    minimum_calibre_version = (6, 0, 0)

    actual_plugin = 'calibre_plugins.epub_to_xtc_converter.ui:InterfaceAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.epub_to_xtc_converter.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()

    def genesis(self):
        pass
