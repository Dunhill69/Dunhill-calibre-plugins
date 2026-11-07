try:
    load_translations()
except NameError:
    pass

from qt.core import (
    QWidget, QVBoxLayout, QFormLayout, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox,
    QLabel, QPushButton, QHBoxLayout, QGroupBox, QLineEdit
)
from calibre.gui2 import info_dialog, error_dialog

from calibre_plugins.goodreads_series_explorer.prefs import prefs, DEFAULTS
from calibre_plugins.goodreads_series_explorer import lang


def modes():
    return [
        ('auto', _('Automatic: normal connection and, if Goodreads blocks it, calibre\'s built-in browser')),
        ('browser', _('Always calibre\'s built-in browser (slower, but gets past the blocks)')),
        ('normal', _('Normal connection only')),
    ]


class ConfigWidget(QWidget):
    def __init__(self):
        super().__init__()
        p = prefs()
        layout = QVBoxLayout(self)

        # ---- conexión
        box = QGroupBox(_('Connection to Goodreads'))
        form = QFormLayout(box)
        self.mode = QComboBox()
        keys = []
        for key, text in modes():
            self.mode.addItem(text, key)
            keys.append(key)
        self.mode.setCurrentIndex(keys.index(p['connection_mode']) if p['connection_mode'] in keys else 0)
        form.addRow(_('Mode:'), self.mode)

        self.pause = QDoubleSpinBox()
        self.pause.setRange(0.5, 10.0)
        self.pause.setSingleStep(0.5)
        self.pause.setDecimals(1)
        self.pause.setSuffix(' s')
        self.pause.setValue(float(p['request_pause']))
        form.addRow(_('Pause between requests:'), self.pause)

        self.max_pages = QSpinBox()
        self.max_pages.setRange(0, 100)
        self.max_pages.setValue(int(p['max_new_pages']))
        form.addRow(_('New pages of your books read per opening:'), self.max_pages)

        hint = QLabel(_('A longer pause and fewer pages per opening mean fewer Goodreads blocks, '
                        'but the first load of each series takes longer. calibre\'s built-in browser '
                        'looks more like a real browser: from calibre 9.17 on it is Camoufox, which '
                        'gets past the Goodreads anti-bot checks (the first time it takes a while '
                        'to open and, if it was never used, calibre downloads it); in earlier '
                        'versions it is calibre\'s Chromium browser.'))
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #666;')
        form.addRow(hint)
        layout.addWidget(box)

        # ---- búsqueda
        box = QGroupBox(_('Search'))
        form = QFormLayout(box)
        self.language = QComboBox()
        ui_code = lang.calibre_language()
        self.language.addItem(_('Same as calibre ({0})').format(lang.display_name(ui_code)), 'auto')
        for code in sorted(lang.CHOICES, key=lambda c: lang.display_name(c).lower()):
            self.language.addItem(lang.display_name(code)[:1].upper() + lang.display_name(code)[1:], code)
        idx = self.language.findData(p['edition_language'])
        self.language.setCurrentIndex(idx if idx >= 0 else 0)
        self.language.setToolTip(_('Language of the editions looked up on Goodreads: titles, covers '
                                   'and synopses of the books you are missing are shown in this '
                                   'language when such an edition exists.'))
        form.addRow(_('Language of the editions:'), self.language)
        self.auto_spanish = QCheckBox(_('Automatically look up the edition in that language for missing books'))
        self.auto_spanish.setChecked(bool(p['auto_spanish']))
        self.auto_spanish.setToolTip(_('If you turn it off far fewer requests are made: the missing books '
                                       'are shown with their original title and a button to look them up.'))
        form.addRow(self.auto_spanish)
        self.wish_tag = QLineEdit()
        tag = p['wishlist_tag']
        self.wish_tag.setText(_('To get') if tag is None else tag)
        self.wish_tag.setPlaceholderText(_('(no tag)'))
        self.wish_tag.setToolTip(_('Tag added to the empty entries you create for the books you are '
                                   'missing, so you can find your wishlist in the Tag browser. '
                                   'Leave it empty to add no tag.'))
        form.addRow(_('Tag for empty entries:'), self.wish_tag)
        layout.addWidget(box)

        # ---- caché
        box = QGroupBox(_('Cache'))
        form = QFormLayout(box)
        days = ' ' + _('days')
        self.days_series = QSpinBox()
        self.days_series.setRange(0, 60)
        self.days_series.setSuffix(days)
        self.days_series.setValue(int(p['cache_days_series']))
        form.addRow(_('Series and author lists:'), self.days_series)
        self.days_other = QSpinBox()
        self.days_other.setRange(0, 365)
        self.days_other.setSuffix(days)
        self.days_other.setValue(int(p['cache_days_other']))
        form.addRow(_('Book pages, searches and editions:'), self.days_other)
        row = QHBoxLayout()
        clear = QPushButton(_('Clear cache'))
        clear.clicked.connect(self.clear_cache)
        row.addWidget(clear)
        reset = QPushButton(_('Restore defaults'))
        reset.clicked.connect(self.reset)
        row.addWidget(reset)
        row.addStretch()
        form.addRow(row)
        layout.addWidget(box)
        layout.addStretch()

    def reset(self):
        self.mode.setCurrentIndex(max(0, self.mode.findData(DEFAULTS['connection_mode'])))
        self.pause.setValue(DEFAULTS['request_pause'])
        self.max_pages.setValue(DEFAULTS['max_new_pages'])
        self.language.setCurrentIndex(max(0, self.language.findData(DEFAULTS['edition_language'])))
        self.auto_spanish.setChecked(DEFAULTS['auto_spanish'])
        self.wish_tag.setText(_('To get'))
        self.days_series.setValue(DEFAULTS['cache_days_series'])
        self.days_other.setValue(DEFAULTS['cache_days_other'])

    def clear_cache(self):
        from calibre_plugins.goodreads_series_explorer.worker import clear_cache
        try:
            count = clear_cache()
        except Exception as e:
            error_dialog(self, _('Error'), _('Could not clear the cache: {0}').format(e), show=True)
            return
        info_dialog(self, _('Cache'), _('{0} saved pages were deleted.').format(count), show=True)

    def save_settings(self):
        p = prefs()
        p['connection_mode'] = self.mode.currentData()
        p['request_pause'] = float(self.pause.value())
        p['max_new_pages'] = int(self.max_pages.value())
        p['edition_language'] = self.language.currentData()
        p['auto_spanish'] = self.auto_spanish.isChecked()
        tag = self.wish_tag.text().strip()
        # Si queda la predeterminada se guarda None, así sigue el idioma de calibre
        p['wishlist_tag'] = None if tag == _('To get') else tag
        p['cache_days_series'] = int(self.days_series.value())
        p['cache_days_other'] = int(self.days_other.value())
