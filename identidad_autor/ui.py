# -*- coding: utf-8 -*-
from __future__ import (unicode_literals, division, absolute_import, print_function)

import csv
import io

try:
    load_translations()
except NameError:
    pass

from qt.core import (QMenu, QFileDialog, QIcon, QPixmap, QDialog, QVBoxLayout,
                     QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
                     QLineEdit, QLabel, QHeaderView, QComboBox, QApplication, QToolButton,
                     Qt)

from calibre.gui2 import error_dialog, info_dialog, question_dialog
from calibre.gui2.actions import InterfaceAction
from calibre.utils.config import JSONConfig

# --- PERSISTENCIA ---
PLUGIN_PREFS = JSONConfig('plugins/identidad_autor')
PREFS_KEY_MAPA_COMBINADO = 'mapa_identidades_v2'   # {seudónimo: [nombre real, orden]}
PREFS_KEY_ESTILO = 'estilo_encapsulado'

ESTILO_DEFECTO = 'Paréntesis (Autor)'
ESTILOS = {
    'Paréntesis (Autor)': (' (', ')'),
    'Corchetes [Autor]': (' [', ']'),
    'Nombre Real & Autor': ('&', ''),          # dos autores: el real y el seudónimo
    'Sustitución Directa (Solo Nombre Real)': (None, None),
}
# Cuántos cambios se muestran como ejemplo antes de confirmar
MAX_EJEMPLOS = 12


def cargar_mapa():
    """Mapa guardado (se lee siempre de nuevo: puede haber cambiado desde la configuración)."""
    return dict(PLUGIN_PREFS.get(PREFS_KEY_MAPA_COMBINADO, {}) or {})


def guardar_mapa(mapa, estilo=None):
    PLUGIN_PREFS[PREFS_KEY_MAPA_COMBINADO] = mapa
    if estilo is not None:
        PLUGIN_PREFS[PREFS_KEY_ESTILO] = estilo
    PLUGIN_PREFS.commit()


def separar(info):
    """Entrada del mapa -> (nombre real, orden)."""
    if isinstance(info, (list, tuple)):
        return (info[0] if info else ''), (info[1] if len(info) > 1 else '')
    return info or '', ''


def leer_csv(path):
    """Lee un CSV de 2 o 3 columnas (seudónimo, nombre real, orden). Detecta el
    separador (; , o tabulación) y saltea la fila de encabezados."""
    with open(path, 'r', encoding='utf-8-sig') as f:
        texto = f.read()
    try:
        dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=';,\t')
    except csv.Error:
        class dialecto(csv.excel):
            delimiter = ';'
    filas = list(csv.reader(io.StringIO(texto), dialecto))
    resultado = {}
    for i, fila in enumerate(filas):
        if len(fila) < 2:
            continue
        k, real = fila[0].strip(), fila[1].strip()
        orden = fila[2].strip() if len(fila) > 2 else ''
        if i == 0 and k.lower() in ('nombre', 'seudonimo', 'seudónimo', 'en calibre', 'autor',
                                    'name', 'pseudonym', 'author'):
            continue   # encabezados
        if k and real and k != real:
            resultado[k] = [real, orden]
    return resultado


