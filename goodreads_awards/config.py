# -*- coding: utf-8 -*-
"""
Goodreads Awards plugin configuration.
"""

try:
    load_translations()
except NameError:
    pass

from qt.core import (
    QWidget, QVBoxLayout, QLabel, QComboBox,
    QGroupBox, QCheckBox, QFrame, QHBoxLayout
)

from calibre.utils.config import JSONConfig

prefs = JSONConfig('plugins/goodreads_awards')

# Valores por defecto
prefs.defaults['guardar_premios']      = True
prefs.defaults['col_premios']          = ''
prefs.defaults['solo_ganadores']       = False
prefs.defaults['max_premios']          = '3'
prefs.defaults['solo_premio_principal'] = False

# Separador FIJO: coma + espacio (ideal para modo etiquetas)
prefs.defaults['separador_premios']    = ', '

def get_custom_text_columns(db):
    result = {}
    for key, meta in db.field_metadata.custom_field_metadata().items():
        if meta.get('datatype') == 'text':
            result[key] = meta.get('name', key)
    return result

def _get_db():
    try:
        from calibre.gui2.ui import get_gui
        gui = get_gui()
        return gui.current_db if gui else None
    except:
        return None

class ConfigWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._setup_ui()
        self._populate_combo()
        self._load_prefs()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Encabezado informativo
        info_text = _(
            '<b>Goodreads Awards — Configuration</b><br>'
            '<small>Choose the column where the awards found on Goodreads will be saved.<br>'
            'The column should be of type <b>"Comma separated text"</b> so each award appears as an independent tag.<br><br>'
            '<i>Note: This plugin can use the <b>Goodreads ID</b> if it was previously retrieved by the Goodreads Metadata plugin.</i>'
            '</small>'
        )
        info = QLabel(info_text)
        info.setWordWrap(True)
        layout.addWidget(info)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        # Grupo de Opciones de descarga
        group = QGroupBox(_('Download options'))
        gl = QVBoxLayout(group)

        self.chk_premios = QCheckBox(_('Save literary awards'))
        gl.addWidget(self.chk_premios)

        # Fila: Selección de columna
        row_col = QHBoxLayout()
        lbl_col = QLabel(_('Custom column for awards:'))
        self.combo_col = QComboBox()
        self.combo_col.setMinimumWidth(280)
        row_col.addWidget(lbl_col)
        row_col.addWidget(self.combo_col)
        gl.addLayout(row_col)

        self.chk_solo_ganadores = QCheckBox(_('Save only winners (exclude nominations and longlists)'))
        gl.addWidget(self.chk_solo_ganadores)

        self.chk_solo_principal = QCheckBox(_('Save only the most important award if there is one (Pulitzer, Nobel, Hugo, etc.)'))
        gl.addWidget(self.chk_solo_principal)

        # Fila: Máximo de premios
        row_max = QHBoxLayout()
        lbl_max = QLabel(_('Maximum awards to save:'))
        self.combo_max = QComboBox()
        self.combo_max.addItems(['1', '2', '3', '5', '10', '15', _('All')])
        row_max.addWidget(lbl_max)
        row_max.addWidget(self.combo_max)
        row_max.addStretch()
        gl.addLayout(row_max)

        # Nota aclaratoria sobre el máximo
        self.nota_maximo = QLabel(
            _('<i style="color: #666666;">Note: If you only want the main award, '
            'selecting "1" or "2" is recommended. If the book won in multiple categories, '
            'a higher number will keep all distinct trophies.</i>')
        )
        self.nota_maximo.setWordWrap(True)
        gl.addWidget(self.nota_maximo)

        # Nota importante sobre etiquetas
        nota_etiquetas = QLabel(
            _('<br><b>Important for using as tags:</b><br>'
            '• Configure the column in Calibre as <b>"Comma separated text, shown in the tag browser"</b>.<br>'
            '• This allows you to filter books by specific awards just like genres.')
        )
        nota_etiquetas.setWordWrap(True)
        nota_etiquetas.setStyleSheet("color: #0066cc;")
        gl.addWidget(nota_etiquetas)

        layout.addWidget(group)
        layout.addStretch()

    def _populate_combo(self):
        db = _get_db()
        if db:
            cols = get_custom_text_columns(db)
            self.combo_col.clear()
            self.combo_col.addItem(_('— Select column —'), '')
            for lookup, label in sorted(cols.items(), key=lambda x: x[1].lower()):
                self.combo_col.addItem(f'{label}  [{lookup}]', lookup)

    def _load_prefs(self):
        self.chk_premios.setChecked(prefs['guardar_premios'])
        
        saved_col = prefs['col_premios']
        if saved_col:
            idx = self.combo_col.findData(saved_col)
            if idx >= 0:
                self.combo_col.setCurrentIndex(idx)

        self.chk_solo_ganadores.setChecked(prefs['solo_ganadores'])
        self.chk_solo_principal.setChecked(prefs['solo_premio_principal'])

        # Lógica para cargar el valor máximo y manejar la traducción de "All"
        max_val = prefs['max_premios']
        if max_val in ('Todos', 'All'):
            target_text = _('All')
        else:
            target_text = str(max_val)
            
        idx_max = self.combo_max.findText(target_text)
        if idx_max >= 0:
            self.combo_max.setCurrentIndex(idx_max)

    def save_settings(self):
        prefs['guardar_premios'] = self.chk_premios.isChecked()
        prefs['col_premios']     = self.combo_col.currentData() or ''
        prefs['solo_ganadores']  = self.chk_solo_ganadores.isChecked()
        prefs['solo_premio_principal'] = self.chk_solo_principal.isChecked()
        
        max_txt = self.combo_max.currentText()
        # Guardamos una referencia neutra para evitar problemas de idioma al recargar
        prefs['max_premios'] = 'All' if max_txt == _('All') else max_txt
