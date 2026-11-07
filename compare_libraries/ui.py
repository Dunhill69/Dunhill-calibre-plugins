# -*- coding: utf-8 -*-

import os
import sqlite3
import threading
import traceback
import unicodedata
from pathlib import Path

from qt.core import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                     QPushButton, QLabel, QHeaderView, QComboBox, QFileDialog, Qt,
                     QApplication, QProgressBar, QCheckBox, QGroupBox)
from calibre.gui2 import gprefs, error_dialog, info_dialog, question_dialog
from calibre_plugins.compare_libraries.config import prefs

# Rol de Qt donde guardamos el índice del libro dentro de self.libros_faltantes.
# Así la selección funciona aunque el usuario reordene la tabla.
ROL_INDICE = Qt.ItemDataRole.UserRole


def normalizar(texto):
    """Minúsculas, Unicode normalizado y sin espacios repetidos."""
    texto = unicodedata.normalize('NFKC', texto or '')
    return ' '.join(texto.casefold().split())


def clave_libro(titulo, autores):
    """Clave de comparación: título + autores ORDENADOS.
    (GROUP_CONCAT de SQLite no garantiza el orden: 'A & B' y 'B & A' se tomaban como libros distintos.)"""
    return (normalizar(titulo), tuple(sorted(normalizar(a) for a in autores)))


class CompareDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.gui = parent
        self.current_library_path = self.gui.current_db.library_path
        self.current_target_path = ""
        self.setWindowTitle("Comparar Bibliotecas - Libros Faltantes")
        self.resize(950, 680)

        self.layout = QVBoxLayout(self)

        # --- SECCIÓN SUPERIOR: SELECCIÓN DE BIBLIOTECA A COMPARAR ---
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Biblioteca externa a comparar:", self))

        self.combo_libraries = QComboBox(self)
        self.combo_libraries.setEditable(True)
        top_layout.addWidget(self.combo_libraries, stretch=1)

        self.btn_browse = QPushButton("Examinar...", self)
        self.btn_browse.clicked.connect(self.examinar_carpeta)
        top_layout.addWidget(self.btn_browse)

        self.btn_scan = QPushButton("Comparar", self)
        self.btn_scan.setStyleSheet("font-weight: bold;")
        self.btn_scan.clicked.connect(self.comparar_bibliotecas)
        top_layout.addWidget(self.btn_scan)
        self.layout.addLayout(top_layout)

        # --- ESTADO Y PROGRESO ---
        self.lbl_info = QLabel("Selecciona una biblioteca externa y haz clic en 'Comparar' para encontrar libros faltantes.", self)
        self.layout.addWidget(self.lbl_info)

        self.lbl_current_file = QLabel("", self)
        self.lbl_current_file.setStyleSheet("color: #444444; font-style: italic; font-size: 11px;")
        self.lbl_current_file.setVisible(False)
        self.layout.addWidget(self.lbl_current_file)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)

        # --- TABLA ---
        self.table = QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Título", "Autor(es)", "Formatos Disponibles"])
        for col, ancho in enumerate((350, 250, 250)):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(col, ancho)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.layout.addWidget(self.table)

        # --- FILTROS Y OPCIONES ---
        options_layout = QVBoxLayout()
        self.group_formats = QGroupBox("Filtrar por formatos de ebook (selecciona uno o varios)", self)
        formats_layout = QHBoxLayout()

        def chk(texto, clave):
            c = QCheckBox(texto, self)
            c.setChecked(prefs.get(clave, True))
            formats_layout.addWidget(c)
            return c

        self.chk_fmt_epub = chk("EPUB", 'format_epub')
        self.chk_fmt_pdf = chk("PDF", 'format_pdf')
        self.chk_fmt_mobi = chk("MOBI", 'format_mobi')
        self.chk_fmt_azw3 = chk("AZW3", 'format_azw3')
        self.chk_fmt_fb2 = chk("FB2", 'format_fb2')
        self.chk_fmt_cbr = chk("CBR/CBZ", 'format_cbr')
        self.chk_fmt_todos = chk("Todos", 'format_todos')
        self.group_formats.setLayout(formats_layout)
        options_layout.addWidget(self.group_formats)

        self.chk_delete_source = QCheckBox("Eliminar libros de la biblioteca externa tras importarlos con éxito (Mover)", self)
        self.chk_delete_source.setStyleSheet("color: #d93025; font-weight: bold;")
        options_layout.addWidget(self.chk_delete_source)

        self.chk_permanente = QCheckBox("Borrar del origen definitivamente (sin pasar por la papelera de Calibre)", self)
        self.chk_permanente.setChecked(prefs.get('delete_permanent', False))
        self.chk_permanente.toggled.connect(lambda v: prefs.__setitem__('delete_permanent', v))
        options_layout.addWidget(self.chk_permanente)

        self.chk_auto_continue = QCheckBox("Continuar automáticamente entre tandas sin preguntar (Proceso desatendido)", self)
        options_layout.addWidget(self.chk_auto_continue)
        self.layout.addLayout(options_layout)

        # --- ACCIONES ---
        btn_layout = QHBoxLayout()
        self.btn_import = QPushButton("Importar faltantes seleccionados (en tandas de 50)", self)
        self.btn_import.setStyleSheet("font-weight: bold; background-color: #2b78e4; color: white;")
        self.btn_import.setEnabled(False)
        self.btn_import.clicked.connect(self.importar_libros_faltantes)
        btn_layout.addWidget(self.btn_import)

        self.btn_cancel_import = QPushButton("Cancelar", self)
        self.btn_cancel_import.setStyleSheet("background-color: #d93025; color: white; font-weight: bold;")
        self.btn_cancel_import.setEnabled(False)
        self.btn_cancel_import.clicked.connect(self.solicitar_cancelacion)
        btn_layout.addWidget(self.btn_cancel_import)

        self.btn_limpiar = QPushButton("Limpiar origen (borrar los que ya están aquí)", self)
        self.btn_limpiar.setToolTip(
            "Busca en la biblioteca externa los libros que ya existen en esta biblioteca\n"
            "(con todos sus formatos) y los elimina de la externa.")
        self.btn_limpiar.clicked.connect(self.limpiar_origen)
        btn_layout.addWidget(self.btn_limpiar)

        self.btn_close = QPushButton("Cerrar", self)
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_close)
        self.layout.addLayout(btn_layout)

        self.libros_faltantes = []
        self.cancel_requested = False
        self.cargar_fuentes()

    # ------------------------------------------------------------------ utilidades
    @staticmethod
    def ejecutar_sin_congelar(funcion, *args, **kwargs):
        """Ejecuta una tarea larga en un hilo aparte y mientras tanto deja que la
        interfaz siga respondiendo (evita el aviso 'calibre no está respondiendo')."""
        resultado, error = {}, {}

        def tarea():
            try:
                resultado['valor'] = funcion(*args, **kwargs)
            except Exception:
                error['detalle'] = traceback.format_exc()

        hilo = threading.Thread(target=tarea, daemon=True)
        hilo.start()
        while hilo.is_alive():
            QApplication.processEvents()
            hilo.join(0.05)
        if error:
            raise RuntimeError(error['detalle'])
        return resultado.get('valor')

    def bloquear_botones(self, ocupado):
        self.btn_scan.setEnabled(not ocupado)
        self.btn_close.setEnabled(not ocupado)
        self.btn_browse.setEnabled(not ocupado)
        self.btn_limpiar.setEnabled(not ocupado)

    # ------------------------------------------------------------------ fuentes
    def cargar_fuentes(self):
        self.combo_libraries.clear()
        curr_abs = os.path.normcase(os.path.abspath(self.current_library_path))

        saved_path = prefs.get('target_library_path', '').strip()
        if saved_path and os.path.exists(saved_path):
            self.combo_libraries.addItem(f"[Predeterminada] {saved_path}", saved_path)

        stats = gprefs.get('library_usage_stats', {})
        for path in sorted(stats.keys()):
            if os.path.exists(os.path.join(path, 'metadata.db')):
                if os.path.normcase(os.path.abspath(path)) != curr_abs and path != saved_path:
                    self.combo_libraries.addItem(path, path)

    def examinar_carpeta(self):
        d = QFileDialog.getExistingDirectory(self, "Seleccionar Biblioteca Calibre", "")
        if d:
            index = self.combo_libraries.findData(d)
            if index < 0:
                self.combo_libraries.addItem(d, d)
                index = self.combo_libraries.count() - 1
            self.combo_libraries.setCurrentIndex(index)

    # ------------------------------------------------------------------ lectura
    @staticmethod
    def obtener_mapa_libros_seguro(lib_path):
        """Lee metadata.db en SOLO LECTURA con sqlite3.
        Devuelve {clave: [info, ...]} (lista porque una biblioteca puede tener duplicados).
        Usa books.path para ubicar la carpeta de cada libro en lugar de recorrer el disco."""
        libros = {}
        db_file = os.path.join(lib_path, 'metadata.db')
        if not os.path.exists(db_file):
            return libros

        uri = Path(os.path.abspath(db_file)).as_uri() + '?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
        try:
            cur = conn.cursor()
            autores = {}
            for book_id, nombre in cur.execute(
                    'SELECT bal.book, a.name FROM books_authors_link bal '
                    'JOIN authors a ON a.id = bal.author ORDER BY bal.book, bal.id'):
                autores.setdefault(book_id, []).append(nombre)

            formatos = {}
            for book_id, fmt, nombre in cur.execute('SELECT book, format, name FROM data'):
                formatos.setdefault(book_id, []).append((fmt.lower(), nombre))

            filas = cur.execute('SELECT id, title, path FROM books').fetchall()
        finally:
            conn.close()

        for book_id, titulo, rel_path in filas:
            titulo = titulo or 'Desconocido'
            lista_autores = autores.get(book_id) or ['Desconocido']
            book_dir = os.path.join(lib_path, rel_path) if rel_path else None
            archivos = []
            if book_dir:
                for fmt, nombre in formatos.get(book_id, []):
                    ruta = os.path.join(book_dir, f'{nombre}.{fmt}')
                    if os.path.isfile(ruta):
                        archivos.append({'format': fmt, 'path': ruta})

            info = {
                'external_id': book_id,
                'title': titulo,
                'author': ' & '.join(lista_autores),
                'archivos': archivos,
                # Todos los formatos que el libro tiene registrados, para saber
                # si al "mover" hay que borrar el libro entero o solo algunos formatos.
                'formatos_db': {fmt for fmt, _ in formatos.get(book_id, [])},
            }
            libros.setdefault(clave_libro(titulo, lista_autores), []).append(info)
        return libros

    def formatos_permitidos(self):
        """None = sin filtro."""
        if self.chk_fmt_todos.isChecked():
            return None
        permitidos = set()
        if self.chk_fmt_epub.isChecked(): permitidos.add('epub')
        if self.chk_fmt_pdf.isChecked(): permitidos.add('pdf')
        if self.chk_fmt_mobi.isChecked(): permitidos.add('mobi')
        if self.chk_fmt_azw3.isChecked(): permitidos.add('azw3')
        if self.chk_fmt_fb2.isChecked(): permitidos.add('fb2')
        if self.chk_fmt_cbr.isChecked(): permitidos.update(['cbr', 'cbz'])
        return permitidos

    # ------------------------------------------------------------------ comparar
    def obtener_ruta_externa(self):
        """Devuelve la ruta de la biblioteca externa elegida, o None (mostrando el error)."""
        target_path = self.combo_libraries.currentData() or self.combo_libraries.currentText().strip()
        if target_path.startswith("[Predeterminada] "):
            target_path = target_path[len("[Predeterminada] "):].strip()

        if not target_path or not os.path.exists(os.path.join(target_path, 'metadata.db')):
            error_dialog(self, "Biblioteca no válida",
                         "Selecciona una biblioteca de Calibre válida (que contenga 'metadata.db').", show=True)
            return None
        if os.path.normcase(os.path.abspath(target_path)) == os.path.normcase(os.path.abspath(self.current_library_path)):
            error_dialog(self, "Misma biblioteca", "La biblioteca externa es la misma que la actual.", show=True)
            return None
        return target_path

    def comparar_bibliotecas(self):
        target_path = self.obtener_ruta_externa()
        if not target_path:
            return

        self.current_target_path = target_path
        prefs['target_library_path'] = target_path
        prefs['format_epub'] = self.chk_fmt_epub.isChecked()
        prefs['format_pdf'] = self.chk_fmt_pdf.isChecked()
        prefs['format_mobi'] = self.chk_fmt_mobi.isChecked()
        prefs['format_azw3'] = self.chk_fmt_azw3.isChecked()
        prefs['format_fb2'] = self.chk_fmt_fb2.isChecked()
        prefs['format_cbr'] = self.chk_fmt_cbr.isChecked()
        prefs['format_todos'] = self.chk_fmt_todos.isChecked()

        self.bloquear_botones(True)
        self.btn_import.setEnabled(False)
        self.libros_faltantes = []
        self.poblar_tabla()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.lbl_current_file.setVisible(True)
        try:
            self.lbl_info.setText("Analizando biblioteca actual (local)...")
            self.progress_bar.setValue(15)
            QApplication.processEvents()
            libros_actuales = self.ejecutar_sin_congelar(self.obtener_mapa_libros_seguro, self.current_library_path)

            self.lbl_info.setText("Analizando biblioteca externa...")
            self.progress_bar.setValue(50)
            QApplication.processEvents()
            libros_externos = self.ejecutar_sin_congelar(self.obtener_mapa_libros_seguro, target_path)

            self.lbl_info.setText("Comparando catálogos y aplicando filtros...")
            self.progress_bar.setValue(80)
            QApplication.processEvents()

            permitidos = self.formatos_permitidos()
            for key, lista in libros_externos.items():
                if key in libros_actuales:
                    continue
                # Si la biblioteca externa tiene el mismo libro repetido, se toma
                # solo uno para no crear duplicados en la de destino.
                for info in lista:
                    archivos = [a for a in info['archivos']
                                if permitidos is None or a['format'] in permitidos]
                    if archivos:
                        copia = dict(info)
                        copia['archivos'] = archivos
                        self.libros_faltantes.append(copia)
                        break

            self.poblar_tabla()
            self.progress_bar.setValue(100)
            if self.libros_faltantes:
                self.lbl_info.setText(f"Se encontraron <b>{len(self.libros_faltantes)}</b> libros faltantes con los formatos seleccionados.")
                self.btn_import.setEnabled(True)
            else:
                self.lbl_info.setText("No hay libros faltantes con los filtros de formato especificados.")
        except Exception as e:
            error_dialog(self, "Error al comparar", str(e), det_msg=traceback.format_exc(), show=True)
            self.lbl_info.setText("Ocurrió un error al comparar las bibliotecas.")
        finally:
            QApplication.restoreOverrideCursor()
            self.progress_bar.setVisible(False)
            self.lbl_current_file.setVisible(False)
            self.bloquear_botones(False)

    def poblar_tabla(self):
        # Con el ordenamiento activo, setItem() reubica filas mientras se llena la tabla
        # y las columnas quedan mezcladas: hay que desactivarlo durante el llenado.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.libros_faltantes))
        # Para encontrar rápido la fila de cada libro y quitarla al importarlo
        self.celdas_por_libro = {}
        for row, item in enumerate(self.libros_faltantes):
            celda = QTableWidgetItem(item['title'])
            celda.setData(ROL_INDICE, row)
            self.celdas_por_libro[id(item)] = celda
            self.table.setItem(row, 0, celda)
            self.table.setItem(row, 1, QTableWidgetItem(item['author']))
            self.table.setItem(row, 2, QTableWidgetItem(", ".join(a['format'].upper() for a in item['archivos'])))
        self.table.setSortingEnabled(True)

    def quitar_de_tabla(self, item):
        """Quita de la tabla la fila de un libro ya procesado, en el momento."""
        celda = getattr(self, 'celdas_por_libro', {}).pop(id(item), None)
        if celda is not None:
            fila = self.table.row(celda)
            if fila >= 0:
                self.table.removeRow(fila)

    def solicitar_cancelacion(self):
        self.cancel_requested = True
        self.btn_cancel_import.setEnabled(False)
        self.lbl_info.setText("Cancelando importación... Se detendrá en breve.")

    # ------------------------------------------------------------------ importar
    @staticmethod
    def abrir_biblioteca_origen(path):
        """Abre la biblioteca de origen igual que 'Copiar a biblioteca': con el gestor de
        bibliotecas de la propia interfaz (library_broker). Si no está disponible
        (versiones viejas), la abre con LibraryDatabase(is_second_db=True).
        Devuelve (db, broker)."""
        try:
            from calibre.gui2.ui import get_gui
            broker = get_gui(fail_if_absent=True).library_broker
            return broker.get_library(path), broker
        except Exception:
            traceback.print_exc()
            from calibre.db.legacy import LibraryDatabase
            return LibraryDatabase(path, is_second_db=True), None

    @staticmethod
    def importar_uno(ext_db, dest_db, item, datos_identicos, usar_copia_nativa, conservar_uuid):
        """Importa un libro. Devuelve (nuevo_id, accion) con accion 'add' o 'duplicate'.

        - Sin filtro de formatos: usa copy_one_book, la misma función de 'Copiar a biblioteca'
          (copia metadatos, portada, todos los formatos, archivos extra y anotaciones).
        - Con filtro de formatos: agrega solo los formatos elegidos.
        En ambos casos Calibre revisa si ya existe un libro igual en el destino
        (mismo autor y título casi igual) y en ese caso no lo agrega."""
        from calibre.db.utils import find_identical_books
        dest = dest_db.new_api

        if usar_copia_nativa:
            from calibre.db.copy_to_library import copy_one_book
            r = copy_one_book(item['external_id'], ext_db, dest_db,
                              duplicate_action='ignore', preserve_date=True,
                              identical_books_data=datos_identicos,
                              preserve_uuid=conservar_uuid)
            return r.get('new_book_id'), r.get('action')

        mi = ext_db.new_api.get_metadata(item['external_id'], get_cover=True, cover_as_data=True)
        if find_identical_books(mi, datos_identicos):
            return None, 'duplicate'
        formatos = {a['format'].upper(): a['path'] for a in item['archivos']}
        ids, _dups = dest.add_books([(mi, formatos)], add_duplicates=True, run_hooks=False)
        nuevo_id = ids[0] if ids else None
        if nuevo_id:
            dest.update_data_for_find_identical_books(nuevo_id, datos_identicos)
        return nuevo_id, 'add'

    @staticmethod
    def eliminar_de_origen(ext_db, item, permanente=False):
        """Borra un libro de la biblioteca de origen con la API de Calibre.
        - Si se importaron todos sus formatos: se elimina el libro.
        - Si el filtro dejó formatos sin importar: solo se quitan los importados.
        Devuelve 'completo' o 'parcial'."""
        api = ext_db.new_api
        importados = {a['format'] for a in item['archivos']}
        if importados >= item['formatos_db']:
            # permanente=False: va a la papelera de Calibre de esa biblioteca (recuperable).
            api.remove_books([item['external_id']], permanent=permanente)
            return 'completo'
        api.remove_formats({item['external_id']: [f.upper() for f in importados]})
        return 'parcial'

    @staticmethod
    def copia_en_destino(ext_api, dest_api, book_id, datos_identicos):
        """Busca en el destino el mismo libro (mismo criterio que usa Calibre para detectar
        duplicados: mismos autores y título casi igual).
        Devuelve (ids_en_destino, formatos_que_faltan_en_destino)."""
        from calibre.db.utils import find_identical_books
        from calibre.ebooks.metadata.book.base import Metadata
        mi = Metadata(ext_api.field_for('title', book_id) or '',
                      list(ext_api.field_for('authors', book_id) or ()))
        mi.languages = list(ext_api.field_for('languages', book_id) or ())
        ids = find_identical_books(mi, datos_identicos)
        if not ids:
            return set(), set()
        fmts_origen = {f.upper() for f in (ext_api.formats(book_id, verify_formats=False) or ())}
        fmts_destino = set()
        for bid in ids:
            fmts_destino |= {f.upper() for f in (dest_api.formats(bid, verify_formats=False) or ())}
        return ids, fmts_origen - fmts_destino

    # ------------------------------------------------------------------ limpiar origen
    def limpiar_origen(self):
        """Elimina de la biblioteca externa los libros que ya existen en esta,
        siempre que aquí estén todos sus formatos (así no se pierde nada)."""
        target_path = self.obtener_ruta_externa()
        if not target_path:
            return
        self.current_target_path = target_path
        permanente = self.chk_permanente.isChecked()

        self.bloquear_botones(True)
        self.btn_import.setEnabled(False)
        self.lbl_info.setText("Buscando en la biblioteca externa los libros que ya están aquí...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        dest_api = self.gui.current_db.new_api
        ext_db = broker = None

        def analizar(ext_db):
            ext_api = ext_db.new_api
            datos = dest_api.data_for_find_identical_books()
            a_borrar, con_formatos_extra = [], []
            for book_id in ext_api.all_book_ids():
                ids, faltan = self.copia_en_destino(ext_api, dest_api, book_id, datos)
                if not ids:
                    continue
                titulo = f"{ext_api.field_for('title', book_id)} - " \
                         f"{' & '.join(ext_api.field_for('authors', book_id) or ())}"
                if faltan:
                    con_formatos_extra.append(f"{titulo}  (aquí falta: {', '.join(sorted(faltan))})")
                else:
                    a_borrar.append((book_id, titulo))
            return a_borrar, con_formatos_extra

        try:
            ext_db, broker = self.ejecutar_sin_congelar(self.abrir_biblioteca_origen, target_path)
            a_borrar, con_formatos_extra = self.ejecutar_sin_congelar(analizar, ext_db)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            error_dialog(self, "Error al analizar", "No se pudo analizar la biblioteca externa.",
                         det_msg=str(e), show=True)
            self.bloquear_botones(False)
            self.lbl_info.setText("")
            return
        QApplication.restoreOverrideCursor()

        borrados, error = 0, ""
        try:
            extra = ""
            if con_formatos_extra:
                extra = (f"\n\n{len(con_formatos_extra)} libros también están aquí, pero en la externa "
                         f"tienen formatos que aquí faltan: esos NO se borran.")
            if not a_borrar:
                info_dialog(self, "Nada para limpiar",
                            "No hay libros en la biblioteca externa que ya estén completos en esta." + extra,
                            det_msg="\n".join(con_formatos_extra), show=True)
                return

            destino_txt = "de forma DEFINITIVA" if permanente else "(a la papelera de Calibre de esa biblioteca)"
            detalle = "Se eliminarán:\n" + "\n".join(t for _, t in a_borrar)
            if con_formatos_extra:
                detalle += "\n\nNo se eliminarán (tienen formatos que aquí faltan):\n" + "\n".join(con_formatos_extra)
            if not question_dialog(
                    self, "Confirmar limpieza",
                    f"Se encontraron {len(a_borrar)} libros en\n{target_path}\n"
                    f"que ya existen en esta biblioteca con todos sus formatos.\n\n"
                    f"¿Eliminarlos de la biblioteca externa {destino_txt}?" + extra,
                    det_msg=detalle):
                return

            self.cancel_requested = False
            self.btn_cancel_import.setEnabled(True)
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            self.lbl_current_file.setVisible(True)
            ext_api = ext_db.new_api
            for n, (book_id, titulo) in enumerate(a_borrar):
                if self.cancel_requested:
                    break
                self.lbl_current_file.setText(f"🗑 {titulo}")
                try:
                    self.ejecutar_sin_congelar(ext_api.remove_books, [book_id], permanent=permanente)
                    borrados += 1
                except Exception as e:
                    error = str(e)
                    break
                self.progress_bar.setValue(int((n + 1) / len(a_borrar) * 100))
                self.lbl_info.setText(f"Eliminando de la biblioteca externa... {borrados}/{len(a_borrar)}")
        finally:
            self.progress_bar.setVisible(False)
            self.lbl_current_file.setVisible(False)
            self.btn_cancel_import.setEnabled(False)
            self.bloquear_botones(False)
            self.btn_import.setEnabled(bool(self.libros_faltantes))
            try:
                if broker is not None:
                    broker.prune_loaded_dbs()
                elif ext_db is not None:
                    ext_db.close()
            except Exception:
                traceback.print_exc()

        self.lbl_info.setText(f"Limpieza terminada: {borrados} libros eliminados de la biblioteca externa.")
        if error:
            error_dialog(self, "Error al eliminar",
                         f"Se eliminaron {borrados} libros y luego ocurrió un error.", det_msg=error, show=True)
        else:
            info_dialog(self, "Limpieza terminada",
                        f"Libros eliminados de la biblioteca externa: {borrados}"
                        + (f"\nNo eliminados (tienen formatos que aquí faltan): {len(con_formatos_extra)}"
                           if con_formatos_extra else ""),
                        det_msg="\n".join(con_formatos_extra), show=True)

    def importar_libros_faltantes(self):
        filas = {i.row() for i in self.table.selectionModel().selectedRows()}
        if filas:
            indices = sorted(self.table.item(r, 0).data(ROL_INDICE) for r in filas)
            items_a_procesar = [self.libros_faltantes[i] for i in indices]
        else:
            items_a_procesar = list(self.libros_faltantes)
        if not items_a_procesar:
            return

        eliminar_origen = self.chk_delete_source.isChecked()
        permanente = self.chk_permanente.isChecked()
        auto_continue = self.chk_auto_continue.isChecked()
        usar_copia_nativa = self.chk_fmt_todos.isChecked()

        if eliminar_origen and not question_dialog(
                self, "Confirmar mover",
                f"Se importarán {len(items_a_procesar)} libros y después se eliminarán de:\n"
                f"{self.current_target_path}\n\n¿Continuar?"):
            return

        self.btn_import.setEnabled(False)
        self.bloquear_botones(True)
        self.lbl_info.setText("Preparando (abriendo la biblioteca de origen y revisando duplicados)...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        dest_db = self.gui.current_db
        ext_db = broker = None
        try:
            ext_db, broker = self.ejecutar_sin_congelar(self.abrir_biblioteca_origen, self.current_target_path)
            # Datos para que Calibre detecte duplicados en el destino (se calcula una sola vez)
            datos_identicos = self.ejecutar_sin_congelar(dest_db.new_api.data_for_find_identical_books)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            error_dialog(self, "No se pudo preparar la importación",
                         "No se pudo abrir la biblioteca de origen con la API de Calibre.",
                         det_msg=str(e), show=True)
            self.btn_import.setEnabled(True)
            self.bloquear_botones(False)
            return
        QApplication.restoreOverrideCursor()

        self.cancel_requested = False
        self.btn_cancel_import.setEnabled(True)

        total_added_ids = []
        errores = []           # (título, mensaje)
        duplicados = []        # títulos que Calibre detectó como ya existentes en el destino
        borrados_completos = 0
        borrados_parciales = 0
        borrados_duplicados = 0
        error_borrado = ""

        batch_size = 50
        lotes = [items_a_procesar[i:i + batch_size] for i in range(0, len(items_a_procesar), batch_size)]
        total_lotes = len(lotes)

        try:
            for lote_idx, lote_items in enumerate(lotes):
                if self.cancel_requested:
                    break

                self.progress_bar.setValue(0)
                self.progress_bar.setVisible(True)
                self.lbl_current_file.setVisible(True)
                self.lbl_info.setText(f"Tanda {lote_idx + 1}/{total_lotes} - Importando a Calibre...")
                procesados = set()

                for n, item in enumerate(lote_items):
                    if self.cancel_requested or error_borrado:
                        break
                    self.lbl_current_file.setText(f"➕ {item['title']} - {item['author']}")
                    QApplication.processEvents()

                    # 1. Copiar el libro (en un hilo aparte, como hace Calibre)
                    try:
                        nuevo_id, accion = self.ejecutar_sin_congelar(
                            self.importar_uno, ext_db, dest_db, item, datos_identicos,
                            usar_copia_nativa, eliminar_origen)
                    except Exception as err:
                        errores.append((item['title'], str(err)))
                        print(err)
                        continue

                    procesados.add(id(item))
                    self.quitar_de_tabla(item)
                    self.lbl_info.setText(
                        f"Tanda {lote_idx + 1}/{total_lotes} - Importando a Calibre... "
                        f"(quedan {self.table.rowCount()} en la lista)")
                    if accion == 'duplicate':
                        duplicados.append(item['title'])
                        # Si se está moviendo y aquí ya está el libro con todos sus formatos,
                        # también se borra del origen (no se pierde nada).
                        if eliminar_origen:
                            try:
                                ids, faltan = self.copia_en_destino(
                                    ext_db.new_api, dest_db.new_api, item['external_id'], datos_identicos)
                                if ids and not faltan:
                                    ext_db.new_api.remove_books([item['external_id']], permanent=permanente)
                                    borrados_duplicados += 1
                            except Exception:
                                error_borrado = traceback.format_exc()
                                print(error_borrado)
                    elif nuevo_id:
                        total_added_ids.append(nuevo_id)
                        # 2. Mostrarlo en la lista principal de Calibre en el momento
                        self.mostrar_libro_agregado([nuevo_id])

                        # 3. Si se está moviendo, borrarlo del origen
                        if eliminar_origen:
                            try:
                                if self.eliminar_de_origen(ext_db, item, permanente) == 'completo':
                                    borrados_completos += 1
                                else:
                                    borrados_parciales += 1
                            except Exception:
                                error_borrado = traceback.format_exc()
                                print(error_borrado)

                    self.progress_bar.setValue(int((n + 1) / len(lote_items) * 100))

                # Quitar de la tabla lo ya procesado (agregado o detectado como duplicado)
                self.libros_faltantes = [it for it in self.libros_faltantes if id(it) not in procesados]
                self.poblar_tabla()
                self.progress_bar.setVisible(False)
                self.lbl_current_file.setVisible(False)

                if error_borrado:
                    break  # no seguir si el borrado del origen falla

                if lote_idx < total_lotes - 1 and not self.cancel_requested and not auto_continue:
                    if not question_dialog(
                            self, "Tanda completada",
                            f"Se completó la tanda {lote_idx + 1} de {total_lotes}.\n\n"
                            f"Libros importados hasta ahora: {len(total_added_ids)}\n"
                            f"¿Continuar con la siguiente tanda?"):
                        self.cancel_requested = True
        finally:
            self.progress_bar.setVisible(False)
            self.lbl_current_file.setVisible(False)
            try:
                if broker is not None:
                    broker.prune_loaded_dbs()
                elif ext_db is not None:
                    ext_db.close()
            except Exception:
                traceback.print_exc()

        if total_added_ids:
            self.mostrar_en_calibre(total_added_ids)

        self.btn_import.setEnabled(bool(self.libros_faltantes))
        self.bloquear_botones(False)
        self.btn_cancel_import.setEnabled(False)

        # --- Resumen ---
        resumen = [f"Libros importados: {len(total_added_ids)}",
                   f"Ya existían en esta biblioteca (no se agregaron): {len(duplicados)}",
                   f"Libros con errores: {len(errores)}"]
        if eliminar_origen:
            resumen.append(f"Eliminados del origen: {borrados_completos}")
            if borrados_duplicados:
                resumen.append(f"Eliminados del origen porque ya estaban aquí completos: {borrados_duplicados}")
            if borrados_parciales:
                resumen.append(f"Solo se quitaron los formatos importados (el libro conserva otros): {borrados_parciales}")
        detalle = "\n".join(f"{t}: {m}" for t, m in errores)
        if duplicados:
            detalle += "\n\nYa existían en esta biblioteca:\n" + "\n".join(duplicados)
        if error_borrado:
            detalle += "\n\nError al eliminar del origen:\n" + error_borrado

        if error_borrado:
            error_dialog(self, "Error al eliminar del origen",
                         "Los libros se importaron, pero no se pudieron eliminar de la biblioteca de origen.\n\n"
                         + "\n".join(resumen), det_msg=detalle, show=True)
        elif errores and not total_added_ids:
            error_dialog(self, "Error en la importación", "No se pudo importar ningún libro.\n\n"
                         + "\n".join(resumen), det_msg=detalle, show=True)
        else:
            titulo = "Importación detenida" if self.cancel_requested else "Importación completada"
            info_dialog(self, titulo, "\n".join(resumen), det_msg=detalle, show=True)
        self.accept()

    def mostrar_libro_agregado(self, ids):
        """Inserta en la vista principal de Calibre los libros recién agregados, con los
        mismos pasos que usa Calibre al añadir libros, para verlos aparecer en vivo."""
        try:
            vista = self.gui.library_view
            # 1. Avisar a la vista de datos que hay ids nuevos (se ponen arriba de la lista)
            self.gui.current_db.data.books_added(ids)
            # 2. Avisar al modelo de la tabla para que dibuje las filas nuevas
            vista.model().books_added(len(ids))
            # 3. Seleccionar y desplazarse al libro recién agregado
            vista.select_rows(ids, using_ids=True, change_current=True, scroll=True)
        except Exception:
            traceback.print_exc()
        QApplication.processEvents()

    def mostrar_en_calibre(self, ids):
        """Al terminar, filtra la vista para mostrar solo los libros recién agregados (marcándolos).
        No vuelve a llamar a books_added(): las filas ya se insertaron una por una."""
        try:
            self.gui.current_db.set_marked_ids(ids)
            self.gui.search.set_search_string('marked:true')
            self.gui.library_view.select_rows(ids)
        except Exception:
            traceback.print_exc()
        try:
            self.gui.tags_view.recount()
        except Exception:
            pass
