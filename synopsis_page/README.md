# Synopsis Page

A calibre plugin that adds a page with the book cover and its synopsis (taken from the **Comments** field) to EPUB and AZW3 books, right after the cover.

Interface in English and Spanish.

## Features

- Edits the book directly, without converting it, so its formatting is kept.
- Cover position: top (centered), left or right with the text wrapping around it, or bottom. A floating cover can be placed after paragraph N (handy when the synopsis starts with centered taglines).
- Optional title, author, series and heading.
- Adjustable cover width and frame (none, thin border, shadow), justified text and paragraph indent.
- Page placement: after the cover, at the start or at the end of the book; optional Table of Contents entry.
- Works on many books at once. Running it again replaces the page; **Remove synopsis page** takes it out.
- Saves an `ORIGINAL_EPUB` / `ORIGINAL_AZW3` copy before the first change (optional).

## Requirements

calibre 6.0 or later — Windows, macOS and Linux.

## Installation

1. Download `Synopsis Page.zip` from [Releases](https://github.com/Dunhill69/Dunhill-calibre-plugins/releases).
2. In calibre: **Preferences → Plugins → Load plugin from file** and select the zip.
3. Restart calibre and add the button to a toolbar if needed.

## Usage

Select one or more books and click **Synopsis Page**. Settings are in the button menu → **Customize plugin…**

## Translations

`translations/messages.pot` is the template. Copy it as `xx.po`, translate it (for example with Poedit) and place the compiled `xx.mo` in the `translations` folder.

## Support

If you find it useful, you can buy me a coffee: [Ko-fi](https://ko-fi.com/dunhill69) · [PayPal](https://paypal.me/Dunhill69)

## License

GPL v3
