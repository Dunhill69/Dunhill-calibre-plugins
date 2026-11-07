#!/usr/bin/env python3
"""Genera los .zip instalables de los complementos en la carpeta dist/.

Uso:
    python3 build.py                 # todos los complementos
    python3 build.py calibre_updater # solo uno (o varios, separados por espacio)
"""
import os
import re
import sys
import unicodedata
import zipfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(RAIZ, 'dist')
EXCLUIR_DIRS = {'__pycache__', '.git', '.vscode', '.idea'}
EXCLUIR_EXT = ('.pyc', '.pyo', '.zip')
EXCLUIR_ARCH = {'.DS_Store', 'Thumbs.db'}


def complementos():
    for d in sorted(os.listdir(RAIZ)):
        ruta = os.path.join(RAIZ, d)
        if os.path.isfile(os.path.join(ruta, '__init__.py')) and any(
                f.startswith('plugin-import-name-') for f in os.listdir(ruta)):
            yield d


def leer_datos(carpeta):
    s = open(os.path.join(RAIZ, carpeta, '__init__.py'), encoding='utf-8').read()
    nombre = (re.search(r"PLUGIN_NAME\s*=\s*['\"](.+?)['\"]", s)
              or re.search(r"\bname\s*=\s*['\"](.+?)['\"]", s)).group(1)
    v = (re.search(r"PLUGIN_VERSION\s*=\s*\(([\d,\s]+)\)", s)
         or re.search(r"\bversion\s*=\s*\(([\d,\s]+)\)", s)).group(1)
    version = '.'.join(x.strip() for x in v.split(',') if x.strip())
    return nombre, version


def empaquetar(carpeta):
    nombre, version = leer_datos(carpeta)
    ascii_ = unicodedata.normalize('NFKD', nombre).encode('ascii', 'ignore').decode()
    seguro = re.sub(r'[^\w.-]+', '_', ascii_).strip('_')
    destino = os.path.join(DIST, f'{seguro}-v{version}.zip')
    base = os.path.join(RAIZ, carpeta)
    with zipfile.ZipFile(destino, 'w', zipfile.ZIP_DEFLATED) as z:
        for raiz, dirs, archivos in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUIR_DIRS)
            for f in sorted(archivos):
                if f in EXCLUIR_ARCH or f.endswith(EXCLUIR_EXT):
                    continue
                completo = os.path.join(raiz, f)
                z.write(completo, os.path.relpath(completo, base))
    print(f'  {nombre} {version} -> dist/{os.path.basename(destino)}')


def main():
    disponibles = list(complementos())
    pedidos = sys.argv[1:] or disponibles
    faltan = [p.strip('/') for p in pedidos if p.strip('/') not in disponibles]
    if faltan:
        sys.exit('No encontré: ' + ', '.join(faltan) +
                 '\nDisponibles: ' + ', '.join(disponibles))
    os.makedirs(DIST, exist_ok=True)
    print('Generando complementos:')
    for p in pedidos:
        empaquetar(p.strip('/'))


if __name__ == '__main__':
    main()
