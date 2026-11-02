#!/usr/bin/env python3
"""固定种子的弦乐四重奏作曲循环试听，并记录主题回归、起音耦合和硬规则。"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT = ROOT / 'runs' / 'composer_quartet_v1'
COMMAND = ('/key G /tempo 96 /compose-grammar strings allegro 32 downbeat '
           'seed=composer-quartet-v1 composer=on')


def main():
    """试听文件走确定性草图，保证同一个 seed 能重做。
    交互命令 composer=on 在有 API Key 时仍由模型出草图。"""
    import random
    from llm_compose import spec_to_music21, validate_score_spec
    from score_learning.composer_sketch import deterministic_sketch
    from score_learning.leadsheet import script as lscript
    from score_learning.leadsheet.compose import compose
    OUT.mkdir(parents=True, exist_ok=True)
    sc = lscript.load('strings')
    sketch = deterministic_sketch(
        sc, 'allegro', 'major', 32, 1, random.Random('composer-quartet-v1'))
    res = compose(sc, 'allegro', 'major', 1, 32, seed='composer-quartet-v1',
                  layout='downbeat', title='弦乐四重奏（作曲草图）', tempo=96,
                  composer_sketch=sketch)
    spec = res['spec']
    plan = res['plan']
    spec['grammar'] = {
        'form': plan.get('form'), 'form_rule': plan.get('form_rule'),
        'seed': res.get('seed_used'), 'units': res['units'],
        'layout': plan.get('layout'),
    }
    _score = spec_to_music21(spec)
    trace = '试听使用确定性草图，不调用模型。交互命令 composer=on 在有 API Key 时由模型出草图。\n'
    issues = validate_score_spec(spec)
    composer = spec.get('composer') or {}
    report = (composer.get('rounds') or [{}])[-1].get('report') or {}
    summary = {
        'command': COMMAND,
        'sketch_source': 'deterministic',
        'fallback': composer.get('fallback'),
        'enabled': bool(composer.get('enabled')),
        'ok': composer.get('ok'),
        'rounds': len(composer.get('rounds') or []),
        'return_similarity': report.get('return_similarity'),
        'onset_jaccard': report.get('onset_jaccard'),
        'vn2_repeat': report.get('vn2_repeat'),
        'cello_repeat': report.get('cello_repeat'),
        'grammar_violations': res['violations'],
        'score_spec_notes': issues,
        'form': (spec.get('grammar') or {}).get('form'),
        'form_rule': (spec.get('grammar') or {}).get('form_rule'),
    }
    (OUT / 'comparison.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (OUT / 'generated_spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    (OUT / 'generated_trace.txt').write_text(COMMAND + '\n' + trace + '\n')
    _score.write('musicxml', fp=str(OUT / 'generated_strings.musicxml'))
    _score.write('midi', fp=str(OUT / 'generated_strings.mid'))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
