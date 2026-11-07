# -*- coding: utf-8 -*-

from calibre.customize import InterfaceActionBase

class CompareLibrariesPlugin(InterfaceActionBase):
    name                    = 'Compare Libraries'
    description             = ('Compara la biblioteca actual con otra biblioteca o carpeta, importa los libros '
                               'faltantes sin duplicados y puede limpiar el origen.')
    supported_platforms     = ['linux', 'windows', 'osx']
    author                  = 'Dunhill'
    version                 = (1, 2, 0)
    minimum_calibre_version = (6, 0, 0)

    # Ruta a la clase de la acción
    actual_plugin_class     = 'calibre_plugins.compare_libraries.action:CompareLibrariesAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.compare_libraries.config import ConfigWidget
        return ConfigWidget(self.gui)

    def save_settings(self, config_widget):
        config_widget.save_settings()

    def load_actual_plugin(self, gui):
        from calibre_plugins.compare_libraries.action import CompareLibrariesAction
        return CompareLibrariesAction(gui, self.name)
