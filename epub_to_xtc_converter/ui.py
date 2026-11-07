# -*- coding: utf-8 -*-
from __future__ import (unicode_literals, division, absolute_import, print_function)

import os
import shutil
from functools import partial

from qt.core import QIcon, QPixmap, QMenu, QToolButton

from calibre.gui2 import error_dialog, Dispatcher
from calibre.gui2.actions import InterfaceAction

try:
    load_translations()
except NameError:
    pass

# Formatos de entrada, en orden de preferencia
INPUT_FORMATS = ('EPUB', 'KEPUB', 'AZW3', 'MOBI', 'FB2', 'DOCX', 'HTMLZ', 'ODT', 'RTF', 'TXT')


class InterfaceAction(InterfaceAction):
    name = 'EPUB to XTC Converter'
    PLUGIN_ICONS = ['images/icon.png', 'icon.png']

    action_spec = (_('Convert to XTC'), None, _('Converts the selected books to the XTC format of the Xteink X4'), 'Ctrl+Shift+X')
    popup_type = QToolButton.ToolButtonPopupMode.MenuButtonPopup
    action_type = 'current'

    def genesis(self):
        self.icon = QIcon()
        try:
            icon_data = self.load_resources(self.PLUGIN_ICONS)
            raw_data = icon_data.get('images/icon.png') or icon_data.get('icon.png')
            if raw_data:
                pix = QPixmap()
                pix.loadFromData(raw_data)
                self.icon = QIcon(pix)
                self.qaction.setIcon(self.icon)
        except Exception as e:
            print("EPUB_TO_XTC: Error loading icon: {}".format(e))

        self.qaction.triggered.connect(self.run_conversion)
        self.menu = QMenu(self.gui)
        self.menu.addAction(self.icon, _('Convert now'), self.run_conversion)
        self.menu.addAction(_('Preview XTC'), self.show_preview)
        self.menu.addSeparator()
        self.menu.addAction(_('Configure plugin...'), self.show_config)
        self.menu.addAction(_('About {0}').format(_('EPUB to XTC Converter')), self.show_about)
        self.qaction.setMenu(self.menu)

    def show_about(self):
        from calibre_plugins.epub_to_xtc_converter.support import show_about
        show_about(self.gui, self.interface_action_base_plugin)

    def show_preview(self):
        from calibre_plugins.epub_to_xtc_converter.xtc_format import NotXTC
        from calibre_plugins.epub_to_xtc_converter.preview import PreviewDialog

        view = self.gui.library_view
        index = view.currentIndex()
        if not index.isValid():
            return error_dialog(self.gui, _('Error'), _('No books selected'), show=True)
        book_id = view.model().id(index)
        db = self.gui.current_db.new_api
        title = db.field_for('title', book_id)
        formats = set(db.formats(book_id) or ())
        fmt = 'XTCH' if 'XTCH' in formats else 'XTC' if 'XTC' in formats else None
        if fmt is None:
            return error_dialog(self.gui, _('Error'),
                                _('"{0}" has no XTC or XTCH format. Convert it first.').format(title), show=True)
        path = db.format_abspath(book_id, fmt)
        if not path:
            return error_dialog(self.gui, _('Error'), _('The {0} file of this book could not be found.').format(fmt), show=True)
        try:
            d = PreviewDialog(self.gui, path, title)
        except NotXTC:
            return error_dialog(self.gui, _('Error'),
                                _('The {0} format of "{1}" is not a valid XTC file. It was probably created by '
                                  'version 1.x of this plugin, which only saved the text. Convert the book again.').format(fmt, title),
                                show=True)
        d.exec()

    def show_config(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def run_conversion(self):
        from calibre.ptempfile import PersistentTemporaryDirectory
        from calibre.utils.localization import lang_as_iso639_1
        from calibre_plugins.epub_to_xtc_converter.config import current_settings

        view = self.gui.library_view
        rows = view.selectionModel().selectedRows()
        if not rows:
            return error_dialog(self.gui, _('Error'), _('No books selected'), show=True)
        ids = list(view.get_selected_ids())

        db = self.gui.current_db.new_api
        settings = current_settings()
        out_fmt = 'XTCH' if settings['grayscale'] and not settings.get('xtch_as_xtc') else 'XTC'
        tdir = PersistentTemporaryDirectory('_xtc')
        books, skipped = [], []
        for book_id in ids:
            mi = db.get_metadata(book_id, get_user_categories=False)
            title = mi.title or _('Unknown')
            available = set(db.formats(book_id) or ())
            fmt = next((f for f in INPUT_FORMATS if f in available), None)
            if fmt is None:
                skipped.append(title)
                continue
            src = os.path.join(tdir, '%d_in.%s' % (book_id, fmt.lower()))
            if not db.copy_format_to(book_id, fmt, src):
                skipped.append(title)
                continue
            lang = ''
            if mi.languages:
                try:
                    lang = lang_as_iso639_1(mi.languages[0]) or ''
                except Exception:
                    lang = ''
            books.append({
                'book_id': book_id,
                'title': title,
                'authors': ' & '.join(mi.authors or []),
                'publisher': mi.publisher or '',
                'language': lang,
                'input': src,
                'output': os.path.join(tdir, '%d_out.%s' % (book_id, out_fmt.lower())),
            })

        if not books:
            shutil.rmtree(tdir, ignore_errors=True)
            return error_dialog(self.gui, _('Error'),
                                _('None of the selected books has a format that can be converted (EPUB, AZW3, MOBI...).'),
                                det_msg='\n'.join(skipped), show=True)

        if len(books) == 1:
            desc = _('Convert to {0}: {1}').format(out_fmt, books[0]['title'])
        else:
            desc = _('Convert {0} books to {1}').format(len(books), out_fmt)
        done = partial(self.conversion_done, tdir=tdir, fmt=out_fmt,
                       library_id=getattr(db, 'library_id', None), skipped=skipped)
        self.gui.job_manager.run_job(
            Dispatcher(done), 'arbitrary_n',
            args=['calibre_plugins.epub_to_xtc_converter.jobs', 'convert_books', (books, settings)],
            description=desc)
        self.gui.status_bar.show_message(_('Converting to {0}...').format(out_fmt), 3000)

    def conversion_done(self, job, tdir=None, fmt='XTC', library_id=None, skipped=()):
        try:
            if job.failed:
                self.gui.job_exception(job, dialog_title=_('Could not convert to XTC'))
                return
            db = self.gui.current_db.new_api
            if library_id is not None and getattr(db, 'library_id', None) != library_id:
                return error_dialog(self.gui, _('Error'),
                                    _('The library was changed while converting. The XTC files were not added.'),
                                    show=True)
            results = job.result or []
            added, failed = [], []
            for r in results:
                if r.get('ok') and os.path.exists(r['output']):
                    db.add_format(r['book_id'], fmt, r['output'], replace=True, run_hooks=False)
                    added.append(r)
                else:
                    failed.append(r)
            if added:
                view = self.gui.library_view
                view.model().refresh_ids([r['book_id'] for r in added], current_row=view.currentIndex().row())
                if len(added) == 1:
                    msg = _('Done: {0} ({1} pages)').format(added[0]['title'], added[0].get('pages', 0))
                else:
                    msg = _('Done: {} XTC files created').format(len(added))
                self.gui.status_bar.show_message(msg, 5000)
            if failed or skipped:
                det = []
                for r in failed:
                    if r.get('blank_book'):
                        det.append(_('{0}: {1} of {2} pages came out blank. calibre could not draw the text, '
                                     'usually because fonts are missing (for example when running calibre under Wine). '
                                     'The file was not added.').format(r.get('title', ''), r.get('blank', 0), r.get('pages', 0)))
                    else:
                        det.append('%s\n%s' % (r.get('title', ''), r.get('error', '')))
                for t in skipped:
                    det.append(_('{0}: no format that can be converted').format(t))
                error_dialog(self.gui, _('Error'),
                             _('{0} of the selected books could not be converted. Click "Show details" for more information.').format(
                                 len(failed) + len(skipped)),
                             det_msg='\n\n'.join(det), show=True)
        finally:
            if tdir:
                shutil.rmtree(tdir, ignore_errors=True)
