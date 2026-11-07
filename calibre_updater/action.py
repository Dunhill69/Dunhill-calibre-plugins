# -*- coding: utf-8 -*-

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from qt.core import (QIcon, QToolButton, QPixmap, QStandardPaths, Qt, QUrl,
                     QProgressDialog, QMenu, QMetaObject, Q_ARG, QDialog,
                     QDialogButtonBox, QVBoxLayout, QHBoxLayout, QLabel,
                     QPushButton, pyqtSlot, QTextEdit, QApplication, QMessageBox)
from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import question_dialog, info_dialog, error_dialog, open_url
from calibre.constants import numeric_version

try:
    load_translations()
except NameError:
    pass

from calibre_plugins.calibre_updater.config import prefs
from calibre_plugins.calibre_updater import changelog as clog
from calibre_plugins.calibre_updater.changelog import parse_v

UA = {'User-Agent': 'Mozilla/5.0'}
LATEST_URL = 'https://code.calibre-ebook.com/latest'
RECHECK_INTERVAL_MS = 3 * 60 * 60 * 1000      # revisión automática con calibre abierto
REMIND_INTERVAL_S = 24 * 60 * 60              # una misma versión se recuerda, como mucho, cada 24 h
PREVIEW_URL = 'https://download.calibre-ebook.com/preview/'
DOWNLOAD_PAGE = 'https://calibre-ebook.com/download'
LINUX_INSTALLER = 'https://download.calibre-ebook.com/linux-installer.sh'
# Solo para pruebas: ofrecer la Beta aunque sea más vieja que la estable (siempre False al publicar)
TEST_BETA_IGNORE_STABLE = False
MIN_INSTALLER_SIZE = 10 * 1024 * 1024   # un instalador real pesa >100 MB


def current_version_str():
    return '.'.join(map(str, numeric_version[:3]))


def running_beta():
    """Las versiones beta (preview) de calibre usan 100 o más en el último número: 9.15.101."""
    return parse_v(numeric_version)[2] >= 100


def _running_under_wine():
    try:
        import ctypes
        return hasattr(ctypes.WinDLL('ntdll'), 'wine_get_version')
    except Exception:
        return False


_INSTALL_KIND = None


def unsupported_install():
    """Tipo de instalación que el complemento NO debe actualizar solo, o None si es la oficial.
    'portable', 'wine', 'flatpak', 'appimage', 'snap', 'distro' o 'source'."""
    global _INSTALL_KIND
    if _INSTALL_KIND is not None:
        return _INSTALL_KIND or None
    kind = ''
    try:
        import calibre.constants as cc
        system = platform.system().lower()
        frozen = bool(getattr(cc, 'isfrozen', getattr(sys, 'frozen', False)))
        if system == 'windows':
            if getattr(cc, 'isportable', False) or os.environ.get('CALIBRE_PORTABLE_BUILD'):
                kind = 'portable'
            elif _running_under_wine():
                kind = 'wine'
            elif not frozen:
                kind = 'source'
        elif system == 'linux':
            if os.path.exists('/.flatpak-info') or os.environ.get('FLATPAK_ID'):
                kind = 'flatpak'
            elif os.environ.get('APPIMAGE') or os.environ.get('APPDIR'):
                kind = 'appimage'
            elif os.environ.get('SNAP'):
                kind = 'snap'
            elif getattr(cc, 'is_running_from_develop', False):
                kind = 'source'
            elif not frozen:
                kind = 'distro'      # paquete de la distribución (apt, dnf, pacman...)
        elif system == 'darwin':
            if not frozen or getattr(cc, 'is_running_from_develop', False):
                kind = 'source'
    except Exception as e:
        print('Calibre Updater: could not detect installation type: %r' % e)
    _INSTALL_KIND = kind
    print('Calibre Updater: installation type: %s' % (kind or 'official'))
    return kind or None


def install_kind_name(kind):
    return {'portable': 'Portable', 'wine': 'Wine', 'flatpak': 'Flatpak', 'appimage': 'AppImage',
            'snap': 'Snap', 'distro': _('distribution package'), 'source': _('source code')}.get(kind, kind)


def install_kind_howto(kind):
    return {
        'portable': _('Download the new Portable version from the <a href="https://calibre-ebook.com/download_portable">'
                      'calibre website</a> and install it over your current portable folder.'),
        'wine': _('Run the new Windows installer manually inside Wine.'),
        'flatpak': _('Update it from your software center or with the command <b>flatpak update</b>.'),
        'appimage': _('Download the new AppImage from the same place you got the current one.'),
        'snap': _('Update it with the command <b>snap refresh</b>.'),
        'distro': _("Update it with your distribution's package manager."),
        'source': _('Update your copy of the calibre source code.'),
    }.get(kind, '')


PORTABLE_MAX_PATH = 58      # límite del instalador Portable de calibre para la ruta de la carpeta


def install_folder():
    """Carpeta (o .app en macOS) de la copia de calibre que se está ejecutando. No depende del
    nombre que el usuario le haya puesto: se obtiene de la ubicación real del programa."""
    system = platform.system().lower()
    try:
        if system == 'windows':
            pb = os.environ.get('CALIBRE_PORTABLE_BUILD')
            if pb:
                # El lanzador Portable la define como <carpeta>\Calibre\calibre.exe
                return os.path.normpath(os.path.dirname(os.path.dirname(os.path.abspath(pb))))
            exe = _current_windows_calibre_exe() or sys.executable or ''
            return os.path.normpath(os.path.dirname(os.path.abspath(exe)))
        if system == 'darwin':
            return _current_mac_app_path()
        d = os.path.dirname(os.path.realpath(sys.executable or ''))
        for _i in range(4):
            if os.path.exists(os.path.join(d, 'calibre-debug')) and os.path.isdir(os.path.join(d, 'lib')):
                return d
            d = os.path.dirname(d)
        return os.path.dirname(os.path.realpath(sys.executable or ''))
    except Exception as e:
        print('Calibre Updater: could not detect the installation folder: %r' % e)
        return ''


def plugin_version():
    """Versión de este complemento, tomada de __init__.py (por ejemplo "1.23.0")."""
    try:
        from calibre_plugins.calibre_updater import CalibreUpdatePlugin
        return '.'.join(map(str, CalibreUpdatePlugin.version))
    except Exception:
        return '?'


def system_description():
    """Sistema operativo en forma legible: "Windows 11 (26100)", "macOS 15.5 (Apple Silicon)",
    "CachyOS (x86_64)". Nunca falla: si algo no se puede leer, usa lo que da Python."""
    try:
        system = platform.system().lower()
        machine = platform.machine()
        if system == 'windows':
            build = sys.getwindowsversion().build
            name = 'Windows 11' if build >= 22000 else 'Windows %s' % platform.release()
            return '%s (%s)' % (name, build)
        if system == 'darwin':
            chip = 'Apple Silicon' if machine.lower() in ('arm64', 'aarch64') else 'Intel'
            return 'macOS %s (%s)' % (platform.mac_ver()[0] or '?', chip)
        if system == 'linux':
            name = ''
            for path in ('/etc/os-release', '/usr/lib/os-release'):
                try:
                    with open(path, encoding='utf-8', errors='replace') as f:
                        for line in f:
                            if line.startswith('PRETTY_NAME='):
                                name = line.split('=', 1)[1].strip().strip('"\'')
                                break
                except OSError:
                    continue
                if name:
                    break
            return '%s (%s)' % (name or 'Linux ' + platform.release(), machine)
    except Exception:
        pass
    return platform.platform()


# --- Ícono personalizado de calibre (macOS) ---
# Es el mismo mecanismo que "Obtener información > pegar ícono" del Finder: no modifica los
# archivos firmados de calibre. Al reemplazarse la app (actualización de calibre) o a veces
# al actualizar macOS, el ícono se pierde; el complemento lo vuelve a aplicar.
MAC_SET_ICON_JS = r'''
ObjC.import('AppKit');
function run(argv) {
  var img = null;
  if (argv[0]) {
    img = $.NSImage.alloc.initWithContentsOfFile(argv[0]);
    if (!img || img.isNil()) { return 'bad-image'; }
  }
  return $.NSWorkspace.sharedWorkspace.setIconForFileOptions(img, argv[1], 0) ? 'ok' : 'failed';
}
'''


def mac_icon_supported():
    return platform.system().lower() == 'darwin' and not unsupported_install()


def mac_custom_icon():
    """Copia guardada del ícono elegido por el usuario, o '' si no hay."""
    path = prefs['mac_custom_icon'] or ''
    return path if path and os.path.isfile(path) else ''


def _mac_icon_present(app):
    """True si la app tiene un ícono personalizado aplicado (archivo "Icon\\r" y marca del Finder)."""
    if not os.path.exists(os.path.join(app, 'Icon\r')):
        return False
    try:
        out = subprocess.run(['/usr/bin/xattr', '-px', 'com.apple.FinderInfo', app], capture_output=True,
                             text=True, timeout=10).stdout
        data = bytes.fromhex(''.join(out.split()))
        return len(data) > 8 and bool(data[8] & 0x04)      # kHasCustomIcon
    except Exception:
        return True      # si no se puede comprobar, se asume aplicado (no se insiste)


def apply_mac_icon(icon_path, app=None):
    """Aplica (o, con icon_path vacío, quita) el ícono personalizado. Devuelve True si salió bien."""
    app = app or _current_mac_app_path()
    try:
        r = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', MAC_SET_ICON_JS, icon_path or '', app],
                           capture_output=True, text=True, timeout=30)
        ok = r.stdout.strip() == 'ok'
        print('Calibre Updater: custom icon %s on %r: %s %s' % ('set' if icon_path else 'removed', app,
                                                                r.stdout.strip(), r.stderr.strip()))
        if ok:
            # El Finder a veces tarda en mostrar el cambio: se le avisa que la app cambió
            subprocess.run(['/usr/bin/touch', app], capture_output=True, timeout=10)
        return ok
    except Exception as e:
        print('Calibre Updater: could not apply the custom icon: %r' % e)
        return False


def ensure_mac_icon():
    """Al abrir calibre: si hay un ícono elegido y macOS o una actualización lo quitaron, se vuelve a poner."""
    try:
        icon = mac_custom_icon()
        if icon and mac_icon_supported():
            app = _current_mac_app_path()
            if not _mac_icon_present(app):
                apply_mac_icon(icon, app)
    except Exception as e:
        print('Calibre Updater: custom icon check failed: %r' % e)


def _folder_key(path):
    return os.path.normcase(os.path.normpath(path)) if path else ''


def optin_case():
    """Instalaciones que el complemento actualiza SOLO si el usuario lo permite para esa carpeta:
    'portable' (Portable de Windows) o 'beta' (Beta instalada con el instalador oficial).
    None si no corresponde (instalación estándar, o tipos que nunca se actualizan solos)."""
    system = platform.system().lower()
    kind = unsupported_install()
    if kind == 'portable':
        if system == 'windows' and not _running_under_wine():
            return 'portable'
        return None
    if kind:
        return None
    if running_beta():
        if system == 'linux' and _folder_key(install_folder()) != _folder_key('/opt/calibre'):
            return None     # el instalador de Linux solo actualiza /opt/calibre
        return 'beta'
    return None


