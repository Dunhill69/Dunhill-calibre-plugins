from calibre.customize import InterfaceActionBase

try:
    load_translations()
except NameError:
    pass


class Cover3DPlugin(InterfaceActionBase):
    name = '3D Cover'
    description = ('Turns flat book covers into 3D hardcover books, with spine, page '
                   'edges and shadow. Inspired by the "Create Hardcover" plugin by sornay.')
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'Dunhill'
    version = (1, 6, 3)
    minimum_calibre_version = (5, 0, 0)
    actual_plugin = 'calibre_plugins.cover3d.ui:Cover3DAction'
