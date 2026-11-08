# Complementos de calibre de Dunhill / Dunhill's calibre plugins

Este es el hogar oficial de mis complementos para [calibre](https://calibre-ebook.com). Los publico también en el foro [MobileRead](https://www.mobileread.com/forums/forumdisplay.php?f=237) con el nombre **Dunhill**.

This is the official home of my plugins for [calibre](https://calibre-ebook.com). I also publish them on the [MobileRead](https://www.mobileread.com/forums/forumdisplay.php?f=237) forums as **Dunhill**.

## Complementos / Plugins

> 🇪🇸 Los complementos marcados tienen la interfaz **solo en español**. / Plugins marked 🇪🇸 have a **Spanish-only** interface.

### Fuentes de metadatos / Metadata sources

| Complemento | Versión | Idioma / Language | Descripción | Description |
|---|---|---|---|---|
| [AnnasArchivePlus](annas_archive_plus/README.md) | 1.3.1 | 🇪🇸 Solo español / Spanish only | Fuente de metadatos de Anna's Archive: busca por título, autor o ISBN y guarda el identificador annasarchive. | Anna's Archive metadata source: searches by title, author or ISBN and stores the annasarchive identifier. |

### Tiendas («Conseguir libros») / Stores ("Get books")

| Complemento | Versión | Idioma / Language | Descripción | Description |
|---|---|---|---|---|
| [Danmei Novel Finder](danmei_novel_finder/README.md) | 1.2.1 | 🇪🇸 Solo español / Spanish only | Explora el catálogo de danmeinovel.com y descarga novelas como EPUB (directo a la biblioteca) o TXT. | Browses the danmeinovel.com catalog and downloads novels as EPUB (straight into the library) or TXT. |
| [Elejandría](elejandria_store/README.md) | 1.1.2 | 🇪🇸 Solo español / Spanish only | Libros gratis y legales en español de elejandria.com, con descarga directa en EPUB, PDF y MOBI. | Free and legal Spanish books from elejandria.com, with direct EPUB, PDF and MOBI downloads. |

### Complementos de interfaz / User interface plugins

| Complemento | Versión | Idioma / Language | Descripción | Description |
|---|---|---|---|---|
| [3D Cover](cover_3d/README.md) | 1.6.3 | Inglés y español / English and Spanish | Convierte las portadas planas en libros de tapa dura en 3D, con lomo, cantos y sombra. | Turns flat covers into 3D hardcover books, with spine, page edges and shadow. |
| [Calibre CSS](calibre_css/README.md) | 1.7.1 | Inglés y español / English and Spanish | Usa un estilo CSS distinto en el panel de detalles y en el visor para cada biblioteca. | Uses a different CSS style for the book details panel and the viewer in each library. |
| [Calibre Updater](calibre_updater/README.md) | 1.23.6 | Inglés, español y 17 idiomas más / English, Spanish and 17 more languages | Avisa cuando hay una nueva versión de calibre y la instala por el método oficial en Linux, Windows y macOS. | Notifies you of new calibre versions and installs them the official way on Linux, Windows and macOS. |
| [Compare Libraries](compare_libraries/README.md) | 1.2.0 | 🇪🇸 Solo español / Spanish only | Compara la biblioteca actual con otra biblioteca o carpeta e importa los libros faltantes sin duplicados. | Compares the current library with another library or folder and imports the missing books without duplicates. |
| [Delete Extra Files](delete_extra_files/README.md) | 1.3.0 | Inglés y español / English and Spanish | Borra de forma selectiva y segura las carpetas de archivos extra de toda la biblioteca. | Selectively and safely deletes the extra-files folders from the whole library. |
| [EPUB to XTC Converter](epub_to_xtc_converter/README.md) | 2.3.0 | Inglés y español / English and Spanish | Convierte libros al formato XTC/XTCH del lector Xteink X4, con las páginas generadas por calibre. | Converts books to the XTC/XTCH format of the Xteink X4 e-reader, with pages rendered by calibre. |
| [Goodreads Awards](goodreads_awards/README.md) | 1.2.0 | Inglés y español / English and Spanish | Busca los libros en Goodreads y guarda sus premios literarios en una columna. | Looks books up on Goodreads and stores their literary awards in a column. |
| [Goodreads Series Explorer](goodreads_series_explorer/README.md) | 1.12.0 | Inglés y español / English and Spanish | Explora en Goodreads la saga o serie completa del libro seleccionado, con los datos de las ediciones en tu idioma. | Explores the whole Goodreads series of the selected book, with the data of the editions in your language. |
| [Identidad Autor](identidad_autor/README.md) | 1.1.0 | 🇪🇸 Solo español / Spanish only | Gestiona seudónimos y nombres reales de autores con lógica jerárquica. | Manages author pseudonyms and real names with hierarchical logic. |
| [Integrity Analysis](integrity_analysis/README.md) | 1.6.1 | Inglés y español / English and Spanish | Revisa la integridad de la biblioteca de calibre y sus componentes. | Runs integrity checks and analysis on your calibre library and its components. |
| [Mylar Series Plus](mylar_series_plus/README.md) | 1.1.0 | Inglés, español y 17 idiomas más / English, Spanish and 17 more languages | Crea los metadatos series.json de Mylar3 y fichas visuales de la serie en los comentarios, desde ComicVine. | Creates Mylar3 series.json metadata and visual series cards in the comments, from ComicVine. |

## Instalación / Installation

**ES:** Descargá el `.zip` del complemento desde [Releases](https://github.com/Dunhill69/Dunhill-calibre-plugins/releases) y en calibre andá a **Preferencias → Complementos → Cargar complemento desde archivo**.

**EN:** Download the plugin `.zip` from [Releases](https://github.com/Dunhill69/Dunhill-calibre-plugins/releases) and in calibre go to **Preferences → Plugins → Load plugin from file**.

## Compilar desde el código / Build from source

```bash
python3 build.py              # todos / all
python3 build.py calibre_updater   # uno solo / just one
```

Los `.zip` quedan en la carpeta `dist/`. / The `.zip` files are written to `dist/`.

## Preguntas y problemas / Questions and issues

Usá [Issues](https://github.com/Dunhill69/Dunhill-calibre-plugins/issues) o el hilo de cada complemento en MobileRead. / Use [Issues](https://github.com/Dunhill69/Dunhill-calibre-plugins/issues) or each plugin's MobileRead thread.

## Apoyar / Support

Si mis complementos te sirven, podés invitarme un café. / If you find my plugins useful, you can buy me a coffee.

[![Ko-fi](https://img.shields.io/badge/Ko--fi-dunhill69-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/dunhill69) [![PayPal](https://img.shields.io/badge/PayPal-Dunhill69-00457C?logo=paypal&logoColor=white)](https://paypal.me/Dunhill69)

## Licencia / License

[GPL v3](LICENSE)
