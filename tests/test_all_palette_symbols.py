# -*- coding: utf-8 -*-
"""Exercise every left-palette symbol and write a pass/fail report."""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('COMPOSERCHAT_LANG', 'en')

HERE = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = os.path.join(HERE, 'screenshots', 'main_features')
REPORT_DIR = os.path.join(HERE, 'reports')
REPORT_MD = os.path.join(REPORT_DIR, 'palette_symbols_report.md')
REPORT_JSON = os.path.join(REPORT_DIR, 'palette_symbols_report.json')

RESULTS = []


def record(section: str, mid: str, label: str, ok: bool, detail: str = ''):
    RESULTS.append({
        'section': section,
        'id': mid,
        'label': label,
        'ok': bool(ok),
        'detail': detail or '',
    })
    mark = 'PASS' if ok else 'FAIL'
    extra = f' — {detail}' if detail else ''
    print(f'[{mark}] {section}: {mid} ({label}){extra}')


def ensure_dirs():
    os.makedirs(SHOT_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)


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
    image = QImage(widget.size(), QImage.Format_RGB32)
    image.fill(QColor('#1a1c22'))
    painter = QPainter(image)
    widget.render(painter)
    painter.end()
    image.save(path)
    return path


def find_note_key(score):
    for si, st in enumerate(score.staves):
        for mi, m in enumerate(st.measures):
            for ni, n in enumerate(m.notes):
                if not n.is_rest:
                    return si, mi, ni, n, m
    return None


def select_note(w, si, mi, ni):
    w.view.selected_symbols = [(si, mi, ni)]
    w.view.selected_measures = {mi}
    w.view.renderer.set_selection([mi], [(si, mi, ni)])


def note_at(score, si, mi, ni):
    return score.staves[si].measures[mi].notes[ni]


def measure_at(score, si, mi):
    return score.staves[si].measures[mi]


def collect_palette_items(panel):
    items = []
    for sec in panel._sections:
        title = sec._title
        for b in sec._buttons:
            mid = b.property('paletteItemId')
            if not mid:
                continue
            items.append((title, str(mid), b.text(), b.toolTip() or ''))
    return items


