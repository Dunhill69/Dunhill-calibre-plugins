# -*- coding: utf-8 -*-

try:
    load_translations()
except NameError:
    pass

from calibre.customize import InterfaceActionBase

class CalibreUpdatePlugin(InterfaceActionBase):
    name                    = 'Calibre Updater'
    description             = _(
        'Updates calibre using the official method. '
        'Includes smart process management to ensure a clean shutdown and prevents conflicts during installation'
    )
    supported_platforms     = ['linux', 'windows', 'osx']
    author                  = 'Dunhill'
    version                 = (1, 23, 6)
    minimum_calibre_version = (7, 0, 0)

    # Path a la clase de la acción
    actual_plugin_class = 'calibre_plugins.calibre_updater.action:CalibreUpdaterAction'

    def genesis(self):
        pass

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.calibre_updater.config import ConfigWidget
        return ConfigWidget(self.gui)

    def save_settings(self, config_widget):
        config_widget.save_settings()

    def load_actual_plugin(self, gui):
        from calibre_plugins.calibre_updater.action import CalibreUpdaterAction
        return CalibreUpdaterAction(gui, self.name)
