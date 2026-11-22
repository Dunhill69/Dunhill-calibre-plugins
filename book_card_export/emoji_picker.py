#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

from qt.core import (
    QDialog, QDialogButtonBox, QFont, QGridLayout, QHBoxLayout, QIcon, QLabel,
    QLineEdit, QPixmap, QPushButton, QScrollArea, QSize, Qt, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)

try:
    load_translations()
except NameError:
    pass

from calibre_plugins.book_card_export.config import prefs

# Emojis are shown with images bundled in the plugin (images/emoji), because
# many systems have no color emoji font and calibre would show them blank.
PALETTE = [
    (_('Books and reading'), '📖 📚 📕 📗 📘 📙 📓 📔 📒 📜 📄 📃 📑 🔖 🏷️ 📰 🗞️ ✍️ 🖋️ ✒️ 🖊️ 📝 ✏️ 🖍️ 👓 🤓 🧐 📇 🗂️ 📁 📂 🗃️'),
    (_('People'), '👤 👥 🗣️ 👨 👩 🧑 👴 👵 🧒 👶 👨‍🎓 👩‍🎓 🧑‍🏫 👨‍💼 👩‍💼 🧑‍🎨 🦸 🦹 🧙 🧝 🧛 🧟 🧞 🧜 🕵️ 👮 💂 🤴 👸 🥷'),
    (_('Numbers and dates'), '🔢 #️⃣ 0️⃣ 1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣ 7️⃣ 8️⃣ 9️⃣ 🔟 💯 📊 📈 📉 📏 📐 ⏳ ⌛ ⏰ 🕰️ 📅 📆 🗓️ 🆕 🆙 🔄 🔁 🔜 🔚'),
    (_('Ratings'), '⭐ 🌟 ✨ 💫 🏆 🥇 🥈 🥉 🎖️ 🏅 👍 👎 👏 🙌 ❤️ 🧡 💛 💚 💙 💜 🖤 🤍 💔 ❣️ 💖 🔥 💎 👑 ✅ ☑️ ✔️ ❌ ❎ ⚠️'),
    (_('Places and publishing'), '🏢 🏛️ 🏠 🏰 🏯 🗼 🌐 🌍 🌎 🌏 🗺️ 🧭 🏝️ 🏔️ 🌋 🏙️ 🌆 💾 💿 📀 📦 🔗 📱 💻 🖥️ ⌨️ 🖨️ 🎧 🎙️ 📻 💬 💭 📢 📣 ✉️ 📧 📮'),
    (_('Genres'), '🎭 🔍 🔎 🔪 🗡️ ⚔️ 🛡️ 🏹 💀 ☠️ 👻 🎃 🦇 🕷️ 🩸 🐉 🐲 🦄 🧚 🔮 🪄 🚀 🛸 🌌 🪐 👽 🤖 🧬 🧪 🔬 💕 💘 💞 💋 🌹 💐 😂 🤣 😱 😢 🏴‍☠️ ⚓ 🤠 🐎 🏺 ⚖️ 🎓 📐 🧠 🍳 🌱 ⚽ 🎵 🎨 🙏 ☯️'),
    (_('Faces'), '😀 😃 😄 😁 😊 🙂 😉 😍 🥰 😘 😎 🤔 🤨 😐 😴 🥱 😮 😲 🤯 😳 🥺 😭 😡 🤬 😈 🤡 🙄 😬 🤗 🤫'),
    (_('Symbols and bullets'), '▪️ ▫️ ◾ ◽ ⬛ ⬜ 🔹 🔸 🔷 🔶 🔺 🔻 🔴 🟠 🟡 🟢 🔵 🟣 🟤 ⚫ ⚪ ➤ • ➡️ ⬅️ ⬆️ ⬇️ ↪️ ▶️ ⏩ 🔽 🔼 ℹ️ ❓ ❗ 💡 📌 📍 🎯 ♻️ 🚫 🔞 🆓 🆒'),
]

_cache = {}


def emoji_key(e):
    return '-'.join('%x' % ord(c) for c in e if ord(c) != 0xfe0f)


def emoji_pixmap(e):
    '''QPixmap of the bundled image, or None if there is no image for it.'''
    if not e:
        return None
    if not _cache:
        names = ['images/emoji/%s.png' % emoji_key(x)
                 for c, s in PALETTE for x in s.split()]
        try:
            data = get_resources(names) or {}
        except Exception:
            data = {}
        _cache['__loaded__'] = True
        for name, raw in data.items():
            if raw:
                pm = QPixmap()
                pm.loadFromData(raw)
                _cache[name] = pm
    return _cache.get('images/emoji/%s.png' % emoji_key(e))


