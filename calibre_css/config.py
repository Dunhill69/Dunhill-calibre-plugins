#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai

__license__   = 'GPL v3'
__copyright__ = '2026, Dunhill'

try:
    load_translations()
except NameError:
    pass

import os

from qt.core import (QDialog, QDialogButtonBox, QHBoxLayout, QPushButton,
                     QTabWidget, QVBoxLayout, QWidget)

from calibre.utils.config import JSONConfig

PLUGIN_NAME = 'Calibre CSS'
DETAILS_MARK = '\n\n/* --- Calibre CSS --- */\n'

# Same file as previous versions, so saved styles are kept
plugin_prefs = JSONConfig('plugins/calibre_style')
# Named styles, shared by all libraries: {name: css}
plugin_prefs.defaults['details_styles'] = {}
plugin_prefs.defaults['viewer_styles'] = {}
# Style chosen for each library: {normalized library path: name}
plugin_prefs.defaults['details_assign'] = {}
plugin_prefs.defaults['viewer_assign'] = {}
# Viewer stylesheet the user had before the plugin replaced it
plugin_prefs.defaults['viewer_original_css'] = ''
plugin_prefs.defaults['viewer_managed'] = False
plugin_prefs.defaults['schema'] = 1

MODES = ('details', 'viewer')


def normalize_path(path):
    if not path:
        return ''
    return os.path.normcase(os.path.normpath(os.path.abspath(path))).replace('\\', '/')


def preset_styles(mode):
    if mode == 'details':
        return {
            _('Highlighted labels'): (
                'table.fields td.title { color: #1e6fd9; font-style: normal; font-weight: bold; }\n'
                '.series_name { color: #c48a00; font-style: normal; font-weight: bold; }\n'
                '#tags a { color: #2e8b57; }\n'),
            _('Sepia'): (
                'body { font-family: Georgia, "Times New Roman", serif; color: #5b4636; }\n'
                'table.fields td.title { color: #8b6f47; }\n'
                'a { color: #8b4513; }\n'
                '.comments p { font-size: 110%; line-height: 140%; }\n'
                '#comments h3 { color: #8b4513; }\n'),
            _('Large synopsis'): (
                '.comments p { font-size: 125%; margin-bottom: 8px; }\n'
                '.comments-heading, #comments h3 { color: #d9534f; font-size: 140%; }\n'
                '#authors a { font-weight: bold; }\n'),
        }
    return {
        _('Warm night mode'): (
            'body { background: #1e1b16 !important; color: #e8dcc4 !important; }\n'
            'a { color: #d9a441 !important; }\n'),
        _('Comfortable reading'): (
            'p { text-align: justify !important; text-indent: 1.5em !important;\n'
            '    line-height: 1.6 !important; margin: 0 !important; }\n'),
        _('Centered headings'): (
            'h1, h2, h3 { text-align: center !important; color: #8b4513 !important;\n'
            '             font-family: Georgia, serif !important; }\n'),
    }


def unique_name(name, existing):
    if name not in existing:
        return name
    i = 2
    while '%s (%d)' % (name, i) in existing:
        i += 1
    return '%s (%d)' % (name, i)


def _migrate():
    if plugin_prefs['schema'] >= 2:
        return
    # Versions <= 1.3: one CSS per library -> one named style per library
    for mode, old_key in (('details', 'library_css'), ('viewer', 'viewer_css')):
        styles = dict(preset_styles(mode))
        assign = {}
        for p, css in (plugin_prefs.get(old_key) or {}).items():
            if not (css and css.strip()):
                continue
            norm = normalize_path(p)
            name = unique_name(os.path.basename(norm.rstrip('/')) or _('Style'), styles)
            styles[name] = css
            assign[norm] = name
        plugin_prefs[mode + '_styles'] = styles
        plugin_prefs[mode + '_assign'] = assign
        if old_key in plugin_prefs:
            del plugin_prefs[old_key]
    if 'paths_normalized' in plugin_prefs:
        del plugin_prefs['paths_normalized']
    plugin_prefs['schema'] = 2
    # Leftover from 1.2: an option calibre never reads
    try:
        from calibre.gui2 import gprefs
        if 'book_details_user_css' in gprefs:
            del gprefs['book_details_user_css']
    except Exception:
        pass


_migrate()


def get_styles(mode):
    return dict(plugin_prefs[mode + '_styles'] or {})


def get_assignments(mode):
    return dict(plugin_prefs[mode + '_assign'] or {})


def get_css(mode, path):
    name = get_assignments(mode).get(normalize_path(path))
    return get_styles(mode).get(name, '') if name else ''


def get_library_css(path):
    return get_css('details', path)


def get_viewer_css(path):
    return get_css('viewer', path)


def save_mode(mode, styles, assign):
    plugin_prefs[mode + '_styles'] = dict(styles)
    plugin_prefs[mode + '_assign'] = {normalize_path(p): n for p, n in assign.items()
                                      if n and n in styles}


# ---------------------------------------------------------------------------
# Applying styles
# ---------------------------------------------------------------------------

def details_stylesheet(extra_css):
    """calibre's book details CSS (including any user override made in
    Preferences > Look & feel) followed by the library CSS."""
    from calibre.gui2.book_details import css
    base = css()
    return base + DETAILS_MARK + extra_css if extra_css and extra_css.strip() else base


