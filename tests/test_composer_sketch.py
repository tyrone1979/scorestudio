"""Composer sketch: closed vocabulary, form override, quartet roles, one realization."""
import random
from types import SimpleNamespace

from score_learning.composer_sketch import (
    LISTENING_JUDGE, assess_realization, deterministic_sketch, jury_pass, revise_sketch,
    validate_sketch,
)
from score_learning.leadsheet.compose import _Mel, accompaniment_quartet, compose
from score_learning.leadsheet import script as lscript


def _script():
    return lscript.load('strings')


def test_validate_rejects_unknown_transform():
    sc = _script()
    sketch = deterministic_sketch(sc, 'allegro', 'major', 16, 1, random.Random(1))
    sketch['sections'][1]['transform'] = 'retrograde-inversion'
    ok, err = validate_sketch(sketch, sc, 'allegro', 'major', 16)
    assert ok is None
    assert '变形' in err


def test_deterministic_sketch_is_closed():
    sc = _script()
    sketch = deterministic_sketch(sc, 'allegro', 'major', 32, 1, random.Random(2))
    ok, err = validate_sketch(sketch, sc, 'allegro', 'major', 32)
    assert err is None
    quote = [s for s in ok['sections'] if s['role'] == 'quote']
    assert quote and quote[0]['transform'] == 'original'
    assert ok['sections'][-1]['role'] == 'coda'
    assert ok['voices']['violin1'] == 'melody'


def test_revise_adds_full_return():
    sc = _script()
    sketch = deterministic_sketch(sc, 'allegro', 'major', 16, 1, random.Random(3))
    sketch['sections'][-1] = {'label': 'B', 'role': 'contrast', 'bars': 8,
                              'ref': None, 'transform': 'original'}
    out = revise_sketch(sketch, {'has_return': False, 'return_similarity': 0}, random.Random(0))
    assert out['sections'][-1]['role'] == 'quote'
    assert out['sections'][-1]['transform'] == 'original'
    assert out['sections'][-1]['ref'] == 'A'


def test_quartet_duties_do_not_share_onsets():
    g = SimpleNamespace(meter='4/4', bar_ql=4.0, beat_ql=1.0, tonic_pc=0, mode='major')
    slots = [{'t': 0.0, 'tok': '0:M'}, {'t': 4.0, 'tok': '7:M'}]
    bass = [48, 43]
    voic = [[60, 64], [55, 59]]
    mel = _Mel([(0.0, 4.0, 72), (4.0, 4.0, 71)])
    vn2, va, vc = accompaniment_quartet(
        g, slots, bass, 2, mel, 8.0, voic=voic,
        duties={'violin1': 'melody', 'violin2': 'answer', 'viola': 'sustain', 'cello': 'bass'})

    def onsets(bars):
        out = []
        for bi, events in enumerate(bars):
            for on, _d, v in events:
                if v:
                    out.append(round(bi * 4 + on, 3))
        return set(out)

    a, s = onsets(vn2), onsets(va)
    assert a and s
    assert len(a & s) / len(a | s) < 0.5
    sounded = [v[0] for bar in vc for _on, _d, v in bar if v]
    if len(sounded) > 2:
        repeats = sum(x == y for x, y in zip(sounded, sounded[1:])) / (len(sounded) - 1)
        assert repeats < 0.8


def test_conservatory_jury_line():
    items = ('theme', 'breath', 'arc', 'contrast', 'layers', 'ending')
    ok, veto = jury_pass({k: 4 for k in items})
    assert ok and veto == []
    ok, veto = jury_pass({'theme': 2, 'breath': 4, 'arc': 4, 'contrast': 4,
                          'layers': 4, 'ending': 4})
    assert not ok and veto == ['theme']
    ok, _veto = jury_pass({'theme': 3, 'breath': 3, 'arc': 3, 'contrast': 3,
                           'layers': 4, 'ending': 4})
    assert not ok
    ok, veto = jury_pass({'theme': 3, 'breath': 3, 'arc': 4, 'contrast': 4,
                          'layers': 4, 'ending': 3})
    assert ok and veto == []


def test_failed_jury_rewrites_until_it_passes():
    sc = _script()
    sketch = deterministic_sketch(sc, 'allegro', 'major', 16, 1, random.Random(5))
    seen = {'n': 0}

    def judge(_facts):
        seen['n'] += 1
        scores = {k: 4 for k in ('theme', 'breath', 'arc', 'contrast', 'layers', 'ending')}
        if seen['n'] == 1:
            scores['contrast'] = 2
            return {'scores': scores, 'comment': '中段没有离开'}
        return {'scores': scores, 'comment': '中段已经离开'}

    token = LISTENING_JUDGE.set(judge)
    try:
        res = compose(sc, 'allegro', 'major', 1, 16, seed='composer-loop-test',
                      layout='downbeat', composer_sketch=sketch, max_tries=40)
    finally:
        LISTENING_JUDGE.reset(token)
    rounds = res['spec']['composer']['rounds']
    assert seen['n'] >= 2
    assert res['spec']['composer']['ok']
    assert rounds[0]['sketch']['sections'] != rounds[-1]['sketch']['sections']
    assert rounds[-1]['report']['jury']['pass']


def test_compose_with_sketch_returns_and_checks():
    sc = _script()
    sketch = deterministic_sketch(sc, 'allegro', 'major', 16, 1, random.Random(4))
    res = compose(sc, 'allegro', 'major', 1, 16, seed='composer-sketch-test',
                  layout='downbeat', composer_sketch=sketch, max_tries=8)
    assert res['violations'] == []
    comp = res['spec']['composer']
    assert comp['rounds']
    assert comp['rounds'][-1]['report']['has_return']
    report = assess_realization(res['spec'], res['units'], comp['rounds'][-1]['sketch'], 4.0)
    assert report['return_similarity'] >= 0.82
    assert report['onset_jaccard'] < 0.5
    assert res['plan']['source'] == 'composer_sketch'
