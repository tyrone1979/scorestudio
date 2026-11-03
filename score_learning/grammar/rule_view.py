# -*- coding: utf-8 -*-
"""手写规则窗口：左边是给音乐家读的说明，右边是可改的定义文件。"""
from __future__ import annotations

import os

from . import rule_dsl


def _panels():
    path = rule_dsl.rules_path()
    with open(path, encoding='utf-8') as f:
        source = f.read()
    return path, rule_dsl.musician_text(), source


def _ensure_font():
    """离屏测试没有系统字体表，显式装入雅黑，中文才画得出来。"""
    from PyQt5.QtGui import QFontDatabase
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    if QFontDatabase().families():
        return app
    for path in (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simsun.ttc',
                 r'C:\Windows\Fonts\arial.ttf'):
        if os.path.isfile(path):
            QFontDatabase.addApplicationFont(path)
    return app


def build_window():
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QColor, QFont, QPainter
    from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

    path, reading, source = _panels()
    _ensure_font()

    class Panel(QWidget):
        def __init__(self, title, body):
            super().__init__()
            self.title = title
            self.body = body
            self.setMinimumSize(560, 1280)

        def paintEvent(self, _event):
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor('#fffdf8'))
            painter.setPen(QColor('#c8bfb2'))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
            painter.setPen(QColor('#1c1a17'))
            title_font = QFont('Microsoft YaHei', 13)
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.drawText(18, 32, self.title)
            body_font = QFont('Microsoft YaHei', 10)
            painter.setFont(body_font)
            painter.drawText(
                self.rect().adjusted(18, 48, -18, -16),
                int(Qt.TextWordWrap),
                self.body,
            )
            painter.end()

    window = QWidget()
    window.setWindowTitle('手写规则')
    root = QVBoxLayout(window)
    title = QLabel('手写规则')
    title.setStyleSheet('font-family: "Microsoft YaHei"; font-size: 18px; font-weight: 600; color: #1c1a17;')
    path_label = QLabel(path)
    path_label.setStyleSheet('font-family: "Microsoft YaHei"; font-size: 12px; color: #5c564e;')
    hint = QLabel('左边是读法，右边是定义文件。改文件里的数字或删掉一行，保存后重新检查就会按新定义算。')
    hint.setWordWrap(True)
    hint.setStyleSheet('font-family: "Microsoft YaHei"; font-size: 13px; color: #1c1a17;')
    root.addWidget(title)
    root.addWidget(path_label)
    root.addWidget(hint)
    row = QHBoxLayout()
    row.addWidget(Panel('读法', reading), 1)
    row.addWidget(Panel('定义文件', source), 1)
    root.addLayout(row)
    window.resize(1280, 1500)
    window.setStyleSheet('QWidget { background: #f4f1ea; }')
    return window


def save_screenshot(path: str) -> str:
    """无界面环境下把规则窗口画到一张图里，供测试留存。"""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    app = _ensure_font()
    from PyQt5.QtGui import QColor, QFont, QImage, QPainter
    app.setFont(QFont('Microsoft YaHei', 10))
    window = build_window()
    window.resize(1280, 1500)
    window.show()
    app.processEvents()
    image = QImage(window.size(), QImage.Format_RGB32)
    image.fill(QColor('#f4f1ea'))
    painter = QPainter(image)
    window.render(painter)
    painter.end()
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    image.save(path)
    window.close()
    return path
