#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

from qt.core import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
                     QCheckBox, QLineEdit, QSpinBox, QComboBox, QLabel)

from calibre_plugins.synopsis_page.prefs import prefs

try:
    load_translations()
except NameError:
    pass


class ConfigWidget(QWidget):

    def __init__(self):
        QWidget.__init__(self)
        lay = QVBoxLayout(self)

        # --- Content ---
        g = QGroupBox(_('Page content'))
        f = QFormLayout(g)
        self.include_cover = QCheckBox(_('Include the cover'))
        self.show_title = QCheckBox(_('Show the title'))
        self.show_authors = QCheckBox(_('Show the author'))
        self.show_series = QCheckBox(_('Show the series'))
        self.show_heading = QCheckBox(_('Heading before the text:'))
        self.heading_text = QLineEdit()
        for w in (self.include_cover, self.show_title, self.show_authors, self.show_series):
            f.addRow(w)
        f.addRow(self.show_heading, self.heading_text)
        self.show_heading.toggled.connect(self.heading_text.setEnabled)
        lay.addWidget(g)

        # --- Look ---
        g = QGroupBox(_('Look'))
        f = QFormLayout(g)
        self.cover_width = QSpinBox()
        self.cover_width.setRange(10, 100)
        self.cover_width.setSuffix(' %')
        f.addRow(_('Cover width:'), self.cover_width)
        self.cover_style = QComboBox()
        for key, text in (('none', _('No border')), ('line', _('Thin border')),
                          ('shadow', _('Border with shadow'))):
            self.cover_style.addItem(text, key)
        f.addRow(_('Cover frame:'), self.cover_style)
        self.cover_position = QComboBox()
        for key, text in (('top', _('Top, centered')),
                          ('left', _('Left, with text wrapping around it')),
                          ('right', _('Right, with text wrapping around it')),
                          ('bottom', _('Bottom, after the synopsis'))):
            self.cover_position.addItem(text, key)
        f.addRow(_('Cover position:'), self.cover_position)
        self.cover_after_par = QSpinBox()
        self.cover_after_par.setRange(0, 50)
        self.cover_after_par.setSpecialValueText(_('At the start of the text'))
        self.cover_after_par.setPrefix(_('After paragraph '))
        self.cover_after_par.setToolTip(
            _('Useful when the synopsis starts with centered lines: the cover '
              'goes after them, next to the first paragraph of the text.'))
        f.addRow(_('Floating cover:'), self.cover_after_par)
        self.cover_position.currentIndexChanged.connect(self._position_changed)
        self.justify = QCheckBox(_('Justified text'))
        self.indent = QCheckBox(_('Indent paragraphs'))
        f.addRow(self.justify)
        f.addRow(self.indent)
        lay.addWidget(g)

        # --- Placement ---
        g = QGroupBox(_('Placement in the book'))
        f = QFormLayout(g)
        self.position = QComboBox()
        for key, text in (('after_cover', _('After the cover')),
                          ('start', _('At the start of the book')),
                          ('end', _('At the end of the book'))):
            self.position.addItem(text, key)
        f.addRow(_('Insert the page:'), self.position)
        fmts = QHBoxLayout()
        self.fmt_epub = QCheckBox('EPUB')
        self.fmt_azw3 = QCheckBox('AZW3')
        fmts.addWidget(self.fmt_epub)
        fmts.addWidget(self.fmt_azw3)
        fmts.addStretch(1)
        f.addRow(_('Formats to modify:'), fmts)
        self.add_to_toc = QCheckBox(_('Add it to the Table of Contents as:'))
        self.toc_title = QLineEdit()
        f.addRow(self.add_to_toc, self.toc_title)
        self.add_to_toc.toggled.connect(self.toc_title.setEnabled)
        lay.addWidget(g)

        # --- Safety ---
        self.backup = QCheckBox(_('Save an ORIGINAL_EPUB / ORIGINAL_AZW3 copy before '
                                  'modifying (only if the book has none)'))
        lay.addWidget(self.backup)
        note = QLabel(_('The synopsis is taken from the <b>Comments</b> field and '
                        'the cover from the book cover in calibre.'))
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)

        self.load_settings()

    def _position_changed(self, *a):
        self.cover_after_par.setEnabled(
            self.cover_position.currentData() in ('left', 'right'))

    def _set_combo(self, combo, value):
        i = combo.findData(value)
        combo.setCurrentIndex(max(0, i))

    def load_settings(self):
        self.include_cover.setChecked(prefs['include_cover'])
        self.show_title.setChecked(prefs['show_title'])
        self.show_authors.setChecked(prefs['show_authors'])
        self.show_series.setChecked(prefs['show_series'])
        self.show_heading.setChecked(prefs['show_heading'])
        self.heading_text.setText(prefs['heading_text'])
        self.heading_text.setEnabled(prefs['show_heading'])
        self.cover_width.setValue(int(prefs['cover_width']))
        self._set_combo(self.cover_style, prefs['cover_style'])
        self._set_combo(self.cover_position, prefs['cover_position'])
        self.cover_after_par.setValue(int(prefs['cover_after_par']))
        self._position_changed()
        fm = prefs['formats']
        self.fmt_epub.setChecked('EPUB' in fm)
        self.fmt_azw3.setChecked('AZW3' in fm)
        self.justify.setChecked(prefs['justify'])
        self.indent.setChecked(prefs['indent'])
        self._set_combo(self.position, prefs['position'])
        self.add_to_toc.setChecked(prefs['add_to_toc'])
        self.toc_title.setText(prefs['toc_title'])
        self.toc_title.setEnabled(prefs['add_to_toc'])
        self.backup.setChecked(prefs['backup'])

    def save_settings(self):
        prefs['include_cover'] = self.include_cover.isChecked()
        prefs['show_title'] = self.show_title.isChecked()
        prefs['show_authors'] = self.show_authors.isChecked()
        prefs['show_series'] = self.show_series.isChecked()
        prefs['show_heading'] = self.show_heading.isChecked()
        prefs['heading_text'] = self.heading_text.text().strip() or _('Synopsis')
        prefs['cover_width'] = self.cover_width.value()
        prefs['cover_style'] = self.cover_style.currentData()
        prefs['cover_position'] = self.cover_position.currentData()
        prefs['cover_after_par'] = self.cover_after_par.value()
        fm = [f for f, w in (('EPUB', self.fmt_epub), ('AZW3', self.fmt_azw3))
              if w.isChecked()]
        prefs['formats'] = fm or ['EPUB']
        prefs['justify'] = self.justify.isChecked()
        prefs['indent'] = self.indent.isChecked()
        prefs['position'] = self.position.currentData()
        prefs['add_to_toc'] = self.add_to_toc.isChecked()
        prefs['toc_title'] = self.toc_title.text().strip() or _('Synopsis')
        prefs['backup'] = self.backup.isChecked()
