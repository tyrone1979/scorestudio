from scripts.eval.compare_bwv318 import longest, edit_similarity, window_counts, extract
from music21 import note, stream, tie


def events(pitches, duration=1):
    return [{'midi': p, 'on': i * duration, 'dur': duration, 'ioi': duration,
             'measure': i // 4 + 1} for i, p in enumerate(pitches)]


def test_longest_exact_and_transposed():
    a = events([60, 62, 64, 65, 67])
    b = events([65, 67, 69, 70, 72])
    assert longest(a, b)['longest_notes'] == 0
    assert longest(a, b, transpose=True)['longest_notes'] == 5
    assert longest(a, b, transpose=True)['matches'][0]['transpose_semitones'] == -5


def test_rhythm_and_gaps_are_not_ignored():
    a = events([60, 62, 64, 65, 67])
    b = events([60, 62, 64, 65, 67], duration=.5)
    assert longest(a, b)['longest_notes'] == 0
    assert longest(a, b, rhythm=False)['longest_notes'] == 5
    b = events([60, 62, 64, 65, 67])
    b[2]['ioi'] = 2
    assert longest(a, b)['longest_notes'] == 3


def test_static_figures_excluded_and_window_counts():
    assert longest(events([60]*8), events([60]*8))['longest_notes'] == 0
    assert longest(events([60]*8), events([60]*8), require_variety=False)['longest_notes'] == 8
    rows = window_counts(events([60, 62, 64, 65, 67]), events([65, 67, 69, 70, 72]), sizes=(4,))
    assert rows == [{'n': 4, 'eligible_generated_windows': 2, 'exact': 0, 'transposed': 2}]
    assert edit_similarity([1, 2, 3], [1, 2, 3]) == 1
    assert edit_similarity([1, 2], [3, 4]) == 0


def test_tie_continuations_are_merged():
    p = stream.Part()
    m = stream.Measure(number=1)
    a, b, c = note.Note('C4'), note.Note('C4'), note.Note('D4')
    a.tie = tie.Tie('start')
    b.tie = tie.Tie('stop')
    m.append([a, b, c]);p.append(m)
    es = extract(p)
    assert len(es) == 2
    assert es[0]['dur'] == 2 and es[0]['ioi'] == 2
