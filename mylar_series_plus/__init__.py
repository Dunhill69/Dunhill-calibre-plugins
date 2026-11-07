# -*- coding: utf-8 -*-

try:
    load_translations()
except NameError:
    pass

from calibre.customize import InterfaceActionBase

class MylarSeriesPlusPlugin(InterfaceActionBase):
    name                = 'Mylar Series Plus'
    description         = _(
        'Creates Mylar3 series.json metadata and visual series cards in the comments from ComicVine.'
    )
    supported_platforms = ['windows', 'osx', 'linux']
    author              = 'Dunhill'
    version             = (1, 1, 0)
    minimum_calibre_version = (6, 0, 0)

    # Importante: vincula la clase MylarSeriesPlus dentro de action.py
    actual_plugin       = 'calibre_plugins.mylar_series_plus.action:MylarSeriesPlus'

    def is_customizable(self):
        return True

    def config_widget(self):
        # Ventana de configuración (Preferencias → Complementos → Personalizar)
        from calibre_plugins.mylar_series_plus.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