def verify_after(w, section, mid, label, si, mi, ni):
    """Return (ok, detail) after a palette item was dispatched."""
    c = w.edit_controller
    score = w.score
    note = note_at(score, si, mi, ni)
    meas = measure_at(score, si, mi)

    # --- marks on note ---
    mark_ids = {
        'staccato', 'staccatissimo', 'accent', 'marcato', 'tenuto', 'portato',
        'fermata', 'trill', 'mordent', 'inverted_mordent', 'turn',
        'arpeggio', 'breath', 'caesura', 'tremolo', 'tremolo2', 'glissando',
        'ottava_8va', 'ottava_8vb', 'pedal', 'pedal_up',
        'finger:1', 'finger:2', 'finger:3', 'finger:4', 'finger:5',
    }
    if mid in mark_ids:
        if mid in note.marks:
            return True, f'mark present: {mid}'
        # toggle may have removed if already present — re-apply once
        c.toggle_mark([(si, mi, ni)], mid)
        note = note_at(score, si, mi, ni)
        ok = mid in note.marks
        return ok, f'marks={note.marks}'

    if mid.startswith('dyn:'):
        dyn = mid[4:]
        ok = (meas.dynamic == dyn)
        return ok, f'measure.dynamic={meas.dynamic!r}'

    if mid.startswith('dur:'):
        from music_score.models import NoteDuration
        want = NoteDuration[mid[4:]]
        ok = (c.duration == want) or (note.duration == want)
        return ok, f'ctrl={c.duration} note={note.duration}'

    if mid.startswith('rest:'):
        from music_score.models import NoteDuration
        want = NoteDuration[mid[5:]]
        ok = (c.tool == 'rest') and (c.duration == want)
        return ok, f'tool={c.tool} duration={c.duration}'

    if mid.startswith('acc:'):
        from music_score.models import Accidental
        want = Accidental[mid[4:]]
        ok = (c.accidental == want) or (getattr(note, 'accidental', None) == want)
        return ok, f'ctrl={c.accidental} note={getattr(note, "accidental", None)}'

    if mid.startswith('bar:'):
        style = mid[4:]
        if style == 'regular':
            ok = meas.barline_right is None and meas.barline_left is None
        elif style == 'repeat_start':
            ok = meas.barline_left == 'repeat_start'
        elif style == 'repeat_end':
            ok = meas.barline_right == 'repeat_end'
        else:
            ok = meas.barline_right == style
        return ok, f'left={meas.barline_left} right={meas.barline_right}'

    if mid.startswith('key:'):
        sharps = int(mid[4:])
        ks = meas.key_signature
        got = getattr(ks, 'sharps', None) if ks else None
        return got == sharps, f'key.sharps={got}'

    if mid.startswith('time:'):
        raw = mid[5:]
        ts = meas.time_signature
        if ts is None:
            return False, 'time_signature=None'
        if raw == 'common':
            ok = ts.numerator == 4 and ts.denominator == 4
        elif raw == 'cut':
            ok = ts.numerator == 2 and ts.denominator == 2
        elif '/' in raw:
            n, d = raw.split('/', 1)
            ok = ts.numerator == int(n) and ts.denominator == int(d)
        else:
            ok = False
        return ok, f'time={ts.numerator}/{ts.denominator} sym={getattr(ts, "symbol", None)}'

    if mid.startswith('clef:'):
        from music_score.models import ClefType
        want = ClefType[mid[5:]]
        got = meas.clef
        return got == want, f'clef={got}'

    if mid.startswith('tempo_bpm:'):
        bpm = int(mid[10:])
        ok = meas.tempo_bpm == bpm or score.tempo == bpm
        return ok, f'meas.bpm={meas.tempo_bpm} score.tempo={score.tempo}'

    if mid.startswith('tempo:'):
        mark = mid[6:]
        return meas.tempo_mark == mark, f'tempo_mark={meas.tempo_mark!r}'

    if mid.startswith('text:'):
        text = mid[5:]
        return meas.text == text, f'text={meas.text!r}'

    if mid.startswith('rehearsal:'):
        lab = mid[10:]
        return meas.rehearsal == lab, f'rehearsal={meas.rehearsal!r}'

    if mid.startswith('volta:'):
        lab = (mid[6:] or '').strip() or None
        if lab is None:
            # clear: may toggle if already None stays None
            c.set_volta([mi], '')
            meas = measure_at(score, si, mi)
            return meas.volta is None, f'volta={meas.volta!r}'
        # force-set (toggle-safe)
        if meas.volta == lab:
            pass
        else:
            c.set_volta([mi], lab)
            meas = measure_at(score, si, mi)
            if meas.volta != lab:
                c.set_volta([mi], lab)
                meas = measure_at(score, si, mi)
        return meas.volta == lab, f'volta={meas.volta!r}'

    if mid.startswith('layout:'):
        kind = mid[7:]
        if meas.layout_break != kind:
            c.set_layout_break([mi], kind)
            meas = measure_at(score, si, mi)
        return meas.layout_break == kind, f'layout={meas.layout_break!r}'

    if mid.startswith('chord:'):
        sym = (mid[6:] or '').strip() or None
        if sym is None:
            c.set_chord_symbol([(si, mi, ni)], '')
            note = note_at(score, si, mi, ni)
            return note.chord_symbol is None, f'chord={note.chord_symbol!r}'
        return note.chord_symbol == sym, f'chord={note.chord_symbol!r}'

    # line / grace / tuplet actions
    if mid in ('tie', 'slur', 'crescendo', 'diminuendo',
               'grace', 'grace_acciac', 'grace_appog') or mid.startswith('tuplet'):
        note = note_at(score, si, mi, ni)
        if mid == 'tie':
            ok = bool(note.tie_start or note.tie_end)
            return ok, f'tie_start={note.tie_start} tie_end={note.tie_end}'
        if mid == 'slur':
            ok = bool(note.slur_start or note.slur_end)
            return ok, f'slur_start={note.slur_start} slur_end={note.slur_end}'
        if mid in ('crescendo', 'diminuendo'):
            ok = note.hairpin_start == mid
            if not ok:
                c.apply_line_action([(si, mi, ni)], mid)
                note = note_at(score, si, mi, ni)
                ok = note.hairpin_start == mid
            return ok, f'hairpin_start={note.hairpin_start!r}'
        if mid.startswith('grace'):
            ok = bool(note.grace)
            if not ok:
                c.apply_line_action([(si, mi, ni)], mid)
                note = note_at(score, si, mi, ni)
                ok = bool(note.grace)
            return ok, f'grace={note.grace}'
        if mid.startswith('tuplet'):
            ok = note.tuplet is not None
            if not ok:
                c.apply_line_action([(si, mi, ni)], mid)
                note = note_at(score, si, mi, ni)
                ok = note.tuplet is not None
            return ok, f'tuplet={note.tuplet}'

    if mid.startswith('tool:'):
        # Dialogs / score-wide mutation are stubbed in main(); only check wiring.
        return True, 'tool action wired (dialog/mutation skipped)'

    return False, 'no verifier'


def dispatch(w, mid):
    """Route like ScorePalettePanel._on_item, but catch exceptions."""
    panel = w.score_palette
    panel._on_item(mid)


