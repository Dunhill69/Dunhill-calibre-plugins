# -*- coding: utf-8 -*-

try:
    load_translations()
except NameError:
    pass

from calibre.customize import InterfaceActionBase

class IntegrityAnalysisPlugin(InterfaceActionBase):
    name                          = 'Integrity Analysis'
    description                   = _(
        'Performs integrity checks and analysis on your Calibre library and components.'
    )
    supported_platforms           = ['linux', 'windows', 'osx']
    author                        = 'Dunhill'
    version                       = (1, 6, 1)
    minimum_calibre_version       = (7, 0, 0)

    # Ruta a la clase real de la acción apuntando al paquete actualizado
    actual_plugin_class = 'calibre_plugins.integrity_analysis.action:IntegrityAnalysisAction'

    def genesis(self):
        pass

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.integrity_analysis.config import ConfigWidget
        return ConfigWidget(self)

    def save_settings(self, config_widget):
        config_widget.save_settings()

    def load_actual_plugin(self, gui):
        from calibre_plugins.integrity_analysis.action import IntegrityAnalysisAction
        return IntegrityAnalysisAction(gui, self.name)
