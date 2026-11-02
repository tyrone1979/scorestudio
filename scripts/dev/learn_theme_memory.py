#!/usr/bin/env python3
"""Learn additive theme-memory policies from existing cached corpus features."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import yaml
from score_learning.learn_core import is_heldout
from score_learning.theme_memory import learn_policy
from score_learning.grammar import script as G
from score_learning.leadsheet import script as L
from score_learning.leadsheet.learn import sub_splits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--styles', nargs='+', default=['chorale'] + L.available())
    args = parser.parse_args()
    report = {'version': 5, 'styles': {}}
    for style in args.styles:
        cache = ROOT / 'runs' / 'grammar_cache' / ('bach_chorales.json' if style == 'chorale' else style + '.json')
        data = json.loads(cache.read_text())
        pieces = data['pieces']
        if style == 'chorale':
            train = [p for p in pieces if not is_heldout(p['id'])]
            policies = {mode: learn_policy([p for p in train if p['mode'] == mode]) for mode in ('major', 'minor')}
            payload = {'theme_memory': policies}
            dest = Path(G.DEFAULT_YAML).with_name('theme_memory.yaml')
        else:
            policies = {}
            available = L.load(style)['subs']
            for sub, (_meter, train, _heldout) in sub_splits(pieces, style).items():
                if sub in available:
                    policies[sub] = learn_policy(train)
                    print(f'{style}/{sub}: {policies[sub]["matched_phrases"]}/{policies[sub]["eligible_phrases"]} matched', flush=True)
            payload = {'subs': policies}
            dest = Path(L.paths(style)[0]).with_name('theme_memory.yaml')
        payload['provenance'] = {'cache': str(cache.relative_to(ROOT)),
                                 'cache_sha256': hashlib.sha256(cache.read_bytes()).hexdigest(),
                                 'split': 'exclude is_heldout(id), MD5 modulo 10 == 0'}
        # Additive sidecars avoid rewriting the large historical grammar files.
        dest.write_text('# Learned aggregate motif relations; no corpus melody fragments.\n' +
                        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
        report['styles'][style] = {'policy_path': str(dest.relative_to(ROOT)), **payload}
        print(f'{style}: {dest.relative_to(ROOT)}', flush=True)
    out = ROOT / 'runs' / 'theme_memory_v2'
    out.mkdir(exist_ok=True)
    (out / 'learning_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
