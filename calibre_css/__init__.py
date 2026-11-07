#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai

__license__   = 'GPL v3'
__copyright__ = '2026, Dunhill'

try:
    load_translations()
except NameError:
    pass

from calibre.customize import InterfaceActionBase


class CalibreCSSPlugin(InterfaceActionBase):
    name                    = 'Calibre CSS'
    description             = _('Use a different CSS style for the book details panel '
                                'and the e-book viewer in each library')
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'Dunhill'
    version                 = (1, 7, 1)
    minimum_calibre_version = (7, 0, 0)
    actual_plugin           = 'calibre_plugins.calibre_style.action:CalibreCSSAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        # Preferences > Plugins > Customize plugin
        from calibre_plugins.calibre_style.config import CalibreCSSWidget
        from calibre.gui2.ui import get_gui
        return CalibreCSSWidget(get_gui(), self)

    def save_settings(self, config_widget):
        config_widget.save_settings()
