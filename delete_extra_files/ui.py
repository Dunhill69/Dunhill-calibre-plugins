# -*- coding: utf-8 -*-

import os
import shutil

try:
    load_translations()
except NameError:
    pass

try:
    _
except NameError:
    def _(s):
        return s

try:
    from qt.core import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QListWidget, QListWidgetItem, 
        QAbstractItemView, QMessageBox, Qt
    )
except ImportError:
    from PyQt5.Qt import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QListWidget, QListWidgetItem, 
        QAbstractItemView, QMessageBox, Qt
    )


class DeleteExtraFilesDialog(QDialog):
    def __init__(self, gui, db):
        super().__init__(gui)
        self.gui = gui
        self.db = db
        self.extra_files_map = {} 
        
        self.init_ui()
        self.scan_library()

    def init_ui(self):
        self.setWindowTitle(_('Selective Extra Files Cleaner - Calibre'))
        self.resize(640, 480)
        
        layout = QVBoxLayout(self)
        
        self.label_status = QLabel(_('Scanning library for extra files...'))
        layout.addWidget(self.label_status)
        
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.list_widget)
        
        layout_buttons = QHBoxLayout()
        self.btn_select_all = QPushButton(_('Select all'))
        self.btn_select_all.clicked.connect(self.select_all_items)
        self.btn_select_all.setEnabled(False)
        
        self.btn_deselect_all = QPushButton(_('Deselect all'))
        self.btn_deselect_all.clicked.connect(self.deselect_all_items)
        self.btn_deselect_all.setEnabled(False)
        
        layout_buttons.addWidget(self.btn_select_all)
        layout_buttons.addWidget(self.btn_deselect_all)
        layout.addLayout(layout_buttons)
        
        self.btn_delete = QPushButton(_('Delete selected extra files'))
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self.delete_files)
        layout.addWidget(self.btn_delete)

    def scan_library(self):
        self.extra_files_map.clear()
        self.list_widget.clear()
        
        db_view = self.db.new_api
        all_ids = db_view.all_book_ids()
        
        for book_id in all_ids:
            try:
                book_id_int = int(book_id)
                archivos_raw = []
                
                if hasattr(db_view, 'list_extra_files'):
                    archivos_raw = db_view.list_extra_files(book_id_int) or []
                elif hasattr(db_view, 'list_data_files'):
                    archivos_raw = db_view.list_data_files(book_id_int) or []

                if archivos_raw:
                    archivos_clean = []
                    for item in archivos_raw:
                        if isinstance(item, str):
                            clean_str = item
                        elif isinstance(item, dict) and 'name' in item:
                            clean_str = str(item['name'])
                        elif isinstance(item, (tuple, list)):
                            clean_str = str(item[0])
                        else:
                            clean_str = str(item)
                        
                        # Intercepta y traduce el aviso nativo de Calibre sobre mayúsculas/minúsculas
                        clean_str = clean_str.replace('Conflicto de mayúsculas y minúsculas', _('Case conflict'))
                        
                        archivos_clean.append(clean_str)

                    if archivos_clean:
                        title = self.db.title(book_id_int, index_is_id=True)
                        self.extra_files_map[book_id_int] = {
                            'raw': archivos_raw,
                            'clean': archivos_clean
                        }
                        
                        archivos_str = ", ".join(archivos_clean)
                        item_text = _('ID: {0} - {1} ({2} files: {3})').format(book_id_int, title, len(archivos_clean), archivos_str)
                        
                        list_item = QListWidgetItem(item_text)
                        list_item.setData(Qt.UserRole, book_id_int)
                        list_item.setFlags(list_item.flags() | Qt.ItemIsUserCheckable)
                        list_item.setCheckState(Qt.Checked)
                        
                        self.list_widget.addItem(list_item)

            except Exception as e:
                print(f"Error processing book {book_id}: {e}")
                continue
                
        count = len(self.extra_files_map)
        if count > 0:
            self.label_status.setText(_('Found {0} books with extra files:').format(count))
            self.btn_delete.setEnabled(True)
            self.btn_select_all.setEnabled(True)
            self.btn_deselect_all.setEnabled(True)
        else:
            self.label_status.setText(_('Great! No extra files found in the library.'))

    def select_all_items(self):
        for index in range(self.list_widget.count()):
            self.list_widget.item(index).setCheckState(Qt.Checked)

    def deselect_all_items(self):
        for index in range(self.list_widget.count()):
            self.list_widget.item(index).setCheckState(Qt.Unchecked)

    def delete_files(self):
        selected_book_ids = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.Checked:
                val = item.data(Qt.UserRole)
                if val is not None:
                    selected_book_ids.append(int(val))
                
        if not selected_book_ids:
            QMessageBox.warning(self, _('Warning'), _('No books selected for cleaning.'))
            return

        confirm = QMessageBox.question(
            self, 
            _('Confirm deletion'), 
            _('Are you sure you want to permanently delete the extra files from the {0} selected books?').format(len(selected_book_ids)),
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        
        if confirm != QMessageBox.Yes:
            return
            
        db_view = self.db.new_api
        deleted_count = 0
        
        for book_id in selected_book_ids:
            if book_id in self.extra_files_map:
                book_info = self.extra_files_map[book_id]
                clean_files = book_info['clean']
                raw_files = book_info['raw']

                # 1. Borrado via API con objetos/tuplas originales
                try:
                    if hasattr(db_view, 'remove_extra_files'):
                        db_view.remove_extra_files(book_id, raw_files)
                except Exception:
                    pass

                # 2. Borrado via API con rutas limpias (strings)
                try:
                    if hasattr(db_view, 'remove_extra_files'):
                        db_view.remove_extra_files(book_id, clean_files)
                except Exception:
                    pass

                # 3. Borrado de data_files en subcarpeta data/
                try:
                    if hasattr(db_view, 'remove_data_file'):
                        for rel_file in clean_files:
                            fname = rel_file.replace('data/', '').replace('data\\', '')
                            try:
                                db_view.remove_data_file(book_id, fname)
                            except Exception:
                                pass
                except Exception:
                    pass

                # 4. Borrado físico asegurado en el sistema operativo (Linux/Windows)
                try:
                    book_path = self.db.abspath(book_id, index_is_id=True)
                    
                    if book_path and os.path.exists(book_path):
                        # A. Borrar los archivos sueltos
                        for rel_file in clean_files:
                            full_path = os.path.join(book_path, rel_file)
                            if os.path.exists(full_path):
                                try:
                                    os.remove(full_path)
                                except Exception:
                                    pass

                        # B. Aniquilación de la subcarpeta 'data' completa
                        data_dir = os.path.join(book_path, 'data')
                        if os.path.exists(data_dir):
                            try:
                                shutil.rmtree(data_dir, ignore_errors=True)
                            except Exception:
                                pass

                        # C. Limpieza final de cualquier otra carpeta que haya quedado vacía
                        for root, dirs, dummy_files in os.walk(book_path, topdown=False):
                            for d in dirs:
                                dir_path = os.path.join(root, d)
                                try:
                                    if os.path.exists(dir_path) and not os.listdir(dir_path):
                                        os.rmdir(dir_path)
                                except Exception:
                                    pass

                except Exception as e:
                    print(f"Error getting physical path for book {book_id}: {e}")

                deleted_count += 1
                
        QMessageBox.information(self, _('Process completed'), _('Successfully cleaned extra files from {0} books.').format(deleted_count))
        
        self.gui.library_view.model().refresh()
        self.accept()
