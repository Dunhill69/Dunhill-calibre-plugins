import re

from qt.core import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                     QLineEdit, QPushButton, Qt)
from html import escape

# Tipos de recurso de ComicVine que acepta el complemento
#   4050 = volume (serie de cómics)  -> lo normal para Mylar
#   4075 = series (serie de TV)      -> se mantiene por compatibilidad
RESOURCES = {'4050': 'volume', '4075': 'series'}


def parse_comicvine_input(raw_text):
    '''Devuelve (prefijo, id) a partir de un enlace o ID, o (None, None).'''
    raw_text = (raw_text or '').strip()
    m = re.search(r'\b(40\d\d)-(\d+)\b', raw_text)
    if m:
        return m.group(1), m.group(2)
    if raw_text.isdigit():
        return '4050', raw_text  # ID suelto: se toma como volumen
    return None, None


class ComicVineDialog(QDialog):
    def __init__(self, parent=None, series_name=""):
        super().__init__(parent)
        self.setWindowTitle(f'Mylar Plus: {series_name}')
        self.setMinimumWidth(460)
        self.result_id = None
        self.result_prefix = None
        self.setup_ui(series_name)

    def setup_ui(self, series_name):
        layout = QVBoxLayout(self)

        # Instrucciones
        info_label = QLabel(f"Introduce el enlace o ID de ComicVine para:<br><b>{escape(series_name)}</b>")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info_label)

        # Campo de entrada
        self.url_input = QLineEdit(self)
        self.url_input.setPlaceholderText("Ej: https://comicvine.gamespot.com/batman/4050-796/")
        self.url_input.returnPressed.connect(self.process_input)
        layout.addWidget(self.url_input)

        self.error_label = QLabel(self)
        self.error_label.setStyleSheet('color: #c0392b')
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        # Botones
        button_layout = QHBoxLayout()
        self.btn_import = QPushButton('Importar Magia', self)
        self.btn_import.setDefault(True)
        self.btn_import.clicked.connect(self.process_input)
        self.btn_cancel = QPushButton('Cancelar', self)
        self.btn_cancel.clicked.connect(self.reject)

        button_layout.addWidget(self.btn_import)
        button_layout.addWidget(self.btn_cancel)
        layout.addLayout(button_layout)

    def process_input(self):
        prefix, cid = parse_comicvine_input(self.url_input.text())
        if not cid:
            self.error_label.setText('No reconozco ese enlace. Pegá la dirección de la serie '
                                     '(…/4050-NÚMERO/) o solo el número.')
            self.error_label.show()
            return
        if prefix not in RESOURCES:
            self.error_label.setText(f'El enlace es de otro tipo de ficha de ComicVine ({prefix}). '
                                     'Usá el enlace del volumen/serie (…/4050-NÚMERO/).')
            self.error_label.show()
            return
        self.result_prefix, self.result_id = prefix, cid
        self.accept()
