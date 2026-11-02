#!/usr/bin/env python3
"""Symbolic similarity audit of the actual listening scores (not a plagiarism detector)."""
from __future__ import annotations
import hashlib
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from music21 import converter, corpus, stream
from score_learning.learn_core import is_heldout


def extract(part):
    """Sounding monophonic note attacks, tie-continuations merged; rests via IOI."""
    events = []
    for n in part.recurse().notes:
        onset = float(n.getOffsetInHierarchy(part))
        midi = int(n.pitches[-1].midi)
        duration = float(n.quarterLength)
        if duration <= 0:
            continue
        tie = getattr(n, 'tie', None)
        if (tie and tie.type in ('stop', 'continue') and events and
            events[-1]['midi'] == midi and abs(events[-1]['on'] + events[-1]['dur'] - onset) < 1e-7):
            events[-1]['dur'] += duration
            continue
        events.append({'midi': midi, 'name': n.pitches[-1].nameWithOctave,
                       'on': onset, 'dur': duration, 'measure': n.measureNumber})
    for i, e in enumerate(events):
        e['ioi'] = events[i + 1]['on'] - e['on'] if i + 1 < len(events) else e['dur']
    return events


def longest(a, b, transpose=False, rhythm=True, require_variety=True):
    matches = []
    for i in range(len(a)):
        for j in range(len(b)):
            shift = a[i]['midi'] - b[j]['midi'] if transpose else 0
            k = 0
            while i + k < len(a) and j + k < len(b):
                x, y = a[i + k], b[j + k]
                if x['midi'] != y['midi'] + shift:
                    break
                if rhythm and (abs(x['dur'] - y['dur']) > 1e-7 or
                               (k and abs(a[i + k - 1]['ioi'] - b[j + k - 1]['ioi']) > 1e-7)):
                    break
                k += 1
            if k >= 3 and (not require_variety or len({x['midi'] for x in a[i:i + k]}) >= 3):
                matches.append({'notes': k, 'generated_index': i, 'bach_index': j,
                                'transpose_semitones': shift,
                                'generated_measure': a[i]['measure'], 'bach_measure': b[j]['measure'],
                                'generated_on': a[i]['on'], 'bach_on': b[j]['on'],
                                'duration_ql': a[i + k - 1]['on'] + a[i + k - 1]['dur'] - a[i]['on']})
    matches.sort(key=lambda r: (-r['notes'], -r['duration_ql'], r['generated_index'], r['bach_index']))
    # Remove contained instances with the same diagonal alignment.
    kept = []
    for r in matches:
        if not any(r['generated_index'] >= q['generated_index'] and
                   r['generated_index'] + r['notes'] <= q['generated_index'] + q['notes'] and
                   r['bach_index'] - q['bach_index'] == r['generated_index'] - q['generated_index']
                   for q in kept):
            kept.append(r)
    return {'longest_notes': kept[0]['notes'] if kept else 0, 'matches': kept[:12]}


def edit_similarity(a, b):
    """Whole-sequence normalized Levenshtein; insert/delete/substitute cost 1."""
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        row = [i]
        for j, y in enumerate(b, 1):
            row.append(min(row[-1] + 1, prev[j] + 1, prev[j - 1] + (x != y)))
        prev = row
    return 1 - prev[-1] / max(len(a), len(b), 1)


def window_counts(a, b, sizes=(4, 6, 8, 12)):
    rows = []
    for n in sizes:
        counts = {'n': n, 'eligible_generated_windows': 0, 'exact': 0, 'transposed': 0}
        for i in range(len(a) - n + 1):
            xs = a[i:i + n]
            if len({e['midi'] for e in xs}) < 3:
                continue
            counts['eligible_generated_windows'] += 1
            same = moved = False
            for j in range(len(b) - n + 1):
                ys = b[j:j + n]
                shift = xs[0]['midi'] - ys[0]['midi']
                rhythm_ok = (all(abs(x['dur'] - y['dur']) < 1e-7 for x, y in zip(xs, ys)) and
                             all(abs(x['ioi'] - y['ioi']) < 1e-7 for x, y in zip(xs[:-1], ys[:-1])))
                if rhythm_ok and all(x['midi'] == y['midi'] + shift for x, y in zip(xs, ys)):
                    moved = True
                    same |= shift == 0
            counts['exact'] += same
            counts['transposed'] += moved
        rows.append(counts)
    return rows


def grid(part, step=1.0):
    es = extract(part)
    return [next((e['midi'] for e in es if e['on'] - 1e-7 <= t * step < e['on'] + e['dur'] - 1e-7), None)
            for t in range(int(float(part.duration.quarterLength) / step))]


