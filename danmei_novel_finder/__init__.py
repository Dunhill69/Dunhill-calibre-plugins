#!/usr/bin/env python
# Danmei Novel Finder — complemento de tienda para calibre
# Autor: Dunhill

from calibre.customize import StoreBase

PLUGIN_NAME = 'Danmei Novel Finder'
PLUGIN_VERSION = (1, 2, 1)


class DanmeiStoreWrapper(StoreBase):
    name = PLUGIN_NAME
    description = ('Explora el catálogo de danmeinovel.com y descarga novelas como EPUB '
                   '(directo a la biblioteca) o como TXT.')
    author = 'Dunhill'
    version = PLUGIN_VERSION
    minimum_calibre_version = (6, 0, 0)
    supported_platforms = ['windows', 'osx', 'linux']

    actual_plugin = 'calibre_plugins.DanmeiStore.main:DanmeiStore'

    headquarters = 'CN'
    formats = ['EPUB', 'TXT']
    drm_free_only = True
    affiliate = False
