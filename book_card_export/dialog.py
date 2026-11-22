#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

import os

from calibre.gui2 import choose_dir, choose_save_file, error_dialog, info_dialog
from qt.core import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QIcon, QLabel, QPixmap,
    QPlainTextEdit, QProgressDialog, QPushButton, QScrollArea, QSplitter, Qt,
    QTimer, QVBoxLayout, QWidget,
)

try:
    load_translations()
except NameError:
    pass

from calibre_plugins.book_card_export import card, tgtext
from calibre_plugins.book_card_export.config import prefs


class CardDialog(QDialog):

    def __init__(self, gui, action, ids, start, selected, mode='library'):
        QDialog.__init__(self, gui)
        self.gui = gui
        self.action = action
        self.db = gui.current_db.new_api
        self.ids = ids
        self.pos = start
        self.selected = selected
        self.mode = mode
        self.data = None
        self.image = None
        self.setWindowIcon(get_icons('images/icon.png', 'Book Card Export'))
        self.resize(1200, 760)

        l = QVBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal, self)
        l.addWidget(split, 1)

        # ---------- left: card preview
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel('<b>%s</b>' % _('Card preview')))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.preview)
        ll.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        b = QPushButton(_('Copy card image'))
        b.setToolTip(_('Copy the whole card as an image, to paste it in Telegram or elsewhere'))
        b.clicked.connect(self.copy_card)
        row.addWidget(b)
        b = QPushButton(_('Save image...'))
        b.clicked.connect(self.save_image)
        row.addWidget(b)
        row.addStretch()
        ll.addLayout(row)
        split.addWidget(left)

        # ---------- right: Telegram text
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel('<b>%s</b>' % _('Text for Telegram')))
        self.text = QPlainTextEdit()
        self.text.textChanged.connect(self.update_counter)
        rl.addWidget(self.text, 1)
        h = QHBoxLayout()
        self.premium = QCheckBox(_('I have Telegram Premium'))
        self.premium.setChecked(prefs['premium'])
        self.premium.toggled.connect(self.premium_toggled)
        h.addWidget(self.premium)
        h.addStretch()
        self.counter = QLabel()
        h.addWidget(self.counter)
        rl.addLayout(h)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        rl.addWidget(self.hint)
        h = QHBoxLayout()
        b = QPushButton(_('1. Copy cover'))
        b.setToolTip(_('Paste it in Telegram with Ctrl+V: the window to send the photo opens'))
        b.clicked.connect(self.copy_cover)
        h.addWidget(b)
        self.copy_text_btn = QPushButton(_('2. Copy text'))
        self.copy_text_btn.setToolTip(_('Paste it in the caption field of the photo'))
        self.copy_text_btn.clicked.connect(lambda: self.copy_part(0))
        h.addWidget(self.copy_text_btn)
        self.copy_part2_btn = QPushButton(_('3. Copy part 2'))
        self.copy_part2_btn.setToolTip(_('Send it as a new message after the photo'))
        self.copy_part2_btn.clicked.connect(lambda: self.copy_part(1))
        h.addWidget(self.copy_part2_btn)
        b = QPushButton(_('Restore text'))
        b.setToolTip(_('Discard your changes and generate the text again'))
        b.clicked.connect(self.reset_text)
        h.addWidget(b)
        rl.addLayout(h)
        split.addWidget(right)
        split.setSizes([680, 520])

        # ---------- bottom
        bl = QHBoxLayout()
        self.prev_btn = QPushButton(_('&Previous'))
        self.prev_btn.clicked.connect(lambda: self.go(-1))
        self.next_btn = QPushButton(_('&Next'))
        self.next_btn.clicked.connect(lambda: self.go(1))
        try:
            self.prev_btn.setIcon(QIcon.ic('back.png'))
            self.next_btn.setIcon(QIcon.ic('forward.png'))
        except Exception:
            pass
        self.pos_label = QLabel()
        bl.addWidget(self.prev_btn)
        bl.addWidget(self.next_btn)
        bl.addWidget(self.pos_label)
        bl.addStretch()
        if len(selected) > 1:
            b = QPushButton(_('Export the %d selected as images...') % len(selected))
            b.clicked.connect(self.export_selected)
            bl.addWidget(b)
        b = QPushButton(_('Configure'))
        b.clicked.connect(self.configure)
        bl.addWidget(b)
        b = QPushButton(_('Help'))
        b.clicked.connect(self.help)
        bl.addWidget(b)
        b = QPushButton(_('About'))
        b.clicked.connect(self.about)
        bl.addWidget(b)
        b = QPushButton(_('Close'))
        b.clicked.connect(self.accept)
        bl.addWidget(b)
        l.addLayout(bl)

        QTimer.singleShot(0, self.load_book)

    # ---------- loading
    def load_book(self):
        book_id = self.ids[self.pos]
        try:
            self.data = card.collect(self.db, book_id)
            self.image = card.render_image(self.data)
        except Exception:
            import traceback
            return error_dialog(self, _('Error'), _('Could not create the card.'),
                                det_msg=traceback.format_exc(), show=True)
        self.setWindowTitle('%s - %s' % (_('Book card'), self.data['title']))
        self.show_preview()
        self.reset_text()
        self.prev_btn.setEnabled(self.pos > 0)
        self.next_btn.setEnabled(self.pos < len(self.ids) - 1)
        if self.mode == 'selected':
            fmt = _('%(pos)d of %(total)d selected books')
        elif self.mode == 'view':
            fmt = _('%(pos)d of %(total)d books in the current search')
        else:
            fmt = _('%(pos)d of %(total)d books in the library')
        self.pos_label.setText(fmt % dict(pos=self.pos + 1, total=len(self.ids)))

    def show_preview(self):
        if self.image is None:
            return
        w = max(200, self.scroll.viewport().width() - 4)
        img = self.image
        if prefs['background'] == 'transparent':
            img = card.checkerboard_preview(img)
        pm = QPixmap.fromImage(img)
        pm = pm.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pm)

    def resizeEvent(self, ev):
        QDialog.resizeEvent(self, ev)
        QTimer.singleShot(0, self.show_preview)

    def go(self, delta):
        new = self.pos + delta
        if 0 <= new < len(self.ids):
            self.pos = new
            self.load_book()

    # ---------- Telegram text
    def reset_text(self):
        if self.data is not None:
            self.text.setPlainText(card.telegram_text(self.data))

    def notice(self):
        return '⬇️ __%s__' % _('The synopsis continues in the next message')

    def parts(self):
        return tgtext.split_text(self.text.toPlainText(), card.caption_limit(), self.notice())

    def premium_toggled(self, checked):
        prefs['premium'] = bool(checked)
        self.update_counter()

    def update_counter(self):
        text = self.text.toPlainText()
        n = tgtext.tg_len(text)
        limit = card.caption_limit()
        fits = n <= limit
        color = '#2e7d32' if fits else '#c62828'
        self.counter.setText('<span style="color:%s"><b>%d</b> / %d %s</span>' % (
            color, n, limit, _('characters')))
        if fits:
            self.hint.setText(_('Everything fits in one message: copy the cover, paste it in '
                                'Telegram (Ctrl+V) and then paste the text in the caption field.'))
            self.copy_text_btn.setText(_('2. Copy text'))
            self.copy_part2_btn.setVisible(False)
        else:
            parts = self.parts()
            self.hint.setText(_('It does not fit in the photo caption: it will be split in %d '
                                'parts. Part 1 goes in the caption and part 2 as the next message.')
                              % len(parts))
            self.copy_text_btn.setText(_('2. Copy part 1'))
            self.copy_part2_btn.setVisible(len(parts) > 1)

    def copy_part(self, index):
        text = self.text.toPlainText()
        if tgtext.tg_len(text) > card.caption_limit():
            parts = self.parts()
            if index == 1:
                text = '\n\n'.join(parts[1:])
            else:
                text = parts[0]
        QApplication.clipboard().setText(text)
        self.flash(_('Text copied'))

    def copy_cover(self):
        if self.data:
            QApplication.clipboard().setImage(self.data['cover'])
            self.flash(_('Cover copied'))

    def copy_card(self):
        if self.image is not None:
            QApplication.clipboard().setImage(self.image)
            self.flash(_('Card copied'))

    def flash(self, msg):
        try:
            self.gui.status_bar.show_message(msg, 3000)
        except Exception:
            pass
        old = self.pos_label.text()
        self.pos_label.setText('<b>✔ %s</b>' % msg)
        QTimer.singleShot(1800, lambda: self.pos_label.setText(old))

    # ---------- saving
    def save_image(self):
        if not self.data:
            return
        ext = card.image_ext()
        transparent = prefs['background'] == 'transparent'
        exts = ['png'] if transparent else ['png', 'jpg']
        path = choose_save_file(self, 'book-card-export-image', _('Save card image'),
                                filters=[(_('Images'), exts)],
                                all_files=False,
                                initial_filename=card.safe_filename(self.data, ext))
        if path:
            base, e = os.path.splitext(path)
            fmt = e.lstrip('.').lower()
            if fmt not in ('png', 'jpg', 'jpeg'):
                fmt = ext
                path += '.' + ext
            elif transparent and fmt != 'png':
                # JPG can't be transparent: save it as PNG
                fmt = 'png'
                path = base + '.png'
            if card.save_image(self.data, path, fmt):
                self.flash(_('Saved as %s') % os.path.basename(path))
            else:
                error_dialog(self, _('Error'), _('Could not save the image.'), show=True)

    def export_selected(self):
        folder = choose_dir(self, 'book-card-export-dir', _('Choose the folder for the cards'))
        if not folder:
            return
        ext = card.image_ext()
        pd = QProgressDialog(_('Exporting cards...'), _('Cancel'), 0, len(self.selected), self)
        pd.setWindowModality(Qt.WindowModality.WindowModal)
        pd.setMinimumDuration(0)
        done, errors = 0, []
        for i, book_id in enumerate(self.selected):
            if pd.wasCanceled():
                break
            pd.setValue(i)
            QApplication.processEvents()
            try:
                data = card.collect(self.db, book_id)
                if card.save_image(data, os.path.join(folder, card.safe_filename(data, ext)), ext):
                    done += 1
                else:
                    errors.append(data['title'])
            except Exception as e:
                errors.append('%s: %s' % (book_id, e))
        pd.setValue(len(self.selected))
        msg = _('%d cards saved in:') % done + '\n' + folder
        info_dialog(self, _('Export finished'), msg,
                    det_msg='\n'.join(errors) if errors else None, show=True)

    # ---------- others
    def configure(self):
        if self.action.interface_action_base_plugin.do_user_config(self):
            self.premium.blockSignals(True)
            self.premium.setChecked(prefs['premium'])
            self.premium.blockSignals(False)
            self.load_book()

    def help(self):
        from calibre_plugins.book_card_export.help_dialog import HelpDialog
        HelpDialog(self).exec()

    def about(self):
        from calibre_plugins.book_card_export.about import AboutDialog
        AboutDialog(self, self.action.interface_action_base_plugin).exec()