def vertical_longest(a_parts, b_parts):
    ag, bg = [grid(p) for p in a_parts], [grid(p) for p in b_parts]
    a, b = list(zip(*ag)), list(zip(*bg))
    best = {'beats': 0}
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            if k > best['beats']:
                best = {'beats': k, 'generated_on': i, 'bach_on': j,
                        'pitches': a[i:i + k]}
    return best


def main():
    out = ROOT / 'runs/theme_memory_v1'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated', type=Path, default=out/'generated_theme_memory_piano.musicxml')
    parser.add_argument('--reference', type=Path, default=out/'bach_bwv318_piano.musicxml')
    parser.add_argument('--output', type=Path, default=out/'bwv318_similarity.json')
    args = parser.parse_args()
    paths = [args.generated.resolve(), args.reference.resolve()]
    generated, bach = [converter.parse(str(p)) for p in paths]
    a, b = extract(generated.parts[0]), extract(bach.parts[0])
    strict = longest(a, b)
    shifted = longest(a, b, transpose=True)
    pitch_only = longest(a, b, transpose=True, rhythm=False)
    def tokens(es, shift=0):
        return [(e['midi'] + shift, e['dur']) for e in es]
    global_score = edit_similarity(tokens(a), tokens(b))
    shifts = [(edit_similarity(tokens(a), tokens(b, shift)), shift) for shift in range(-12, 13)]
    best_global, best_shift = max(shifts)
    voice_matches = []
    for i, p in enumerate(generated.parts):
        for j, q in enumerate(bach.parts):
            r = longest(extract(p), extract(q), transpose=True)
            voice_matches.append({'generated_voice': p.partName, 'bach_voice': q.partName,
                                  'same_voice': i == j,
                                  'longest_including_repeated_tones': longest(
                                      extract(p), extract(q), transpose=True,
                                      require_variety=False)['longest_notes'], **r})
    # Descriptive background only: different score lengths are not controlled.
    cache = json.loads((ROOT/'runs/grammar_cache/bach_chorales.json').read_text())['pieces']
    ids = sorted({p['id'] for p in cache if p['mode'] == 'major' and p['meter'] == '4/4'
                  and is_heldout(p['id']) and p['id'] != 'bwv318'})[:20]
    context = []
    for pid in ids:
        s = corpus.parse('bach/' + pid)
        es = extract(s.parts[0])
        context.append({'id': pid, 'notes': len(es),
                        'longest_transposed_rhythmic': longest(a, es, transpose=True)['longest_notes']})
    # Check legacy caches/analysis metadata for BWV 318 exposure, without claiming
    # that absence from this v1 split proves absence from every historical model.
    learning = json.loads((out/'learning_report.json').read_text())
    train_ids = sorted(str(p['id']) for p in cache if p['mode'] == 'major' and not is_heldout(p['id']))
    policy_hash = learning['styles']['chorale']['theme_memory']['major']['train_ids_sha256']
    assert hashlib.sha256('\n'.join(train_ids).encode()).hexdigest() == policy_hash
    result = {
        'method': 'exact note attacks, ties merged; IOI preserves gaps; no time-warping or ornament removal',
        'note_counts': {'generated_soprano': len(a), 'bach_soprano': len(b)},
        'whole_sequence_edit_similarity_pitch_duration': global_score,
        'best_transposed_whole_sequence_edit_similarity': best_global,
        'best_global_shift': best_shift,
        'strict': strict, 'transposed_rhythm_preserving': shifted,
        'repetition_inclusive': {
            'strict': longest(a, b, require_variety=False)['longest_notes'],
            'transposed_rhythmic': longest(a, b, transpose=True, require_variety=False)['longest_notes']},
        'transposed_pitch_only': pitch_only,
        'window_matches': window_counts(a, b),
        'all_voice_pair_matches': voice_matches,
        'four_voice_quarter_grid': vertical_longest(generated.parts, bach.parts),
        'background_heldout_major_4_4': context,
        'v1_training_provenance': {'bwv318_heldout': is_heldout('bwv318'),
                                   'bwv318_in_v1_train': 'bwv318' in train_ids,
                                   'train_hash_verified': True},
        'files': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'generated_events': a, 'bach_events': b,
        'limitations': ['No single overall plagiarism percentage is defined.',
                       'Main motif scan requires >=3 notes and >=3 different pitches; raw repeated-tone-inclusive maxima are also reported.',
                       'No approximation for inserted/deleted ornaments or expressive timing.',
                       'Attack duration/IOI must be exact; symbolic spelling is compared via sounding MIDI.',
                       'Background sample is descriptive, with unequal lengths and no significance test.',
                       'V1 heldout provenance is not a proof about all historical training pipelines.'],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k not in ('generated_events', 'bach_events', 'all_voice_pair_matches', 'files')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