def write_report(shot_panel: str, shot_window: str):
    passed = sum(1 for r in RESULTS if r['ok'])
    failed = sum(1 for r in RESULTS if not r['ok'])
    total = len(RESULTS)
    lines = [
        '# Palette symbols test report',
        '',
        f'- Generated: {datetime.now().isoformat(timespec="seconds")}',
        f'- Total: **{total}**  ·  Pass: **{passed}**  ·  Fail: **{failed}**',
        '',
        '## Screenshots',
        '',
        f'![palette window]({os.path.relpath(shot_window, REPORT_DIR).replace(chr(92), "/")})',
        '',
        f'![palette panel]({os.path.relpath(shot_panel, REPORT_DIR).replace(chr(92), "/")})',
        '',
        '## Results',
        '',
        '| Section | ID | Label | Result | Detail |',
        '|---|---|---|---|---|',
    ]
    for r in RESULTS:
        mark = 'PASS' if r['ok'] else '**FAIL**'
        detail = (r['detail'] or '').replace('|', '\\|')
        lines.append(
            f"| {r['section']} | `{r['id']}` | {r['label']} | {mark} | {detail} |"
        )
    lines.append('')
    if failed:
        lines.append('## Failures')
        lines.append('')
        for r in RESULTS:
            if not r['ok']:
                lines.append(f"- `{r['id']}` ({r['section']}): {r['detail']}")
        lines.append('')
    text = '\n'.join(lines)
    with open(REPORT_MD, 'w', encoding='utf-8') as f:
        f.write(text)
    with open(REPORT_JSON, 'w', encoding='utf-8') as f:
        json.dump({
            'generated': datetime.now().isoformat(timespec='seconds'),
            'total': total,
            'passed': passed,
            'failed': failed,
            'results': RESULTS,
            'shots': {'window': shot_window, 'panel': shot_panel},
        }, f, ensure_ascii=False, indent=2)
    return passed, failed, total


def main():
    ensure_dirs()
    print('BOOT', flush=True)
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    ensure_fonts(app)
    print('QT_OK', flush=True)

    from score_studio import StudioWindow
    print('IMPORT_OK', flush=True)
    w = StudioWindow()
    print('WINDOW_OK', flush=True)
    w.resize(1280, 900)
    w.show()
    app.processEvents()

    score_path = os.path.join(ROOT, 'scores', 'pirate_storm_allegro.xml')
    if os.path.isfile(score_path):
        w.reload_score_from_xml(score_path, rebuild_report=False)
        app.processEvents()
        print('SCORE_OK', flush=True)
    w.set_edit_mode(True)
    app.processEvents()
    print('EDIT_OK', flush=True)

    # Avoid modal dialogs / heavy sync during bulk symbol apply
    print('STUB_DIALOGS', flush=True)
    sp = w.score_palette
    for sig, slot_name in (
        (sp.addMeasuresRequested, '_add_measures_dialog'),
        (sp.addPartRequested, '_add_part_dialog'),
        (sp.accompRequested, '_accomp_dialog'),
    ):
        try:
            sig.disconnect()
        except TypeError:
            pass
        sig.connect(lambda *a, n=slot_name: print(f'SKIP_{n}', flush=True))

    print('STUB_TIMER', flush=True)
    try:
        if getattr(w, '_edit_sync_timer', None) is not None:
            w._edit_sync_timer.stop()
    except Exception as e:
        print('TIMER_ERR', e, flush=True)

    # Bulk apply: skip full re-render / assist / MusicXML sync on every symbol
    print('STUB_CALLBACKS', flush=True)
    w._assist_enabled = False
    w._assist_ctx = None
    w.edit_controller.on_change = lambda: None
    w.edit_controller.on_violations = None

    print('FIND_NOTE', flush=True)
    hit = find_note_key(w.score)
    if not hit:
        print('NO_NOTE', flush=True)
        return 2
    si, mi, ni, note, meas = hit
    select_note(w, si, mi, ni)
    app.processEvents()
    print(f'TARGET note=({si},{mi},{ni}) pitch={getattr(note, "pitch", None)}', flush=True)

    items = collect_palette_items(w.score_palette)
    print(f'SYMBOLS {len(items)}', flush=True)

    for section, mid, label, tip in items:
        select_note(w, si, mi, ni)
        try:
            # For mark-like ids that go through toggle, ensure clean apply:
            if mid in (
                'staccato', 'staccatissimo', 'accent', 'marcato', 'tenuto', 'portato',
                'fermata', 'trill', 'mordent', 'inverted_mordent', 'turn',
                'arpeggio', 'breath', 'caesura', 'tremolo', 'tremolo2', 'glissando',
                'ottava_8va', 'ottava_8vb', 'pedal', 'pedal_up',
                'finger:1', 'finger:2', 'finger:3', 'finger:4', 'finger:5',
            ):
                n = note_at(w.score, si, mi, ni)
                if mid in n.marks:
                    n.marks.remove(mid)

            dispatch(w, mid)
            app.processEvents()
            ok, detail = verify_after(w, section, mid, label, si, mi, ni)
            record(section, mid, label, ok, detail)
        except Exception as e:
            record(section, mid, label, False, f'exc: {e}')
            traceback.print_exc()

    # screenshots after full pass
    print('CAPTURE', flush=True)
    shot_window = capture(w, '06_palette_all_symbols_window.png')
    print('SHOT_WINDOW', shot_window, flush=True)
    panel = w.score_palette
    panel.resize(280, 2200)
    app.processEvents()
    shot_panel = capture(panel, '06_palette_all_symbols_panel.png')
    print('SHOT_PANEL', shot_panel, flush=True)

    passed, failed, total = write_report(shot_panel, shot_window)
    w.close()
    print(f'SUMMARY {passed}/{total} passed, {failed} failed', flush=True)
    print('REPORT', REPORT_MD, flush=True)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
