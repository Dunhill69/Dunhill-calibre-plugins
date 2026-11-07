from calibre.customize import InterfaceActionBase

try:
    load_translations()
except NameError:
    pass


class GoodreadsSeriesExplorerPlugin(InterfaceActionBase):
    name                    = 'Goodreads Series Explorer'
    description             = _('Explores whole series and sagas from Goodreads from your '
                                'library, with the data of the editions in your language.')
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'Walter'
    version                 = (1, 12, 0)
    # qt.core y los enums de Qt6 requieren calibre 6 o superior
    minimum_calibre_version = (6, 0, 0)
    actual_plugin           = 'calibre_plugins.goodreads_series_explorer.main:GoodreadsSeriesExplorerAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.goodreads_series_explorer.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
