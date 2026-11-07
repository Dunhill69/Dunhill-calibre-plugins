# -*- coding: utf-8 -*-

try:
    load_translations()
except NameError:
    pass

import os

from qt.core import (QWidget, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                     QFileDialog, QVBoxLayout, QCheckBox, QFrame, Qt)
from calibre.utils.config import JSONConfig

# Almacenamiento de la configuración
prefs = JSONConfig('plugins/calibre_updater_settings')

# Valores por defecto
prefs.defaults['download_dir'] = ''
prefs.defaults['only_maintenance'] = False
prefs.defaults['check_betas'] = False
prefs.defaults['translate_changelog'] = True
prefs.defaults['changelog_cache'] = {}
# Carpetas de copias Beta/Portable que el usuario permitió actualizar automáticamente
prefs.defaults['auto_update_folders'] = []
# Carpetas en las que el usuario permitió instalar versiones Beta
prefs.defaults['beta_install_folders'] = []
# Carpeta opcional para descargar las Betas (vacía: la misma que las versiones estables)
prefs.defaults['beta_download_dir'] = ''
# macOS: copia del ícono personalizado de calibre elegido por el usuario
prefs.defaults['mac_custom_icon'] = ''


class ConfigWidget(QWidget):
    def __init__(self, gui):
        QWidget.__init__(self)
        self.gui = gui
        self.l = QVBoxLayout()
        self.setLayout(self.l)

        # --- SECCIÓN: CARPETA PERSONALIZADA ---
        self.label_info = QLabel(_('Select a custom folder to download the calibre installer. '
                                   'If left blank, the default Downloads folder will be used.'))
        self.label_info.setWordWrap(True)
        self.setMinimumWidth(520)
        self.l.addWidget(self.label_info)

        self.h = QHBoxLayout()
        self.l.addLayout(self.h)

        self.label = QLabel(_('Custom folder:'))
        self.h.addWidget(self.label)

        self.path_edit = QLineEdit(self)
        self.path_edit.setText(prefs['download_dir'])
        self.h.addWidget(self.path_edit)

        self.btn = QPushButton(_('Browse...'), self)
        self.btn.clicked.connect(self.choose_dir)
        self.h.addWidget(self.btn)

        self.l.addSpacing(15)

        # --- SECCIÓN: AVISOS ---
        self._add_section(_('Notifications'))

        # Traducción del changelog
        self.translate_checkbox = QCheckBox(_('Translate the list of changes into the calibre interface language'))
        self.translate_checkbox.setToolTip(_('Uses the free Google Translate service. Only the public list of '
                                             'calibre changes is sent; no personal data or library information.'))
        self.translate_checkbox.setChecked(prefs['translate_changelog'])
        self.l.addWidget(self.translate_checkbox)

        # Versiones de mantenimiento
        self.maint_checkbox = QCheckBox(_('Notify only of maintenance versions (maintenance)'))
        self.maint_checkbox.setToolTip(_('If checked, only corrective versions (e.g., 9.8.1) are notified automatically. '
                                         'Note: new major/minor versions (e.g., 9.9.0) will not be notified until '
                                         'their first corrective release. You can always update from the toolbar button.'))
        self.maint_checkbox.setChecked(prefs['only_maintenance'])
        self.l.addWidget(self.maint_checkbox)

        # Versiones Beta (Preview) - solo aviso
        self.betas_checkbox = QCheckBox(_('Notify about Beta versions (Preview)'))
        self.betas_checkbox.setToolTip(_('If checked, the plugin will notify you when a new Beta (Preview) version is '
                                         'available. It will only install it if you also enable "Also install Beta '
                                         'versions" in Advanced Configuration.'))
        self.betas_checkbox.setChecked(prefs['check_betas'])
        self.l.addWidget(self.betas_checkbox)

        # --- SECCIÓN: ESTA INSTALACIÓN (solo información) ---
        from calibre_plugins.calibre_updater import action as act
        self.act = act
        self.l.addSpacing(10)
        self._add_section(_('This calibre installation'))
        version = act.current_version_str()
        if act.running_beta():
            version = _('{v} (Beta)').format(v=version)
        kind = act.unsupported_install()
        tipo = act.install_kind_name(kind) if kind else _('Official installer')
        folder = act.install_folder()
        sistema = act.system_description()
        complemento = 'Calibre Updater %s' % act.plugin_version()
        filas = [(_('Version:'), version), (_('Type:'), tipo), (_('Folder:'), folder),
                 (_('System:'), sistema), (_('Plugin:'), complemento)]
        info = QLabel('<table cellspacing="2">' + ''.join(
            '<tr><td>%s&nbsp;</td><td>%s</td></tr>' % (k, _html(v)) for k, v in filas) + '</table>')
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        h_info = QHBoxLayout()
        h_info.addWidget(info, 1)
        # Botón para pegar todo junto en un mensaje del foro, sin capturas
        self._info_text = '\n'.join(['calibre %s' % version] + ['%s %s' % (k, v) for k, v in filas[1:]])
        self.copy_btn = QPushButton(_('Copy information'), self)
        self.copy_btn.clicked.connect(self._copy_info)
        h_info.addWidget(self.copy_btn, 0, Qt.AlignmentFlag.AlignBottom)
        self.l.addLayout(h_info)

        # --- SECCIÓN: ÍCONO DE CALIBRE (solo macOS) ---
        if act.mac_icon_supported():
            self.l.addSpacing(10)
            self._add_section(_('calibre icon'))
            h_icon = QHBoxLayout()
            self.icon_preview = QLabel()
            self.icon_preview.setFixedSize(52, 52)
            self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            h_icon.addWidget(self.icon_preview)
            self.icon_state = QLabel()
            self.icon_state.setWordWrap(True)
            h_icon.addWidget(self.icon_state, 1)
            btn_choose = QPushButton(_('Choose...'), self)
            btn_choose.clicked.connect(self._choose_icon)
            h_icon.addWidget(btn_choose)
            self.btn_restore = QPushButton(_('Restore original'), self)
            self.btn_restore.clicked.connect(self._restore_icon)
            h_icon.addWidget(self.btn_restore)
            self.l.addLayout(h_icon)
            note = QLabel('<small>%s</small>' % _('The plugin applies your icon again after each calibre update, '
                                                  'and also if macOS restores the original icon.'))
            note.setWordWrap(True)
            self.l.addWidget(note)
            self._refresh_icon()

        # --- SECCIÓN: CONFIGURACIÓN AVANZADA (copias Beta o Portable, e instalación de Betas) ---
        self.optin_checkbox = None
        self.optin_note = None
        self.beta_install_checkbox = None
        case = act.optin_case()
        beta_case = act.beta_install_case()
        self.adv_widgets = []
        if case or beta_case:
            self.l.addSpacing(10)
            self._add_section(_('Advanced Configuration'), self.adv_widgets)
        if case:
            blocker = act.optin_blocker()
            if blocker:
                lbl = QLabel(blocker)
                lbl.setWordWrap(True)
                self.l.addWidget(lbl)
            else:
                text = (_('Automatically update this Portable copy') if case == 'portable'
                        else _('Update this Beta to the next stable version'))
                self.optin_checkbox = QCheckBox(text)
                self._optin_value = act.optin_enabled()      # lo que eligió el usuario
                self.optin_checkbox.setChecked(self._optin_value)
                self.optin_checkbox.clicked.connect(self._optin_clicked)
                self.l.addWidget(self.optin_checkbox)
                note = _('Only the copy in this folder will be updated. Other copies of calibre on this '
                         'computer will not be modified.')
                if case == 'beta':
                    note += ' ' + _('The stable version will be installed; future Beta versions must be '
                                    'installed manually.')
                self._optin_note_text = '<small>%s</small>' % note
                lbl = QLabel(self._optin_note_text)
                lbl.setWordWrap(True)
                lbl.setContentsMargins(22, 0, 0, 0)
                self.l.addWidget(lbl)
                self.optin_note = lbl

        # Instalar también las Betas: solo visible con "Avisar de versiones Beta" activado
        self.beta_widgets = []
        if beta_case:
            self.beta_install_checkbox = QCheckBox(_('Also install Beta versions'))
            self.beta_install_checkbox.setChecked(act.beta_install_enabled() or (
                act._folder_key(folder) in [act._folder_key(x) for x in (prefs['beta_install_folders'] or [])]))
            self.beta_install_checkbox.clicked.connect(self._beta_install_clicked)
            self.l.addWidget(self.beta_install_checkbox)
            lbl = QLabel('<small>%s</small>' % _('Beta versions are for testing and may contain bugs. '
                                                  'It is recommended to keep a backup of your library.'))
            lbl.setWordWrap(True)
            lbl.setContentsMargins(22, 0, 0, 0)
            self.l.addWidget(lbl)
            # Carpeta aparte para descargar las Betas (opcional)
            beta_dir_w = QWidget(self)
            hb = QHBoxLayout(beta_dir_w)
            hb.setContentsMargins(22, 0, 0, 0)
            hb.addWidget(QLabel(_('Beta download folder:')))
            self.beta_dir_edit = QLineEdit(self)
            self.beta_dir_edit.setText(prefs['beta_download_dir'])
            self.beta_dir_edit.setPlaceholderText(_('Same as stable versions'))
            hb.addWidget(self.beta_dir_edit, 1)
            btn_bd = QPushButton(_('Browse...'), self)
            btn_bd.clicked.connect(self._choose_beta_dir)
            hb.addWidget(btn_bd)
            self.l.addWidget(beta_dir_w)
            self.beta_widgets = [self.beta_install_checkbox, lbl, beta_dir_w]
            self.betas_checkbox.toggled.connect(self._update_beta_visibility)
            self.beta_install_checkbox.toggled.connect(self._update_beta_visibility)
        self._update_beta_visibility()

        self.l.addStretch()

    def _refresh_icon(self):
        from qt.core import QPixmap
        icon = self.act.mac_custom_icon()
        pm = QPixmap(icon) if icon else QPixmap()
        if not pm.isNull():
            self.icon_preview.setPixmap(pm.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
            self.icon_state.setText(_('Custom icon'))
        else:
            self.icon_preview.clear()
            self.icon_state.setText(_('Original icon') if not icon else _('Custom icon'))
        self.btn_restore.setEnabled(bool(icon))

    def _choose_icon(self):
        import shutil
        from calibre.gui2 import error_dialog
        from calibre.utils.config import config_dir
        path, _f = QFileDialog.getOpenFileName(self, _('Select an icon'), os.path.expanduser('~'),
                                               _('Images') + ' (*.icns *.png *.jpg *.jpeg *.tiff)')
        if not path:
            return
        # Se guarda una copia: el original puede moverse o borrarse
        ext = os.path.splitext(path)[1].lower() or '.png'
        dest = os.path.join(config_dir, 'plugins', 'calibre_updater_icon' + ext)
        try:
            for old in (prefs['mac_custom_icon'],):
                if old and os.path.isfile(old) and old != dest:
                    os.remove(old)
            shutil.copyfile(path, dest)
        except Exception as e:
            error_dialog(self, _('Calibre Updater'), _('The icon could not be applied.'), det_msg=str(e), show=True)
            return
        if self.act.apply_mac_icon(dest):
            prefs['mac_custom_icon'] = dest
        else:
            error_dialog(self, _('Calibre Updater'), _('The icon could not be applied.'), show=True)
        self._refresh_icon()

    def _restore_icon(self):
        self.act.apply_mac_icon('')
        old = prefs['mac_custom_icon']
        prefs['mac_custom_icon'] = ''
        try:
            if old and os.path.isfile(old):
                os.remove(old)
        except Exception:
            pass
        self._refresh_icon()

    def _copy_info(self):
        from qt.core import QApplication
        QApplication.clipboard().setText(self._info_text)
        self.copy_btn.setText(_('Copied'))

    def _update_beta_visibility(self, *args):
        show_beta = self.betas_checkbox.isChecked()
        for w in self.beta_widgets:
            w.setVisible(show_beta)
        # La sección avanzada se oculta si solo contiene la opción de Betas y esta no se muestra
        if self.adv_widgets:
            visible = bool(self.act.optin_case()) or (bool(self.beta_widgets) and show_beta)
            for w in self.adv_widgets:
                w.setVisible(visible)
        # Quien permite instalar Betas también recibe las estables: la otra casilla queda incluida.
        # Se muestra marcada y con una explicación, para que no parezca que no funciona; al
        # desactivar las Betas vuelve a mostrar lo que el usuario había elegido.
        includes = bool(self.beta_install_checkbox is not None and show_beta and self.beta_install_checkbox.isChecked())
        if self.optin_checkbox is not None:
            self.optin_checkbox.blockSignals(True)
            self.optin_checkbox.setChecked(True if includes else self._optin_value)
            self.optin_checkbox.blockSignals(False)
            self.optin_checkbox.setEnabled(not includes)
            self.optin_note.setText('<small>%s</small>' % _('Already included in "Also install Beta versions": '
                                                             'stable versions are also installed.')
                                    if includes else self._optin_note_text)
        # Al mostrar u ocultar opciones, la ventana se ajusta para que no quede nada cortado
        win = self.window()
        if win is not None and win is not self and win.isVisible():
            win.adjustSize()

    def _choose_beta_dir(self):
        d = QFileDialog.getExistingDirectory(self, _('Select Download Folder'), self.beta_dir_edit.text())
        if d:
            self.beta_dir_edit.setText(d)

    def _beta_install_clicked(self, checked):
        if checked:
            from calibre.gui2 import question_dialog
            ok = question_dialog(self, _('Calibre Updater'),
                                 _('Beta versions are for testing and may contain bugs. It is recommended to keep '
                                   'a backup of your library.<br><br>Allow the plugin to install Beta versions in '
                                   'this folder?<br><br><b>{folder}</b>').format(
                                     folder=_html(self.act.install_folder())), show_copy_button=False)
            if not ok:
                self.beta_install_checkbox.setChecked(False)

    def _add_section(self, title, widgets=None):
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        self.l.addWidget(separator)
        label = QLabel('<b>' + title + '</b>')
        self.l.addWidget(label)
        if widgets is not None:
            widgets.extend([separator, label])

    def _optin_clicked(self, checked):
        # Confirmación al activar, repitiendo la carpeta: nadie la activa sin querer
        if checked:
            from calibre.gui2 import question_dialog
            ok = question_dialog(self, _('Calibre Updater'),
                                 _('Allow the plugin to update calibre in this folder?<br><br><b>{folder}</b>').format(
                                     folder=_html(self.act.install_folder())), show_copy_button=False)
            if not ok:
                self.optin_checkbox.setChecked(False)
        self._optin_value = self.optin_checkbox.isChecked()

    def choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, _('Select Download Folder'), self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def save_settings(self):
        prefs['download_dir'] = self.path_edit.text().strip()
        prefs['translate_changelog'] = self.translate_checkbox.isChecked()
        prefs['only_maintenance'] = self.maint_checkbox.isChecked()
        prefs['check_betas'] = self.betas_checkbox.isChecked()
        if self.optin_checkbox is not None:
            self.act.set_optin_enabled(self._optin_value)
        if self.beta_install_checkbox is not None:
            self.act.set_beta_install_enabled(self.beta_install_checkbox.isChecked())
            prefs['beta_download_dir'] = self.beta_dir_edit.text().strip()


def _html(text):
    return (text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
