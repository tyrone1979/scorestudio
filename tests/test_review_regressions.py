"""Regression coverage for chat isolation, editor persistence and score export."""
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from music21 import instrument, key, meter, note, stream
from deliver import ly_key, ly_pitch, score_to_lilypond
from music_score.models import (
    Score, Staff, Measure, Note, Pitch, NoteName, NoteDuration, TimeSignature,
)
from music_score.editor_core import RuleEngine, SuggestionEngine
from music_score.exporter import model_to_m21
from score_studio import StudioWindow, m21_to_model


@pytest.mark.parametrize('spelling,expected', [
    ('B-4', "bes'"), ('E--3', 'eeses'), ('Bb3', 'bes'),
    ('F#4', "fis'"), ('C4', "c'"), ('C2', 'c,'),
])
def test_lilypond_pitch_spelling(spelling, expected):
    assert ly_pitch(spelling) == expected


@pytest.mark.parametrize('sharps', range(-7, 8))
@pytest.mark.parametrize('mode', ['major', 'minor'])
def test_lilypond_key_matches_signature(sharps, mode):
    tonic = key.KeySignature(sharps).asKey(mode).tonic
    assert ly_key(sharps, mode) == rf'\key {ly_pitch(tonic.name + "3")} \{mode}'


def test_flat_note_and_chord_lilypond_export():
    from music21 import chord
    sc = stream.Score()
    p = stream.Part()
    p.append(note.Note('B-4'))
    p.append(chord.Chord(['E-4', 'G4', 'B-4']))
    sc.append(p)
    text = score_to_lilypond(sc, mode='minor')
    assert "bes'4" in text
    assert "<ees' g' bes'>4" in text
    assert r'\key a \minor' in text


def changed_meter_score():
    def quarter():
        return Note(Pitch(NoteName.C, 4), NoteDuration.QUARTER)
    return Score(time_signature=TimeSignature(4, 4), staves=[Staff(measures=[
        Measure(number=1),
        Measure(number=2, time_signature=TimeSignature(3, 4)),
        Measure(number=3, notes=[quarter() for _ in range(3)]),
    ])])


def test_inherited_meter_blocks_overflow_and_suggestions():
    sc = changed_meter_score()
    rules = RuleEngine(strict=False)
    verdict = rules.check_placement(sc, 0, 2, Pitch(NoteName.D, 4), NoteDuration.QUARTER)
    assert verdict.code == 'overflow'
    assert rules.check_duration_change(sc, 0, 2, 0, NoteDuration.HALF).blocked
    assert SuggestionEngine(rules).suggest(sc, 0, 2, None, NoteDuration.QUARTER) == []
    sc.staves[0].measures[2].notes.append(Note(Pitch(NoteName.C, 4), NoteDuration.QUARTER))
    assert any(v.code == 'overflow' and v.measure_idx == 2 for v in rules.lint_score(sc))


@pytest.mark.parametrize('factory', [instrument.Violin, instrument.Clarinet, instrument.Piano])
def test_instrument_survives_editor_roundtrip(factory, tmp_path):
    from music21 import converter
    sc = stream.Score()
    p = stream.Part()
    original = factory()
    original.midiChannel = 3
    p.insert(0, original)
    m = stream.Measure(number=1)
    m.insert(0, meter.TimeSignature('4/4'))
    m.append(note.Note('C4', quarterLength=4))
    p.append(m)
    sc.append(p)
    result = model_to_m21(m21_to_model(sc, title='Roundtrip'))
    actual = result.parts[0].getInstrument()
    assert actual.midiProgram == original.midiProgram
    assert actual.midiChannel == 3
    assert str(actual.transposition) == str(original.transposition)
    path = tmp_path / 'roundtrip.xml'
    result.write('musicxml', fp=str(path))
    assert converter.parse(str(path)).parts[0].getInstrument().midiProgram == original.midiProgram


def test_stale_chat_result_does_not_apply_to_current_chat():
    session = SimpleNamespace(last_skill_ids=[])
    result = ('ok', object(), {'title': 'A'}, 'Done', {})
    ui = SimpleNamespace(
        _chat_id='B', _compose_session=object(), chat_send_btn=Mock(),
        _chat_busy_timer=Mock(), _persist_background_chat_result=Mock(),
        _apply_composed_score=Mock(),
    )
    StudioWindow._on_chat_ready(ui, ('chat_result', 'A', session, result))
    ui._persist_background_chat_result.assert_called_once_with('A', session, result)
    ui._apply_composed_score.assert_not_called()


