# -*- coding: utf-8 -*-
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtGui import QFont, QFontDatabase, QColor, QImage, QPainter
from PyQt5.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
app.setFont(QFont('Microsoft YaHei', 10))
for fp in (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simsun.ttc'):
    if os.path.isfile(fp):
        QFontDatabase.addApplicationFont(fp)

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

panel = w.score_palette
titles = [s._title for s in panel._sections]
print('PALETTE_SECTIONS', len(titles))
for t in titles:
    print(' -', t)

outdir = os.path.join(ROOT, 'tests', 'screenshots', 'main_features')
os.makedirs(outdir, exist_ok=True)

# Full window with left palette visible
out_main = os.path.join(outdir, '05_palette_window.png')
img = QImage(w.size(), QImage.Format_RGB32)
img.fill(QColor('#1a1c22'))
painter = QPainter(img)
w.render(painter)
painter.end()
img.save(out_main)
print('SHOT_WINDOW', out_main, os.path.getsize(out_main))

# Tall crop of the palette itself
panel.resize(280, 1800)
app.processEvents()
out_panel = os.path.join(outdir, '05_palette_symbols.png')
img = QImage(panel.size(), QImage.Format_RGB32)
img.fill(QColor('#22252c'))
painter = QPainter(img)
panel.render(painter)
painter.end()
img.save(out_panel)
print('SHOT_PANEL', out_panel, os.path.getsize(out_panel))

found = False
for si, st in enumerate(w.score.staves):
    for mi, m in enumerate(st.measures):
        for ni, n in enumerate(m.notes):
            if n.is_rest:
                continue
            c = w.edit_controller
            c.toggle_mark([(si, mi, ni)], 'portato')
            c.apply_line_action([(si, mi, ni)], 'ottava_8va')
            c.apply_line_action([(si, mi, ni)], 'pedal')
            c.set_chord_symbol([(si, mi, ni)], 'G7')
            c.set_volta([mi], '1')
            c.set_layout_break([mi], 'system')
            print('MARKS', n.marks, 'chord', n.chord_symbol,
                  'volta', m.volta, 'layout', m.layout_break)
            found = True
            break
        if found:
            break
    if found:
        break
print('FOUND_NOTE', found)
w.close()
print('OK')
