#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

from calibre.customize import InterfaceActionBase

try:
    load_translations()
except NameError:
    pass


class SynopsisPagePlugin(InterfaceActionBase):
    name = 'Synopsis Page'
    description = _('Adds a page with the book cover and its synopsis '
                    '(Comments field) to EPUB and AZW3 books.')
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'Dunhill'
    version = (1, 2, 0)
    minimum_calibre_version = (6, 0, 0)

    actual_plugin = 'calibre_plugins.synopsis_page.action:SynopsisPageAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.synopsis_page.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
