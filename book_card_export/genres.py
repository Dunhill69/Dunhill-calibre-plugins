#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

import unicodedata

from qt.core import (
    QHBoxLayout, QIcon, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSize, Qt, QVBoxLayout, QWidget,
)

try:
    load_translations()
except NameError:
    pass

from calibre_plugins.book_card_export.config import prefs

# (words to look for in the tag, emoji). The first match wins, so the more
# specific ones go first. Words are compared without accents and in lower case.
SUGGESTIONS = (
    (('ciencia ficcion', 'science fiction', 'sci-fi', 'scifi', 'space opera',
      'cyberpunk', 'ciberpunk', 'steampunk'), '🚀'),
    (('distop', 'dystop', 'postapocal', 'post-apocal'), '🤖'),
    (('vampir',), '🧛'),
    (('zombi',), '🧟'),
    (('fantas', 'fantasy', 'dragon'), '🐉'),
    (('magia', 'magic', 'brujer', 'witch'), '🪄'),
    (('paranormal', 'sobrenatural', 'supernatural', 'esoter'), '🔮'),
    (('terror', 'horror', 'miedo', 'gotic', 'gothic', 'fantasma', 'ghost'), '👻'),
    (('erotic', 'erotismo'), '💋'),
    (('romant', 'romance', 'amor', 'love'), '💕'),
    (('thriller', 'suspens', 'suspense'), '🔪'),
    (('polic', 'detect', 'crimen', 'crime', 'criminal', 'negra', 'noir'), '🕵️'),
    (('misterio', 'mystery', 'enigma', 'intriga'), '🔍'),
    (('artes marciales', 'martial art'), '⚔️'),
    (('belic', 'guerra', 'war', 'militar', 'military'), '⚔️'),
    (('histor',), '📜'),
    (('piratas', 'pirate'), '🏴‍☠️'),
    (('western', 'oeste', 'vaquer'), '🤠'),
    (('aventura', 'adventure', 'accion', 'action'), '🗺️'),
    (('mitolog', 'mytholog', 'arqueolog'), '🏺'),
    (('humor', 'comedia', 'comedy', 'satira', 'satire'), '😂'),
    (('drama', 'teatro', 'theatre', 'theater'), '🎭'),
    (('poesia', 'poetry', 'poema', 'poem'), '🌹'),
    (('juvenil', 'young adult', 'infantil', 'children', 'ninos'), '🧒'),
    (('biograf', 'memorias', 'memoir', 'autobiograf'), '👤'),
    (('filosof', 'philosoph'), '🧠'),
    (('psicolog', 'psycholog'), '🧠'),
    (('autoayuda', 'self-help', 'self help', 'desarrollo personal', 'crecimiento personal'), '🌱'),
    (('religi', 'espiritual', 'spiritual', 'teolog'), '🙏'),
    (('politic', 'derecho', 'law'), '⚖️'),
    (('econom', 'negocio', 'business', 'finanz', 'financ', 'empresa'), '📈'),
    (('divulgac', 'ciencia', 'science', 'fisica', 'quimica', 'biolog', 'medicin'), '🧪'),
    (('viaje', 'travel', 'geograf'), '🌍'),
    (('cocina', 'cooking', 'gastronom', 'receta'), '🍳'),
    (('deporte', 'sport', 'futbol'), '⚽'),
    (('musica', 'music'), '🎵'),
    (('arte', 'artes', 'art', 'pintura', 'fotograf'), '🎨'),
    (('educac', 'education', 'ensenanza', 'texto', 'estudio'), '🎓'),
    (('ensayo', 'essay', 'no ficcion', 'nonfiction', 'non-fiction'), '📝'),
    (('clasic', 'classic'), '🏛️'),
    (('comic', 'manga', 'novela grafica', 'graphic novel'), '💬'),
    (('cuento', 'relato', 'short stor'), '📃'),
    (('novela', 'novel', 'ficcion', 'fiction', 'narrativa', 'literatura'), '📖'),
)


WHOLE_WORDS = frozenset(('art', 'arte', 'artes', 'law', 'war', 'love', 'texto'))


def _norm(s):
    s = unicodedata.normalize('NFKD', s.lower())
    return ''.join(c for c in s if not unicodedata.combining(c))


def suggest(tag):
    t = _norm(tag)
    for words, emoji in SUGGESTIONS:
        for w in words:
            if w in t:
                # short words must be whole words, they are inside many others
                if w in WHOLE_WORDS and w not in t.replace('-', ' ').replace(',', ' ').split():
                    continue
                return emoji
    return ''


