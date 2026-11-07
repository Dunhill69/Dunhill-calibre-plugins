# -*- coding: utf-8 -*-
from __future__ import (unicode_literals, division, absolute_import, print_function)
from calibre.customize import InterfaceActionBase

class IdentidadAutorPlugin(InterfaceActionBase):
    name                    = 'Identidad Autor'
    description             = 'Gestiona seudónimos y nombres reales con lógica jerárquica.'
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'Dunhill'
    version                 = (1, 1, 0)
    minimum_calibre_version = (6, 0, 0)

    actual_plugin = 'calibre_plugins.identidad_autor.ui:IdentidadAutorUI'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.identidad_autor.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
