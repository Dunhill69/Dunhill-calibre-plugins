#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL v3'
__copyright__ = '2026, Dunhill'

from calibre.utils.config import JSONConfig

try:
    load_translations()
except NameError:
    pass

prefs = JSONConfig('plugins/Synopsis Page')

prefs.defaults['show_heading'] = True
prefs.defaults['heading_text'] = _('Synopsis')
prefs.defaults['show_title'] = True
prefs.defaults['show_authors'] = True
prefs.defaults['show_series'] = False
prefs.defaults['include_cover'] = True
prefs.defaults['cover_width'] = 45          # % of the page width
prefs.defaults['cover_style'] = 'shadow'    # none | line | shadow
prefs.defaults['cover_position'] = 'top'    # top | left | right | bottom
prefs.defaults['cover_after_par'] = 0       # paragraph after which the floating cover goes
prefs.defaults['formats'] = ['EPUB', 'AZW3']
prefs.defaults['position'] = 'after_cover'  # after_cover | start | end
prefs.defaults['justify'] = True
prefs.defaults['indent'] = True
prefs.defaults['add_to_toc'] = True
prefs.defaults['toc_title'] = _('Synopsis')
prefs.defaults['backup'] = True             # save ORIGINAL_<FMT> the first time
prefs.defaults['max_cover_height'] = 1200   # px; taller covers are scaled down
