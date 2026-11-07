"""Ajustes del complemento (sin Qt, para poder usarlos desde los hilos de trabajo)."""

DEFAULTS = {
    # 'auto' = conexión normal y, si Goodreads bloquea, el navegador interno de calibre
    # 'browser' = siempre el navegador interno; 'normal' = nunca
    'connection_mode': 'auto',
    'request_pause': 1.2,          # segundos entre dos consultas a Goodreads
    'max_new_pages': 12,           # fichas nuevas de tus libros que se leen por apertura
    'auto_spanish': True,          # buscar automáticamente la edición en el idioma elegido
    'edition_language': 'auto',
    # Etiqueta de las entradas vacías (lista de deseos). None = la predeterminada
    # en el idioma de calibre ("A conseguir"); '' = no poner etiqueta
    'wishlist_tag': None,    # 'auto' = el idioma de la interfaz de calibre, o un código (spa, por...)
    'cache_days_series': 3,
    'cache_days_other': 30,
}

_prefs = None


def prefs():
    global _prefs
    if _prefs is None:
        from calibre.utils.config import JSONConfig
        _prefs = JSONConfig('plugins/goodreads_series_explorer')
        for k, v in DEFAULTS.items():
            _prefs.defaults[k] = v
    return _prefs


def settings():
    """Copia de los ajustes actuales como diccionario. Si no se pueden leer, los
    valores por defecto."""
    try:
        p = prefs()
        return {k: p.get(k, v) for k, v in DEFAULTS.items()}
    except Exception:
        return dict(DEFAULTS)
