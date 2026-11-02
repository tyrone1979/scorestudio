#!/usr/bin/env python3
"""Paired v1 theme ablation and reproducible Bach/generated listening files."""
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
    parser.add_argument('--seeds', type=int, default=12)
    parser.add_argument('--audio', action='store_true')
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error('--seeds must be positive')
    from score_learning.grammar import script as G
    from score_learning.grammar.compose import compose
    from score_learning.leadsheet import script as L
    from score_learning.leadsheet.compose import compose as compose_lead
    out = ROOT / 'runs' / 'theme_memory_v1'
    out.mkdir(exist_ok=True)
    sc = G.load()
    rows = []
    for seed in range(args.seeds):
        for enabled in (False, True):
            r = compose(sc, key_sharps=1, total_bars=16, seed=f'theme-eval-{seed}',
                        layout='downbeat', theme_memory=enabled)
            rows.append({'style': 'chorale', 'seed': seed, 'enabled': enabled,
                         'violations': len(r['violations']), 'attempts': r['attempts'],
                         'planned': sum(x['source_phrase'] is not None for x in r['theme_memory']['relations']),
                         'realized': sum(x['status'] == 'realized' for x in r['theme_memory']['relations']),
                         **r['theme_memory']['evaluation']})
        print(f'chorale paired seed {seed}: complete', flush=True)
    for style, sub in [('folk', 'reel'), ('sonata', 'allegro'), ('jazz', 'swing')]:
        for seed in range(min(args.seeds, 3)):
            for enabled in (False, True):
                r = compose_lead(L.load(style), sub, total_bars=32, seed=f'theme-eval-{seed}',
                                 layout='downbeat', theme_memory=enabled)
                rows.append({'style': style, 'seed': seed, 'enabled': enabled,
                             'violations': len(r['violations']), 'attempts': r['attempts'],
                             'planned': sum(x['source_section'] is not None for x in r['theme_memory']['relations']),
                             'realized': sum(x['source_section'] is not None and
                                             x['status'] in ('realized', 'section_memory')
                                             for x in r['theme_memory']['relations']),
                             **r['theme_memory']['evaluation']})
            print(f'{style} paired seed {seed}: complete', flush=True)
    summary = []
    for style in sorted({r['style'] for r in rows}):
        grouped = {}
        for enabled in (False, True):
            rr = [r for r in rows if r['style'] == style and r['enabled'] == enabled]
            grouped[str(enabled).lower()] = {
                'n': len(rr), 'hard_violations': sum(r['violations'] for r in rr),
                **{metric: sum(r[metric] for r in rr) / len(rr) for metric in (
                    'recall_rate', 'exact_opening_recall_rate', 'whole_phrase_duplicate_rate')},
                'planned': sum(r['planned'] for r in rr), 'realized': sum(r['realized'] for r in rr),
            }
        summary.append({'style': style, **grouped})
    result = {'version': 1, 'seeds': args.seeds,
              'comparison': 'v1 off/on; legacy memory stays enabled in both arms',
              'warning': 'symbolic structural proxies, not perceptual memorability or listener preference',
              'rows': rows, 'summary': summary}
    (out / 'paired_evaluation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if args.audio:
        make_audio(out)


def make_audio(out):
    import copy
    import pretty_midi
    from music21 import corpus, dynamics, instrument, tempo
    from llm_compose import ComposeSession, compose_from_text
    from render_enhance import preset, render_to_wav
    from score_learning.learn_core import is_heldout
    # This score is in the MD5-heldout partition of the cached Bach corpus.
    bach = corpus.parse('bach/bwv318')
    assert is_heldout('bwv318')
    session = ComposeSession()
    command = '/tempo 72 /compose-grammar G 16 downbeat seed=theme-v1-demo memory=on'
    generated, spec, message = compose_from_text(session, command)
    (out / 'generated_spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    (out / 'generated_trace.txt').write_text(command + '\n' + message)
    sources = [('bach_bwv318_piano', bach), ('generated_theme_memory_piano', generated)]
    rendering = []
    for name, original in sources:
        original.write('musicxml', fp=str(out / (name + '.musicxml')))
        score = copy.deepcopy(original)
        for part in score.parts:
            for el in list(part.recurse().getElementsByClass(instrument.Instrument)):
                el.activeSite.remove(el)
            part.insert(0, instrument.Piano())
            for el in list(part.recurse().getElementsByClass(tempo.MetronomeMark)):
                el.activeSite.remove(el)
            for el in list(part.recurse().getElementsByClass(dynamics.Dynamic)):
                el.activeSite.remove(el)
            for n in part.recurse().notes:
                n.volume.velocity = 80
                n.volume.velocityIsRelative = False
        score.parts[0].insert(0, tempo.MetronomeMark(number=72))
        midi = out / (name + '.mid')
        score.write('midi', fp=str(midi))
        pm = pretty_midi.PrettyMIDI(str(midi))
        for inst in pm.instruments:
            inst.program = 0
            for n in inst.notes:
                n.velocity = 80
        pm.write(str(midi))
        settings = preset(piano=True, soundfont='generaluser', reverb=0.12, velocity='natural')
        info = render_to_wav(str(midi), str(out / (name + '.wav')), settings)
        if not info['ok']:
            raise RuntimeError(info)
        info['wav_sha256'] = hashlib.sha256(Path(info['wav']).read_bytes()).hexdigest()
        rendering.append(info)
        print(f"Rendered {name}: {info['duration']} seconds", flush=True)
    manifest = {'reference': 'J. S. Bach, BWV 318',
                'reference_source': 'music21 bundled corpus: bach/bwv318',
                'reference_heldout': True, 'generated_command': command,
                'comparison': 'same piano SoundFont, tempo=72, MIDI velocity=80, sample rate=44100; full pieces differ in length',
                'rendering': rendering}
    files = ['score_learning/theme_memory.py', 'score_learning/grammar/compose.py',
             'score_learning/leadsheet/compose.py', 'compose_kernel.py', 'llm_compose.py',
             'skills/composition/genre/packs/sacred/chorale/theme_memory.yaml']
    manifest['implementation_sha256'] = {
        f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files}
    manifest['artifacts_sha256'] = {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in out.iterdir()
        if f.suffix in ('.mid', '.musicxml') or f.name == 'generated_spec.json'}
    (out / 'listening_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