class GenresWidget(QWidget):

    def __init__(self, parent, db):
        QWidget.__init__(self, parent)
        self.db = db
        self.emojis = dict(prefs['tag_emojis'] or {})
        l = QVBoxLayout(self)
        lab = QLabel(_('Double click on a genre to choose its emoji. Genres without an emoji '
                       'are shown with just their name.'))
        lab.setWordWrap(True)
        l.addWidget(lab)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(_('Search genre...'))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.apply_filter)
        l.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setIconSize(QSize(20, 20))
        self.list.itemDoubleClicked.connect(self.choose)
        l.addWidget(self.list, 1)
        h = QHBoxLayout()
        b = QPushButton(_('Change emoji...'))
        b.clicked.connect(lambda: self.choose(self.list.currentItem()))
        h.addWidget(b)
        b = QPushButton(_('Remove emoji'))
        b.clicked.connect(self.remove)
        h.addWidget(b)
        h.addStretch()
        b = QPushButton(_('Suggest emojis'))
        b.setToolTip(_('Assigns the usual emoji to the genres that have none '
                       '(Fantasy 🐉, Science fiction 🚀, Romance 💕, Horror 👻...). '
                       'You can change them afterwards.'))
        b.clicked.connect(self.suggest_all)
        h.addWidget(b)
        l.addLayout(h)
        self.load()

    def load(self):
        self.list.clear()
        tags = []
        if self.db is not None:
            try:
                api = self.db.new_api
                names = api.get_id_map('tags')
                counts = api.get_usage_count_by_id('tags')
                tags = [(names[i], counts.get(i, 0)) for i in names]
            except Exception:
                tags = []
        known = {t.lower() for t, c in tags}
        # keep emojis of genres that are not in this library (other libraries)
        for t in self.emojis:
            if t.lower() not in known:
                tags.append((t, 0))
        tags.sort(key=lambda x: _norm(x[0]))
        for name, count in tags:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, name)
            it.setData(Qt.ItemDataRole.UserRole + 1, count)
            self.set_text(it)
            self.list.addItem(it)
        self.apply_filter()

    def emoji_of(self, name):
        for k, v in self.emojis.items():
            if k.lower() == name.lower():
                return v
        return ''

    def set_text(self, it):
        from calibre_plugins.book_card_export.emoji_picker import emoji_icon
        name = it.data(Qt.ItemDataRole.UserRole)
        count = it.data(Qt.ItemDataRole.UserRole + 1)
        e = self.emoji_of(name)
        label = '%s  (%d)' % (name, count) if count else name
        icon = emoji_icon(e) if e else None
        if icon is not None:
            it.setIcon(icon)
            it.setText(label)
        else:
            it.setIcon(QIcon())
            it.setText(('%s   %s' % (e, label)) if e else ('      ' + label))

    def apply_filter(self):
        q = _norm(self.filter.text().strip())
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(q) and q not in _norm(it.data(Qt.ItemDataRole.UserRole)))

    def set_emoji(self, name, e):
        for k in list(self.emojis):
            if k.lower() == name.lower():
                del self.emojis[k]
        if e:
            self.emojis[name] = e

    def choose(self, it):
        if it is None:
            return
        from calibre_plugins.book_card_export.emoji_picker import pick_emoji
        name = it.data(Qt.ItemDataRole.UserRole)
        e = pick_emoji(self, name, self.emoji_of(name))
        if e is not None:
            self.set_emoji(name, e)
            self.set_text(it)

    def remove(self):
        it = self.list.currentItem()
        if it is not None:
            self.set_emoji(it.data(Qt.ItemDataRole.UserRole), '')
            self.set_text(it)

    def suggest_all(self):
        n = 0
        for i in range(self.list.count()):
            it = self.list.item(i)
            name = it.data(Qt.ItemDataRole.UserRole)
            if not self.emoji_of(name):
                e = suggest(name)
                if e:
                    self.set_emoji(name, e)
                    self.set_text(it)
                    n += 1
        from calibre.gui2 import info_dialog
        info_dialog(self, _('Suggest emojis'),
                    _('Emojis assigned to %d genres. The rest have no usual emoji: '
                      'you can choose one with a double click.') % n, show=True)

    def tag_emojis(self):
        return dict(self.emojis)
