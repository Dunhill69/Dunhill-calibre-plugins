# Book Card Export

A calibre plugin that creates a **book card** — cover, details and synopsis, like the one calibre shows in the book details — to **save it as an image** or **share it in Telegram**.

Interface in English and Spanish.

## Features

- **Card image** (PNG or JPG) with the cover, the fields of calibre's book details panel and the synopsis. Copy it to the clipboard or save it; export all the selected books at once.
- **Text for Telegram**, editable, with bold and italic (`**bold**`, `__italic__`), ready to paste as the caption of the cover photo.
  - Character counter with the caption limit (1024, or 4096 with Telegram Premium).
  - If it does not fit, it is split in two parts between paragraphs: part 1 as the caption, part 2 as the next message.
- **Emojis**: one for each field and one for each genre (tag), chosen from a picker with ~290 emojis by category, plus your own. "Suggest emojis" assigns the usual ones to your genres (Fantasy 🐉, Science fiction 🚀, Romance 💕, Horror 👻...). You choose whether they are shown in the Telegram text, in the card image, or both.
- **Background**: according to the theme (light/dark), custom color, transparent (PNG), or **Quick colors** that match Telegram's dark and light themes.
- Optional tags as **hashtags**, footer "Exported from calibre", extra CSS for the card.
- Navigate with Previous/Next through the library, the current search or the selected books.
- Built-in help window (English and Spanish).

## Usage

1. Select a book and click **Book card** in the toolbar.
2. To share in Telegram: **1. Copy cover** → paste it in Telegram (Ctrl+V) → **2. Copy text** → paste it in the caption field.
3. The arrow next to the button has **Configure**, **Help** and **About**.

## Requirements

calibre 6.0 or later. Windows, macOS and Linux.

## Notes

- Emojis may look blank in the text panel if your system has no color emoji font (on Linux: `sudo apt install fonts-noto-color-emoji`). They look fine in Telegram, and the plugin uses its own images in the picker and in the card image.
- Telegram always shows images over a white background, so a transparent background is not useful there: use the Quick colors.

## Credits

Emoji images rendered from [Noto Color Emoji](https://github.com/googlefonts/noto-emoji) (SIL Open Font License 1.1).

## Support

If this plugin is useful to you, you can support its development: [Ko-fi](https://ko-fi.com/dunhill69) · [PayPal](https://paypal.me/Dunhill69)
