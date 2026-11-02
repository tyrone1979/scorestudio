#!/usr/bin/env python3
"""Generate one reusable /compose-grammar string-quartet audition bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np

from llm_compose import ComposeSession, compose_from_text, validate_score_spec
from render_enhance import preset, render_raw, write_wav
from scripts.eval.compare_bwv318 import extract
from scripts.eval.four_voice_orchestral import export_audio, finish_events, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', default='four-voice-audition-v2-1')
    ap.add_argument('--output-dir', type=Path,
                    default=ROOT / 'runs' / 'four_voice_audition_v2')
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    command = (f'/key D /tempo 60 /compose-grammar strings allegro 32 downbeat '
               f'seed={args.seed}')
    score, spec, trace = compose_from_text(ComposeSession(), command)
    violations = validate_score_spec(spec)
    if len(score.parts) != 4 or violations:
        raise RuntimeError(f'Invalid quartet: parts={len(score.parts)}, violations={violations}')

    xml = out / 'score.musicxml'
    midi = out / 'score.mid'
    wav = out / 'score.wav'
    score.write('musicxml', fp=str(xml))
    voices = [finish_events(extract(part)) for part in score.parts]
    export_audio(voices, 128., midi)

    settings = preset(piano=False, soundfont='generaluser', reverb=.12, velocity='natural')
    rendered = render_raw(str(midi), settings)
    if rendered is None:
        raise RuntimeError('SoundFont rendering failed')
    audio, sr = rendered
    peak = float(np.abs(audio).max())
    if peak <= 0:
        raise RuntimeError('Silent render')
    write_wav(str(wav), audio * (.9 / peak), sr)

    with wave.open(str(wav)) as wf:
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype='<i2').astype(float) / 32768
        qa = {'duration_seconds': wf.getnframes() / wf.getframerate(),
              'sample_rate': wf.getframerate(), 'peak': float(np.abs(pcm).max()),
              'rms': float(np.sqrt(np.mean(pcm ** 2))),
              'near_full_scale_samples': int(np.sum(np.abs(pcm) >= .999))}
    if qa['rms'] <= .0001 or qa['near_full_scale_samples']:
        raise RuntimeError(f'Audio QA failed: {qa}')

    onset = [{round(e['on'], 7) for e in part} for part in voices]
    inner_sync = len(onset[1] & onset[2]) / max(len(onset[1] | onset[2]), 1)
    a = [(round(e['on'], 7), e['midi'], round(e['dur'], 7))
         for e in voices[0] if 0 <= e['on'] < 32]
    reprise = [(round(e['on'] - 64, 7), e['midi'], round(e['dur'], 7))
               for e in voices[0] if 64 <= e['on'] < 96]
    theme = spec.get('grammar', {}).get('theme_memory', {})
    manifest = {'command': command, 'seed': args.seed,
                'learned_form_trace': next((x.strip() for x in trace.split('·') if '曲式' in x), None),
                'learned_intra_phrase_motif': theme.get('intra_phrase'),
                'legacy_a_reprise_exact': a == reprise, 'inner_onset_jaccard': inner_sync,
                'hard_rule_violations': violations, 'voice_stats': stats(voices, 128.),
                'render': settings.to_dict(), 'audio_qa': qa,
                'sha256': {'musicxml': hashlib.sha256(xml.read_bytes()).hexdigest(),
                           'midi': hashlib.sha256(midi.read_bytes()).hexdigest(),
                           'wav': hashlib.sha256(wav.read_bytes()).hexdigest()}}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    (out / 'trace.txt').write_text(command + '\n' + trace)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
