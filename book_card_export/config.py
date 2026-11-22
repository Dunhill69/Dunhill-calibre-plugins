#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

from calibre.utils.config import JSONConfig

DEFAULT_EMOJI = '▪️'
from qt.core import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QIcon, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QMenu, QPushButton, QSize, Qt, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

try:
    load_translations()
except NameError:
    pass

prefs = JSONConfig('plugins/Book Card Export')
prefs.defaults['premium'] = False
prefs.defaults['emojis'] = True
prefs.defaults['hashtags'] = False
prefs.defaults['theme'] = 'light'
prefs.defaults['background'] = 'theme'   # theme | custom | transparent
prefs.defaults['bg_color'] = '#fdf6e3'
prefs.defaults['footer'] = True
prefs.defaults['fields'] = None          # None = use the fields shown by calibre
prefs.defaults['emoji_map'] = ''        # old text format, still read
prefs.defaults['field_emojis'] = {}     # field key -> emoji ('' = none)
prefs.defaults['custom_emojis'] = []    # user's own palette
prefs.defaults['tag_emojis'] = {}       # tag name -> emoji
prefs.defaults['tg_tag_emojis'] = True  # emoji on each genre in the Telegram text
prefs.defaults['card_emojis'] = False   # emoji in front of each field in the card image
prefs.defaults['card_tag_emojis'] = False  # emoji on each genre in the card image
prefs.defaults['extra_css'] = ''
prefs.defaults['card_width'] = 1000
prefs.defaults['cover_width'] = 380
prefs.defaults['image_format'] = 'png'

# Fields that never go in the field list (they have their own place in the card)
EXCLUDED = frozenset(('title', 'authors', 'comments', 'path', 'cover',
                      'ondevice', 'marked', 'id', 'sort', 'author_sort',
                      'au_map', 'series_index'))


# (label, background color, text theme) - colors of Telegram Desktop and others
PRESETS = (
    (_('Telegram dark: chat background'), '#0e1621', 'dark'),
    (_('Telegram dark: message'), '#182533', 'dark'),
    (_('Telegram dark: my message'), '#2b5278', 'dark'),
    (_('Telegram light: white'), '#ffffff', 'light'),
    (_('Telegram light: my message'), '#effdde', 'light'),
    (_('Sepia'), '#f4ecd8', 'light'),
    (_('Black'), '#000000', 'dark'),
)


def calibre_field_list(db):
    '''[(field, visible)] in the order of calibre's book details panel.'''
    fm = db.field_metadata
    result = None
    try:
        from calibre.gui2.book_details import get_field_list
        result = list(get_field_list(fm))
    except Exception:
        result = None
    if not result:
        val = None
        try:
            val = db.prefs.get('book_display_fields')
        except Exception:
            pass
        if not val:
            try:
                from calibre.gui2 import gprefs
                val = gprefs.get('book_display_fields')
            except Exception:
                val = None
        if val:
            result = [(f, v) for f, v in val if f in fm]
        else:
            result = [(f, True) for f in ('series', 'tags', 'publisher',
                                          'pubdate', 'rating', 'languages')]
    return [(f, v) for f, v in result if f not in EXCLUDED and f in fm]


def active_fields(db):
    chosen = prefs['fields']
    fm = db.field_metadata
    if chosen is None:
        return [f for f, v in calibre_field_list(db) if v]
    return [f for f in chosen if f in fm and f not in EXCLUDED]


def default_emojis():
    from calibre_plugins.book_card_export.tgtext import STANDARD_EMOJIS
    d = dict(STANDARD_EMOJIS)
    d['title'] = '📖'
    d['authors'] = '✍️'
    return d


def tag_emoji_map():
    return {k.lower(): v for k, v in (prefs['tag_emojis'] or {}).items() if v}


def emoji_map():
    '''Final map used for the Telegram text (keys in lower case).'''
    m = parse_emoji_map(prefs['emoji_map'])
    for k, v in (prefs['field_emojis'] or {}).items():
        m[k.lower()] = v
    return m


def parse_emoji_map(text):
    '''Lines like "#pages=📄" or "Páginas=📄" -> {key_or_name: emoji}.'''
    res = {}
    for line in (text or '').splitlines():
        line = line.strip()
        if not line or line.startswith('//') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        k, v = k.strip(), v.strip()
        if k:
            res[k.lower()] = v
    return res


