# -*- coding: utf-8 -*-
"""手写规则定义文件：音乐家改文件，检查和写作跟着变。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from score_learning.grammar import rule_dsl
from score_learning.grammar.check import parallel_perfect, spacing_ok

HERE = os.path.dirname(os.path.abspath(__file__))
SHOT = os.path.join(HERE, 'screenshots', 'handwritten_rules_gui.png')


def test_file_lists_every_handwritten_rule():
    book = rule_dsl.load()
    for rid in rule_dsl.RULE_IDS:
        assert rid in book, rid
        assert book[rid].get('name')
        assert book[rid].get('means')
        assert book[rid]['must']
    assert 'shared' in book
    assert rule_dsl.cadence_lock_beats() == 3
    assert rule_dsl.unattested_forbidden()
    assert rule_dsl.structural_on()
    text = rule_dsl.musician_text(book)
    for rid in list(rule_dsl.RULE_IDS) + ['shared']:
        assert rid in text


def test_defaults_match_the_old_predicates():
    assert parallel_perfect(67, 60, 69, 62)
    assert parallel_perfect(67, 55, 72, 48)
    assert not parallel_perfect(69, 50, 69, 62)
    assert spacing_ok([67, 67, 60, 48])
    assert not spacing_ok([60, 64, 55, 48])
    assert rule_dsl.out_of_range(80, 62, 78)
    assert not rule_dsl.out_of_range(78, 62, 78)
    assert rule_dsl.bad_melodic(60, 66)
    assert not rule_dsl.bad_melodic(60, 62)


def test_editing_the_file_changes_the_decision():
    src = open(rule_dsl.rules_path(), encoding='utf-8').read()
    looser = src.replace('soprano leap exceeds: 2', 'soprano leap exceeds: 8', 1)
    book = rule_dsl.load(text=looser)
    # 女高音从 64 到 72，跳进 8 个半音。默认「超过 2」算隐伏；改成超过 8 则不算。
    assert rule_dsl.hidden_perfect_outer(64, 48, 72, 60)
    assert not rule_dsl.hidden_perfect_outer(64, 48, 72, 60, book=book)

    wider = src.replace('tenor to bass at most: 19', 'tenor to bass at most: 30', 1)
    book = rule_dsl.load(text=wider)
    voices = [72, 60, 55, 36]  # 次中音与低音相距 19，不超过 19；再拉大才越界
    assert not rule_dsl.spacing_violation(voices)
    far = [72, 60, 55, 30]  # 相距 25
    assert rule_dsl.spacing_violation(far)
    assert not rule_dsl.spacing_violation(far, book=book)

    no_range = src.replace('the pitch is outside the voice range', 'this line no longer checks range', 1)
    book = rule_dsl.load(text=no_range)
    assert not rule_dsl.out_of_range(90, 62, 78, book=book)
    assert rule_dsl.cadence_lock_beats(book=rule_dsl.load(
        text=src.replace('the phrase ending uses the cadence formula', 'the ending is no longer locked', 1))) == 0


def test_studio_menu_opens_the_rules_window():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt5.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setFont(QFont('Microsoft YaHei', 10))
    for font_path in (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simsun.ttc'):
        if os.path.isfile(font_path):
            QFontDatabase.addApplicationFont(font_path)
    from score_studio import StudioWindow

    window = StudioWindow()
    window.resize(1280, 800)
    window.show()
    app.processEvents()
    help_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == '帮助')
    labels = [a.text() for a in help_menu.actions()]
    assert 'Handwritten rules' in labels
    window.show_handwritten_rules()
    rules = window._handwritten_rules_window
    rules.resize(1280, 900)
    rules.show()
    app.processEvents()
    studio_path = os.path.join(HERE, 'screenshots', 'score_studio_gui.png')
    image = QImage(window.size(), QImage.Format_RGB32)
    image.fill(QColor('#1a1c22'))
    painter = QPainter(image)
    window.render(painter)
    painter.end()
    image.save(studio_path)
    assert os.path.getsize(studio_path) > 20000
    window.close()
    rules.close()


def test_rules_window_screenshot():
    from score_learning.grammar.rule_view import save_screenshot

    path = save_screenshot(SHOT)
    assert os.path.isfile(path)
    assert os.path.getsize(path) > 20000


if __name__ == '__main__':
    test_file_lists_every_handwritten_rule()
    test_defaults_match_the_old_predicates()
    test_editing_the_file_changes_the_decision()
    test_rules_window_screenshot()
    test_studio_menu_opens_the_rules_window()
    print('handwritten rule DSL: ok')
    print(SHOT)