def optin_blocker():
    """Motivo por el que no se puede ofrecer la opción en esta carpeta, o ''."""
    if optin_case() == 'portable' and len(install_folder()) > PORTABLE_MAX_PATH:
        return _('The path of this Portable folder is too long (more than {n} characters), so it cannot '
                 'be updated automatically. Move it to a shorter path, such as D:\\Calibre Portable.').format(
                     n=PORTABLE_MAX_PATH)
    return ''


def optin_enabled():
    """True si el usuario permitió actualizar automáticamente la copia de ESTA carpeta.
    Se guarda por carpeta: una Beta y una estable comparten configuración, y marcar una
    no debe afectar a la otra."""
    key = _folder_key(install_folder())
    return bool(key) and key in [_folder_key(x) for x in (prefs['auto_update_folders'] or [])]


def set_optin_enabled(enabled):
    key = _folder_key(install_folder())
    if not key:
        return
    folders = [x for x in (prefs['auto_update_folders'] or []) if _folder_key(x) != key]
    if enabled:
        folders.append(install_folder())
    prefs['auto_update_folders'] = folders


def optin_hint():
    """Frase que recuerda que existe la opción, si esta copia puede usarla y aún no la tiene activada."""
    if optin_case() and not optin_blocker() and not optin_enabled():
        return _('You can also allow the plugin to update this copy automatically in its settings '
                 '(<b>Advanced Configuration</b>).')
    return ''


def cleanup_optin():
    """Una Beta que ya pasó a ser estable deja de necesitar el permiso: se quita, para que una
    Beta nueva en esa misma carpeta vuelva a requerir que el usuario lo elija."""
    try:
        if optin_enabled() and not running_beta() and not unsupported_install():
            set_optin_enabled(False)
            print('Calibre Updater: Beta updated to stable; automatic update permission removed for %r'
                  % install_folder())
    except Exception as e:
        print('Calibre Updater: could not clean up the update permission: %r' % e)


def linux_arch():
    """Arquitectura con el nombre que usa calibre en sus archivos para Linux, o None."""
    m = platform.machine().lower()
    if m in ('x86_64', 'amd64'):
        return 'x86_64'
    if m in ('aarch64', 'arm64'):
        return 'arm64'
    return None


def beta_install_case():
    """Copias en las que el usuario puede permitir instalar versiones Beta:
    'msi' / 'portable' (Windows), 'mac' (la app de calibre) o 'linux' (/opt/calibre).
    None si no corresponde."""
    system = platform.system().lower()
    kind = unsupported_install()
    if system == 'windows':
        if _running_under_wine():
            return None
        if kind is None:
            return 'msi'
        if kind == 'portable' and len(install_folder()) <= PORTABLE_MAX_PATH:
            return 'portable'
        return None
    if kind is not None:
        return None
    if system == 'darwin':
        return 'mac'
    if system == 'linux' and linux_arch() and _folder_key(install_folder()) == _folder_key('/opt/calibre'):
        return 'linux'
    return None


def beta_install_enabled():
    """True si el usuario permitió instalar Betas en ESTA carpeta (y sigue activado el aviso de Betas)."""
    if not prefs['check_betas'] or not beta_install_case():
        return False
    key = _folder_key(install_folder())
    return bool(key) and key in [_folder_key(x) for x in (prefs['beta_install_folders'] or [])]


def beta_install_hint():
    """Cómo habilitar la instalación de Betas, si esta copia puede usarla y todavía no está activada."""
    if beta_install_case() and not beta_install_enabled():
        return _('To install Beta versions, enable <b>Also install Beta versions</b> in the plugin settings '
                 '(Advanced Configuration). The option to install it will then appear in the plugin menu.')
    return ''


def set_beta_install_enabled(enabled):
    key = _folder_key(install_folder())
    if not key:
        return
    folders = [x for x in (prefs['beta_install_folders'] or []) if _folder_key(x) != key]
    if enabled:
        folders.append(install_folder())
    prefs['beta_install_folders'] = folders


def can_auto_update():
    if not running_beta() and not unsupported_install():
        return True          # instalación oficial estándar
    if beta_install_enabled():
        return True          # quien instala Betas también recibe las estables
    return bool(optin_case()) and not optin_blocker() and optin_enabled()


def manual_update_only():
    """True si el complemento solo debe avisar (Beta o instalación no oficial sin permiso del usuario)."""
    return not can_auto_update()


# --- VENTANA DE REGISTRO (LINUX) ---
class LogWindow(QDialog):
    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.success = False
        self.setWindowTitle(_("Calibre Update Log"))
        self.resize(600, 400)
        layout = QVBoxLayout(self)

        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: monospace;")
        layout.addWidget(self.log_output)

        self.status_label = QLabel(_("Waiting for authentication..."), self)
        layout.addWidget(self.status_label)

        self.btn_close = QPushButton(_("Close and Restart Calibre"), self)
        self.btn_close.setEnabled(False)
        self.btn_close.clicked.connect(self.finalizar_todo)
        layout.addWidget(self.btn_close)

    @pyqtSlot(str)
    def append_text(self, text):
        self.log_output.append(text)
        self.log_output.ensureCursorVisible()

    @pyqtSlot(str)
    def set_status(self, text):
        self.status_label.setText(text)

    @pyqtSlot(bool)
    def installation_finished(self, ok):
        self.success = ok
        if not ok:
            self.btn_close.setText(_("Close"))
        self.btn_close.setEnabled(True)

    def finalizar_todo(self):
        self.accept()
        if self.success:
            # Cierre ordenado (base de datos, preferencias) y relanzamiento:
            # arranca el binario recién instalado en /opt/calibre
            self.gui.quit(restart=True)


# --- DIÁLOGO DE AVISO ---
class UpdateNoticeDialog(QDialog):
    def __init__(self, parent, version_nueva, icon_pixmap, cl_translated, cl_original,
                 beta_version_text="", is_beta_alert=False, tr_error="", notify_only=False):
        super().__init__(parent)
        self.cl_translated = cl_translated
        self.cl_original = cl_original
        self.tr_error = tr_error
        self.showing_translation = bool(cl_translated)

        self.setWindowTitle(_("New Beta Version Available") if is_beta_alert else _("Update Available!"))
        self.setMinimumWidth(560)
        self.resize(600, 520)
        layout = QVBoxLayout(self)

        h_layout = QHBoxLayout()
        img_label = QLabel()
        if not icon_pixmap.isNull():
            img_label.setPixmap(icon_pixmap.scaled(60, 60, Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation))
        h_layout.addWidget(img_label)

        self.can_install_beta = bool(is_beta_alert and beta_install_enabled())
        if self.can_install_beta:
            msg_text = _("A new Beta version of calibre (<b>{v}</b>) is available. Beta versions are for testing "
                         "and may contain bugs. Do you want to install it now?").format(v=version_nueva)
        elif is_beta_alert:
            msg_text = _("A new Beta version of Calibre (<b>{v}</b>) has been detected. "
                         "Automatic updates are restricted to stable releases.").format(v=version_nueva)
            if beta_install_hint():
                msg_text += '<br><br>' + beta_install_hint()
        elif notify_only and unsupported_install():
            kind = unsupported_install()
            msg_text = _("Version <b>{v}</b> (Stable) is available. This calibre installation ({kind}) "
                         "cannot be updated automatically by this plugin.").format(
                v=version_nueva, kind=install_kind_name(kind)) + '<br><br>' + install_kind_howto(kind)
            if optin_hint():
                msg_text += ' ' + optin_hint()
        elif notify_only:
            msg_text = _("Version <b>{v}</b> (Stable) is available. You are using a Beta version of calibre, "
                         "so automatic updates are disabled. You can install it manually from the "
                         "<a href=\"https://calibre-ebook.com/download\">calibre website</a>.").format(v=version_nueva)
            if optin_hint():
                msg_text += ' ' + optin_hint()
        else:
            msg_text = _("Version <b>{v}</b> (Stable) is available. Do you want to update now?").format(v=version_nueva)
        msg = QLabel(msg_text)
        msg.setWordWrap(True)
        msg.setOpenExternalLinks(True)
        h_layout.addWidget(msg, 1)
        layout.addLayout(h_layout)

        # Cabecera de cambios
        cl_header = QHBoxLayout()
        cl_header.addWidget(QLabel('<b>' + _("Recent changes:") + '</b>'))
        self.info_label = QLabel()
        self.info_label.setStyleSheet("color: gray; font-size: 11px; font-style: italic;")
        cl_header.addWidget(self.info_label)
        cl_header.addStretch()
        if cl_translated and cl_original:
            self.btn_toggle = QPushButton()
            self.btn_toggle.setFlat(True)
            self.btn_toggle.setStyleSheet("font-size: 11px;")
            self.btn_toggle.clicked.connect(self.toggle_language)
            cl_header.addWidget(self.btn_toggle)
        layout.addLayout(cl_header)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, 1)
        self.refresh_changelog()


        if beta_version_text:
            if not is_beta_alert and beta_install_hint():
                beta_version_text += '<br>' + beta_install_hint()
            beta_lbl = QLabel(beta_version_text)
            beta_lbl.setWordWrap(True)
            beta_lbl.setStyleSheet("color: #555555; background-color: #f4f6f8; border: 1px solid #e1e4e8; "
                                   "border-radius: 4px; padding: 6px; font-size: 11px; margin-top: 4px;")
            layout.addWidget(beta_lbl)

        btn_layout = QHBoxLayout()
        # Versión del complemento y sistema, discretos: así cualquier captura del aviso ya los muestra
        ver_lbl = QLabel('Calibre Updater %s · %s' % (plugin_version(), system_description()))
        ver_lbl.setStyleSheet("color: #888888; font-size: 10px;")
        ver_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        btn_layout.addWidget(ver_lbl, 0, Qt.AlignmentFlag.AlignBottom)
        btn_layout.addStretch()
        if self.can_install_beta:
            btn_upd = QPushButton(_("Install Beta"))
            btn_upd.clicked.connect(self.accept)
            btn_layout.addWidget(btn_upd)
            btn_later = QPushButton(_("Not Now"))
            btn_later.setDefault(True)
            btn_later.clicked.connect(self.reject)
            btn_layout.addWidget(btn_later)
        elif is_beta_alert or notify_only:
            btn_close = QPushButton(_("Close"))
            btn_close.clicked.connect(self.reject)
            btn_layout.addWidget(btn_close)
        else:
            btn_upd = QPushButton(_("Update Now"))
            btn_upd.setDefault(True)
            btn_upd.clicked.connect(self.accept)
            btn_layout.addWidget(btn_upd)
            btn_later = QPushButton(_("Not Now"))
            btn_later.clicked.connect(self.reject)
            btn_layout.addWidget(btn_later)
        layout.addLayout(btn_layout)

    def refresh_changelog(self):
        if self.showing_translation:
            self.log_view.setHtml(self.cl_translated)
            self.info_label.setText(_("(automatic translation)"))
        elif self.cl_original:
            self.log_view.setHtml(self.cl_original)
            if self.tr_error:
                self.info_label.setText(_("(original, in English: automatic translation not available)"))
                self.info_label.setToolTip(self.tr_error)
            else:
                self.info_label.setText(_("(original, in English)"))
        else:
            self.log_view.setPlainText(_("Could not load the list of changes."))
            self.info_label.setText('')
        if hasattr(self, 'btn_toggle'):
            self.btn_toggle.setText(_("Show original") if self.showing_translation else _("Show translation"))

    def toggle_language(self):
        self.showing_translation = not self.showing_translation
        self.refresh_changelog()


