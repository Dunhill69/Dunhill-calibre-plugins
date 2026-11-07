# -*- coding: utf-8 -*-

try:
    load_translations()
except NameError:
    pass

try:
    from qt.core import (QHBoxLayout, QLabel, QVBoxLayout, QWidget, QCheckBox,
                         QGroupBox, QPushButton, QLineEdit, QFileDialog)
except ImportError:
    from PyQt5.Qt import (QHBoxLayout, QLabel, QVBoxLayout, QWidget, QCheckBox,
                          QGroupBox, QPushButton, QLineEdit, QFileDialog)

from calibre.utils.config import JSONConfig

plugin_prefs = JSONConfig('plugins/integrity_analysis_prefs')

plugin_prefs.defaults['check_missing_formats'] = True
plugin_prefs.defaults['check_empty_records'] = True
plugin_prefs.defaults['check_missing_covers'] = True
plugin_prefs.defaults['only_cover_if_db_has_cover'] = False
plugin_prefs.defaults['check_missing_opf'] = True
plugin_prefs.defaults['auto_show_error_log'] = True
plugin_prefs.defaults['auto_mark_books'] = True
plugin_prefs.defaults['use_exclusions'] = True
plugin_prefs.defaults['exclusions_file'] = ''


class ConfigWidget(QWidget):

    def __init__(self, plugin):
        super(ConfigWidget, self).__init__()
        self.plugin = plugin
        self.initialize_ui()

    def initialize_ui(self):
        layout = QVBoxLayout(self)

        # --- Comprobaciones ---
        group_box = QGroupBox(_('Library Integrity Settings'), self)
        group_layout = QVBoxLayout(group_box)

        self.chk_formats = QCheckBox(_('Check for missing or empty book formats (EPUB, PDF, etc.)'), self)
        self.chk_formats.setChecked(plugin_prefs['check_missing_formats'])
        group_layout.addWidget(self.chk_formats)

        self.chk_empty = QCheckBox(_('Report books without any format (empty records)'), self)
        self.chk_empty.setToolTip(_('Uncheck this if you keep metadata-only records on purpose.'))
        self.chk_empty.setChecked(plugin_prefs['check_empty_records'])
        group_layout.addWidget(self.chk_empty)

        self.chk_covers = QCheckBox(_('Check for missing cover.jpg files in book folders'), self)
        self.chk_covers.setChecked(plugin_prefs['check_missing_covers'])
        group_layout.addWidget(self.chk_covers)

        self.chk_cover_db = QCheckBox(_('Only report a missing cover.jpg if calibre says the book has a cover'), self)
        self.chk_cover_db.setChecked(plugin_prefs['only_cover_if_db_has_cover'])
        group_layout.addWidget(self.chk_cover_db)

        self.chk_opf = QCheckBox(_('Check for missing or corrupted metadata.opf files'), self)
        self.chk_opf.setChecked(plugin_prefs['check_missing_opf'])
        group_layout.addWidget(self.chk_opf)

        layout.addWidget(group_box)

        # --- Resultado ---
        out_box = QGroupBox(_('After the scan'), self)
        out_layout = QVBoxLayout(out_box)

        self.chk_log = QCheckBox(_('Automatically show error logs and report summaries after scan'), self)
        self.chk_log.setChecked(plugin_prefs['auto_show_error_log'])
        out_layout.addWidget(self.chk_log)

        self.chk_mark = QCheckBox(_('Automatically mark problematic books and show them in the library'), self)
        self.chk_mark.setChecked(plugin_prefs['auto_mark_books'])
        out_layout.addWidget(self.chk_mark)

        layout.addWidget(out_box)

        # --- Exclusiones ---
        ex_box = QGroupBox(_('Exclusions'), self)
        ex_layout = QVBoxLayout(ex_box)

        self.chk_excl = QCheckBox(_('Apply the exclusions file during the scan'), self)
        self.chk_excl.setChecked(plugin_prefs['use_exclusions'])
        ex_layout.addWidget(self.chk_excl)

        ex_layout.addWidget(QLabel(_('Exclusions file (leave empty to use the default location):'), self))
        row = QHBoxLayout()
        self.txt_file = QLineEdit(self)
        from calibre_plugins.integrity_analysis.exclusions import DEFAULT_FILE
        self.txt_file.setPlaceholderText(DEFAULT_FILE)
        self.txt_file.setText(plugin_prefs['exclusions_file'])
        row.addWidget(self.txt_file)
        btn = QPushButton(_('Browse...'), self)
        btn.clicked.connect(self.browse_file)
        row.addWidget(btn)
        ex_layout.addLayout(row)

        layout.addWidget(ex_box)
        layout.addStretch(1)


    def browse_file(self):
        path, _f = QFileDialog.getSaveFileName(
            self, _('Choose exclusions file'),
            self.txt_file.text() or 'integrity_analysis_exclusions.json',
            'JSON (*.json);;All Files (*)',
            options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            self.txt_file.setText(path)

    def save_settings(self):
        plugin_prefs['check_missing_formats'] = self.chk_formats.isChecked()
        plugin_prefs['check_empty_records'] = self.chk_empty.isChecked()
        plugin_prefs['check_missing_covers'] = self.chk_covers.isChecked()
        plugin_prefs['only_cover_if_db_has_cover'] = self.chk_cover_db.isChecked()
        plugin_prefs['check_missing_opf'] = self.chk_opf.isChecked()
        plugin_prefs['auto_show_error_log'] = self.chk_log.isChecked()
        plugin_prefs['auto_mark_books'] = self.chk_mark.isChecked()
        plugin_prefs['use_exclusions'] = self.chk_excl.isChecked()
        plugin_prefs['exclusions_file'] = self.txt_file.text().strip()
