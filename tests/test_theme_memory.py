"""Motif relation learning and constrained generation, without LLM/network/audio."""
import copy
import random

import pytest
from score_learning.theme_memory import (
    evaluate_phrases, informative, learn_policy, plan_intra_phrase, plan_references,
    signature, similarity,
)


def events(pitches, duration=1):
    return [(p, duration) for p in pitches]


def synthetic_piece(pid='train'):
    # Two phrases share a motif under transposition; a third is contrast.
    seqs = [[60, 62, 64, 67, 65, 64, 62, 60],
            [65, 67, 69, 72, 70, 69, 67, 65],
            [60, 59, 55, 50, 53, 57, 54, 48]]
    return {'id': pid, 'beats': [{'midi': [m]} for seq in seqs for m in seq],
            'phrases': [{'start': i * 8, 'end': i * 8 + 7} for i in range(3)]}


def test_transposition_and_tempo_invariance():
    a = events([60, 62, 64, 67])
    b = events([65, 67, 69, 72], 2)
    assert similarity(a, b) == 1
    assert signature(a) == signature(b)
    assert similarity(a, events([60, 59, 55, 50])) < .82
    assert not informative(events([60, 60, 60, 60]))


def test_edit_tolerant_but_not_identical():
    a = events([60, 62, 64, 67, 65, 64, 62, 60])
    b = events([60, 62, 63, 64, 67, 65, 64, 62, 60])
    assert .7 < similarity(a, b) < 1


def test_learning_stores_relations_not_corpus_melodies():
    import json
    p = learn_policy([synthetic_piece()])
    assert p['matched_phrases'] > 0
    assert p['transform_counts']['transpose'] > 0
    assert p['train_pieces'] == 1
    assert p == learn_policy([synthetic_piece()])
    assert 'midi' not in json.dumps(p) and 'beats' not in p
    assert learn_policy([])['enabled'] is False


def test_learning_discovers_within_phrase_location_span_and_density():
    def bar(pitches):
        return {'notes': [[float(i), 1., 0, p] for i, p in enumerate(pitches)]}
    piece={'id':'intra','bars':[
        bar([60,62,64]),bar([65,67,69,67]),
        bar([67,69,71]),bar([70,72,74,72]),
        bar([60,59,57]),bar([55,57,59]),bar([60,64,67]),bar([60,62,60]),
    ]}
    policy=learn_policy([piece])
    model=policy['intra_phrase']
    assert model['matched'] > 0
    assert any(k.startswith('2:0:2') for k in model['relation_counts'])
    planned=plan_intra_phrase(policy,random.Random(3))
    assert planned and planned['source_bar'] < planned['target_bar']
    assert planned['source_note_counts']
    assert planned['target_bars']
    assert planned['learned_occurrences'] == 1 + len(planned['target_bars'])
    assert planned['core_shape']
    assert planned['core_rhythm']
    assert planned['hierarchy'] == 'opening_theme'
    assert planned['source_bar'] == 0


def test_plan_deterministic_backward_only_and_disableable():
    policy = learn_policy([synthetic_piece()])
    a = plan_references(6, policy, random.Random(31))
    assert a == plan_references(6, policy, random.Random(31))
    assert any(r is not None for r in a)
    assert all(r is None or r < k for k, r in enumerate(a))
    policy['enabled'] = False
    assert plan_references(6, policy, random.Random(31)) == [None] * 6


def test_verifier_reads_notes_and_rejects_static_false_themes():
    ph = [events([60, 62, 64, 67]), events([65, 67, 69, 72])]
    assert evaluate_phrases(ph)['recall_rate'] == 1
    assert evaluate_phrases([events([60]*8), events([60]*8)])['recall_rate'] == 0


def test_final_spec_verifier_ignores_generation_claims():
    from score_learning.theme_memory import phrases_from_spec
    spec = {'theme_memory': {'status': 'realized'}, 'parts': [{'events': [
        [p, 'quarter'] for p in ['C4', 'D4', 'E4', 'G4', 'F4', 'G4', 'A4', 'C5']
    ]}]}
    phrases = phrases_from_spec(spec, [(0, 4), (4, 8)])
    assert evaluate_phrases(phrases)['exact_opening_recall_rate'] == 1
    spec['parts'][0]['events'][4:] = [[p, 'quarter'] for p in ['C4', 'B3', 'G3', 'D3']]
    assert evaluate_phrases(phrases_from_spec(spec, [(0, 4), (4, 8)]))['recall_rate'] == 0


