# -*- coding: utf-8 -*-
from calibre.customize import InterfaceActionBase

try:
    load_translations()
except NameError:
    pass

class GoodreadsAwardsPlugin(InterfaceActionBase):
    name                    = 'Goodreads Awards'
    description             = _(
        'Search books on goodreads.com by title and author, '
        'and extract literary awards.'
    )
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'Dunhill'
    version                 = (1, 2, 0)
    minimum_calibre_version = (5, 0, 0)

    actual_plugin = 'calibre_plugins.goodreads_awards.main:GoodreadsAwardsAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.goodreads_awards.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
