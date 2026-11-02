#!/usr/bin/env python3
"""Generate one fixed-seed audition without replacing earlier listening files."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    from llm_compose import ComposeSession, compose_from_text, validate_score_spec
    from render_enhance import preset, render_to_wav
    from music21 import dynamics, instrument, tempo
    import numpy as np
    import pretty_midi
    import wave
    out = args.output_dir.resolve()
    if out.exists():
        parser.error('Output directory already exists; choose a new directory to preserve prior auditions.')
    command = f'/tempo 72 /compose-grammar G 16 downbeat seed={args.seed} memory=on'
    score, spec, trace = compose_from_text(ComposeSession(), command)
    issues = validate_score_spec(spec)
    if issues:
        raise RuntimeError(f'Score specification validation failed: {issues}')
    previous = json.loads((ROOT/'runs/theme_memory_v1/generated_spec.json').read_text())
    if spec['parts'] == previous['parts']:
        raise RuntimeError('Unexpected identical note events to the first audition')
    out.mkdir(parents=True)
    xml = out/'generated_theme_memory_piano.musicxml'
    score.write('musicxml', fp=str(xml))
    (out/'generated_spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    (out/'generated_trace.txt').write_text(command + '\n' + trace)
    for part in score.parts:
        for cls in (instrument.Instrument, tempo.MetronomeMark, dynamics.Dynamic):
            for el in list(part.recurse().getElementsByClass(cls)):
                el.activeSite.remove(el)
        part.insert(0, instrument.Piano())
        for n in part.recurse().notes:
            n.volume.velocity = 80
            n.volume.velocityIsRelative = False
    score.parts[0].insert(0, tempo.MetronomeMark(number=72))
    midi, wav = out/'generated_theme_memory_piano.mid', out/'generated_theme_memory_piano.wav'
    score.write('midi', fp=str(midi))
    pm = pretty_midi.PrettyMIDI(str(midi))
    for inst in pm.instruments:
        inst.program = 0
        for n in inst.notes:
            n.velocity = 80
    pm.write(str(midi))
    info = render_to_wav(str(midi), str(wav), preset(
        piano=True, soundfont='generaluser', reverb=.12, velocity='natural'))
    if not info['ok']:
        raise RuntimeError(info)
    with wave.open(str(wav)) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(float)/32768
        qa = {'sample_rate': w.getframerate(), 'channels': w.getnchannels(),
              'duration_seconds': w.getnframes()/w.getframerate(),
              'peak': float(np.max(np.abs(audio))),
              'rms': float(np.sqrt(np.mean(audio**2))),
              'near_full_scale_samples': int(np.sum(np.abs(audio) >= .999))}
    if qa['rms'] <= .0001 or qa['near_full_scale_samples']:
        raise RuntimeError(f'Audio QA failed: {qa}')
    manifest = {'command': command, 'different_from_take1': True,
                'score_spec_issues': issues, 'theme_memory': spec['grammar']['theme_memory'],
                'rendering': info, 'audio_qa': qa,
                'files_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (xml,midi,wav,out/'generated_spec.json')}}
    (out/'listening_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({'command':command,'audio_qa':qa,
                      'theme_relations':spec['grammar']['theme_memory']['relations']},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