def test_chorale_constrained_memory_and_determinism():
    from score_learning.grammar import script as S
    from score_learning.grammar.compose import compose
    sc = S.load()
    policy = learn_policy([synthetic_piece()])
    policy['recall_probability'] = 1
    policy['by_phase'] = {}
    sc['theme_memory'] = {'major': policy}
    a = compose(sc, total_bars=12, seed='theme-regression', layout='downbeat')
    b = compose(sc, total_bars=12, seed='theme-regression', layout='downbeat')
    assert a['spec']['parts'] == b['spec']['parts']
    assert not a['violations']
    assert any(r['status'] == 'realized' for r in a['theme_memory']['relations'])
    assert all(r['status'] in ('new', 'realized', 'relaxed') for r in a['theme_memory']['relations'])
    off = compose(sc, total_bars=12, seed='theme-regression', layout='downbeat', theme_memory=False)
    assert not off['violations']
    assert not any(r['source_phrase'] for r in off['theme_memory']['relations'])


def test_leadsheet_theme_recall_and_legal_score():
    from score_learning.leadsheet import script as S
    from score_learning.leadsheet.compose import compose
    sc = copy.deepcopy(S.load('folk'))
    policy = learn_policy([synthetic_piece()])
    policy['recall_probability'] = 1
    policy['by_phase'] = {}
    policy['duration_median_ql'] = 4
    sc['subs']['reel']['theme_memory'] = policy
    sc['subs']['reel']['section_memory_enabled'] = False
    a = compose(sc, 'reel', total_bars=24, seed='theme-regression', layout='downbeat')
    assert not a['violations']
    assert any(r['status'] == 'realized' for r in a['theme_memory']['relations'])
    b = compose(sc, 'reel', total_bars=24, seed='theme-regression', layout='downbeat')
    assert a['spec']['parts'] == b['spec']['parts']


def test_unrealizable_chorale_theme_is_explicitly_reported(monkeypatch):
    from score_learning.grammar import script as S
    import score_learning.grammar.compose as C
    sc = S.load()
    policy = learn_policy([synthetic_piece()])
    policy.update(recall_probability=1, by_phase={})
    sc['theme_memory'] = {'major': policy}
    original = C.compose_phrase_candidates
    def no_constrained_candidates(*args, **kwargs):
        return [] if kwargs.get('theme') is not None else original(*args, **kwargs)
    monkeypatch.setattr(C, 'compose_phrase_candidates', no_constrained_candidates)
    result = C.compose(sc, total_bars=12, seed='theme-relax', layout='downbeat')
    assert not result['violations']
    assert any(r['status'] == 'relaxed' and r['reason'] for r in result['theme_memory']['relations'])


def test_compose_grammar_command_can_disable_new_memory():
    from llm_compose import ComposeSession, compose_from_text
    _score, spec, _message = compose_from_text(
        ComposeSession(), '/compose-grammar G 8 downbeat seed=theme-command memory=off')
    assert spec['grammar']['theme_memory']['enabled'] is False


def test_background_policy_files_respect_heldout_split():
    import hashlib
    import json
    from pathlib import Path
    from score_learning.learn_core import is_heldout
    from score_learning.grammar import script as S
    root = Path(__file__).resolve().parents[1]
    cache = root / 'runs/grammar_cache/bach_chorales.json'
    if not cache.exists():
        pytest.skip('Corpus cache required only for the provenance integration check')
    pieces = json.loads(cache.read_text())['pieces']
    for mode, policy in S.load().get('theme_memory', {}).items():
        ids = sorted(str(p['id']) for p in pieces if p['mode'] == mode and not is_heldout(p['id']))
        assert policy['train_ids_sha256'] == hashlib.sha256('\n'.join(ids).encode()).hexdigest()
