#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai

__license__   = 'GPL v3'
__copyright__ = '2026, Dunhill'

from qt.core import (QColor, QFont, QPainter, QPlainTextEdit, QRect, QSize,
                     Qt, QTextCursor, QTextEdit, QTextFormat, QWidget)


class _LineArea(QWidget):

    def __init__(self, editor):
        QWidget.__init__(self, editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_area_width(), 0)

    def paintEvent(self, ev):
        self.editor.paint_line_area(ev)


class CodeEditor(QPlainTextEdit):
    """Plain text editor with monospace font, line numbers and go-to-line."""

    def __init__(self, parent=None):
        QPlainTextEdit.__init__(self, parent)
        f = QFont('monospace')
        f.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(f)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self._area = _LineArea(self)
        self.blockCountChanged.connect(self._update_width)
        self.updateRequest.connect(self._update_area)
        self._update_width()

    def line_area_width(self):
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 8 + self.fontMetrics().horizontalAdvance('9') * digits

    def _update_width(self, *a):
        self.setViewportMargins(self.line_area_width(), 0, 0, 0)

    def _update_area(self, rect, dy):
        if dy:
            self._area.scroll(0, dy)
        else:
            self._area.update(0, rect.y(), self._area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_width()

    def resizeEvent(self, ev):
        QPlainTextEdit.resizeEvent(self, ev)
        cr = self.contentsRect()
        self._area.setGeometry(QRect(cr.left(), cr.top(), self.line_area_width(), cr.height()))

    def paint_line_area(self, ev):
        p = QPainter(self._area)
        pal = self.palette()
        p.fillRect(ev.rect(), pal.color(pal.ColorRole.AlternateBase))
        p.setPen(pal.color(pal.ColorRole.PlaceholderText))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        h = self.fontMetrics().height()
        while block.isValid() and top <= ev.rect().bottom():
            if block.isVisible() and bottom >= ev.rect().top():
                p.drawText(0, top, self._area.width() - 4, h,
                           Qt.AlignmentFlag.AlignRight, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1
        p.end()

    def go_to_line(self, line):
        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        c = QTextCursor(block)
        c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(c)
        self.centerCursor()
        sel = QTextEdit.ExtraSelection()
        col = QColor(255, 200, 0, 90)
        sel.format.setBackground(col)
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = QTextCursor(block)
        self.setExtraSelections([sel])
        self.setFocus()
