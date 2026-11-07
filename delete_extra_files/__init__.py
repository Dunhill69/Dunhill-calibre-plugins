# -*- coding: utf-8 -*-

try:
    load_translations()
except NameError:
    pass

from calibre.customize import InterfaceActionBase

class DeleteExtraFilesPlugin(InterfaceActionBase):
    name                      = 'Delete Extra Files'
    description               = _('Selectively and securely deletes extra data folders (extra files) from the entire Calibre library.')
    supported_platforms       = ['linux', 'windows', 'osx']
    author                    = 'Dunhill'
    version                   = (1, 3, 0)
    minimum_calibre_version   = (7, 0, 0)

    # Points exactly to the corrected module and class
    actual_plugin_class = 'calibre_plugins.delete_extra_files.action:DeleteExtraFilesAction'

    def genesis(self):
        pass

    def is_customizable(self):
        return False

    def load_actual_plugin(self, gui):
        from calibre_plugins.delete_extra_files.action import DeleteExtraFilesAction
        return DeleteExtraFilesAction(gui, self.name)