class GestionarIdentidadesDialog(QDialog):
    def __init__(self, parent, mapa_actual):
        super(GestionarIdentidadesDialog, self).__init__(parent)
        self.setWindowTitle('Gestión avanzada: identidades y orden de autor')
        self.resize(900, 700)
        self.mapa_trabajo = dict(mapa_actual)
        self.setup_ui()
        self.rellenar_tabla()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # --- CONFIGURACIÓN ---
        estilo_box = QHBoxLayout()
        estilo_box.addWidget(QLabel("<b>Formato visual:</b>"))
        self.combo_estilo = QComboBox()
        for nombre in sorted(ESTILOS.keys()):
            self.combo_estilo.addItem(nombre)
        idx = self.combo_estilo.findText(PLUGIN_PREFS.get(PREFS_KEY_ESTILO, ESTILO_DEFECTO))
        if idx >= 0:
            self.combo_estilo.setCurrentIndex(idx)
        self.combo_estilo.setToolTip(
            'Cómo queda el autor de un libro firmado con seudónimo:\n'
            '• Paréntesis: «Nombre Real (Seudónimo)»\n'
            '• Corchetes: «Nombre Real [Seudónimo]»\n'
            '• Nombre Real & Autor: dos autores, el real y el seudónimo\n'
            '• Sustitución directa: solo el nombre real')
        estilo_box.addWidget(self.combo_estilo)
        estilo_box.addStretch()

        btn_base = QPushButton("Cargar base incluida")
        btn_base.setToolTip("Agrega los seudónimos conocidos que trae el complemento "
                            "(no reemplaza los que ya tenés).")
        btn_base.clicked.connect(self.cargar_base)
        estilo_box.addWidget(btn_base)
        btn_importar = QPushButton("Importar CSV")
        btn_importar.setToolTip("Columnas: seudónimo; nombre real; orden (opcional).\n"
                                "El separador puede ser ; , o tabulación.")
        btn_importar.clicked.connect(self.importar_csv)
        estilo_box.addWidget(btn_importar)
        btn_exportar = QPushButton("Exportar CSV")
        btn_exportar.clicked.connect(self.exportar_csv)
        estilo_box.addWidget(btn_exportar)
        layout.addLayout(estilo_box)

        # --- BUSCADOR ---
        search_layout = QHBoxLayout()
        self.txt_buscar = QLineEdit()
        self.txt_buscar.setPlaceholderText("Filtrar por cualquier campo...")
        self.txt_buscar.textChanged.connect(self.filtrar_tabla)
        search_layout.addWidget(self.txt_buscar)
        self.lbl_contador = QLabel("Registros: 0")
        search_layout.addWidget(self.lbl_contador)
        layout.addLayout(search_layout)

        # --- TABLA DE 3 COLUMNAS ---
        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(['En calibre (seudónimo)', 'Nombre real', 'Orden (sort)'])
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.itemChanged.connect(self.actualizar_mapa_desde_celda)
        layout.addWidget(self.tabla)

        # --- ACCIONES ---
        fila_btns = QHBoxLayout()
        btn_add = QPushButton("+ Fila")
        btn_add.clicked.connect(self.agregar_fila)
        btn_del = QPushButton("- Borrar")
        btn_del.clicked.connect(self.eliminar_fila)
        btn_copy = QPushButton("Copiar real")
        btn_copy.clicked.connect(self.copiar_nombre_real)
        fila_btns.addWidget(btn_add)
        fila_btns.addWidget(btn_copy)
        fila_btns.addWidget(btn_del)
        fila_btns.addStretch()
        hint = QLabel('Si «Orden» queda vacío, el libro se ordena por el apellido del nombre real.')
        hint.setStyleSheet('color: #777;')
        fila_btns.addWidget(hint)
        layout.addLayout(fila_btns)

        btns_fin = QHBoxLayout()
        btn_save = QPushButton("Guardar cambios")
        btn_save.clicked.connect(self.accept)
        btn_save.setStyleSheet("font-weight: bold; background-color: #d4edda; color: #1d3b24;")
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        btns_fin.addStretch()
        btns_fin.addWidget(btn_save)
        btns_fin.addWidget(btn_cancel)
        layout.addLayout(btns_fin)

    def rellenar_tabla(self, filtro=""):
        self.tabla.blockSignals(True)
        self.tabla.setRowCount(0)
        filtro = filtro.lower()
        for k, info in sorted(self.mapa_trabajo.items(), key=lambda x: x[0].lower()):
            real, orden = separar(info)
            if not filtro or any(filtro in x.lower() for x in (k, real, orden)):
                row = self.tabla.rowCount()
                self.tabla.insertRow(row)
                item = QTableWidgetItem(k)
                item.setData(Qt.ItemDataRole.UserRole, k)   # clave original, por si se renombra
                self.tabla.setItem(row, 0, item)
                self.tabla.setItem(row, 1, QTableWidgetItem(real))
                self.tabla.setItem(row, 2, QTableWidgetItem(orden))
        self.tabla.blockSignals(False)
        self.lbl_contador.setText("Registros: {}".format(len(self.mapa_trabajo)))

    def filtrar_tabla(self):
        self.rellenar_tabla(self.txt_buscar.text())

    def actualizar_mapa_desde_celda(self, item):
        row = item.row()
        it0, it1, it2 = self.tabla.item(row, 0), self.tabla.item(row, 1), self.tabla.item(row, 2)
        if not it0:
            return
        k = it0.text().strip()
        anterior = it0.data(Qt.ItemDataRole.UserRole)
        real = it1.text().strip() if it1 else ''
        orden = it2.text().strip() if it2 else ''
        # Si se cambió el seudónimo, se borra la clave vieja (antes quedaba duplicada)
        if anterior and anterior != k:
            self.mapa_trabajo.pop(anterior, None)
        if k:
            self.mapa_trabajo[k] = [real, orden]
            self.tabla.blockSignals(True)
            it0.setData(Qt.ItemDataRole.UserRole, k)
            self.tabla.blockSignals(False)
        self.lbl_contador.setText("Registros: {}".format(len(self.mapa_trabajo)))

    def agregar_fila(self):
        row = self.tabla.rowCount()
        self.tabla.insertRow(row)
        for i in range(3):
            self.tabla.setItem(row, i, QTableWidgetItem(""))
        self.tabla.setCurrentCell(row, 0)
        self.tabla.editItem(self.tabla.item(row, 0))

    def eliminar_fila(self):
        row = self.tabla.currentRow()
        if row < 0:
            return
        it0 = self.tabla.item(row, 0)
        if it0 is not None:
            for k in {it0.text().strip(), it0.data(Qt.ItemDataRole.UserRole) or ''}:
                self.mapa_trabajo.pop(k, None)
        self.tabla.removeRow(row)
        self.lbl_contador.setText("Registros: {}".format(len(self.mapa_trabajo)))

    def copiar_nombre_real(self):
        row = self.tabla.currentRow()
        if row >= 0 and self.tabla.item(row, 1):
            QApplication.clipboard().setText(self.tabla.item(row, 1).text())

    def cargar_base(self):
        from calibre_plugins.identidad_autor.identidades import MAPA_AUTORES
        nuevos = 0
        for k, real in MAPA_AUTORES.items():
            if k not in self.mapa_trabajo and real and k != real:
                self.mapa_trabajo[k] = [real, '']
                nuevos += 1
        self.rellenar_tabla(self.txt_buscar.text())
        info_dialog(self, "Base incluida",
                    "Se agregaron {} seudónimos ({} ya estaban).".format(
                        nuevos, len(MAPA_AUTORES) - nuevos), show=True)

    def importar_csv(self):
        path = QFileDialog.getOpenFileName(self, "Importar CSV", "", "CSV (*.csv *.txt)")[0]
        if not path:
            return
        try:
            datos = leer_csv(path)
        except Exception as e:
            error_dialog(self, "Error", "Error al leer el CSV: {}".format(e), show=True)
            return
        self.mapa_trabajo.update(datos)
        self.rellenar_tabla(self.txt_buscar.text())
        info_dialog(self, "Importar CSV", "Se importaron {} registros.".format(len(datos)), show=True)

    def exportar_csv(self):
        path = QFileDialog.getSaveFileName(self, "Exportar CSV", "identidades.csv", "CSV (*.csv)")[0]
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.writer(f, delimiter=';')
                w.writerow(['Seudónimo', 'Nombre real', 'Orden'])
                for k, info in sorted(self.mapa_trabajo.items(), key=lambda x: x[0].lower()):
                    real, orden = separar(info)
                    w.writerow([k, real, orden])
        except Exception as e:
            error_dialog(self, "Error", "No se pudo guardar el CSV: {}".format(e), show=True)
            return
        info_dialog(self, "Exportar CSV", "Se exportaron {} registros.".format(len(self.mapa_trabajo)), show=True)

    def get_data(self):
        # Se descartan las filas sin nombre real
        limpio = {k: [r, o] for k, (r, o) in ((k, separar(v)) for k, v in self.mapa_trabajo.items()) if k and r}
        return limpio, self.combo_estilo.currentText()


