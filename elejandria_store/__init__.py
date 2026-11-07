# -*- coding: utf-8 -*-
from calibre.customize import StoreBase


class ElejandriaStore(StoreBase):
    name = 'Elejandría'
    description = ('Libros gratis y legales en español (dominio público y licencias abiertas) '
                   'de elejandria.com, con descarga directa en EPUB, PDF y MOBI')
    author = 'Dunhill'
    version = (1, 1, 2)
    minimum_calibre_version = (6, 0, 0)
    supported_platforms = ['windows', 'osx', 'linux']
    actual_plugin = 'calibre_plugins.elejandria_store.elejandria_plugin:ElejandriaStorePlugin'

    drm_free_only = True
    headquarters = 'ES'
    formats = ['EPUB', 'PDF', 'MOBI']
    affiliate = False
