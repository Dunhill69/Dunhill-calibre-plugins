from calibre.utils.config import JSONConfig

# Crea el archivo de configuración en la carpeta de Calibre
# Esto permite que la API Key sea persistente
prefs = JSONConfig('plugins/mylar_series_plus')

# Valor por defecto vacío
prefs.defaults['api_key'] = ''


def ConfigWidget():
    # Import diferido: config.py también se carga fuera de la interfaz gráfica
    from qt.core import QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit

    class _ConfigWidget(QWidget):

        def __init__(self):
            QWidget.__init__(self)
            lay = QVBoxLayout(self)

            form = QFormLayout()
            self.key_edit = QLineEdit(self)
            self.key_edit.setText(prefs['api_key'])
            form.addRow('API Key de ComicVine:', self.key_edit)
            link = QLabel('<a href="https://comicvine.gamespot.com/api/">'
                          'Conseguí una API Key gratis en comicvine.gamespot.com/api</a>', self)
            link.setOpenExternalLinks(True)
            form.addRow('', link)
            lay.addLayout(form)
            lay.addStretch(1)

        def save_settings(self):
            prefs['api_key'] = self.key_edit.text().strip()

    return _ConfigWidget()