def apply_details_css(gui, extra_css):
    bi = getattr(getattr(gui, 'book_details', None), 'book_info', None)
    if bi is None:
        return
    bi._calibre_stylist_css = extra_css or ''
    if not getattr(bi, '_calibre_stylist_patched', False):
        # If calibre reloads its CSS (e.g. after changing it in Preferences),
        # put the library CSS back on top
        orig = bi.refresh_css

        def refresh_css():
            orig()
            if bi._calibre_stylist_css:
                bi.setDefaultStyleSheet(details_stylesheet(bi._calibre_stylist_css))
                bi.setHtml(bi.last_set_html)
        bi.refresh_css = refresh_css
        bi._calibre_stylist_patched = True
    bi.setDefaultStyleSheet(details_stylesheet(extra_css))
    # The default stylesheet is only used when the HTML is parsed: re-render
    if getattr(bi, 'last_set_html', ''):
        bi.setHtml(bi.last_set_html)


def apply_viewer_css(extra_css):
    """Write the library CSS as the viewer's "user stylesheet". When the
    library has none, restore the stylesheet the user had before."""
    from calibre.gui2.viewer.config import vprefs
    vprefs.refresh()
    sd = dict(vprefs['session_data'] or {})
    current = sd.get('user_stylesheet', '') or ''
    managed = plugin_prefs['viewer_managed']
    if extra_css and extra_css.strip():
        if not managed:
            plugin_prefs['viewer_original_css'] = current
            plugin_prefs['viewer_managed'] = True
        target = extra_css
    else:
        if not managed:
            return
        target = plugin_prefs['viewer_original_css'] or ''
        plugin_prefs['viewer_managed'] = False
        plugin_prefs['viewer_original_css'] = ''
    if current != target:
        if target:
            sd['user_stylesheet'] = target
        else:
            sd.pop('user_stylesheet', None)
        vprefs['session_data'] = sd


def reset_calibre_details_css(gui):
    """Remove the user's override of calibre's book details CSS, the same as
    Restore defaults in Preferences > Look & feel > Book details."""
    from calibre.utils.resources import set_data
    set_data('templates/book_details.css', None)
    from calibre.gui2.book_details import css
    css(True)
    try:
        gui.book_details.book_info.refresh_css()
    except Exception:
        pass


def reset_calibre_viewer_css():
    """Empty the viewer's own user stylesheet."""
    plugin_prefs['viewer_original_css'] = ''
    if plugin_prefs['viewer_managed']:
        return   # restored to empty when a library without style is opened
    from calibre.gui2.viewer.config import vprefs
    vprefs.refresh()
    sd = dict(vprefs['session_data'] or {})
    if sd.pop('user_stylesheet', None) is not None:
        vprefs['session_data'] = sd


def apply_all(gui, library_path=None):
    if library_path is None:
        db = getattr(gui, 'current_db', None)
        library_path = getattr(db, 'library_path', None)
    if not library_path:
        return
    try:
        apply_details_css(gui, get_library_css(library_path))
    except Exception:
        import traceback
        traceback.print_exc()
    try:
        apply_viewer_css(get_viewer_css(library_path))
    except Exception:
        import traceback
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Configuration UI
# ---------------------------------------------------------------------------

def _find_base_plugin():
    from calibre.customize.ui import find_plugin
    return find_plugin(PLUGIN_NAME)


class CalibreCSSWidget(QWidget):
    """Used both in the toolbar dialog and in Preferences > Plugins."""

    def __init__(self, gui, plugin=None, parent=None):
        QWidget.__init__(self, parent)
        self.gui = gui
        self.plugin = plugin
        from calibre_plugins.calibre_style.css_tab import CSSTab

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget(self)
        self.tab_details = CSSTab(self, gui, mode='details')
        self.tab_viewer = CSSTab(self, gui, mode='viewer')
        self.tabs.addTab(self.tab_details, _('Book details panel'))
        self.tabs.addTab(self.tab_viewer, _('E-book viewer'))
        from calibre_plugins.calibre_style.book_tab import BookCSSTab
        self.tab_book = BookCSSTab(self, gui)
        self.tabs.addTab(self.tab_book, _('Book CSS'))
        lay.addWidget(self.tabs)

        bottom = QHBoxLayout()
        self.about_button = QPushButton('☕ ' + _('About / Donate'), self)
        self.about_button.clicked.connect(self.show_about)
        bottom.addWidget(self.about_button)
        bottom.addStretch(1)
        lay.addLayout(bottom)
        self.setMinimumSize(780, 560)

    def show_about(self):
        from calibre_plugins.calibre_style.support import show_about
        show_about(self, self.plugin or _find_base_plugin())

    def save_settings(self):
        self.tab_book.maybe_save()
        self.tab_book.cleanup()
        for tab in (self.tab_details, self.tab_viewer):
            save_mode(tab.mode, *tab.get_settings())
        if self.tab_details.reset_calibre_base:
            reset_calibre_details_css(self.gui)
        if self.tab_viewer.reset_calibre_base:
            reset_calibre_viewer_css()
        if self.gui is not None:
            apply_all(self.gui)


class ConfigDialog(QDialog):

    def __init__(self, gui, plugin=None, tab=0):
        QDialog.__init__(self, gui)
        self.setWindowTitle(_('Calibre CSS: styles per library'))
        lay = QVBoxLayout(self)
        self.widget = CalibreCSSWidget(gui, plugin, self)
        lay.addWidget(self.widget)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.widget.tabs.setCurrentIndex(tab)
        self.resize(1100, 720)

    def accept(self):
        if not self.widget.tab_book.maybe_save():
            return
        self.widget.save_settings()
        QDialog.accept(self)

    def reject(self):
        if not self.widget.tab_book.maybe_save():
            return
        self.widget.tab_book.cleanup()
        QDialog.reject(self)