def emoji_icon(e):
    pm = emoji_pixmap(e)
    return QIcon(pm) if pm is not None else None


class EmojiPicker(QDialog):

    def __init__(self, parent, title, current=''):
        QDialog.__init__(self, parent)
        self.setWindowTitle(_('Choose emoji'))
        self.result_emoji = None
        l = QVBoxLayout(self)
        l.addWidget(QLabel(_('Emoji for: <b>%s</b>') % title))

        self.tabs = QTabWidget()
        l.addWidget(self.tabs, 1)
        self.build_tabs()

        h = QHBoxLayout()
        h.addWidget(QLabel(_('Other emoji:')))
        self.other = QLineEdit()
        self.other.setPlaceholderText(_('Paste or type an emoji'))
        self.other.setText(current)
        self.other.setMaximumWidth(120)
        self.other.textChanged.connect(self.update_preview)
        h.addWidget(self.other)
        self.preview = QLabel()
        self.preview.setMinimumWidth(36)
        h.addWidget(self.preview)
        b = QPushButton(_('Use it'))
        b.clicked.connect(lambda: self.choose(self.other.text().strip()))
        h.addWidget(b)
        b = QPushButton(_('Add to my emojis'))
        b.setToolTip(_('Saves it in your own palette, so it appears in the list from now on'))
        b.clicked.connect(self.add_custom)
        h.addWidget(b)
        h.addStretch()
        l.addLayout(h)
        self.update_preview()

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        b = bb.addButton(_('No emoji'), QDialogButtonBox.ButtonRole.ResetRole)
        b.clicked.connect(lambda: self.choose(''))
        bb.rejected.connect(self.reject)
        l.addWidget(bb)
        self.resize(620, 480)

    def update_preview(self):
        e = self.other.text().strip()
        pm = emoji_pixmap(e)
        if pm is not None:
            self.preview.setPixmap(pm.scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
            self.preview.setToolTip('')
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(e)
            self.preview.setToolTip(_('There is no image for this emoji: it may look blank here, '
                                      'but Telegram will show it'))

    def build_tabs(self, select_custom=False):
        self.tabs.clear()
        custom = [e for e in prefs['custom_emojis'] if e]
        if custom:
            self.tabs.addTab(self.page(custom, removable=True), _('My emojis'))
        for cat, s in PALETTE:
            self.tabs.addTab(self.page(s.split()), cat)
        if custom and not select_custom:
            self.tabs.setCurrentIndex(1)

    def page(self, emojis, removable=False):
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        w = QWidget()
        v = QVBoxLayout(w)
        if removable:
            v.addWidget(QLabel(_('Right click on an emoji to remove it.')))
        g = QGridLayout()
        g.setSpacing(2)
        cols = 12
        for i, e in enumerate(emojis):
            b = QToolButton()
            b.setAutoRaise(True)
            b.setMinimumSize(42, 42)
            b.setToolTip(e)
            icon = emoji_icon(e)
            if icon is not None:
                b.setIcon(icon)
                b.setIconSize(QSize(30, 30))
            else:
                b.setText(e)
                f = QFont(b.font())
                f.setPointSize(f.pointSize() + 6)
                b.setFont(f)
            b.clicked.connect(lambda checked=False, e=e: self.choose(e))
            if removable:
                b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda pos, e=e: self.remove_custom(e))
            g.addWidget(b, i // cols, i % cols)
        v.addLayout(g)
        v.addStretch()
        sa.setWidget(w)
        return sa

    def add_custom(self):
        e = self.other.text().strip()
        if not e:
            return
        lst = list(prefs['custom_emojis'])
        if e not in lst:
            lst.append(e)
            prefs['custom_emojis'] = lst
        self.build_tabs(select_custom=True)
        self.tabs.setCurrentIndex(0)

    def remove_custom(self, e):
        prefs['custom_emojis'] = [x for x in prefs['custom_emojis'] if x != e]
        self.build_tabs(select_custom=True)

    def choose(self, e):
        self.result_emoji = e
        self.accept()


def pick_emoji(parent, title, current=''):
    '''Returns the chosen emoji ('' = no emoji) or None if cancelled.'''
    d = EmojiPicker(parent, title, current)
    if d.exec() == QDialog.DialogCode.Accepted:
        return d.result_emoji
    return None
