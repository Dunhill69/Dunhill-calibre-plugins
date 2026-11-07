# -*- coding: utf-8 -*-
from qt.core import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout


class ConfigWidget(QWidget):
    """Configuración: abre la base de identidades (seudónimo -> nombre real)."""

    def __init__(self):
        QWidget.__init__(self)
        lay = QVBoxLayout(self)
        from calibre_plugins.identidad_autor.ui import cargar_mapa, PLUGIN_PREFS, PREFS_KEY_ESTILO, ESTILO_DEFECTO
        info = QLabel('<b>Identidad Autor</b> reemplaza los seudónimos de los libros seleccionados '
                      'por el nombre real del autor, según tu base de identidades.<br><br>'
                      'Seudónimos cargados: <b>{}</b><br>Formato: <b>{}</b>'.format(
                          len(cargar_mapa()), PLUGIN_PREFS.get(PREFS_KEY_ESTILO, ESTILO_DEFECTO)))
        info.setWordWrap(True)
        lay.addWidget(info)
        self.info = info
        row = QHBoxLayout()
        btn = QPushButton('Gestionar base de identidades...')
        btn.clicked.connect(self.abrir)
        row.addWidget(btn)
        row.addStretch()
        lay.addLayout(row)
        lay.addStretch()

    def abrir(self):
        from qt.core import QDialog
        from calibre_plugins.identidad_autor.ui import (GestionarIdentidadesDialog, cargar_mapa,
                                                        guardar_mapa)
        d = GestionarIdentidadesDialog(self, cargar_mapa())
        if d.exec() == QDialog.DialogCode.Accepted:
            guardar_mapa(*d.get_data())

    def save_settings(self):
        pass   # los cambios se guardan al cerrar la base de identidades