class ConfigWidget(QWidget):

    def __init__(self):
        QWidget.__init__(self)
        from calibre.gui2.ui import get_gui
        self.gui = get_gui()
        self.db = self.gui.current_db if self.gui is not None else None

        l = QVBoxLayout(self)
        tabs = QTabWidget(self)
        l.addWidget(tabs)

        # ---- General
        gen = QWidget()
        gl = QVBoxLayout(gen)

        g1 = QGroupBox(_('Card image'))
        f1 = QFormLayout(g1)
        self.background = QComboBox()
        self.background.addItem(_('According to the theme'), 'theme')
        self.background.addItem(_('Custom color'), 'custom')
        self.background.addItem(_('Transparent'), 'transparent')
        i = self.background.findData(prefs['background'])
        self.background.setCurrentIndex(max(0, i))
        self.bg_color = prefs['bg_color']
        self.color_btn = QPushButton()
        self.color_btn.setToolTip(_('Choose the background color'))
        self.color_btn.clicked.connect(self.choose_color)
        self.presets_btn = QToolButton()
        self.presets_btn.setText(_('Quick colors'))
        self.presets_btn.setToolTip(_('Background colors that match Telegram, so the card blends into the chat'))
        self.presets_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        pm = QMenu(self.presets_btn)
        for label, color, theme in PRESETS:
            ac = pm.addAction(self.swatch(color), label)
            ac.triggered.connect(lambda checked=False, c=color, t=theme: self.apply_preset(c, t))
        self.presets_btn.setMenu(pm)
        hb = QHBoxLayout()
        hb.addWidget(self.background)
        hb.addWidget(self.color_btn)
        hb.addWidget(self.presets_btn)
        hb.addStretch()
        f1.addRow(_('Background:'), hb)
        self.theme = QComboBox()
        self.theme.addItem(_('Light (dark text)'), 'light')
        self.theme.addItem(_('Dark (light text)'), 'dark')
        i = self.theme.findData(prefs['theme'])
        self.theme.setCurrentIndex(max(0, i))
        f1.addRow(_('Theme:'), self.theme)
        self.transp_note = QLabel(_('With a transparent background the image is always saved as PNG, '
                                    'because JPG has no transparency. Telegram always shows images over a '
                                    'white background, even when sent as a file: for Telegram, use one of '
                                    'the Quick colors instead.'))
        self.transp_note.setWordWrap(True)
        f1.addRow(self.transp_note)
        self.img_format = QComboBox()
        self.img_format.addItem('PNG', 'png')
        self.img_format.addItem('JPG', 'jpg')
        i = self.img_format.findData(prefs['image_format'])
        self.img_format.setCurrentIndex(max(0, i))
        f1.addRow(_('Image format:'), self.img_format)
        self.background.currentIndexChanged.connect(self.background_changed)
        self.update_color_button()
        self.footer = QCheckBox(_('Add "Exported from calibre" at the bottom'))
        self.footer.setChecked(prefs['footer'])
        f1.addRow(self.footer)
        gl.addWidget(g1)

        g2 = QGroupBox(_('Telegram'))
        v2 = QVBoxLayout(g2)
        self.premium = QCheckBox(_('I have Telegram Premium (photo captions up to 4096 characters instead of 1024)'))
        self.premium.setChecked(prefs['premium'])
        self.hashtags = QCheckBox(_('Add the tags as hashtags at the end (#Thriller #Novela)'))
        self.hashtags.setChecked(prefs['hashtags'])
        for w in (self.premium, self.hashtags):
            v2.addWidget(w)
        gl.addWidget(g2)

        g3 = QGroupBox(_('Where to show the emojis'))
        g = QGridLayout(g3)
        g.addWidget(QLabel('<b>%s</b>' % _('Telegram text')), 0, 1)
        g.addWidget(QLabel('<b>%s</b>' % _('Card image')), 0, 2)
        g.addWidget(QLabel(_('In front of each field')), 1, 0)
        g.addWidget(QLabel(_('On each genre (tag)')), 2, 0)
        self.emojis = QCheckBox()
        self.emojis.setChecked(prefs['emojis'])
        self.tg_tag_emojis = QCheckBox()
        self.tg_tag_emojis.setChecked(prefs['tg_tag_emojis'])
        self.card_emojis = QCheckBox()
        self.card_emojis.setChecked(prefs['card_emojis'])
        self.card_tag_emojis = QCheckBox()
        self.card_tag_emojis.setChecked(prefs['card_tag_emojis'])
        g.addWidget(self.emojis, 1, 1)
        g.addWidget(self.card_emojis, 1, 2)
        g.addWidget(self.tg_tag_emojis, 2, 1)
        g.addWidget(self.card_tag_emojis, 2, 2)
        lab = QLabel(_('The emoji of each field is chosen in the Fields tab, '
                       'and the one of each genre in the Genres tab.'))
        lab.setWordWrap(True)
        g.addWidget(lab, 3, 0, 1, 3)
        g.setColumnStretch(3, 1)
        gl.addWidget(g3)
        gl.addStretch()
        tabs.addTab(gen, _('General'))

        # ---- Fields
        fw = QWidget()
        fl = QVBoxLayout(fw)
        lab = QLabel(_('Tick the fields to include and drag them to change the order. '
                       'Title, authors and synopsis are always included.'))
        lab.setWordWrap(True)
        fl.addWidget(lab)
        self.emojis_now = dict(default_emojis())
        self.emojis_now.update(prefs['field_emojis'] or {})
        hh = QHBoxLayout()
        self.title_btn = QPushButton()
        self.title_btn.clicked.connect(lambda: self.choose_fixed('title', _('Title')))
        self.authors_btn = QPushButton()
        self.authors_btn.clicked.connect(lambda: self.choose_fixed('authors', _('Authors')))
        hh.addWidget(self.title_btn)
        hh.addWidget(self.authors_btn)
        hh.addStretch()
        fl.addLayout(hh)
        self.fields = QListWidget()
        self.fields.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.fields.itemDoubleClicked.connect(self.choose_item_emoji)
        self.fields.setIconSize(QSize(20, 20))
        fl.addWidget(self.fields, 1)
        he = QHBoxLayout()
        b = QPushButton(_('Change emoji...'))
        b.setToolTip(_('Choose the emoji of the selected field (or double click it)'))
        b.clicked.connect(lambda: self.choose_item_emoji(self.fields.currentItem()))
        he.addWidget(b)
        he.addWidget(QLabel(_('The emoji is used in the Telegram text.')))
        he.addStretch()
        fl.addLayout(he)
        self.update_fixed_buttons()
        h = QHBoxLayout()
        self.follow_calibre = QCheckBox(_('Use the same fields as the calibre book details panel'))
        self.follow_calibre.setChecked(prefs['fields'] is None)
        self.follow_calibre.toggled.connect(self.follow_toggled)
        h.addWidget(self.follow_calibre)
        h.addStretch()
        b = QPushButton(_('Reload from calibre'))
        b.clicked.connect(self.reload_from_calibre)
        h.addWidget(b)
        fl.addLayout(h)
        tabs.addTab(fw, _('Fields'))
        self.load_fields(use_calibre=prefs['fields'] is None)
        self.follow_toggled(self.follow_calibre.isChecked())

        # ---- Genres
        from calibre_plugins.book_card_export.genres import GenresWidget
        self.genres = GenresWidget(self, self.db)
        tabs.addTab(self.genres, _('Genres'))

        # ---- Style
        sw = QWidget()
        sl = QVBoxLayout(sw)
        lab = QLabel(_('Extra CSS for the card. Classes: .title, .author, .label, .value, .comments, .footer'))
        lab.setWordWrap(True)
        sl.addWidget(lab)
        self.css = QPlainTextEdit()
        self.css.setPlaceholderText('.comments { color: #007a00; font-style: italic; font-weight: bold; }')
        self.css.setPlainText(prefs['extra_css'])
        sl.addWidget(self.css, 1)
        tabs.addTab(sw, _('Style'))

    def swatch(self, color):
        from qt.core import QColor, QPixmap
        pm = QPixmap(16, 16)
        pm.fill(QColor(color))
        return QIcon(pm)

    def apply_preset(self, color, theme):
        self.bg_color = color
        self.background.setCurrentIndex(max(0, self.background.findData('custom')))
        self.theme.setCurrentIndex(max(0, self.theme.findData(theme)))
        self.update_color_button()

    def update_color_button(self):
        self.color_btn.setText('  ')
        self.color_btn.setStyleSheet('QPushButton { background-color: %s; min-width: 40px; '
                                     'border: 1px solid #888; border-radius: 3px; }' % self.bg_color)
        self.background_changed()

    def background_changed(self, *args):
        mode = self.background.currentData()
        self.color_btn.setVisible(mode == 'custom')
        self.transp_note.setVisible(mode == 'transparent')
        self.img_format.setEnabled(mode != 'transparent')

    def choose_color(self):
        from qt.core import QColor, QColorDialog
        c = QColorDialog.getColor(QColor(self.bg_color), self, _('Background color'))
        if c.isValid():
            self.bg_color = c.name()
            self.update_color_button()
            # suggest the text colors that can be read on this background
            light_bg = c.lightness() >= 128
            self.theme.setCurrentIndex(max(0, self.theme.findData('light' if light_bg else 'dark')))

    def follow_toggled(self, checked):
        # with calibre's fields the list can't be changed, but emojis can
        if checked:
            self.load_fields(use_calibre=True)
        self.fields.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop if checked
                                    else QAbstractItemView.DragDropMode.InternalMove)
        for i in range(self.fields.count()):
            it = self.fields.item(i)
            flags = it.flags()
            if checked:
                flags &= ~Qt.ItemFlag.ItemIsUserCheckable
            else:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            it.setFlags(flags)

    def reload_from_calibre(self):
        self.load_fields(use_calibre=True)
        self.follow_toggled(self.follow_calibre.isChecked())

    def load_fields(self, use_calibre=False):
        self.fields.clear()
        if self.db is None:
            return
        fm = self.db.field_metadata
        base = calibre_field_list(self.db)
        if use_calibre or prefs['fields'] is None:
            order = base
        else:
            chosen = [f for f in prefs['fields'] if f in fm]
            rest = [(f, False) for f, v in base if f not in chosen]
            order = [(f, True) for f in chosen] + rest
        for key, visible in order:
            try:
                name = fm[key]['name'] or key
            except Exception:
                name = key
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setData(Qt.ItemDataRole.UserRole + 1, name)
            self.set_item_text(it)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked)
            self.fields.addItem(it)

    def emoji_for(self, key):
        return self.emojis_now.get(key, default_emojis().get(key, DEFAULT_EMOJI))

    def set_item_text(self, it):
        from calibre_plugins.book_card_export.emoji_picker import emoji_icon
        key = it.data(Qt.ItemDataRole.UserRole)
        name = it.data(Qt.ItemDataRole.UserRole + 1)
        e = self.emoji_for(key)
        icon = emoji_icon(e)
        if icon is not None:
            it.setIcon(icon)
            it.setText('%s  (%s)' % (name, key))
        else:
            it.setIcon(QIcon())
            it.setText('%s   %s  (%s)' % (e or '—', name, key))

    def update_fixed_buttons(self):
        from calibre_plugins.book_card_export.emoji_picker import emoji_icon
        for btn, key, name in ((self.title_btn, 'title', _('Title')),
                               (self.authors_btn, 'authors', _('Authors'))):
            e = self.emoji_for(key)
            icon = emoji_icon(e)
            if icon is not None:
                btn.setIcon(icon)
                btn.setText(name)
            else:
                btn.setIcon(QIcon())
                btn.setText('%s  %s' % (e or '—', name))

    def choose_fixed(self, key, name):
        from calibre_plugins.book_card_export.emoji_picker import pick_emoji
        e = pick_emoji(self, name, self.emoji_for(key))
        if e is not None:
            self.emojis_now[key] = e
            self.update_fixed_buttons()

    def choose_item_emoji(self, it):
        if it is None:
            return
        from calibre_plugins.book_card_export.emoji_picker import pick_emoji
        key = it.data(Qt.ItemDataRole.UserRole)
        e = pick_emoji(self, it.data(Qt.ItemDataRole.UserRole + 1), self.emoji_for(key))
        if e is not None:
            self.emojis_now[key] = e
            self.set_item_text(it)

    def save_settings(self):
        prefs['theme'] = self.theme.currentData()
        prefs['background'] = self.background.currentData()
        prefs['bg_color'] = self.bg_color
        prefs['image_format'] = self.img_format.currentData()
        prefs['footer'] = self.footer.isChecked()
        prefs['premium'] = self.premium.isChecked()
        prefs['emojis'] = self.emojis.isChecked()
        prefs['tg_tag_emojis'] = self.tg_tag_emojis.isChecked()
        prefs['card_emojis'] = self.card_emojis.isChecked()
        prefs['card_tag_emojis'] = self.card_tag_emojis.isChecked()
        prefs['tag_emojis'] = self.genres.tag_emojis()
        prefs['hashtags'] = self.hashtags.isChecked()
        prefs['field_emojis'] = dict(self.emojis_now)
        prefs['extra_css'] = self.css.toPlainText()
        if self.follow_calibre.isChecked():
            prefs['fields'] = None
        else:
            keys = []
            for i in range(self.fields.count()):
                it = self.fields.item(i)
                if it.checkState() == Qt.CheckState.Checked:
                    keys.append(it.data(Qt.ItemDataRole.UserRole))
            prefs['fields'] = keys
