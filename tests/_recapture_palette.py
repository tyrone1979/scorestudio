# -*- coding: utf-8 -*-
"""Recapture clean palette screenshots with music fonts loaded (no bulk mutation)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtGui import QFont, QColor, QImage, QPainter
from PyQt5.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
from music_score.fonts import ensure_music_fonts, music_ui_font
print('FONTS', ensure_music_fonts(), flush=True)
app.setFont(QFont('Microsoft YaHei', 10))

from score_studio import StudioWindow

w = StudioWindow()
w.resize(1280, 900)
w.show()
app.processEvents()
score_path = os.path.join(ROOT, 'scores', 'pirate_storm_allegro.xml')
if os.path.isfile(score_path):
    w.reload_score_from_xml(score_path, rebuild_report=False)
    app.processEvents()
w.set_edit_mode(True)
app.processEvents()

outdir = os.path.join(ROOT, 'tests', 'screenshots', 'main_features')
os.makedirs(outdir, exist_ok=True)


def capture(widget, name):
    path = os.path.join(outdir, name)
    img = QImage(widget.size(), QImage.Format_RGB32)
    img.fill(QColor('#1a1c22'))
    p = QPainter(img)
    widget.render(p)
    p.end()
    img.save(path)
    print('SHOT', path, os.path.getsize(path), flush=True)
    return path


capture(w, '05_palette_window.png')
panel = w.score_palette
panel.resize(280, 2200)
app.processEvents()
capture(panel, '05_palette_symbols.png')
capture(w, '06_palette_all_symbols_window.png')
capture(panel, '06_palette_all_symbols_panel.png')

# smoke: first clef button text should be musical symbol, not 'G' or box
btn = panel._sections[0]._buttons[0]
print('CLEF_BTN', repr(btn.text()), 'font', btn.font().family(), flush=True)
w.close()
print('OK', flush=True)
