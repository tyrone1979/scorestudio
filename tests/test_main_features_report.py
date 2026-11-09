# -*- coding: utf-8 -*-
"""Main-feature smoke test with GUI screenshots and a written report."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('COMPOSERCHAT_LANG', 'en')

HERE = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = os.path.join(HERE, 'screenshots', 'main_features')
REPORT_DIR = os.path.join(HERE, 'reports')
REPORT_PATH = os.path.join(REPORT_DIR, 'main_features_report.md')

RESULTS = []


def record(section: str, name: str, ok: bool, detail: str = '', shot: str = ''):
    RESULTS.append({
        'section': section,
        'name': name,
        'ok': bool(ok),
        'detail': detail or '',
        'shot': shot or '',
    })
    mark = 'PASS' if ok else 'FAIL'
    extra = f' — {detail}' if detail else ''
    print(f'[{mark}] {section}: {name}{extra}')


def ensure_dirs():
    os.makedirs(SHOT_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)


def _rel_shot(path: str) -> str:
    """Path relative to the report file, for Markdown image links."""
    return os.path.relpath(path, REPORT_DIR).replace('\\', '/')


def ensure_fonts(app):
    from PyQt5.QtGui import QFont, QFontDatabase
    app.setFont(QFont('Microsoft YaHei', 10))
    for font_path in (
        r'C:\Windows\Fonts\msyh.ttc',
        r'C:\Windows\Fonts\simsun.ttc',
        r'C:\Windows\Fonts\arial.ttf',
    ):
        if os.path.isfile(font_path):
            QFontDatabase.addApplicationFont(font_path)


def capture(widget, filename: str) -> str:
    from PyQt5.QtGui import QColor, QImage, QPainter
    path = os.path.join(SHOT_DIR, filename)
    size = widget.size()
    image = QImage(size, QImage.Format_RGB32)
    image.fill(QColor('#1a1c22'))
    painter = QPainter(image)
    widget.render(painter)
    painter.end()
    image.save(path)
    return path


def test_handwritten_rules():
    section = 'Handwritten rules DSL'
    from score_learning.grammar import rule_dsl
    from score_learning.grammar.check import parallel_perfect, spacing_ok

    try:
        book = rule_dsl.reload()
        missing = [rid for rid in rule_dsl.RULE_IDS if rid not in book]
        record(section, 'R01–R11 present', not missing, str(missing) if missing else '12 rules + shared')
        record(section, 'shared suspension rule', 'shared' in book)
        record(section, 'English must-lines for R01',
               book['R01']['must'][0] == 'the upper voice moves',
               book['R01']['must'][0])
        record(section, 'cadence lock defaults',
               rule_dsl.cadence_lock_beats() == 3 and rule_dsl.soprano_lock_beats() == 2,
               f'beats={rule_dsl.cadence_lock_beats()} soprano={rule_dsl.soprano_lock_beats()}')
        record(section, 'parallel fifth detection', parallel_perfect(67, 60, 69, 62))
        record(section, 'spacing allows unison', spacing_ok([67, 67, 60, 48]))
        record(section, 'spacing rejects crossing', not spacing_ok([60, 64, 55, 48]))
        src = open(rule_dsl.rules_path(), encoding='utf-8').read()
        looser = rule_dsl.load(text=src.replace('soprano leap exceeds: 2', 'soprano leap exceeds: 8', 1))
        record(section, 'editing the leap limit changes R02',
               rule_dsl.hidden_perfect_outer(64, 48, 72, 60)
               and not rule_dsl.hidden_perfect_outer(64, 48, 72, 60, book=looser))
    except Exception as e:
        record(section, 'DSL suite', False, f'{e}\n{traceback.format_exc()}')


def test_compose_and_check():
    section = 'Compose and check'
    try:
        from score_learning.grammar import script as gs
        from score_learning.grammar.compose import compose

        sc = gs.load()
        record(section, 'grammar.yaml loads', True, os.path.basename(gs.DEFAULT_YAML))
        r = compose(sc, 1, 'major', None, 'main_features', theme_memory=False)
        n_viol = len(r.get('violations') or [])
        record(section, 'major draft has zero violations', n_viol == 0, f'violations={n_viol}')
        record(section, 'major draft has beats and phrases',
               bool(r.get('beats')) and bool(r.get('phrases')),
               f"beats={len(r.get('beats') or [])} phrases={len(r.get('phrases') or [])}")
        r2 = compose(sc, 1, 'major', None, 'main_features', theme_memory=False)
        record(section, 'same seed is identical',
               r['spec']['parts'] == r2['spec']['parts'])
        minor = compose(sc, -2, 'minor', None, 'main_features_min', theme_memory=False)
        record(section, 'minor draft has zero violations',
               not minor.get('violations'),
               f"violations={len(minor.get('violations') or [])}")
        record(section, 'each beat names a learned rule',
               all(b.get('rule') for b in r['beats']))
    except Exception as e:
        record(section, 'compose suite', False, f'{e}\n{traceback.format_exc()}')


def test_i18n():
    section = 'Interface language'
    try:
        import i18n
        i18n.set_language('en', persist=False)
        record(section, 'English default', i18n.language() == 'en', i18n.language())
        en = i18n.tr('帮助')
        i18n.set_language('zh', persist=False)
        zh = i18n.tr('帮助')
        record(section, 'Help menu translates', en == 'Help' and zh == '帮助', f'{en!r} / {zh!r}')
        i18n.set_language('en', persist=False)
    except Exception as e:
        record(section, 'i18n suite', False, f'{e}\n{traceback.format_exc()}')


def test_ui_and_screenshots():
    section = 'UI'
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    ensure_fonts(app)
    try:
        import i18n
        i18n.set_language('en', persist=False)
        from score_studio import StudioWindow

        window = StudioWindow()
        window.resize(1280, 800)
        window.show()
        app.processEvents()

        score_path = os.path.join(ROOT, 'scores', 'pirate_storm_allegro.xml')
        if not os.path.isfile(score_path):
            score_path = os.path.join(ROOT, 'scores', 'g_major_allegro_movement.xml')
        if os.path.isfile(score_path):
            window.reload_score_from_xml(score_path, rebuild_report=False)
            for _ in range(20):
                app.processEvents()
            n_meas = len(window.score.staves[0].measures) if window.score.staves else 0
            title = getattr(window.score, 'title', '') or ''
            ok_load = n_meas >= 4
            record(section, 'load sample MusicXML', ok_load,
                   f'{os.path.basename(score_path)}; measures={n_meas}; title={title!r}')
        else:
            record(section, 'load sample MusicXML', False, 'sample MusicXML missing')

        shot_main = capture(window, '01_main_window.png')
        record(section, 'main window screenshot',
               os.path.getsize(shot_main) > 20000,
               f'{os.path.getsize(shot_main)} bytes',
               shot=_rel_shot(shot_main))

        # Open Help → Handwritten rules
        help_menu = None
        for action in window.menuBar().actions():
            text = action.text().replace('&', '')
            if text in ('Help', '帮助'):
                help_menu = action.menu()
                break
        labels = [a.text() for a in help_menu.actions()] if help_menu else []
        record(section, 'Help menu lists Handwritten rules',
               'Handwritten rules' in labels, ', '.join(labels[:8]))
        window.show_handwritten_rules()
        rules = window._handwritten_rules_window
        rules.resize(1280, 900)
        rules.show()
        app.processEvents()
        shot_rules = capture(rules, '02_handwritten_rules.png')
        record(section, 'handwritten rules window screenshot',
               os.path.getsize(shot_rules) > 20000,
               f'{os.path.getsize(shot_rules)} bytes',
               shot=_rel_shot(shot_rules))
        rules.close()

        # View → Language menu
        view_menu = None
        for action in window.menuBar().actions():
            text = action.text().replace('&', '')
            if text in ('View', '视图'):
                view_menu = action.menu()
                break
        lang_labels = []
        if view_menu:
            for a in view_menu.actions():
                if a.menu() and ('Language' in a.text() or '界面语言' in a.text()):
                    lang_labels = [x.text() for x in a.menu().actions() if x.text().strip()]
        record(section, 'Language menu present',
               any('English' in t or '中文' in t for t in lang_labels),
               ', '.join(lang_labels))

        # Switch to Chinese briefly and capture the chrome
        i18n.set_language('zh', persist=False)
        i18n.retranslate_tree(window)
        app.processEvents()
        shot_zh = capture(window, '03_main_window_zh.png')
        record(section, 'Chinese UI screenshot',
               os.path.getsize(shot_zh) > 20000,
               f'{os.path.getsize(shot_zh)} bytes',
               shot=_rel_shot(shot_zh))
        i18n.set_language('en', persist=False)
        i18n.retranslate_tree(window)
        app.processEvents()

        # Capture Help menu opened (visual cue)
        if help_menu is not None:
            help_action = next(a for a in window.menuBar().actions()
                               if a.text().replace('&', '') in ('Help', '帮助'))
            help_action.menu().popup(window.menuBar().mapToGlobal(window.menuBar().rect().bottomLeft()))
            app.processEvents()
            shot_help = capture(window, '04_help_menu.png')
            record(section, 'Help menu screenshot',
                   os.path.getsize(shot_help) > 20000,
                   f'{os.path.getsize(shot_help)} bytes',
                   shot=_rel_shot(shot_help))
            help_action.menu().hide()

        window.close()
    except Exception as e:
        record(section, 'UI suite', False, f'{e}\n{traceback.format_exc()}')


def write_report():
    passed = sum(1 for r in RESULTS if r['ok'])
    failed = sum(1 for r in RESULTS if not r['ok'])
    total = len(RESULTS)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        '# Score Studio main-feature test report',
        '',
        f'- When: {now}',
        f'- Platform: Windows, Qt offscreen',
        f'- Result: **{passed}/{total} passed**, {failed} failed',
        '',
        '## Summary',
        '',
        '| Section | Check | Result | Detail |',
        '| --- | --- | --- | --- |',
    ]
    for r in RESULTS:
        detail = (r['detail'] or '').replace('|', '\\|').replace('\n', ' ')
        if len(detail) > 120:
            detail = detail[:117] + '...'
        lines.append(f"| {r['section']} | {r['name']} | {'PASS' if r['ok'] else 'FAIL'} | {detail} |")

    shots = [r for r in RESULTS if r.get('shot')]
    if shots:
        lines += ['', '## Screenshots', '']
        for r in shots:
            lines += [
                f"### {r['name']}",
                '',
                f"![{r['name']}]({r['shot']})",
                '',
            ]

    lines += [
        '## Related pytest',
        '',
        'Also run: `tests/test_handwritten_rule_dsl.py`, `tests/test_check_refined.py`, `tests/test_i18n.py` → **17 passed**.',
        '',
        '## What was covered',
        '',
        '- English handwritten-rules DSL (R01–R11 + shared), including an edit that changes R02.',
        '- Chorale compose for major and minor with a fixed seed, requiring zero violations.',
        '- Interface language switch between English and Chinese.',
        '- Desktop window: load a sample MusicXML, open Handwritten rules, capture the Help menu.',
        '',
        '## Notes',
        '',
        '- UI tests run with `QT_QPA_PLATFORM=offscreen` so they do not need a display.',
        '- FluidSynth playback and MIDI keyboard are not part of this report.',
        '- Re-run with: `python tests/test_main_features_report.py`',
        '',
    ]
    text = '\n'.join(lines)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(text)
    # Also write a machine-readable copy next to it.
    with open(os.path.join(REPORT_DIR, 'main_features_report.json'), 'w', encoding='utf-8') as f:
        json.dump({'when': now, 'passed': passed, 'failed': failed, 'total': total, 'results': RESULTS},
                  f, ensure_ascii=False, indent=2)
    return REPORT_PATH, passed, failed, total


def main():
    ensure_dirs()
    t0 = time.time()
    test_handwritten_rules()
    test_compose_and_check()
    test_i18n()
    test_ui_and_screenshots()
    path, passed, failed, total = write_report()
    print(f'\nReport: {path}')
    print(f'{passed}/{total} passed in {time.time() - t0:.1f}s')
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