# --- ACCIÓN PRINCIPAL ---
class CalibreUpdaterAction(InterfaceAction):
    name = 'CalibreUpdaterAction'
    PLUGIN_ICONS = ['images/icon.png']
    action_spec = (_('Calibre Updater'), None, _('Close and update Calibre'), 'Ctrl+Shift+U')
    popup_type = QToolButton.ToolButtonPopupMode.MenuButtonPopup

    def genesis(self):
        self.latest_v = None
        self.latest_beta = None
        self.update_in_progress = False
        self._pd = None

        self.icon_pix = QPixmap()
        self.icon = QIcon()
        data = self.load_resources(self.PLUGIN_ICONS).get('images/icon.png')
        if data:
            self.icon_pix.loadFromData(data)
            self.icon = QIcon(self.icon_pix)
            self.qaction.setIcon(self.icon)

        self.qaction.triggered.connect(self.ejecutar_actualizacion)

        self.menu = QMenu(self.gui)
        self.update_now_action = self.menu.addAction(self.icon, _('Update now'), self.ejecutar_actualizacion)
        self._refresh_update_action()
        self.menu.aboutToShow.connect(self._refresh_update_action)
        self.menu.addSeparator()
        self.stable_menu_action = self.menu.addAction(_('Stable: Checking...'))
        self.stable_menu_action.setEnabled(False)
        self.beta_menu_action = self.menu.addAction(_('Beta: Checking...'))
        self.beta_menu_action.setEnabled(False)
        self.beta_menu_action.triggered.connect(lambda *a: self.instalar_beta())
        self._beta_menu_text = _('Beta: Checking...')
        self.beta_menu_action.setVisible(bool(prefs['check_betas']))   # solo con los avisos de Betas
        self.menu.addSeparator()
        self.menu.addAction(_('Configure plugin...'), self.show_config_window)
        self.menu.addAction(_('About {0}').format(_('Calibre Updater')), self.show_about)
        self.qaction.setMenu(self.menu)

    def _refresh_update_action(self):
        if hasattr(self, 'beta_menu_action'):
            self._refresh_beta_action()
        upd = self.update_now_action
        if can_auto_update():
            upd.setText(_('Update now'))
            upd.setEnabled(True)
        elif running_beta() and not unsupported_install():
            upd.setText(_('Update now (not available in Beta versions)'))
            upd.setEnabled(False)
        else:
            upd.setText(_('Update now (manual update required)'))
            upd.setEnabled(False)

    def initialization_complete(self):
        cleanup_optin()
        if mac_icon_supported() and mac_custom_icon():
            threading.Thread(target=ensure_mac_icon, daemon=True).start()
        # Se espera a que la ventana principal esté lista antes de chequear
        threading.Thread(target=self.check_updates_startup, daemon=True).start()
        # Aviso si sigue activa la versión anterior del complemento (después de que la ventana se vea)
        from qt.core import QTimer
        QTimer.singleShot(1500, self._warn_old_plugin)
        # Cuando calibre detecta una versión nueva con su propia revisión, el complemento se entera
        # en ese momento: nunca avisa después que calibre y no hace ninguna consulta extra.
        # (La casilla de calibre "mostrar esta notificación" solo oculta su ventana, no su revisión.)
        try:
            uc = getattr(self.gui, 'update_checker', None)
            if uc is not None:
                uc.signal.update_found.connect(self._calibre_found_update, type=Qt.ConnectionType.QueuedConnection)
        except Exception as e:
            print('Calibre Updater: could not connect to calibre update checker: %r' % e)
        # Revisión propia cada 3 h: cubre lo que calibre no avisa (versiones de mantenimiento y Betas)
        self._recheck_timer = QTimer(self)
        self._recheck_timer.setInterval(RECHECK_INTERVAL_MS)
        self._recheck_timer.timeout.connect(self._periodic_check)
        self._recheck_timer.start()

    def _calibre_found_update(self, calibre_version, number_of_plugin_updates=0):
        try:
            if not calibre_version or tuple(calibre_version)[0] <= 0:
                return          # calibre solo avisaba de actualizaciones de complementos
            if parse_v('.'.join(map(str, calibre_version))) <= parse_v(numeric_version):
                return
        except Exception:
            return
        if self.update_in_progress:
            return
        threading.Thread(target=self.check_updates_startup,
                         kwargs={'periodic': True, 'source': 'calibre notice'}, daemon=True).start()

    def _periodic_check(self):
        if self.update_in_progress:
            return
        threading.Thread(target=self.check_updates_startup, kwargs={'periodic': True}, daemon=True).start()

    def _warn_old_plugin(self):
        """La versión anterior se llamaba "Calibre Auto-Updater". Si sigue instalada y activa,
        habría avisos (e instalaciones) duplicados."""
        name = _old_plugin_enabled()
        if not name:
            return
        info_dialog(self.gui, _('Calibre Updater'),
                    _('The previous version of this plugin ("{name}") is still installed and enabled. '
                      'To avoid duplicate notifications, please remove it from '
                      '<b>Preferences → Plugins</b>.').format(name=name), show=True)

    # ------------------------------------------------------------ consultas de red

    def _fetch_stable(self):
        try:
            # Misma función que usa calibre para su propio aviso: verifica el certificado
            # de code.calibre-ebook.com contra la CA de calibre incluida en el programa.
            from calibre.utils.https import get_https_resource_securely
            try:
                raw = get_https_resource_securely(LATEST_URL, timeout=10)
            except TypeError:
                raw = get_https_resource_securely(LATEST_URL)
            v = raw.decode('utf-8').strip()
            if not re.match(r'^\d+\.\d+\.\d+$', v):
                raise ValueError('Unexpected version string: %r' % v[:50])
            self.latest_v = v
            self._set_menu_text('stable', _("Stable: v{v}").format(v=v))
            return v
        except Exception:
            self._set_menu_text('stable', _("Stable: Check failed"))
        return None

    def _fetch_beta(self):
        try:
            req = urllib.request.Request(PREVIEW_URL, headers=UA)
            with urllib.request.urlopen(req, timeout=10, context=clog.ssl_context()) as r:
                page = r.read().decode('utf-8', errors='ignore')
            matches = re.findall(r'calibre[_-](?:64bit-|win64-|portable-installer-)?[vV]?(\d+\.\d+\.\d+)'
                                 r'.*?(\d{2}-[A-Za-z]{3}-\d{4})', page)
            if matches:
                v_beta, fecha = max(matches, key=lambda m: parse_v(m[0]))
                self.latest_beta = v_beta
                texto = _("ℹ️ Latest Beta version detected: v{v} (Published {date})").format(v=v_beta, date=fecha)
                self._set_menu_text('beta', _("Beta: v{v}").format(v=v_beta))
                return v_beta, texto
        except Exception:
            pass
        self._set_menu_text('beta', _("Beta: Check failed"))
        return None, ""

    def _set_menu_text(self, which, text):
        QMetaObject.invokeMethod(self, "update_menu_text", Qt.ConnectionType.QueuedConnection,
                                 Q_ARG(str, which), Q_ARG(str, text))

    @pyqtSlot(str, str)
    def update_menu_text(self, which, text):
        if which == 'stable':
            self.stable_menu_action.setText(text)
        else:
            self._beta_menu_text = text
            self._refresh_beta_action()

    def _installable_beta(self):
        """Versión Beta que se puede instalar ahora, o None."""
        b = self.latest_beta
        if not b or not beta_install_enabled():
            return None
        if parse_v(b) <= parse_v(numeric_version):
            return None
        if self.latest_v and parse_v(b) <= parse_v(self.latest_v) and not TEST_BETA_IGNORE_STABLE:
            return None
        return b

    def _refresh_beta_action(self):
        self.beta_menu_action.setVisible(bool(prefs['check_betas']))
        b = self._installable_beta()
        if b:
            self.beta_menu_action.setText(_('Install Beta v{v}...').format(v=b))
            self.beta_menu_action.setEnabled(True)
        else:
            self.beta_menu_action.setText(self._beta_menu_text)
            self.beta_menu_action.setEnabled(False)

    def _build_changelog(self, target, is_beta):
        """Devuelve (html_traducido, html_original, motivo_si_no_se_tradujo). Corre en un hilo secundario."""
        try:
            releases = clog.parse_changelog(clog.fetch_changelog_text())
        except Exception as e:
            print('Calibre Updater: could not fetch changelog: %r' % e)
            return '', '', ''
        sel = releases[:1] if is_beta else clog.select_release(releases, target)
        original = clog.render_html(sel)

        translated, tr_error = '', ''
        lang = clog.ui_language() if prefs['translate_changelog'] else None
        print('Calibre Updater: interface language=%s, translation target=%s, enabled=%s'
              % (clog.raw_ui_language(), lang, prefs['translate_changelog']))
        if lang and sel:
            # "v2": formato con una sola versión; invalida el caché anterior con varias versiones
            key = '|'.join(('v2', target, lang))
            cache = prefs['changelog_cache'] or {}
            if cache.get('key') == key and cache.get('html'):
                translated = cache['html']
            else:
                try:
                    clog.translate_releases(sel, lang)
                    translated = clog.render_html(sel, translated=True)
                    prefs['changelog_cache'] = {'key': key, 'html': translated}
                except Exception as e:
                    # sin conexión, límite de Google o servicio caído: se muestra en inglés
                    translated = ''
                    tr_error = '%s: %s' % (type(e).__name__, e)
                    print('Calibre Updater: changelog translation failed: ' + tr_error)
        return translated, original, tr_error

    def check_updates_startup(self, periodic=False, source=None):
        log = _file_logger(os.path.join(self.get_download_path(), 'calibre-updater.log'))
        kind_check = source or ('periodic' if periodic else 'startup')
        # La página de Betas solo se consulta si el usuario activó los avisos de Betas
        check_betas = bool(prefs['check_betas'])
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_stable = executor.submit(self._fetch_stable)
            fut_beta = executor.submit(self._fetch_beta) if check_betas else None
            latest_v = fut_stable.result()
            v_beta, beta_text = fut_beta.result() if fut_beta else (None, '')
        # Una Beta igual o anterior a la estable ya quedó superada: no se muestra
        if v_beta and latest_v and parse_v(v_beta) <= parse_v(latest_v) and not (
                TEST_BETA_IGNORE_STABLE and beta_install_enabled() and parse_v(v_beta) > parse_v(numeric_version)):
            v_beta, beta_text = None, ''
            self._set_menu_text('beta', _("Beta: none newer than the stable version"))
        # Los avisos de Beta no aplican a copias Beta/no estándar, salvo que el usuario permita instalar Betas
        beta_install = (running_beta() or bool(unsupported_install())) and not beta_install_enabled()
        if not prefs['check_betas'] or beta_install:
            beta_text = ''   # el recuadro de la beta solo se muestra con la opción activada

        current = parse_v(numeric_version)
        target, is_beta = None, False

        # Con permiso para instalar Betas, se ofrece lo más nuevo: la Beta si supera a la estable
        if (beta_install_enabled() and v_beta and parse_v(v_beta) > current
                and (not latest_v or parse_v(v_beta) > parse_v(latest_v) or TEST_BETA_IGNORE_STABLE)):
            target, is_beta = v_beta, True
        elif latest_v and parse_v(latest_v) > current:
            if prefs['only_maintenance'] and parse_v(latest_v)[2] == 0:
                log('automatic check (%s): installed %s, stable %s, Beta %s -> no notice '
                    '("only maintenance versions" is enabled)' % (kind_check, current_version_str(), latest_v, v_beta))
                return
            target = latest_v
        elif prefs['check_betas'] and not beta_install and v_beta and parse_v(v_beta) > max(
                current, parse_v(latest_v or '0') if not TEST_BETA_IGNORE_STABLE else current):
            target, is_beta = v_beta, True

        state = 'automatic check (%s): installed %s, stable %s, Beta %s' % (
            kind_check, current_version_str(), latest_v or 'unknown', v_beta or 'none')
        if not target:
            log(state + ' -> up to date' if latest_v else state + ' -> could not check the stable version')
            return
        # Si el aviso anterior sigue abierto (el usuario no estuvo), no se apila otro igual
        if periodic and getattr(self, '_notice_open', False):
            log(state + ' -> previous notice still open')
            return
        # En las revisiones periódicas, una versión ya avisada se recuerda como mucho cada 24 h
        last = getattr(self, '_last_notice', {}).get(target)
        if periodic and last and time.time() - last < REMIND_INTERVAL_S:
            log(state + ' -> %s already notified less than 24 h ago' % target)
            return
        log(state + ' -> notice for %s' % target)

        cl_tr, cl_orig, tr_error = self._build_changelog(target, is_beta)
        QMetaObject.invokeMethod(self, "notify_update_available", Qt.ConnectionType.QueuedConnection,
                                 Q_ARG(str, target), Q_ARG(str, beta_text or ''),
                                 Q_ARG(bool, is_beta), Q_ARG(str, cl_tr), Q_ARG(str, cl_orig),
                                 Q_ARG(str, tr_error))

    @pyqtSlot(str, str, bool, str, str, str)
    def notify_update_available(self, version_nueva, beta_text, is_beta_alert, cl_tr, cl_orig, tr_error):
        notify_only = manual_update_only()
        if getattr(self, '_notice_open', False) or self.update_in_progress:
            return
        dlg = UpdateNoticeDialog(self.gui, version_nueva, self.icon_pix, cl_tr, cl_orig,
                                 beta_text, is_beta_alert, tr_error, notify_only)
        if not hasattr(self, '_last_notice'):
            self._last_notice = {}
        self._last_notice[version_nueva] = time.time()
        self._notice_open = True
        try:
            accepted = dlg.exec() == QDialog.DialogCode.Accepted
        finally:
            self._notice_open = False
        if accepted and is_beta_alert and dlg.can_install_beta:
            self.instalar_beta(version_nueva)
        elif accepted and not is_beta_alert and not notify_only:
            self.ejecutar_actualizacion()

    # ------------------------------------------------------------ configuración

    def show_about(self):
        from calibre_plugins.calibre_updater.support import show_about
        show_about(self.gui, self.interface_action_base_plugin)

    def show_config_window(self):
        from calibre_plugins.calibre_updater.config import ConfigWidget
        d = QDialog(self.gui)
        d.setWindowTitle(_('Configure Calibre Updater'))
        layout = QVBoxLayout(d)
        conf = ConfigWidget(self.gui)
        layout.addWidget(conf)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        layout.addWidget(bb)
        # Ancho fijo razonable y alto según el contenido: con textos de varias líneas, Qt a veces
        # calcula una ventana demasiado chica y corta parte de la información
        d.setMinimumWidth(560)
        d.adjustSize()
        d.resize(max(d.width(), 560), d.sizeHint().height())
        if d.exec() == QDialog.DialogCode.Accepted:
            conf.save_settings()
            self._refresh_update_action()
            # Si se acaban de activar los avisos de Betas, se consulta ya para completar el menú
            if prefs['check_betas'] and not self.latest_beta:
                threading.Thread(target=self._fetch_beta, daemon=True).start()
            info_dialog(self.gui, _('Saved'), _('Preferences updated successfully.'), show=True)

    def get_download_path(self, beta=False):
        # normpath: Qt devuelve rutas con "/" (C:/Users/...). Mezcladas con "\\" hacen fallar
        # a msiexec con el error 1619 ("no se pudo abrir el paquete").
        beta_dir = prefs['beta_download_dir'] if beta else ''
        if beta_dir and os.path.isdir(beta_dir):
            return os.path.normpath(os.path.abspath(beta_dir))
        custom_dir = prefs['download_dir']
        if custom_dir and os.path.isdir(custom_dir):
            return os.path.normpath(os.path.abspath(custom_dir))
        d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        d = d if d and os.path.isdir(d) else os.path.expanduser('~')
        return os.path.normpath(os.path.abspath(d))

    def get_versioned_name(self, ext):
        v = self.latest_v or "latest"
        if ext == "msi":
            return f"calibre-64bit-{v}.msi"
        return f"calibre-{v}.{ext}"

    # ------------------------------------------------------------ actualización

    def ejecutar_actualizacion(self, *args):
        if self.update_in_progress:
            return
        case = optin_case() if (running_beta() or unsupported_install()) else None
        if running_beta() and not can_auto_update() and not unsupported_install():
            info_dialog(self.gui, _('Calibre Updater'),
                        _('You are using a Beta version of calibre (v{v}).<br><br>Automatic updates are '
                          'disabled for Beta versions. This plugin will only notify you when a new stable '
                          'version is available.').format(v=current_version_str())
                        + ('<br><br>' + optin_hint() if optin_hint() else ''), show=True)
            return
        kind = unsupported_install()
        if kind and not can_auto_update():
            info_dialog(self.gui, _('Calibre Updater'),
                        _('This calibre installation ({kind}) cannot be updated automatically by this plugin. '
                          'It will only notify you when a new stable version is available.').format(
                            kind=install_kind_name(kind)) + '<br><br>' + install_kind_howto(kind)
                        + ('<br><br>' + optin_hint() if optin_hint() else ''), show=True)
            return
        # Siempre se vuelve a consultar: calibre puede llevar días abierto y el dato del
        # arranque estar viejo. Si la consulta falla, se usa el último valor conocido.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._fetch_stable()
        finally:
            QApplication.restoreOverrideCursor()

        current_v = current_version_str()
        latest_v = self.latest_v
        _file_logger(os.path.join(self.get_download_path(), 'calibre-updater.log'))(
            'update requested on %s (plugin %s, %s): installed %s, latest stable %s' % (
                platform.system(), plugin_version(), system_description(), current_v, latest_v))

        # Con "Instalar también las versiones Beta" activado, el botón instala lo más nuevo según
        # la configuración: la Beta si es más nueva que la estable (se vuelve a consultar, porque
        # puede haber salido con calibre abierto)
        if beta_install_enabled():
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._fetch_beta()
            finally:
                QApplication.restoreOverrideCursor()
            if self._installable_beta():
                self.instalar_beta()
                return

        if latest_v and parse_v(latest_v) <= parse_v(numeric_version):
            info_dialog(self.gui, _('Calibre Up to Date'),
                        _('<b>You already have the latest version installed (v{v}).</b><br><br>'
                          'There are no updates pending.').format(v=current_v), show=True)
            return

        if latest_v:
            header_msg = _('Do you want to update Calibre from version <b>v{curr}</b> to version <b>v{latest}</b>?').format(
                curr=current_v, latest=latest_v)
        else:
            header_msg = _('Do you want to close calibre and start the update?')

        if case:
            # Beta o Portable con permiso del usuario: se repite la carpeta antes de confirmar
            msg = ('<div style="min-width: 450px">' + header_msg + '<br><br>' +
                   _('The copy of calibre in this folder will be updated:<br><b>{folder}</b>').format(
                       folder=install_folder()) + '</div>')
        else:
            msg = _(
                '<div style="min-width: 450px">'
                '{header}<br><br>'
                '<b>IMPORTANT:</b> This plugin is designed for <b>official/standard</b> installations '
                '(from the calibre website). If you use Flatpak, AppImage, or Portable versions, '
                'you must update them MANUALLY.'
                '</div>'
            ).format(header=header_msg)

        if not question_dialog(self.gui, _('Calibre Updater'), msg, show_copy_button=False):
            return
        if not self._ensure_no_running_jobs():
            return
        if not self._ensure_tools_closed():
            return
        if not self._ensure_no_other_calibre():
            return

        sistema = platform.system().lower()
        if sistema == 'linux':
            self.actualizar_linux_pkexec()
        elif sistema == 'windows' and case == 'portable':
            if not latest_v:
                self._download_failed(_('Could not check the latest calibre version.'))
                return
            # El instalador Portable oficial, con la versión exacta (no hay enlace "dist" fijo)
            name = 'calibre-portable-installer-%s.exe' % latest_v
            dest = os.path.join(self.get_download_path(), name)
            self._descargar_con_progreso('https://download.calibre-ebook.com/%s/%s' % (latest_v, name),
                                         dest, 'windows-portable')
        elif sistema == 'windows':
            dest = os.path.join(self.get_download_path(), self.get_versioned_name("msi"))
            self._descargar_con_progreso("https://calibre-ebook.com/dist/win64", dest, "windows")
        elif sistema == 'darwin':
            # calibre publica un único instalador para Mac, válido para Intel y Apple Silicon
            dest = os.path.join(self.get_download_path(), self.get_versioned_name("dmg"))
            self._descargar_con_progreso("https://calibre-ebook.com/dist/osx", dest, "macos")

    def instalar_beta(self, version=None):
        """Instala la última Beta en ESTA copia (solo Windows y solo con permiso del usuario)."""
        if self.update_in_progress:
            return
        v = version or self._installable_beta()
        case = beta_install_case()
        if not v or not case or not beta_install_enabled():
            return
        log = _file_logger(os.path.join(self.get_download_path(), 'calibre-updater.log'))
        log('Beta install requested (plugin %s, %s): installed %s, Beta %s, type %s' % (
            plugin_version(), system_description(), current_version_str(), v, case))
        msg = ('<div style="min-width: 450px">' +
               _('Do you want to install the Beta version <b>v{v}</b>?').format(v=v) + '<br><br>' +
               _('The copy of calibre in this folder will be updated:<br><b>{folder}</b>').format(
                   folder=install_folder()) + '<br><br>' +
               _('The installer will be downloaded to:<br><b>{folder}</b>').format(
                   folder=self.get_download_path(beta=True)) + '<br><br>' +
               _('Beta versions are for testing and may contain bugs. It is recommended to keep a backup '
                 'of your library.') + '</div>')
        if not question_dialog(self.gui, _('Calibre Updater'), msg, show_copy_button=False):
            return
        if not self._ensure_no_running_jobs():
            return
        if not self._ensure_tools_closed():
            return
        if not self._ensure_no_other_calibre():
            return
        base = PREVIEW_URL.rstrip('/') + '/'
        if case == 'linux':
            if not shutil.which('pkexec'):
                error_dialog(self.gui, _('Calibre Updater'),
                             _('<b>pkexec</b> was not found on this system, so the plugin cannot request '
                               'administrator permissions. Close calibre and run this command in a terminal:'),
                             det_msg=('wget -O /tmp/calibre-beta.txz %scalibre-%s-%s.txz && sudo rm -rf /opt/calibre '
                                      '&& sudo mkdir -p /opt/calibre && sudo tar -xJf /tmp/calibre-beta.txz -C /opt/calibre '
                                      '&& sudo /opt/calibre/calibre_postinstall') % (base, v, linux_arch()), show=True)
                return
            name = 'calibre-%s-%s.txz' % (v, linux_arch())
            self._descargar_con_progreso(base + name, os.path.join(self.get_download_path(beta=True), name), 'linux-beta')
        elif case == 'mac':
            name = 'calibre-%s.dmg' % v
            self._descargar_con_progreso(base + name, os.path.join(self.get_download_path(beta=True), name), 'macos')
        elif case == 'portable':
            name = 'calibre-portable-installer-%s.exe' % v
            self._descargar_con_progreso(base + name, os.path.join(self.get_download_path(beta=True), name),
                                         'windows-portable')
        else:
            name = 'calibre-64bit-%s.msi' % v
            self._descargar_con_progreso(base + name, os.path.join(self.get_download_path(beta=True), name), 'windows')

    def _running_jobs_count(self):
        """Trabajos de calibre sin terminar (conversiones, descarga de metadatos, envío a
        dispositivos...): los mismos que muestra el panel "Trabajos". Igual en los tres sistemas."""
        jm = getattr(self.gui, 'job_manager', None)
        if jm is None:
            return 0
        try:
            jobs = getattr(jm, 'jobs', None)
            if jobs is not None:
                return sum(1 for j in list(jobs) if not getattr(j, 'is_finished', False))
        except Exception as e:
            print('Calibre Updater: could not count jobs: %r' % e)
        try:
            return 1 if jm.has_jobs() else 0
        except Exception:
            return 0

    def _ensure_no_running_jobs(self):
        """No se empieza a actualizar con trabajos en curso: al cerrarse, calibre preguntaría
        si cancelarlos y, si el usuario dice que no, la actualización quedaría a medias."""
        while True:
            n = self._running_jobs_count()
            print('Calibre Updater: running jobs: %d' % n)
            if not n:
                return True
            box = QMessageBox(QMessageBox.Icon.Warning, _('Calibre Updater'),
                              _('There are jobs still running in calibre ({n}), such as conversions, metadata '
                                'downloads or sending books to a device.<br><br>Wait until they finish or cancel '
                                'them from the Jobs panel (bottom right corner), then press <b>Retry</b>.').format(n=n),
                              parent=self.gui)
            box.setTextFormat(Qt.TextFormat.RichText)
            btn_retry = box.addButton(_('Retry'), QMessageBox.ButtonRole.AcceptRole)
            btn_cancel = box.addButton(_('Cancel'), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_retry)
            box.setEscapeButton(btn_cancel)
            box.exec()
            if box.clickedButton() is not btn_retry:
                return False

    def _ensure_no_other_calibre(self):
        """Windows: el instalador MSI no puede terminar si hay otra copia de calibre abierta
        (por ejemplo, un calibre portable). No se cierra sola: puede tener trabajo sin guardar."""
        while True:
            others = _other_calibre_copies()
            if not others:
                return True
            folders = []
            for _pid, path in others:
                d = os.path.dirname(path)
                if d not in folders:
                    folders.append(d)
            box = QMessageBox(QMessageBox.Icon.Warning, _('Calibre Updater'),
                              _('Another copy of calibre is running from a different folder (for example, a '
                                'portable version):<br><br>{folders}<br><br>The Windows installer cannot finish '
                                'while it is open. Close it and press <b>Retry</b>.').format(
                                  folders='<br>'.join('<b>%s</b>' % f for f in folders)),
                              parent=self.gui)
            box.setTextFormat(Qt.TextFormat.RichText)
            btn_retry = box.addButton(_('Retry'), QMessageBox.ButtonRole.AcceptRole)
            btn_cancel = box.addButton(_('Cancel'), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_retry)
            box.setEscapeButton(btn_cancel)
            box.exec()
            if box.clickedButton() is not btn_retry:
                return False

    def _ensure_tools_closed(self):
        """El editor y el visor de libros son programas aparte: no se cierran con calibre.
        Si hay alguno abierto, el usuario elige: cerrarlos él mismo, que el plugin los cierre
        (advirtiendo que se pierden cambios sin guardar) o cancelar."""
        while True:
            abiertos = _running_calibre_tools()
            if not abiertos:
                return True
            nombres = {'ebook-edit': _('E-book editor'), 'ebook-viewer': _('E-book viewer'),
                       'calibre-window': _('E-book viewer or editor')}
            tipos = []
            for kind, _pid in abiertos:
                if nombres[kind] not in tipos:
                    tipos.append(nombres[kind])
            lista = ', '.join('<b>%s</b>' % t for t in tipos)
            box = QMessageBox(QMessageBox.Icon.Warning, _('Calibre Updater'),
                              _('The following calibre windows are still open: {apps}.<br><br>'
                                'Save your work and close them, or let the plugin close them.<br><br>'
                                '<b>Warning:</b> if the plugin closes the E-book editor, any unsaved '
                                'changes will be lost.').format(apps=lista), parent=self.gui)
            box.setTextFormat(Qt.TextFormat.RichText)
            btn_retry = box.addButton(_('I closed them, continue'), QMessageBox.ButtonRole.AcceptRole)
            btn_kill = box.addButton(_('Close them for me'), QMessageBox.ButtonRole.DestructiveRole)
            btn_cancel = box.addButton(_('Cancel'), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_retry)
            box.setEscapeButton(btn_cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is btn_kill:
                _kill_calibre_tools(abiertos)
            elif clicked is not btn_retry:
                return False

    # --- Linux ---

    def actualizar_linux_pkexec(self):
        if shutil.which('wget'):
            fetch = 'wget -nv -O- ' + LINUX_INSTALLER
        else:
            fetch = 'curl -fsSL ' + LINUX_INSTALLER
        cmd_instalar = 'set -o pipefail; ' + fetch + ' | sh /dev/stdin'

        if not shutil.which('pkexec'):
            error_dialog(self.gui, _('Calibre Updater'),
                         _('<b>pkexec</b> was not found on this system, so the plugin cannot request '
                           'administrator permissions. Close calibre and run this command in a terminal:'),
                         det_msg='sudo -v && ' + fetch + ' | sudo sh /dev/stdin', show=True)
            return

        self._run_pkexec_in_log_window(['pkexec', 'bash', '-c', cmd_instalar])

    def _install_linux_tarball(self, tarball):
        """Linux: el instalador oficial solo instala versiones estables (verifica una firma que las
        Betas no tienen). Se hace lo mismo que él: descomprimir en /opt/calibre y ejecutar
        calibre_postinstall. Primero en una carpeta aparte y, si algo falla, se deja la anterior."""
        dest_dir = install_folder()
        self._run_pkexec_in_log_window(['pkexec', 'bash', '-c', LINUX_TARBALL_SH, 'calibre-updater',
                                        os.path.abspath(tarball), dest_dir],
                                       delete_on_success=os.path.abspath(tarball))

    def _run_pkexec_in_log_window(self, args, delete_on_success=None):
        log = _file_logger(os.path.join(self.get_download_path(), 'calibre-updater.log'))
        log('running with pkexec: %s' % ' '.join(a if len(a) < 200 else '<script>' for a in args))
        self.update_in_progress = True
        self.log_win = LogWindow(self.gui)
        self.log_win.show()
        win = self.log_win
        queued = Qt.ConnectionType.QueuedConnection

        def run_install():
            ok = False
            try:
                process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, errors='replace')
                QMetaObject.invokeMethod(win, "set_status", queued, Q_ARG(str, _("Installing...")))
                for line in process.stdout:
                    line = line.rstrip()
                    QMetaObject.invokeMethod(win, "append_text", queued, Q_ARG(str, line))
                    if not line.startswith('Downloaded '):      # sin las líneas de porcentaje
                        log('  ' + line)
                rc = process.wait()
                log('pkexec exit code %d' % rc)
                if rc == 0:
                    ok = True
                    if delete_on_success:
                        try:
                            os.remove(delete_on_success)
                            log('installer deleted')
                        except OSError:
                            pass
                    status = _("Completed!")
                elif rc in (126, 127):
                    status = _("Authentication cancelled or not authorized. Nothing was installed.")
                else:
                    status = _("Installation failed (exit code {code}).").format(code=rc)
            except Exception as e:
                QMetaObject.invokeMethod(win, "append_text", queued, Q_ARG(str, "ERROR: " + str(e)))
                log('ERROR: %r' % e)
                status = _("Installation failed.")
            QMetaObject.invokeMethod(win, "set_status", queued, Q_ARG(str, status))
            QMetaObject.invokeMethod(win, "installation_finished", queued, Q_ARG(bool, ok))
            QMetaObject.invokeMethod(self, "_linux_finished", queued)

        threading.Thread(target=run_install, daemon=True).start()

    @pyqtSlot()
    def _linux_finished(self):
        self.update_in_progress = False

    # --- Windows / macOS: descarga ---

    def _descargar_con_progreso(self, url, dest, os_type):
        self.update_in_progress = True
        pd = QProgressDialog(_('Downloading update...'), _('Cancel'), 0, 100, self.gui)
        pd.setWindowTitle(_("Calibre Updater"))
        pd.setMinimumWidth(420)    # en algunos escritorios quedaba muy angosta y cortaba el título
        pd.setAutoClose(False)
        pd.setAutoReset(False)
        pd.setMinimumDuration(0)
        pd.setValue(0)
        pd.show()
        self._pd = pd

        cancel_ev = threading.Event()
        pd.canceled.connect(cancel_ev.set)
        tmp = dest + '.part'
        queued = Qt.ConnectionType.QueuedConnection

        def run():
            try:
                req = urllib.request.Request(url, headers=UA)
                read = 0
                # Contexto SSL por defecto: el certificado SÍ se verifica
                with urllib.request.urlopen(req, timeout=30, context=clog.ssl_context()) as resp, open(tmp, 'wb') as f:
                    total = int(resp.headers.get('Content-Length') or 0)
                    last = -1
                    while not cancel_ev.is_set():
                        chunk = resp.read(512 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        read += len(chunk)
                        if total:
                            val = min(100, int(read * 100 / total))
                            if val != last:
                                last = val
                                QMetaObject.invokeMethod(pd, "setValue", queued, Q_ARG(int, val))
                if cancel_ev.is_set():
                    _silent_remove(tmp)
                    QMetaObject.invokeMethod(self, "_download_cancelled", queued)
                    return
                if (total and read < total) or read < MIN_INSTALLER_SIZE:
                    raise IOError(_('Incomplete or invalid download ({n} bytes received).').format(n=read))
                os.replace(tmp, dest)
                QMetaObject.invokeMethod(self, "_download_finished", queued, Q_ARG(str, dest), Q_ARG(str, os_type))
            except Exception as e:
                _silent_remove(tmp)
                QMetaObject.invokeMethod(self, "_download_failed", queued, Q_ARG(str, str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _close_progress(self):
        if self._pd is not None:
            self._pd.close()
            self._pd.deleteLater()
            self._pd = None
        self.update_in_progress = False

    @pyqtSlot()
    def _download_cancelled(self):
        self._close_progress()

    @pyqtSlot(str)
    def _download_failed(self, err):
        self._close_progress()
        _file_logger(os.path.join(self.get_download_path(), 'calibre-updater.log'))('download FAILED: ' + err)
        if question_dialog(self.gui, _('Download failed'),
                           _('The update could not be downloaded. Do you want to open the calibre '
                             'download page to install it manually?'),
                           det_msg=err, show_copy_button=True):
            open_url(QUrl(DOWNLOAD_PAGE))

    @pyqtSlot(str, str)
    def _download_finished(self, dest, os_type):
        self._close_progress()
        _file_logger(os.path.join(self.get_download_path(), 'calibre-updater.log'))(
            'download finished: %r (%d bytes)' % (dest, os.path.getsize(dest) if os.path.exists(dest) else -1))
        if os_type == 'linux-beta':
            self._install_linux_tarball(dest)
        elif os_type == 'windows-portable':
            self._launch_windows_portable_installer(dest)
        elif os_type == 'windows':
            self._launch_windows_installer(dest)
        else:
            self._launch_mac_installer(dest)

    # --- Windows / macOS: instalación ---

    def _launch_windows_installer(self, dest):
        # Un script .cmd independiente espera a que ESTE proceso de calibre termine (sin tiempo
        # fijo: incluye lo que hagan otros complementos al cerrar, como copias de seguridad),
        # instala con msiexec sin asistente (/qb: solo barra de progreso) y vuelve a abrir calibre.
        # El registro queda junto al instalador descargado, para encontrarlo fácilmente.
        dest = os.path.normpath(os.path.abspath(dest))
        dl_dir = os.path.dirname(dest)
        log_path = os.path.join(self.get_download_path(), 'calibre-updater.log')
        msi_log = os.path.join(dl_dir, 'calibre-updater-msiexec.log')

        log = _file_logger(log_path)

        try:
            script = os.path.join(tempfile.mkdtemp(prefix='calibre-updater-', dir=_system_temp_dir()), 'run_update.cmd')
            calibre_exe = _current_windows_calibre_exe()

            def bat(s):   # en un .cmd el signo % debe duplicarse
                return s.replace('%', '%%')
            content = (WIN_RUNNER_CMD
                       .replace('@PID@', str(os.getpid()))
                       .replace('@MSI@', bat(dest))
                       .replace('@EXE@', bat(calibre_exe or ''))
                       .replace('@INSTDIR@', bat(os.path.dirname(calibre_exe or sys.executable or '').replace("'", "''")))
                       .replace('@LOG@', bat(log_path))
                       .replace('@MSILOG@', bat(msi_log)))
            # UTF-8 + "chcp 65001" en el script: rutas con acentos o ñ funcionan bien
            with open(script, 'w', encoding='utf-8', newline='\r\n') as f:
                f.write(content)
            log('calibre PID %d, calibre.exe=%r, script=%r' % (os.getpid(), calibre_exe, script))
            _start_detached_windows(script, log)
        except Exception as e:
            log('ERROR starting the update script: %r' % e)
            error_dialog(self.gui, _('Calibre Updater'),
                         _('Could not start the installer. You can run it manually from:<br>{p}').format(p=dest),
                         det_msg=str(e), show=True)
            return
        info_dialog(self.gui, _('Calibre Updater'),
                    _('calibre will now close and the new version will be installed automatically.<br><br>'
                      'Windows will ask for permission to install. When the installation finishes, '
                      'calibre will reopen.'), show=True)
        log('closing calibre')
        self.gui.quit()

    def _launch_windows_portable_installer(self, dest):
        # Igual que con el MSI: un script independiente espera a que calibre se cierre, ejecuta el
        # instalador Portable oficial en modo automático (con la carpeta como argumento no pregunta
        # nada y conserva la biblioteca y la configuración) y vuelve a abrir calibre Portable.
        dest = os.path.normpath(os.path.abspath(dest))
        log_path = os.path.join(self.get_download_path(), 'calibre-updater.log')
        log = _file_logger(log_path)
        folder = install_folder()
        target = folder.rstrip('\\')
        if target.endswith(':'):
            target += '\\.'      # "D:\\" rompería las comillas en la línea de comandos
        launcher = os.path.join(folder, 'calibre-portable.exe')
        try:
            script = os.path.join(tempfile.mkdtemp(prefix='calibre-updater-', dir=_system_temp_dir()), 'run_update.cmd')

            def bat(s):
                return s.replace('%', '%%')
            content = (WIN_PORTABLE_RUNNER_CMD
                       .replace('@PID@', str(os.getpid()))
                       .replace('@INST@', bat(dest))
                       .replace('@TARGET@', bat(target))
                       .replace('@EXE@', bat(launcher))
                       .replace('@INSTDIR@', bat(folder.replace("'", "''")))
                       .replace('@LOG@', bat(log_path)))
            with open(script, 'w', encoding='utf-8', newline='\r\n') as f:
                f.write(content)
            log('portable update: calibre PID %d, folder=%r, launcher=%r, script=%r' % (
                os.getpid(), folder, launcher, script))
            _start_detached_windows(script, log)
        except Exception as e:
            log('ERROR starting the update script: %r' % e)
            error_dialog(self.gui, _('Calibre Updater'),
                         _('Could not start the installer. You can run it manually from:<br>{p}').format(p=dest),
                         det_msg=str(e), show=True)
            return
        info_dialog(self.gui, _('Calibre Updater'),
                    _('calibre will now close and the new Portable version will be installed in its folder. '
                      'When the installation finishes, calibre will reopen.'), show=True)
        log('closing calibre')
        self.gui.quit()

    def _launch_mac_installer(self, dest):
        app_path = _current_mac_app_path()
        # El registro queda junto al .dmg descargado (la carpeta Library está oculta en el Finder)
        log_path = os.path.join(self.get_download_path(), 'calibre-updater.log')
        log = _file_logger(log_path)
        log('calibre PID %d, sys.executable=%r, app=%r, dmg=%r' % (os.getpid(), sys.executable, app_path, dest))
        try:
            work = tempfile.mkdtemp(prefix='calibre-updater-', dir=_system_temp_dir())
            runner = os.path.join(work, 'run_update.sh')
            installer = os.path.join(work, 'install_app.sh')
            with open(runner, 'w') as f:
                f.write(MAC_RUNNER_SH)
            with open(installer, 'w') as f:
                f.write(MAC_INSTALL_SH)
            os.chmod(runner, 0o755)
            os.chmod(installer, 0o755)
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            env = dict(os.environ)
            env['CU_MSG_NOT_CLOSED'] = _('calibre did not close, so the update was not installed. '
                                         'The installer was saved in: {p}').format(p=dest)
            if mac_custom_icon():
                # El script lo vuelve a aplicar apenas termina de instalar, antes de reabrir calibre
                env['CU_CUSTOM_ICON'] = mac_custom_icon()
                env['CU_ICON_JS'] = MAC_SET_ICON_JS
            env['CU_MSG_FAILED'] = _('The automatic installation failed. The installer image will open so you '
                                     'can drag calibre to the Applications folder manually.\n\nDetails: {log}').format(log=log_path)
            p = subprocess.Popen(['/bin/bash', runner, str(os.getpid()), dest, app_path, installer, log_path],
                                 env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            log('script started (PID %d): %r' % (p.pid, runner))
        except Exception as e:
            log('ERROR starting the update script: %r' % e)
            error_dialog(self.gui, _('Calibre Updater'),
                         _('Could not start the automatic installation. You can install it manually from:<br>{p}').format(p=dest),
                         det_msg=str(e), show=True)
            return

        info_dialog(self.gui, _('Calibre Updater'),
                    _('calibre will now close, install the new version and reopen automatically.<br><br>'
                      'If calibre is installed in a folder that requires administrator permissions, '
                      'macOS will ask for your password.'), show=True)
        log('closing calibre')
        self.gui.quit()


_CALIBRE_EXE_EXTRA = ('lrfviewer.exe', 'lrf2lrs.exe', 'lrs2lrf.exe', 'web2disk.exe',
                      'fetch-ebook-metadata.exe', 'markdown-calibre.exe')


def _is_calibre_exe(name):
    name = name.lower()
    return name.startswith('calibre') or name.startswith('ebook-') or name in _CALIBRE_EXE_EXTRA


def _windows_calibre_processes():
    """[(pid, ruta_completa, tiene_ventana)] de TODOS los programas de calibre en ejecución, de cualquier
    copia (instalada o portable). API de Windows directa: no depende del idioma ni de psutil."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.K32EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD)]

    # Procesos con ventana visible
    windowed = set()
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, lparam):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            windowed.add(pid.value)
        return True
    user32.EnumWindows(EnumProc(callback), 0)

    # Todos los procesos
    n = 4096
    while True:
        arr = (wintypes.DWORD * n)()
        needed = wintypes.DWORD()
        if not kernel32.K32EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
            raise OSError('K32EnumProcesses failed')
        if needed.value < ctypes.sizeof(arr):
            break
        n *= 2
    result = []
    for pid in arr[:needed.value // ctypes.sizeof(wintypes.DWORD)]:
        if not pid:
            continue
        h = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                if _is_calibre_exe(os.path.basename(buf.value)):
                    result.append((int(pid), buf.value, int(pid) in windowed))
        finally:
            kernel32.CloseHandle(h)
    return result


def _windows_install_dir():
    exe = _current_windows_calibre_exe() or (sys.executable or '')
    return os.path.normcase(os.path.normpath(os.path.dirname(os.path.abspath(exe))))


def _in_dir(path, folder):
    p = os.path.normcase(os.path.normpath(path))
    return p == folder or p.startswith(folder.rstrip('\\/') + os.sep)


def _other_calibre_copies():
    """Programas de calibre que corren desde OTRA carpeta (por ejemplo, un calibre portable).
    Con ellos abiertos el instalador MSI no puede terminar. Devuelve [(pid, ruta)]."""
    if platform.system().lower() != 'windows':
        return []
    try:
        inst = _windows_install_dir()
        me = os.getpid()
        found = [(pid, path) for pid, path, _w in _windows_calibre_processes()
                 if pid != me and not _in_dir(path, inst)]
        print('Calibre Updater: other calibre copies running: %r' % found)
        return found
    except Exception as e:
        print('Calibre Updater: could not check for other calibre copies: %r' % e)
        return []


def _running_calibre_tools():
    """Programas de calibre abiertos aparte de la ventana principal, como lista de (tipo, pid).
    tipo: 'ebook-edit', 'ebook-viewer' o 'calibre-window' (visor o editor abierto DESDE calibre:
    en Windows corre como calibre-parallel.exe, igual que los trabajos en segundo plano,
    pero a diferencia de ellos tiene una ventana visible)."""
    found = []
    me = os.getpid()
    try:
        if platform.system().lower() == 'windows':
            kinds = {'ebook-edit.exe': 'ebook-edit', 'ebook-viewer.exe': 'ebook-viewer',
                     'calibre-parallel.exe': 'calibre-window'}
            seen = {}
            # Método 1: API de Windows, solo programas de ESTA instalación (los de un portable
            # u otra copia se tratan aparte, en _other_calibre_copies)
            api_ok = False
            try:
                inst = _windows_install_dir()
                for pid, path, has_window in _windows_calibre_processes():
                    exe = os.path.basename(path).lower()
                    if pid == me or exe not in kinds or not _in_dir(path, inst):
                        continue
                    if exe == 'calibre-parallel.exe' and not has_window:
                        continue      # trabajo en segundo plano, sin ventana
                    seen[pid] = kinds[exe]
                api_ok = True
            except Exception as e:
                print('Calibre Updater: process enumeration failed: %r' % e)
            # Método 2: lista de procesos por nombre (tasklist), solo si el primero falló
            if not api_ok:
              try:
                out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True,
                                     errors='replace', timeout=15, stdin=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)).stdout
                for line in out.splitlines():
                    cols = [c.strip('"') for c in line.split('","')]
                    if len(cols) > 1 and cols[0].lower() in ('ebook-edit.exe', 'ebook-viewer.exe') and cols[1].isdigit():
                        seen.setdefault(int(cols[1]), kinds[cols[0].lower()])
              except Exception as e:
                print('Calibre Updater: tasklist failed: %r' % e)
            found = [(kind, pid) for pid, kind in sorted(seen.items())]
            print('Calibre Updater: open calibre windows: %r' % found)
        else:
            found = _posix_calibre_windows(me)
            print('Calibre Updater: open calibre windows: %r' % found)
    except Exception as e:
        print('Calibre Updater: could not check for open editor/viewer: %r' % e)
    return found


def _posix_process_list():
    """[(pid, ppid, [args])] de los procesos del usuario actual (Linux: /proc, macOS: ps)."""
    procs = []
    if os.path.isdir('/proc/self'):
        uid = os.getuid()
        for name in os.listdir('/proc'):
            if not name.isdigit():
                continue
            pid = int(name)
            try:
                if os.stat('/proc/%d' % pid).st_uid != uid:
                    continue
                with open('/proc/%d/cmdline' % pid, 'rb') as f:
                    args = [x.decode('utf-8', 'replace') for x in f.read().split(b'\0') if x]
                with open('/proc/%d/stat' % pid, 'rb') as f:
                    ppid = int(f.read().decode('utf-8', 'replace').rsplit(')', 1)[1].split()[1])
            except Exception:
                continue
            if args:
                procs.append((pid, ppid, args))
    else:
        out = subprocess.run(['ps', '-x', '-o', 'pid=,ppid=,args='], capture_output=True, text=True,
                             errors='replace', timeout=15).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
                procs.append((int(parts[0]), int(parts[1]), parts[2:]))
    return procs


def _posix_has_gui(pid):
    """True si el proceso cargó el módulo gráfico de Qt que abre ventanas en pantalla
    (X11/Wayland en Linux, Cocoa en macOS). Los trabajos en segundo plano no lo cargan."""
    markers = (b'libqxcb', b'libQt6XcbQpa', b'libqwayland', b'libQt6WaylandClient', b'libqcocoa')
    maps = '/proc/%d/maps' % pid
    if os.path.exists(maps):
        try:
            with open(maps, 'rb') as f:
                data = f.read()
            return any(m in data for m in markers)
        except Exception:
            return False
    try:   # macOS: no hay /proc; se consulta con lsof
        out = subprocess.run(['lsof', '-p', str(pid), '-Fn'], capture_output=True, timeout=15).stdout
        return any(m in out for m in markers)
    except Exception:
        return False


def _posix_calibre_windows(me):
    """Visor y Editor abiertos en Linux/macOS. Abiertos desde calibre corren como
    'calibre-parallel' (sin --pipe-worker), igual que los trabajos en segundo plano;
    la diferencia es que tienen ventana (ver _posix_has_gui)."""
    procs = _posix_process_list()
    found = []
    for pid, ppid, args in procs:
        if pid == me:
            continue
        exe = os.path.basename(args[0])
        joined = ' '.join(args)
        if exe in ('ebook-viewer', 'ebook-edit'):
            found.append((exe, pid))
            continue
        if '/ebook-viewer.app/' in joined or '/ebook-edit.app/' in joined:
            found.append(('ebook-viewer' if 'viewer' in joined else 'ebook-edit', pid))
            continue
        if exe != 'calibre-parallel' or '--pipe-worker' in args or not _posix_has_gui(pid):
            continue
        # Qué es, según los procesos auxiliares que lanzó
        kind = 'calibre-window'
        for cpid, cppid, cargs in procs:
            if cppid == pid:
                c = ' '.join(cargs)
                if 'tweak_book' in c:
                    kind = 'ebook-edit'
                elif 'viewer_main' in c:
                    kind = 'ebook-viewer'
        found.append((kind, pid))
    return found


def _kill_calibre_tools(tools):
    """Cierra a la fuerza los programas indicados (solo si el usuario lo pidió)."""
    for kind, pid in tools:
        try:
            if platform.system().lower() == 'windows':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True, timeout=15,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000))
            else:
                os.kill(pid, 15)   # SIGTERM
        except Exception as e:
            print('Calibre Updater: could not close %s (%s): %r' % (kind, pid, e))
    time.sleep(1)


WIN_TASK_NAME = 'calibre-updater'


def _start_detached_windows(script, log):
    """Lanza el script de forma que NO muera cuando calibre se cierre.
    1) Proceso "desprendido" del grupo de procesos de calibre (CREATE_BREAKAWAY_FROM_JOB).
    2) Si Windows no lo permite, a través del Programador de tareas, que lo ejecuta como un
       proceso totalmente independiente de calibre."""
    no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    flags = (no_window | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)
             | getattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB', 0x01000000))
    try:
        subprocess.Popen(['cmd.exe', '/d', '/c', script], creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         cwd=os.path.dirname(script))
        log('script started (detached process)')
        return
    except OSError as e:
        log('detached start not allowed (%r); using Task Scheduler' % e)

    def run(args):
        r = subprocess.run(args, capture_output=True, text=True, errors='replace', timeout=30,
                           stdin=subprocess.DEVNULL, creationflags=no_window)
        if r.returncode != 0:
            raise OSError('%s failed (%s): %s' % (args[1], r.returncode, (r.stdout + r.stderr).strip()))
    run(['schtasks', '/Create', '/F', '/TN', WIN_TASK_NAME, '/SC', 'ONCE', '/ST', '23:59',
         '/TR', 'cmd.exe /d /c "%s"' % script])
    run(['schtasks', '/Run', '/TN', WIN_TASK_NAME])
    log('script started (Task Scheduler)')


def _system_temp_dir():
    """Carpeta temporal del SISTEMA. Dentro de calibre, tempfile apunta a una carpeta privada
    de calibre (por ejemplo ...\\Temp\\calibre-zvs774n4) que calibre BORRA al cerrarse: un script
    guardado ahí muere en cuanto calibre termina. Por eso se usa la carpeta superior."""
    d = tempfile.gettempdir()
    while os.path.basename(d.rstrip('\\/')).lower().startswith('calibre'):
        parent = os.path.dirname(d.rstrip('\\/'))
        if not parent or parent == d:
            break
        d = parent
    return d


def _current_windows_calibre_exe():
    """Ruta de calibre.exe para volver a abrirlo después de instalar."""
    d = os.path.dirname(os.path.abspath(sys.executable or ''))
    for _i in range(4):
        exe = os.path.join(d, 'calibre.exe')
        if os.path.isfile(exe):
            return exe
        d = os.path.dirname(d)
    pf = os.environ.get('ProgramFiles', r'C:\Program Files')
    exe = os.path.join(pf, 'Calibre2', 'calibre.exe')
    return exe if os.path.isfile(exe) else ''


def _file_logger(log_path):
    """Escribe líneas con fecha en el registro del plugin (y también en la salida de depuración)."""
    def log(msg):
        print('Calibre Updater: ' + msg)
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write('%s plugin: %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg))
        except Exception:
            pass
    return log


OLD_PLUGIN_NAMES = ('Calibre Auto-Updater',)


def _old_plugin_enabled():
    """Nombre de la versión anterior del complemento si está instalada y activa; si no, None."""
    try:
        from calibre.customize.ui import initialized_plugins, is_disabled
        for p in initialized_plugins():
            module = getattr(p, '__module__', '') or ''
            if p.name in OLD_PLUGIN_NAMES or module.startswith('calibre_plugins.auto_updater'):
                if not is_disabled(p):
                    print('Calibre Updater: previous plugin still enabled: %r' % p.name)
                    return p.name
    except Exception as e:
        print('Calibre Updater: could not check for the previous plugin: %r' % e)
    return None


def _silent_remove(path):
    try:
        os.remove(path)
    except Exception:
        pass


def _current_mac_app_path():
    """Ubicación de la calibre.app que se está ejecutando (normalmente /Applications/calibre.app)."""
    default = '/Applications/calibre.app'
    exe = os.path.realpath(sys.executable or '')
    m = re.search(r'^(.*?\.app)(?:/|$)', exe)
    if not m:
        return default
    path = m.group(1)
    # Ejecutándose desde el .dmg o "traslocada" por Gatekeeper: instalar en Aplicaciones
    if 'AppTranslocation' in path or path.startswith('/Volumes/'):
        return default
    return path


# --- SCRIPTS DE INSTALACIÓN PARA macOS ---
# Corren en un proceso independiente, después de que calibre se cerró.

MAC_RUNNER_SH = r'''#!/bin/bash
# Argumentos: PID_CALIBRE IMAGEN.dmg DESTINO.app INSTALADOR.sh LOG
PID="$1"; DMG="$2"; APP="$3"; INSTALLER="$4"; LOG="$5"
WORKDIR="$(cd "$(dirname "$0")" && pwd)"
exec >>"$LOG" 2>&1
echo "=== $(date) calibre-updater: $DMG -> $APP"

alert() {
  /usr/bin/osascript -e 'on run argv' \
    -e 'display alert "Calibre Updater" message (item 1 of argv) as critical' \
    -e 'end run' "$1" >/dev/null 2>&1
}

# 1. Esperar a que calibre se cierre (máximo 5 minutos)
for i in $(seq 1 300); do
  kill -0 "$PID" 2>/dev/null || break
  sleep 1
done
if kill -0 "$PID" 2>/dev/null; then
  echo "calibre did not close; aborting"
  alert "$CU_MSG_NOT_CLOSED"
  exit 1
fi
sleep 1

# 2. Montar la imagen sin mostrarla en el Finder.
#    "hdiutil attach" está marcado como obsoleto en macOS recientes; si algún día deja de
#    funcionar, se usa su reemplazo "diskutil image attach".
MNT="$(mktemp -d /tmp/calibre-dmg.XXXXXX)"
mount_dmg() {
  if yes | /usr/bin/hdiutil attach -nobrowse -noautoopen -readonly -mountpoint "$MNT" "$DMG"; then
    return 0
  fi
  echo "hdiutil attach failed; trying diskutil image attach"
  /usr/sbin/diskutil image attach --mountOptions nobrowse --readOnly --mountPoint "$MNT" "$DMG"
}
detach_dmg() {
  /usr/bin/hdiutil detach "$MNT" -quiet && return 0
  /usr/sbin/diskutil eject "$MNT" >/dev/null 2>&1 && return 0
  /usr/bin/hdiutil detach "$MNT" -force -quiet
}
if ! mount_dmg; then
  echo "could not mount the disk image"
  rmdir "$MNT" 2>/dev/null
  alert "$CU_MSG_FAILED"
  /usr/bin/open "$DMG"
  exit 1
fi

SRC="$(/usr/bin/find "$MNT" -maxdepth 1 -name '*.app' -print -quit)"
RC=1
if [ -n "$SRC" ]; then
  # 3. Copiar: primero sin permisos de administrador; si no alcanza, se piden
  DEST_DIR="$(dirname "$APP")"
  if [ -w "$DEST_DIR" ] && { [ ! -e "$APP" ] || [ -w "$APP" ]; }; then
    /bin/bash "$INSTALLER" "$SRC" "$APP"; RC=$?
  fi
  if [ "$RC" -ne 0 ]; then
    echo "trying with administrator privileges"
    /usr/bin/osascript -e 'on run argv' \
      -e 'do shell script "/bin/bash " & quoted form of (item 1 of argv) & " " & quoted form of (item 2 of argv) & " " & quoted form of (item 3 of argv) with administrator privileges' \
      -e 'end run' "$INSTALLER" "$SRC" "$APP"
    RC=$?
  fi
else
  echo "no .app found inside the image"
fi

# 4. Desmontar
detach_dmg
rmdir "$MNT" 2>/dev/null

# 5. Reabrir calibre, o dejar la instalación manual como plan B
if [ "$RC" -eq 0 ]; then
  echo "installed OK"
  # La imagen ya no hace falta (si falló, se deja para instalar a mano)
  rm -f "$DMG" && echo "installer deleted"
  if [ -n "$CU_CUSTOM_ICON" ] && [ -f "$CU_CUSTOM_ICON" ]; then
    echo "applying custom icon: $(/usr/bin/osascript -l JavaScript -e "$CU_ICON_JS" "$CU_CUSTOM_ICON" "$APP" 2>&1)"
  fi
  /usr/bin/open "$APP"
else
  echo "install failed (rc=$RC)"
  alert "$CU_MSG_FAILED"
  /usr/bin/open "$DMG"
fi
rm -rf "$WORKDIR"
'''

WIN_RUNNER_CMD = r'''@echo off
chcp 65001 >nul
setlocal
set "MSI=@MSI@"
set "EXE=@EXE@"
set "LOG=@LOG@"
set "MSILOG=@MSILOG@"
echo === %DATE% %TIME% calibre-updater: "%MSI%" >> "%LOG%"

rem 1. Esperar a que calibre se cierre (sin tiempo fijo; maximo 10 minutos)
echo waiting for calibre (PID @PID@) to close >> "%LOG%"
set /a N=0
:wait
tasklist /FI "PID eq @PID@" /NH 2>nul | find " @PID@ " >nul
if errorlevel 1 goto closed
set /a N+=1
if %N% GEQ 600 goto timeout
set /a M=N %% 30
if %M%==0 (
  echo still waiting after %N% seconds; calibre processes: >> "%LOG%"
  tasklist /FI "IMAGENAME eq calibre*" /NH >> "%LOG%" 2>&1
  tasklist /FI "IMAGENAME eq ebook-*" /NH >> "%LOG%" 2>&1
)
ping -n 2 127.0.0.1 >nul
goto wait

:timeout
echo calibre did not close after 10 minutes; opening the installer manually >> "%LOG%"
start "" "%MSI%"
goto end

:closed
echo calibre closed after about %N% seconds >> "%LOG%"
rem Procesos auxiliares que pudieran haber quedado huerfanos
powershell -NoProfile -NonInteractive -Command "Get-Process -Name calibre-parallel -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '@INSTDIR@\*' } | Stop-Process -Force" >nul 2>&1
ping -n 2 127.0.0.1 >nul

rem 2. Instalar sin asistente: /qb = solo barra de progreso (Windows pide permiso de administrador)
echo installing >> "%LOG%"
start "" /wait msiexec.exe /i "%MSI%" /qb /norestart /L*v "%MSILOG%"
set RC=%ERRORLEVEL%
echo msiexec exit code %RC% >> "%LOG%"

rem 0 = OK, 3010 = OK (requiere reinicio de Windows): se borra el instalador, ya no hace falta
if "%RC%"=="0" goto installed
if "%RC%"=="3010" goto installed
rem 1602 / 1625 = el usuario cancelo o no dio permiso: se reabre calibre sin instalar
if "%RC%"=="1602" goto relaunch
if "%RC%"=="1625" goto relaunch
echo installation failed; opening the installer manually >> "%LOG%"
start "" "%MSI%"
goto end

:installed
del "%MSI%" >nul 2>&1
if not exist "%MSI%" echo installer deleted >> "%LOG%"

:relaunch
echo relaunching "%EXE%" >> "%LOG%"
if not "%EXE%"=="" if exist "%EXE%" start "" "%EXE%"

:end
schtasks /Delete /TN "calibre-updater" /F >nul 2>&1
endlocal
(goto) 2>nul & del "%~f0"
'''

WIN_PORTABLE_RUNNER_CMD = r'''@echo off
chcp 65001 >nul
setlocal
set "INST=@INST@"
set "TARGET=@TARGET@"
set "EXE=@EXE@"
set "LOG=@LOG@"
echo === %DATE% %TIME% calibre-updater (portable): "%INST%" -^> "%TARGET%" >> "%LOG%"

rem 1. Esperar a que calibre se cierre (sin tiempo fijo; maximo 10 minutos)
echo waiting for calibre (PID @PID@) to close >> "%LOG%"
set /a N=0
:wait
tasklist /FI "PID eq @PID@" /NH 2>nul | find " @PID@ " >nul
if errorlevel 1 goto closed
set /a N+=1
if %N% GEQ 600 goto timeout
ping -n 2 127.0.0.1 >nul
goto wait

:timeout
echo calibre did not close after 10 minutes; nothing was installed >> "%LOG%"
goto end

:closed
echo calibre closed after about %N% seconds >> "%LOG%"
powershell -NoProfile -NonInteractive -Command "Get-Process -Name calibre-parallel -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '@INSTDIR@\*' } | Stop-Process -Force" >nul 2>&1
ping -n 2 127.0.0.1 >nul

rem 2. Instalador Portable en modo automatico: con la carpeta como argumento no pregunta nada
echo installing >> "%LOG%"
start "" /wait "%INST%" "%TARGET%"
set RC=%ERRORLEVEL%
echo portable installer exit code %RC% >> "%LOG%"
rem Si salio bien, el instalador ya no hace falta; si fallo, se deja para instalar a mano
if "%RC%"=="0" del "%INST%" >nul 2>&1
if "%RC%"=="0" if not exist "%INST%" echo installer deleted >> "%LOG%"

rem 3. Volver a abrir calibre Portable (si fallo, el instalador ya mostro su propio mensaje)
echo relaunching "%EXE%" >> "%LOG%"
if exist "%EXE%" start "" "%EXE%"

:end
schtasks /Delete /TN "calibre-updater" /F >nul 2>&1
endlocal
(goto) 2>nul & del "%~f0"
'''

# Linux: instala un archivo .txz de calibre (Beta) en la carpeta indicada, con vuelta atrás.
# Se ejecuta con pkexec. Argumentos: ARCHIVO.txz CARPETA (normalmente /opt/calibre)
LINUX_TARBALL_SH = r'''
set -o pipefail
TB="$1"; DEST="$2"
case "$DEST" in
  /*) ;;
  *) echo "invalid destination: $DEST"; exit 2 ;;
esac
NEW="$DEST.updating"; OLD="$DEST.old"
rm -rf "$NEW" "$OLD" || exit 3
mkdir -p "$NEW" || exit 3
echo "Extracting $TB ..."
if ! tar -xJf "$TB" -C "$NEW"; then
  echo "could not extract the archive"; rm -rf "$NEW"; exit 4
fi
if [ ! -x "$NEW/calibre" ] || [ ! -x "$NEW/calibre_postinstall" ]; then
  echo "the archive does not look like calibre"; rm -rf "$NEW"; exit 5
fi
echo "Replacing $DEST ..."
if [ -e "$DEST" ] && ! mv "$DEST" "$OLD"; then
  echo "could not move the current installation"; rm -rf "$NEW"; exit 6
fi
if ! mv "$NEW" "$DEST"; then
  echo "could not put the new version in place; restoring the previous one"
  [ -e "$OLD" ] && mv "$OLD" "$DEST"
  rm -rf "$NEW"; exit 7
fi
echo "Running calibre_postinstall ..."
"$DEST/calibre_postinstall" || echo "warning: calibre_postinstall reported an error"
rm -rf "$OLD"
echo "Done."
exit 0
'''

MAC_INSTALL_SH = r'''#!/bin/bash
# Uso: install_app.sh ORIGEN.app DESTINO.app
# Reemplaza la app de forma segura: si algo falla, se restaura la versión anterior.
SRC="$1"; APP="$2"
case "$APP" in
  /*.app) ;;
  *) echo "invalid destination: $APP"; exit 2 ;;
esac
NEW="$APP.updating"
OLD="$APP.old"
rm -rf "$NEW" "$OLD" || exit 1
/usr/bin/ditto "$SRC" "$NEW" || { rm -rf "$NEW"; exit 1; }
if [ -e "$APP" ]; then
  mv "$APP" "$OLD" || { rm -rf "$NEW"; exit 1; }
fi
if ! mv "$NEW" "$APP"; then
  [ -e "$OLD" ] && mv "$OLD" "$APP"
  rm -rf "$NEW"
  exit 1
fi
rm -rf "$OLD"
exit 0
'''