def calcular_cambios(db, ids, mapa, estilo_nom):
    """Lista de (book_id, título, autores_viejos, autores_nuevos, orden_nuevo) para
    los libros que cambian. No toca la base de datos."""
    from calibre.ebooks.metadata import author_to_author_sort
    sep_ini, sep_fin = ESTILOS.get(estilo_nom, ESTILOS[ESTILO_DEFECTO])
    cambios = []
    for b_id in ids:
        autores = list(db.field_for('authors', b_id) or ())
        nuevos, orden = [], []
        hubo_cambio = False
        for a in autores:
            real, orden_fijo = separar(mapa.get(a))
            if real and real != a:
                hubo_cambio = True
                sort_real = orden_fijo or author_to_author_sort(real)
                if sep_ini is None:                      # solo el nombre real
                    pares = [(real, sort_real)]
                elif sep_ini == '&':                     # dos autores
                    pares = [(real, sort_real), (a, db.author_sort_from_authors([a]))]
                else:                                    # «Real (Seudónimo)»
                    pares = [('{}{}{}{}'.format(real, sep_ini, a, sep_fin), sort_real)]
            else:
                pares = [(a, db.author_sort_from_authors([a]))]
            for nombre, s in pares:
                if nombre not in nuevos:
                    nuevos.append(nombre)
                    orden.append(s)
        if hubo_cambio and nuevos != autores:
            cambios.append((b_id, db.field_for('title', b_id), autores, nuevos, ' & '.join(orden)))
    return cambios