def test_concert_pitch_instrument_is_not_transposed_on_export():
    sc = stream.Score()
    p = stream.Part()
    inst = instrument.Clarinet()
    inst.transposition = None
    p.insert(0, inst)
    p.append(note.Note('C4', quarterLength=4))
    sc.append(p)
    actual = model_to_m21(m21_to_model(sc, title='Concert pitch'))
    assert actual.parts[0].getInstrument().transposition is None


def test_background_result_preserves_active_chat(tmp_path):
    meta = tmp_path / 'A.json'
    meta.write_text(json.dumps({'messages': [{'role': 'user', 'text': 'Compose'}]}))
    session = SimpleNamespace(score_spec={'title': 'A'}, revision=1, last_skill_ids=[])
    index = {'active_id': 'B', 'sessions': [{'id': 'A'}, {'id': 'B'}]}
    ui = SimpleNamespace(
        _chat_paths=lambda _: {'meta': str(meta)}, _load_chat_index=lambda: index,
        _save_chat_index=Mock(), _refresh_chat_combo=Mock(),
    )
    StudioWindow._persist_background_chat_result(ui, 'A', session, ('ok', None, session.score_spec, 'Done', {}))
    stored = json.loads(meta.read_text())
    assert stored['compose']['score_spec'] == session.score_spec
    assert stored['messages'][-1]['text'] == 'Done'
    assert index['active_id'] == 'B'


def test_persist_flushes_pending_edits_before_metadata(tmp_path):
    meta = tmp_path / 'chat.json'
    order = []
    index = {'sessions': []}
    ui = SimpleNamespace(
        _chat_id='A', _edit_sync_timer=Mock(isActive=lambda: True),
        _sync_edited_score=lambda **kw: order.append(('flush', kw)) or True,
        _chat_paths=lambda _: {'meta': str(meta)}, _resolve_chat_title=lambda: 'A',
        _compose_session=None, _chat_messages=[], _load_chat_index=lambda: index,
        _save_chat_index=lambda _: order.append(('metadata', {})), _refresh_chat_combo=Mock(),
    )
    StudioWindow._persist_current_chat(ui)
    assert order == [('flush', {'synthesize': False}), ('metadata', {})]
    assert meta.exists()


def test_failed_edit_flush_remains_pending():
    timer = Mock(isActive=lambda: True)
    ui = SimpleNamespace(_chat_id='A', _edit_sync_timer=timer, _sync_edited_score=lambda **_: False)
    assert StudioWindow._persist_current_chat(ui) is False
    timer.start.assert_called_once()


def test_pending_edit_is_written_to_xml_before_save(tmp_path):
    from music21 import converter
    sc = Score(staves=[Staff(measures=[Measure(number=1, notes=[
        Note(Pitch(NoteName.G, 4), NoteDuration.WHOLE),
    ])])])
    xml = tmp_path / 'A.xml'
    index = {'sessions': []}
    ui = SimpleNamespace(
        _chat_id='A', score=sc, musicxml_path=str(xml), _compose_session=None,
        _edit_sync_timer=Mock(isActive=lambda: True), _chat_messages=[],
        _chat_paths=lambda _: {'meta': str(tmp_path / 'A.json'), 'mid': str(tmp_path / 'A.mid')},
        _resolve_chat_title=lambda: 'A', _load_chat_index=lambda: index,
        _save_chat_index=Mock(), _refresh_chat_combo=Mock(),
        play_btn=Mock(), statusBar=lambda: Mock(),
    )
    ui._sync_edited_score = lambda **kw: StudioWindow._sync_edited_score(ui, **kw)
    StudioWindow._persist_current_chat(ui)
    assert converter.parse(str(xml)).recurse().notes[0].pitch.nameWithOctave == 'G4'


def test_close_save_failure_keeps_window_open(monkeypatch):
    import score_studio
    monkeypatch.setattr(score_studio.QMessageBox, 'warning', Mock())
    ui = SimpleNamespace(_persist_current_chat=Mock(side_effect=OSError('disk full')))
    event = Mock()
    StudioWindow.closeEvent(ui, event)
    event.ignore.assert_called_once()


def test_stale_audio_and_report_do_not_update_current_chat():
    ui = SimpleNamespace(_chat_id='B', m21_score=object(), score=object(), _set_audio=Mock())
    StudioWindow._on_audio_ready(ui, ('score_audio', 'A', object(), ('synth', [], 44100)))
    StudioWindow._on_report_ready(ui, (object(), '/old/report.md'))
    ui._set_audio.assert_not_called()
