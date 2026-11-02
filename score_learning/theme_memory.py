"""Learn within-piece motif relations; plan and verify generated thematic recall.

Only aggregate relations are serialized. No training melody is used as a
runtime theme: the first generated phrase supplies the piece's own material.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from typing import Any, Dict, List, Sequence, Tuple

Event = Tuple[int, float]  # MIDI pitch, duration in quarter notes
VERSION = 5
LENGTHS = (4, 6, 8)
MATCH_THRESHOLD = 0.82


def intervals(events: Sequence[Event]) -> Tuple[int, ...]:
    return tuple(b[0] - a[0] for a, b in zip(events, events[1:]))


def informative(events: Sequence[Event]) -> bool:
    """Exclude static/repeated two-pitch figures as evidence of a theme."""
    return len(events) >= 4 and len({m for m, _d in events}) >= 3


def signature(events: Sequence[Event]):
    total = sum(d for _m, d in events)
    return intervals(events), tuple(round(d / max(total, 1e-9), 3) for _m, d in events)


def core_shape(events: Sequence[Event], size: int = 5) -> Tuple[int, ...]:
    """Coarse contour alphabet: direction plus small/large motion, no source pitches."""
    values = []
    for iv in intervals(events[:size]):
        values.append(0 if iv == 0 else (1 if 0 < iv <= 2 else 2 if iv > 2
                                         else -1 if -2 <= iv < 0 else -2))
    return tuple(values)


def core_rhythm(events: Sequence[Event], size: int = 5) -> Tuple[int, ...]:
    """Duration proportions quantized to eighths of the short core."""
    ds = [d for _m, d in events[:size]]
    total = sum(ds)
    return tuple(max(1, min(8, round(8 * d / max(total, 1e-9)))) for d in ds)


def similarity(a: Sequence[Event], b: Sequence[Event]) -> float:
    """Transposition/tempo-invariant, edit-tolerant melodic similarity [0, 1].

    Align interval + normalized duration tokens with Levenshtein DP. This is
    a symbolic proxy, not a claim about perceptual recognition/memorability.
    """
    if len(a) < 2 or len(b) < 2:
        return 0.0
    def tokens(es):
        total = sum(d for _m, d in es)
        return [(iv, es[i + 1][1] / max(total, 1e-9)) for i, iv in enumerate(intervals(es))]
    x, y = tokens(a), tokens(b)
    prev = list(map(float, range(len(y) + 1)))
    for i, (iv, dur) in enumerate(x, 1):
        row = [float(i)]
        for j, (jv, jdur) in enumerate(y, 1):
            # Large interval changes cost 1; one-step ornamentation costs less.
            pitch_cost = min(abs(iv - jv) / 4.0, 1.0)
            rhythm_cost = min(abs(math.log2(max(dur, 1e-9) / max(jdur, 1e-9))), 1.0)
            substitution = 0.75 * pitch_cost + 0.25 * rhythm_cost
            row.append(min(prev[j] + 1, row[-1] + 1, prev[j - 1] + substitution))
        prev = row
    return max(0.0, 1.0 - prev[-1] / max(len(x), len(y)))


def piece_phrases(piece: Dict[str, Any]) -> List[List[Event]]:
    if 'beats' in piece:
        # The chorale generator also works on this beat-level soprano skeleton.
        return [[(int(piece['beats'][i]['midi'][0]), 1.0)
                 for i in range(ph['start'], ph['end'] + 1)]
                for ph in piece['phrases']]
    bars = piece.get('bars') or []
    # Match the leadsheet generator's existing eight-bar analysis grid.
    return [[(int(m), float(d)) for b in bars[start:start + 8]
             for _on, d, _rel, m in b['notes'] if m is not None and d > 0]
            for start in range(0, len(bars), 8)]


def phase(index: int, n: int) -> str:
    return 'last' if index == n - 1 else 'middle'


def _windows(es, n, limit=32):
    # Bound work for long solos/movements, deterministically retaining the head.
    return [(i, es[i:i + n]) for i in range(min(max(0, len(es) - n + 1), limit))
            if informative(es[i:i + n])]


def learn_policy(pieces: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Mine phrase-to-earlier-phrase relations on an already split training set.

    Exact interval/rhythm hashes first; bounded approximate matching second.
    Count at most one relation per target phrase so long pieces do not receive
    one vote for every overlapping window of the same repeated passage.
    """
    eligible, matched, lengths, lags, transforms = Counter(), Counter(), Counter(), Counter(), Counter()
    intra_eligible = intra_matched = 0
    intra_relations, intra_profiles, intra_transforms, intra_harmony = (
        Counter(), Counter(), Counter(), Counter())
    development_patterns, development_profiles, development_harmony = Counter(), Counter(), Counter()
    development_shapes, development_rhythms = Counter(), Counter()
    opening_patterns, opening_profiles, opening_harmony = Counter(), Counter(), Counter()
    opening_shapes, opening_rhythms = Counter(), Counter()
    durations = []
    for piece in sorted(pieces, key=lambda p: str(p['id'])):
        phrases = piece_phrases(piece)
        banks = {n: [] for n in LENGTHS}
        exact = {n: {} for n in LENGTHS}
        for k, es in enumerate(phrases):
            if k:
                candidates = []
                for n in LENGTHS:
                    targets = _windows(es, n, limit=8)
                    if not targets or not banks[n]:
                        continue
                    for offset, dst in targets:
                        sig = signature(dst)
                        source = exact[n].get(sig)
                        if source is not None:
                            j, src = source
                            candidates.append((1.0, n, -offset, j, src, dst))
                            continue
                        # Closest recent source windows; bounded O(length^2).
                        for j, src in banks[n][-32:]:
                            score = similarity(src, dst)
                            if score >= MATCH_THRESHOLD:
                                candidates.append((score, n, -offset, j, src, dst))
                if any(_windows(es, n, 8) and banks[n] for n in LENGTHS):
                    ph = phase(k, len(phrases))
                    eligible[ph] += 1
                    if candidates:
                        _score, n, _off, j, src, dst = max(candidates, key=lambda c: c[:4])
                        matched[ph] += 1
                        lengths[n] += 1
                        lags[k - j] += 1
                        if signature(src) == signature(dst):
                            op = 'repeat' if src[0][0] == dst[0][0] else 'transpose'
                        else:
                            op = 'approximate'
                        transforms[op] += 1
                        durations.append(sum(d for _m, d in src))
            for n in LENGTHS:
                for _offset, src in _windows(es, n):
                    banks[n].append((k, src))
                    exact[n].setdefault(signature(src), (k, src))
        # 八小节主题内部的联合关系：跨度、来源位置、目标位置和音符密度一起学习。
        # 这里只保存计数，不保存训练曲的音高或节奏片段。
        bars = piece.get('bars') or []
        for base in range(0, len(bars) - 1, 8):
            phrase = bars[base:base + 8]
            if len(phrase) < 4:
                continue
            for span in (1, 2):
                for dst in range(span, len(phrase) - span + 1):
                    candidates = []
                    for src in range(0, dst - span + 1):
                        a = [(int(m), float(d)) for bar in phrase[src:src + span]
                             for _on, d, _rel, m in bar.get('notes', []) if m is not None]
                        b = [(int(m), float(d)) for bar in phrase[dst:dst + span]
                             for _on, d, _rel, m in bar.get('notes', []) if m is not None]
                        if len(a) < 3 or len(b) < 3 or len({m for m, _d in a}) < 2:
                            continue
                        candidates.append((similarity(a, b), src, a, b))
                    if not candidates:
                        continue
                    intra_eligible += 1
                    score, src, a, b = max(candidates, key=lambda x: (x[0], -x[1]))
                    if score < MATCH_THRESHOLD:
                        continue
                    intra_matched += 1
                    key = f'{span}:{src}:{dst}'
                    intra_relations[key] += 1
                    counts = tuple(sum(m is not None for *_x, m in bar.get('notes', []))
                                   for bar in phrase[src:src + span])
                    intra_profiles[f'{key}|{",".join(map(str, counts))}'] += 1
                    try:
                        src_tok = phrase[src]['chords'][0][1]
                        dst_tok = phrase[dst]['chords'][0][1]
                        src_root = int(str(src_tok).split(':', 1)[0])
                        dst_root = int(str(dst_tok).split(':', 1)[0])
                        shift = (dst_root - src_root + 6) % 12 - 6
                        intra_harmony[f'{key}|{shift}'] += 1
                    except (KeyError, IndexError, TypeError, ValueError):
                        pass
                    if signature(a) == signature(b):
                        intra_transforms['repeat' if a[0][0] == b[0][0] else 'transpose'] += 1
                    else:
                        intra_transforms['approximate'] += 1
            # Find a single generated anchor whose contour/rhythm returns several times.
            # The serialized pattern contains positions and transformations only, never notes.
            best_chain = best_opening = None
            for span in (1, 2):
                for src in range(0, len(phrase) - span):
                    a = [(int(m), float(d)) for bar in phrase[src:src + span]
                         for _on, d, _rel, m in bar.get('notes', []) if m is not None]
                    if len(a) < 4 or len({m for m, _d in a}) < 3:
                        continue
                    targets = []
                    scores = []
                    shifts = []
                    for dst in range(src + span, len(phrase) - span + 1):
                        if targets and dst < targets[-1] + span:
                            continue
                        b = [(int(m), float(d)) for bar in phrase[dst:dst + span]
                             for _on, d, _rel, m in bar.get('notes', []) if m is not None]
                        score = similarity(a, b)
                        if score < MATCH_THRESHOLD:
                            continue
                        targets.append(dst); scores.append(score)
                        try:
                            ar = int(str(phrase[src]['chords'][0][1]).split(':', 1)[0])
                            br = int(str(phrase[dst]['chords'][0][1]).split(':', 1)[0])
                            shifts.append((br - ar + 6) % 12 - 6)
                        except (KeyError, IndexError, TypeError, ValueError):
                            shifts.append(0)
                    if targets:
                        candidate = (len(targets), sum(scores), -src, span, src, targets, shifts, a)
                        if best_chain is None or candidate[:3] > best_chain[:3]:
                            best_chain = candidate
                        if src == 0 and (best_opening is None or candidate[:3] > best_opening[:3]):
                            best_opening = candidate
            if best_chain is not None:
                _n, _score, _neg, span, src, targets, shifts, a = best_chain
                pattern = f'{span}:{src}:{",".join(map(str, targets))}'
                development_patterns[pattern] += 1
                counts = tuple(sum(m is not None for *_x, m in bar.get('notes', []))
                               for bar in phrase[src:src + span])
                development_profiles[f'{pattern}|{",".join(map(str, counts))}'] += 1
                development_harmony[f'{pattern}|{",".join(map(str, shifts))}'] += 1
                shape = core_shape(a)
                rhythm = core_rhythm(a)
                if shape:
                    development_shapes[f'{pattern}|{",".join(map(str, shape))}'] += 1
                    development_rhythms[f'{pattern}|{",".join(map(str, rhythm))}'] += 1
            if best_opening is not None:
                _n, _score, _neg, span, src, targets, shifts, a = best_opening
                pattern = f'{span}:{src}:{",".join(map(str, targets))}'
                opening_patterns[pattern] += 1
                counts = tuple(sum(m is not None for *_x, m in bar.get('notes', []))
                               for bar in phrase[src:src + span])
                opening_profiles[f'{pattern}|{",".join(map(str, counts))}'] += 1
                opening_harmony[f'{pattern}|{",".join(map(str, shifts))}'] += 1
                shape, rhythm = core_shape(a), core_rhythm(a)
                if shape:
                    opening_shapes[f'{pattern}|{",".join(map(str, shape))}'] += 1
                    opening_rhythms[f'{pattern}|{",".join(map(str, rhythm))}'] += 1
    total, successes = sum(eligible.values()), sum(matched.values())
    ids = sorted(str(p['id']) for p in pieces)
    return {
        'version': VERSION, 'enabled': successes > 0 or intra_matched > 0,
        'train_pieces': len(pieces),
        'train_ids_sha256': hashlib.sha256('\n'.join(ids).encode()).hexdigest(),
        'representation': 'relative_intervals_and_normalized_durations',
        'match_threshold': MATCH_THRESHOLD,
        'eligible_phrases': total, 'matched_phrases': successes,
        'recall_probability': successes / max(total, 1),
        'by_phase': {p: {'eligible': eligible[p], 'matched': matched[p],
                         'p': matched[p] / max(eligible[p], 1)} for p in sorted(eligible)},
        'length_counts': {str(k): v for k, v in sorted(lengths.items())},
        'lag_counts': {str(k): v for k, v in sorted(lags.items())},
        'transform_counts': dict(sorted(transforms.items())),
        'duration_median_ql': sorted(durations)[len(durations) // 2] if durations else 4.0,
        'intra_phrase': {
            'eligible': intra_eligible, 'matched': intra_matched,
            'probability': intra_matched / max(intra_eligible, 1),
            'relation_counts': dict(sorted(intra_relations.items())),
            'source_profile_counts': dict(sorted(intra_profiles.items())),
            'harmony_shift_counts': dict(sorted(intra_harmony.items())),
            'transform_counts': dict(sorted(intra_transforms.items())),
            'development_pattern_counts': dict(sorted(development_patterns.items())),
            'development_source_profile_counts': dict(sorted(development_profiles.items())),
            'development_harmony_shift_counts': dict(sorted(development_harmony.items())),
            'development_core_shape_counts': dict(sorted(development_shapes.items())),
            'development_core_rhythm_counts': dict(sorted(development_rhythms.items())),
            'opening_pattern_counts': dict(sorted(opening_patterns.items())),
            'opening_source_profile_counts': dict(sorted(opening_profiles.items())),
            'opening_harmony_shift_counts': dict(sorted(opening_harmony.items())),
            'opening_core_shape_counts': dict(sorted(opening_shapes.items())),
            'opening_core_rhythm_counts': dict(sorted(opening_rhythms.items())),
        },
    }


def plan_intra_phrase(policy: Dict[str, Any], rng) -> Dict[str, Any] | None:
    """Sample a within-theme development chain from learned aggregate counts."""
    model = policy.get('intra_phrase') or {}
    # Prefer relations whose source is the phrase opening. This hierarchy is
    # learned separately from the corpus, rather than moving a sampled motif
    # to bar zero after generation.
    prefix = 'opening' if model.get('opening_pattern_counts') else 'development'
    chains = model.get(f'{prefix}_pattern_counts') or {}
    if policy.get('enabled') and chains:
        # Sample a learned recurrence *event*: chains with more observed returns
        # receive proportionally more mass, without imposing a hand-written count.
        event_counts = {k: float(v) * len(k.split(':')[2].split(','))
                        for k, v in chains.items()}
        pattern = _choose_string(event_counts, rng)
        span_s, source_s, targets_s = pattern.split(':')
        targets = list(map(int, targets_s.split(',')))
        profiles = {k.split('|', 1)[1]: v for k, v in
                    (model.get(f'{prefix}_source_profile_counts') or {}).items()
                    if k.startswith(pattern + '|')}
        harmonies = {k.split('|', 1)[1]: v for k, v in
                     (model.get(f'{prefix}_harmony_shift_counts') or {}).items()
                     if k.startswith(pattern + '|')}
        shapes = {k.split('|', 1)[1]: v for k, v in
                  (model.get(f'{prefix}_core_shape_counts') or {}).items()
                  if k.startswith(pattern + '|')}
        rhythms = {k.split('|', 1)[1]: v for k, v in
                   (model.get(f'{prefix}_core_rhythm_counts') or {}).items()
                   if k.startswith(pattern + '|')}
        profile = _choose_string(profiles, rng) if profiles else ''
        shifts = _choose_string(harmonies, rng) if harmonies else ''
        harmony_shifts = list(map(int, shifts.split(','))) if shifts else [0] * len(targets)
        shape = _choose_string(shapes, rng) if shapes else ''
        rhythm = _choose_string(rhythms, rng) if rhythms else ''
        return {'span_bars': int(span_s), 'source_bar': int(source_s),
                'target_bar': targets[0], 'target_bars': targets,
                'source_note_counts': list(map(int, profile.split(','))) if profile else [],
                'harmony_shift': harmony_shifts[0], 'harmony_shifts': harmony_shifts,
                'learned_occurrences': 1 + len(targets),
                'hierarchy': 'opening_theme' if prefix == 'opening' else 'free_anchor',
                'core_shape': list(map(int, shape.split(','))) if shape else [],
                'core_rhythm': list(map(int, rhythm.split(','))) if rhythm else []}
    counts = model.get('relation_counts') or {}
    if not policy.get('enabled') or not counts:
        return None
    # Relation keys are structured strings, so sample them without numeric conversion.
    items = sorted(counts.items())
    r = rng.random() * sum(float(v) for _k, v in items)
    relation = items[-1][0]
    for key, value in items:
        r -= float(value)
        if r <= 0:
            relation = key
            break
    span, source, target = map(int, relation.split(':'))
    profiles = {k.split('|', 1)[1]: v for k, v in
                (model.get('source_profile_counts') or {}).items()
                if k.startswith(relation + '|')}
    profile = None
    if profiles:
        pitems = sorted(profiles.items())
        r = rng.random() * sum(float(v) for _k, v in pitems)
        profile = pitems[-1][0]
        for key, value in pitems:
            r -= float(value)
            if r <= 0:
                profile = key
                break
    shifts = {k.split('|', 1)[1]: v for k, v in
              (model.get('harmony_shift_counts') or {}).items()
              if k.startswith(relation + '|')}
    harmony_shift = 0
    if shifts:
        sitems = sorted(shifts.items(), key=lambda kv: int(kv[0]))
        r = rng.random() * sum(float(v) for _k, v in sitems)
        harmony_shift = int(sitems[-1][0])
        for key, value in sitems:
            r -= float(value)
            if r <= 0:
                harmony_shift = int(key)
                break
    return {'span_bars': span, 'source_bar': source, 'target_bar': target,
            'target_bars': [target],
            'source_note_counts': [] if profile is None else list(map(int, profile.split(','))),
            'harmony_shift': harmony_shift, 'harmony_shifts': [harmony_shift],
            'learned_occurrences': 2}


def _choose_string(counts: Dict[str, Any], rng) -> str:
    items = sorted(counts.items())
    r = rng.random() * sum(float(v) for _k, v in items)
    for key, value in items:
        r -= float(value)
        if r <= 0:
            return key
    return items[-1][0]


def choose_weighted(counts, rng, default):
    if not counts:
        return default
    items = sorted(counts.items(), key=lambda kv: int(kv[0]))
    r = rng.random() * sum(float(v) for _k, v in items)
    for key, value in items:
        r -= float(value)
        if r <= 0:
            return int(key)
    return int(items[-1][0])


def plan_references(n: int, policy: Dict[str, Any], rng) -> List[Any]:
    """Sample recurrence phase/lag; enforce one recall for a supported long piece.

    The minimum-one rule is an explicit engineering prior, NOT corpus learning.
    Values are zero-based references to earlier generated phrases/sections.
    """
    refs = [None] * n
    if n < 2 or not policy.get('enabled') or not policy.get('matched_phrases'):
        return refs
    for k in range(1, n):
        p = policy.get('by_phase', {}).get(phase(k, n), {}).get('p', policy['recall_probability'])
        if rng.random() < p:
            lag = choose_weighted(policy.get('lag_counts', {}), rng, 1)
            refs[k] = max(0, k - lag)
    if n >= 3 and all(r is None for r in refs):
        refs[-1] = 0
    return refs


def evaluate_phrases(phrases: Sequence[Sequence[Event]], motif_length=4) -> Dict[str, Any]:
    """Independent score-based verification; no generation trace/Chinese labels."""
    rows = []
    for k, es in enumerate(phrases):
        if not k:
            continue
        best = (0.0, None, None, None)
        exact_head = False
        for src_idx in range(k):
            for src_offset, src in _windows(phrases[src_idx], motif_length):
                for dst_offset, dst in _windows(es, motif_length):
                    score = similarity(src, dst)
                    if dst_offset == 0 and signature(src) == signature(dst):
                        exact_head = True
                    if score > best[0]:
                        best = score, src_idx, src_offset, dst_offset
        rows.append({'phrase': k + 1, 'similarity': round(best[0], 6),
                     'source_phrase': None if best[1] is None else best[1] + 1,
                     'source_offset': best[2], 'target_offset': best[3],
                     'exact_opening_recall': exact_head,
                     'recognized': best[0] >= MATCH_THRESHOLD})
    return {'motif_length': motif_length, 'threshold': MATCH_THRESHOLD, 'relations': rows,
            'recall_rate': sum(r['recognized'] for r in rows) / max(len(rows), 1),
            'exact_opening_recall_rate': sum(r['exact_opening_recall'] for r in rows) / max(len(rows), 1),
            'whole_phrase_duplicate_rate': sum(
                signature(es) in [signature(prev) for prev in phrases[:k]]
                for k, es in enumerate(phrases) if k) / max(len(rows), 1)}


def phrases_from_spec(spec, spans, part_index=0, beat_grid=False):
    """Decode the actual exported event stream, independently of recall labels.

    spans are half-open quarter-note positions. Chorale verification samples
    sounding soprano at quarter-note positions; leadsheet uses note events.
    """
    from music21.pitch import Pitch
    durations = {'whole': 4., 'half': 2., 'quarter': 1., 'eighth': .5,
                 '16th': .25, '32nd': .125,
                 'dotted_whole': 6., 'dotted_half': 3.,
                 'dotted_quarter': 1.5, 'dotted_eighth': .75}
    timeline, t = [], 0.0
    for ev in spec['parts'][part_index]['events']:
        name, dur = ev[:2]
        d = float(dur) if isinstance(dur, (int, float)) else durations[dur]
        names = name if isinstance(name, list) else [name]
        names = [n for n in names if n is not None and str(n).lower() not in ('r', 'rest')]
        if names:
            timeline.append((t, t + d, max(int(Pitch(n).midi) for n in names)))
        t += d
    out = []
    for start, end in spans:
        if beat_grid:
            events = []
            for i in range(max(0, int(round(end - start)))):
                onset = start + i
                m = next((m for a, b, m in timeline if a - 1e-7 <= onset < b - 1e-7), None)
                if m is not None:
                    events.append((m, 1.0))
        else:
            events = [(m, min(b, end) - max(a, start)) for a, b, m in timeline
                      if start - 1e-7 <= a < end - 1e-7]
        out.append(events)
    return out