class IdentidadAutorUI(InterfaceAction):
    name = 'Identidad Autor'
    action_spec = ('Identidad Autor', None, 'Normalizar autores con su nombre real', 'Ctrl+Shift+I')
    popup_type = QToolButton.ToolButtonPopupMode.MenuButtonPopup
    action_type = 'current'

    def genesis(self):
        self.icono = QIcon()
        try:
            icon_data = self.load_resources(['images/icon.png'])
            raw_data = icon_data.get('images/icon.png')
            if raw_data:
                pix = QPixmap()
                pix.loadFromData(raw_data)
                self.icono = QIcon(pix)
                self.qaction.setIcon(self.icono)
        except Exception:
            pass
        self.qaction.triggered.connect(self.run_plugin)
        self._init_menu()

    def _init_menu(self):
        m = QMenu(self.gui)
        m.addAction(self.icono, 'Procesar libros seleccionados', self.run_plugin)
        m.addAction('Gestionar base de identidades...', self.show_config_dialog)
        m.addSeparator()
        m.addAction(_('About {0}').format('Identidad Autor'), self.show_about)
        self.qaction.setMenu(m)

    def show_about(self):
        from calibre_plugins.identidad_autor.support import show_about
        show_about(self.gui, self.interface_action_base_plugin)

    def show_config_dialog(self):
        d = GestionarIdentidadesDialog(self.gui, cargar_mapa())
        if d.exec() == QDialog.DialogCode.Accepted:
            mapa, estilo = d.get_data()
            guardar_mapa(mapa, estilo)

    def run_plugin(self):
        ids = list(self.gui.library_view.get_selected_ids())
        if not ids:
            return error_dialog(self.gui, 'Identidad Autor', 'Seleccioná al menos un libro.', show=True)
        mapa = cargar_mapa()
        if not mapa:
            if question_dialog(self.gui, 'Identidad Autor',
                               'Todavía no hay seudónimos cargados. ¿Abrir la base de identidades?'):
                self.show_config_dialog()
            return

        db = self.gui.current_db.new_api
        estilo = PLUGIN_PREFS.get(PREFS_KEY_ESTILO, ESTILO_DEFECTO)
        cambios = calcular_cambios(db, ids, mapa, estilo)
        if not cambios:
            return info_dialog(self.gui, 'Identidad Autor',
                               'Ninguno de los {} libros seleccionados tiene autores de la base '
                               '(o ya estaban procesados).'.format(len(ids)), show=True)

        lineas = ['• {}: {} → {}'.format(t, ' & '.join(v), ' & '.join(n)) for _b, t, v, n, _o in cambios]
        ejemplos = '\n'.join(lineas[:MAX_EJEMPLOS])
        if len(lineas) > MAX_EJEMPLOS:
            ejemplos += '\n… y {} más (ver detalles)'.format(len(lineas) - MAX_EJEMPLOS)
        if not question_dialog(self.gui, 'Identidad Autor',
                               'Se van a cambiar los autores de {} libros:\n\n{}\n\n¿Continuar?'.format(
                                   len(cambios), ejemplos),
                               det_msg='\n'.join(lineas), show_copy_button=True):
            return

        for b_id, _t, _v, nuevos, orden in cambios:
            db.set_field('authors', {b_id: nuevos})
            db.set_field('author_sort', {b_id: orden})

        self.gui.library_view.model().refresh_ids([c[0] for c in cambios])
        try:
            self.gui.tags_view.recount()   # el panel de etiquetas muestra los autores nuevos
        except Exception:
            pass
        self.gui.status_bar.show_message('Se actualizaron los autores de {} libros.'.format(len(cambios)), 5000)
