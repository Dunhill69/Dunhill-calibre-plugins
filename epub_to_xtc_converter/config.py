# -*- coding: utf-8 -*-

try:
    load_translations()
except NameError:
    pass

from qt.core import (QWidget, QVBoxLayout, QFormLayout, QGroupBox, QComboBox,
                     QSpinBox, QDoubleSpinBox, QCheckBox, QLabel, QHBoxLayout)

from calibre.utils.config import JSONConfig

from calibre_plugins.epub_to_xtc_converter.jobs import DEFAULTS

prefs = JSONConfig('plugins/EPUB to XTC Converter')
prefs.defaults.update(DEFAULTS)


def current_settings():
    return {k: prefs[k] for k in DEFAULTS}


class ConfigWidget(QWidget):

    def __init__(self, gui=None):
        QWidget.__init__(self)
        lay = QVBoxLayout(self)

        # --- Pantalla
        g = QGroupBox(_('Screen'), self)
        f = QFormLayout(g)
        self.mode = QComboBox(g)
        self.mode.addItem(_('4 shades of gray (.xtch) - better quality'), True)
        self.mode.addItem(_('Black and white (.xtc) - faster page turns'), False)
        self.mode.setCurrentIndex(0 if prefs['grayscale'] else 1)
        self.mode.currentIndexChanged.connect(self._update)
        f.addRow(_('Mode:'), self.mode)
        self.xtch_as_xtc = QCheckBox(_('Save 4-shade files with the .xtc extension'), g)
        self.xtch_as_xtc.setToolTip(_('For readers that only recognize .xtc files. The CrossPoint firmware '
                                      'opens them correctly either way.'))
        self.xtch_as_xtc.setChecked(prefs['xtch_as_xtc'])
        f.addRow(self.xtch_as_xtc)

        size = QHBoxLayout()
        self.width = self._spin(prefs['width'], 100, 2000, ' px')
        self.height = self._spin(prefs['height'], 100, 2000, ' px')
        size.addWidget(self.width)
        size.addWidget(QLabel('×'))
        size.addWidget(self.height)
        size.addStretch(1)
        f.addRow(_('Resolution:'), size)
        self.dpi = self._spin(prefs['dpi'], 72, 600, ' ppi')
        self.dpi.setToolTip(_('Pixel density of the screen. Xteink X4: 480×800 at 220 ppi.'))
        f.addRow(_('Density:'), self.dpi)
        lay.addWidget(g)

        # --- Texto
        g = QGroupBox(_('Text and layout'), self)
        f = QFormLayout(g)
        self.font_size = self._spin(prefs['font_size'], 6, 60, ' px')
        self.font_size.setToolTip(_('Base font size. Larger values mean bigger letters and more pages.'))
        f.addRow(_('Font size:'), self.font_size)
        self.margin_lr = self._dspin(prefs['margin_lr'])
        f.addRow(_('Side margins:'), self.margin_lr)
        self.margin_tb = self._dspin(prefs['margin_tb'])
        f.addRow(_('Top and bottom margins:'), self.margin_tb)
        self.hyphenate = QCheckBox(_('Hyphenate words at the end of lines'), g)
        self.hyphenate.setChecked(prefs['hyphenate'])
        f.addRow(self.hyphenate)
        self.justify = QCheckBox(_('Justify text'), g)
        self.justify.setChecked(prefs['justify'])
        f.addRow(self.justify)
        self.remove_spacing = QCheckBox(_('Remove spacing between paragraphs'), g)
        self.remove_spacing.setChecked(prefs['remove_spacing'])
        f.addRow(self.remove_spacing)
        self.page_numbers = QCheckBox(_('Print page numbers at the bottom'), g)
        self.page_numbers.setChecked(prefs['page_numbers'])
        f.addRow(self.page_numbers)
        self.toc_levels = self._spin(prefs['toc_levels'], 1, 6, '')
        self.toc_levels.setToolTip(_('How many levels of the table of contents are used as chapters on the reader.'))
        f.addRow(_('Table of contents levels:'), self.toc_levels)
        lay.addWidget(g)

        # --- Imagen
        g = QGroupBox(_('Image'), self)
        f = QFormLayout(g)
        self.dither = QCheckBox(_('Dithering (recommended for illustrated books and comics)'), g)
        self.dither.setToolTip(_('Simulates intermediate tones with dot patterns. '
                                 'Improves pictures but makes text slightly less sharp.'))
        self.dither.setChecked(prefs['dither'])
        self.dither.toggled.connect(self._update)
        f.addRow(self.dither)
        self.threshold = self._spin(prefs['threshold'], 1, 254, '')
        self.threshold.setToolTip(_('Black and white mode only: higher values make text darker and thicker.'))
        f.addRow(_('Black/white threshold:'), self.threshold)
        lay.addWidget(g)
        lay.addStretch(1)
        self._update()

    def _spin(self, val, lo, hi, suffix):
        s = QSpinBox(self)
        s.setRange(lo, hi)
        s.setValue(int(val))
        if suffix:
            s.setSuffix(suffix)
        return s

    def _dspin(self, val):
        s = QDoubleSpinBox(self)
        s.setRange(0, 100)
        s.setDecimals(1)
        s.setSingleStep(1)
        s.setSuffix(' pt')
        s.setValue(float(val))
        return s

    def _update(self, *a):
        self.threshold.setEnabled(not self.mode.currentData() and not self.dither.isChecked())
        self.xtch_as_xtc.setEnabled(bool(self.mode.currentData()))

    def save_settings(self):
        prefs['grayscale'] = bool(self.mode.currentData())
        prefs['xtch_as_xtc'] = self.xtch_as_xtc.isChecked()
        prefs['width'] = self.width.value()
        prefs['height'] = self.height.value()
        prefs['dpi'] = self.dpi.value()
        prefs['font_size'] = self.font_size.value()
        prefs['margin_lr'] = self.margin_lr.value()
        prefs['margin_tb'] = self.margin_tb.value()
        prefs['hyphenate'] = self.hyphenate.isChecked()
        prefs['remove_spacing'] = self.remove_spacing.isChecked()
        prefs['justify'] = self.justify.isChecked()
        prefs['page_numbers'] = self.page_numbers.isChecked()
        prefs['dither'] = self.dither.isChecked()
        prefs['threshold'] = self.threshold.value()
        prefs['toc_levels'] = self.toc_levels.value()
