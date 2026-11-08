# 3D Cover

A calibre plugin that turns flat book covers into 3D hardcover books, with spine, page edges and drop shadow.

**Idioma de la interfaz / Interface language:** Inglés y español / English and Spanish

**Credits:** inspired by the *Create Hardcover* plugin by **sornay**, which applies the Apple Books hardcover effect to covers. 3D Cover is maintained by **Dunhill**.

### Changes from Create Hardcover

- **Background color:** calibre always stores covers as JPEG, which has no transparency, so the empty area used to turn white. It is now filled with the cover grid background color of the current light or dark theme, the book details panel color (read from the screen, so it also matches custom themes and stylesheets), or a custom color.
- **Tighter crop:** the empty margin around the book is removed, so the book looks bigger in the cover grid.
- **Transparent mode:** saves the cover as PNG (bypassing calibre's JPEG conversion), so the book details panel shows through it. In the cover grid the background may look dark, because calibre caches grid thumbnails without transparency.
- **Book shape:** adjustable angle (0–60°), visible top edge (scales with the angle), optional shadow, spine color (black or taken from the cover) and binding (paperback or hardcover), with live preview. Smaller angles or no shadow make the cover fill more space.
- **Size option:** Normal (500 px), Large (800 px), Extra large (1200 px) or Original (the cover's own width, up to 1600 px).
- **About window** with credits and donation links.
- The backups of original covers (`data/original_cover.jpg`) are compatible with Create Hardcover, so **Restore** also works on books processed with it.

## Features

- **Hardcover compositing** — spine shadow, spine highlight, page edges, rounded corners, background blur
- **RTL support** — full right-to-left spine for Arabic, Hebrew, Persian books
- **Side-by-side preview** — compare original vs generated cover before applying
- **Batch processing** — generate and apply covers for multiple books at once, with progress bars
- **Non-destructive** — original covers are backed up and can be restored at any time
- **Library filtering** — toolbar menu to filter books by generation status
- **Keyboard navigation** — left/right arrows to browse books in the preview dialog

## Requirements

- Calibre 5.0 or newer
- Windows, macOS, or Linux
- No external dependencies — only uses Pillow, which ships with Calibre

## Installation

1. Download `3D-Cover.zip`
2. In Calibre, go to **Preferences > Plugins > Load plugin from file**
3. Select the zip file and restart Calibre
4. A blue book icon appears in your toolbar

## Usage

### Single cover

1. Select a book in your library
2. Click the 3D Cover toolbar icon
3. Check **RTL Spine** if the book is right-to-left
4. Click **Generate**
5. Preview the result, then click **Apply**

### Batch processing

1. Select multiple books in your library
2. Open 3D Cover
3. Click **Generate All** — a progress bar shows status
4. Click **Apply All** to apply all generated covers

### Restoring originals

- Single book: select the book, open 3D Cover, click **Restore**
- Multiple books: click **Restore All** — includes a progress bar

### Library filters

Right-click the toolbar icon for:
- **Show books with generated covers**
- **Show books without generated covers**

### Keyboard shortcuts

- **Left arrow** — previous book
- **Right arrow** — next book

## How it works

The plugin composites pre-rendered overlay images (spine shadows, highlights, page edges) onto your cover using blend modes that replicate Apple Books' rendering:

1. Resize cover to 600px wide (preserving aspect ratio)
2. Apply rounded-rectangle mask
3. Create blurred background with multiply blend
4. Apply spine-linearburn overlay (multiply blend)
5. Apply spine-normal overlay (alpha composite)
6. Apply spine-softlight overlay (soft-light blend)
7. Apply page edges overlay (alpha composite)

## License

MIT


## Support

If this plugin is useful to you: [Ko-fi](https://ko-fi.com/dunhill69) · [PayPal](https://paypal.me/Dunhill69)

---

## Enlaces / Links

- **Descargar / Download:** [Releases](https://github.com/Dunhill69/Dunhill-calibre-plugins/releases?q=cover_3d) · `3D Cover` v1.6.3
- **Reportar un problema / Report an issue:** [Issues](https://github.com/Dunhill69/Dunhill-calibre-plugins/issues)
- **Donar / Donate:** [Ko-fi](https://ko-fi.com/dunhill69) · [PayPal](https://paypal.me/Dunhill69)
