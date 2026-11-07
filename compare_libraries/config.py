# -*- coding: utf-8 -*-

from qt.core import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog
from calibre.utils.config import JSONConfig

prefs = JSONConfig('plugins/compare_libraries_settings')
prefs.defaults['target_library_path'] = ''

class ConfigWidget(QWidget):
    def __init__(self, gui):
        super().__init__()
        self.gui = gui
        self.layout = QVBoxLayout(self)

        self.info_label = QLabel(
            'Define la ruta predeterminada de la biblioteca o carpeta que aparecerá primero al abrir el escáner.'
        )
        self.info_label.setWordWrap(True)
        self.layout.addWidget(self.info_label)

        self.h_layout = QHBoxLayout()
        self.layout.addLayout(self.h_layout)

        self.label = QLabel('Origen predeterminado:')
        self.h_layout.addWidget(self.label)

        self.path_edit = QLineEdit(self)
        self.path_edit.setText(prefs['target_library_path'])
        self.h_layout.addWidget(self.path_edit)

        self.btn_browse = QPushButton('Examinar...', self)
        self.btn_browse.clicked.connect(self.choose_dir)
        self.h_layout.addWidget(self.btn_browse)

    def choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, 'Seleccionar Carpeta o Biblioteca', self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def save_settings(self):
        prefs['target_library_path'] = self.path_edit.text().strip()
