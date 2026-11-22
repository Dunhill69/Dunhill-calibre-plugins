#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

from calibre.customize import InterfaceActionBase

try:
    load_translations()
except NameError:
    pass


class BookCardExportBase(InterfaceActionBase):
    name = 'Book Card Export'
    description = _('Export the book details card as an image, '
                    'and copy the cover and a Telegram-ready text')
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'Dunhill'
    version = (1, 4, 1)
    minimum_calibre_version = (6, 0, 0)

    actual_plugin = 'calibre_plugins.book_card_export.action:BookCardAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.book_card_export.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
