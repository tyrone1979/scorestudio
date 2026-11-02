#!/usr/bin/env python3
"""Generate a learned piano piece and compare its audible motif memory with BWV 846."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from math import log2
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
from music21 import corpus, note, chord, tempo

from llm_compose import ComposeSession, compose_from_text, validate_score_spec
from render_enhance import preset, render_raw, write_wav
from scripts.eval.compare_bwv318 import longest, window_counts


def top_line(part):
    """Highest attack at each onset, suitable for a polyphonic keyboard staff."""
    by_onset = {}
    for obj in part.recurse().notes:
        on = round(float(obj.getOffsetInHierarchy(part)), 7)
        pitches = obj.pitches if isinstance(obj, chord.Chord) else (obj.pitch,)
        midi = max(int(p.midi) for p in pitches)
        dur = float(obj.quarterLength)
        old = by_onset.get(on)
        if dur > 0 and (old is None or midi > old['midi']):
            by_onset[on] = {'midi': midi, 'name': max(pitches).nameWithOctave,
                            'on': on, 'dur': dur,
                            'measure': getattr(obj, 'measureNumber', None)}
    events = [by_onset[k] for k in sorted(by_onset)]
    for i, ev in enumerate(events):
        ev['ioi'] = events[i + 1]['on'] - ev['on'] if i + 1 < len(events) else ev['dur']
    return events


def entropy(values):
    counts = Counter(values)
    total = sum(counts.values())
    return round(-sum((n / total) * log2(n / total) for n in counts.values()), 4) if total else 0


def memory_stats(events):
    intervals = [events[i + 1]['midi'] - events[i]['midi'] for i in range(len(events) - 1)]
    rhythms = [round(e['ioi'], 4) for e in events[:-1]]
    repeated = {}
    for size in (4, 6, 8):
        signatures = []
        for i in range(len(events) - size + 1):
            w = events[i:i + size]
            base = w[0]['midi']
            signatures.append(tuple([e['midi'] - base for e in w] +
                                    [round(e['ioi'], 3) for e in w[:-1]]))
        counts = Counter(signatures)
        covered = sum(1 for sig in signatures if counts[sig] > 1)
        repeated[str(size)] = {
            'windows': len(signatures), 'repeated_windows': covered,
            'coverage': round(covered / max(len(signatures), 1), 4),
            'most_frequent': max(counts.values(), default=0),
        }
    duration = max((e['on'] + e['dur'] for e in events), default=0)
    return {'attacks': len(events), 'duration_quarter_notes': round(duration, 3),
            'attacks_per_quarter': round(len(events) / max(duration, 1), 3),
            'interval_entropy_bits': entropy(intervals),
            'rhythm_entropy_bits': entropy(rhythms),
            'motif_repetition': repeated}


def set_tempo(score, bpm):
    score = copy.deepcopy(score)
    for mark in list(score.recurse().getElementsByClass(tempo.MetronomeMark)):
        mark.activeSite.remove(mark)
    score.insert(0, tempo.MetronomeMark(number=bpm))
    return score


def audio_qa(path):
    with wave.open(str(path)) as wf:
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype='<i2').astype(float) / 32768
        return {'seconds': round(wf.getnframes() / wf.getframerate(), 3),
                'sample_rate': wf.getframerate(), 'peak': round(float(np.abs(pcm).max()), 5),
                'rms': round(float(np.sqrt(np.mean(pcm ** 2))), 5)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', default='piano-learned-memory-v1')
    ap.add_argument('--style', default='sonata')
    ap.add_argument('--sub', default='allegro')
    ap.add_argument('--bars', type=int, default=32)
    ap.add_argument('--tempo', type=int, default=84)
    ap.add_argument('--output-dir', type=Path,
                    default=ROOT / 'runs' / 'piano_bach_comparison')
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    bpm = args.tempo

    command = (f'/key C /tempo {bpm} /compose-grammar {args.style} {args.sub} {args.bars} downbeat '
               f'seed={args.seed} memory=on')
    generated, spec, trace = compose_from_text(ComposeSession(), command)
    violations = validate_score_spec(spec)
    if violations:
        raise RuntimeError(f'Generated score failed validation: {violations}')
    bach = set_tempo(corpus.parse('bach/bwv846'), bpm)

    gen_xml, gen_mid = out / 'generated_piano.musicxml', out / 'generated_piano.mid'
    bach_xml, bach_mid = out / 'bach_bwv846.musicxml', out / 'bach_bwv846.mid'
    generated.write('musicxml', fp=str(gen_xml)); generated.write('midi', fp=str(gen_mid))
    bach.write('musicxml', fp=str(bach_xml)); bach.write('midi', fp=str(bach_mid))

    settings = preset(piano=True, soundfont='salamander', reverb=.10, velocity='natural')
    rendered = []
    for midi in (gen_mid, bach_mid):
        result = render_raw(str(midi), settings)
        if result is None:
            raise RuntimeError(f'Piano rendering failed: {midi}')
        rendered.append(result)
    common_peak = max(float(np.abs(audio).max()) for audio, _ in rendered)
    wavs = (out / 'generated_piano.wav', out / 'bach_bwv846.wav')
    for wav, (audio, sr) in zip(wavs, rendered):
        write_wav(str(wav), audio * (.9 / max(common_peak, 1e-9)), sr)

    gen_line = top_line(generated.parts[0])
    bach_line = top_line(bach.parts[0])
    cross = {
        'longest_exact_pitch_and_rhythm': longest(gen_line, bach_line),
        'longest_transposed_pitch_and_rhythm': longest(gen_line, bach_line, transpose=True),
        'matching_windows': window_counts(gen_line, bach_line),
    }
    theme = spec.get('grammar', {}).get('theme_memory', {})
    report = {
        'generated_by_command': command, 'reference': 'J. S. Bach, BWV 846 Prelude in C major',
        'comparison_scope': 'right-hand/top-line symbolic attacks; same piano, BPM and gain rule',
        'generated': memory_stats(gen_line), 'bach': memory_stats(bach_line),
        'generated_learned_theme': theme, 'cross_piece_overlap': cross,
        'hard_rule_violations': violations,
        'audio': {'generated': audio_qa(wavs[0]), 'bach': audio_qa(wavs[1])},
    }
    report['sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (*wavs, gen_mid, bach_mid, gen_xml, bach_xml)}
    (out / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (out / 'generated_spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    (out / 'trace.txt').write_text(command + '\n' + trace)

    g, b = report['generated'], report['bach']
    learned = theme.get('intra_phrase') or {}
    md = f'''# 学习型钢琴曲与巴赫 BWV 846 对比

两首都用 Salamander 钢琴、{bpm} BPM 和同一峰值增益规则导出。参考曲只用于比较，没有进入奏鸣曲训练集。

## 听觉重点

1. 先听程序曲开头 8 小节，辨认短动机；再听后续是否能认出它的节奏与音程轮廓。
2. BWV 846 的记忆来自持续不变的分解和弦句法，以及和声逐步推进；它并非传统“右手歌唱旋律”。
3. 程序曲的学习模型本次选择：源第 {learned.get('source_bar', '?')} 小节、回答位置 {learned.get('target_bars', [learned.get('target_bar', '?')])}、跨度 {learned.get('span_bars', '?')} 小节；各次回答相似度 {learned.get('realized_similarities', [learned.get('realized_similarity', '?')])}。

## 可核查指标

- 程序曲顶线：{g['attacks']} 次起音，密度 {g['attacks_per_quarter']}/拍，8 音符重复窗口覆盖率 {g['motif_repetition']['8']['coverage']:.1%}。
- BWV 846 顶线：{b['attacks']} 次起音，密度 {b['attacks_per_quarter']}/拍，8 音符重复窗口覆盖率 {b['motif_repetition']['8']['coverage']:.1%}。
- 两曲之间最长“移调后音程与节奏均相同”片段：{cross['longest_transposed_pitch_and_rhythm']['longest_notes']} 个音符。该值只用于排查直接重合，不是抄袭结论。

## 解释边界

重复覆盖率只描述可识别材料是否再次出现，不能单独代表好听或有记忆性。BWV 846 的核心组织在完整和声与织体中，顶线指标会低估它。真正需要听的是：重复是否建立预期，变化是否延续方向，终止是否带来释放。
'''
    (out / '比较报告.md').write_text(md)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
