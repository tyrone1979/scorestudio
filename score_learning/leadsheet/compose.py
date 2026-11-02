# -*- coding: utf-8 -*-
"""按学到的旋律 + 和弦语法作曲（民间舞曲 / 爵士 / 流行 / 牧歌），确定性、零硬规则违例。

流程（每一步都只读 grammar.yaml 里的规则）：

1. 曲式：按学到的字母曲式（AB / AABA …）或人工段落标注的 form_plan（A1A2B1A3，带角色与
   引用）排 8 小节段落；民间舞曲按"段落反复率"把 AB 展开成 AABB；按学到的比例决定弱起。
   段落记忆：同标签原样再现；"引用"整段照抄来源段；同族 / 有引用的其他角色（递进、尾声）
   沿用来源段前 4 小节、后 4 小节重写（变奏）；新段落里的小节按学到的"跨段动机回忆"
   概率照搬前面段落某小节的节奏与音高（原样或模进）。
2. 和声：逐段按和声节奏（每小节在第几拍换和弦）排和弦位置，在 H 规则（前两个和弦 +
   位置的转移概率）上做带约束的前向滤波-后向采样：首和弦取学到的开头分布，段末两和弦
   取 C 规则终止公式，第 4 小节偏向学到的半终止落点，所有转移必须在语料出现过。
3. 旋律：每小节节奏取 R 模板（即兴风格取按拍节奏单元链），按学到的概率照抄前面
   第 1/2/4 小节的节奏与音高；音高用动态规划：强弱位置的和弦音/经过音/半音比例、
   音程分布、大跳回补、非和弦音级进、乐句轮廓（M 模板），末音主音。
4. 伴奏：钢琴左右手按风格织体（舞曲"嘭-嚓"、爵士走动低音 + 三七和弦、流行柱式、
   牧歌持续和弦），低音按动态规划避开与旋律的平行五八度。
   古典钢琴（奏鸣曲 / 肖邦）右手即旋律、左手按拍号写阿尔贝蒂 / 分解和弦 / 低音-和弦-和弦
   音型；弦乐四重奏第二小提琴 + 中提琴双音配位、大提琴低音，各声部两两避开平行五八度。
"""
from __future__ import annotations

import itertools
import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from score_learning.grammar.theory import (QUALITIES, chord_tone_names,
                                           name_with_octave, scale_names, tonic_from_sharps,
                                           tonic_letter_pc)

from .analyze import STYLES, strength
from .check import check_piece, match_voices, parallel_motion, split_streams, stream_parallels
from .learn import UNIT, model_from_rules, note_class, pos_label, rhythm_class, tok_chord
from score_learning.theme_memory import (evaluate_phrases, plan_intra_phrase,
                                         plan_references, phrases_from_spec, similarity)
from score_learning.composer_sketch import assess_realization, cadence_direction, next_sketch
from narrative import Motif, transform_motif

NEG = -1e9
HEAD_BARS = UNIT // 2    # 变奏段沿用来源段开头的小节数（前乐句），后乐句重写
CONTOUR_SIGMA = 6.0      # 旋律偏离乐句轮廓目标音高的容忍度（半音）
DUR_NAMES = [(4.0, 'whole'), (3.0, 'dotted_half'), (2.0, 'half'), (1.5, 'dotted_quarter'),
             (1.0, 'quarter'), (0.75, 'dotted_eighth'), (0.5, 'eighth'), (0.25, '16th'),
             (0.125, '32nd')]
# 乐器：(谱面名, 最低, 最高, 舒适中心)
INSTRUMENTS = {
    'violin': ('Violin', 55, 91, 74), 'flute': ('Flute', 60, 93, 77),
    'trumpet': ('Trumpet', 55, 82, 69), 'clarinet': ('Clarinet', 52, 89, 70),
    'voice': ('Voice', 55, 79, 67), 'soprano': ('Soprano', 60, 81, 70),
    'piano': ('Piano RH', 60, 88, 74),
}
# 织体 → 伴奏声部：(谱面名, MIDI 音色, 谱号)
TEXTURE_ACC = {
    'melody_piano': [('Piano RH', 0, 'treble'), ('Piano LH', 0, 'bass')],
    'piano': [('Piano LH', 0, 'bass')],
    'quartet': [('Violin II', 40, 'treble'), ('Viola', 41, 'alto'), ('Violoncello', 42, 'bass')],
    'orchestra': [('Violin II', 40, 'treble'), ('Viola', 41, 'alto'), ('Violoncello', 42, 'bass')],
}
# 古典双管编制的管乐 + 定音鼓（总谱次序在弦乐之上）
ORCH_WINDS = [('Flute', 73, 'treble'), ('Oboe', 68, 'treble'), ('Horn', 60, 'treble'),
              ('Bassoon', 70, 'bass'), ('Timpani', 47, 'bass')]
FLUTE_RANGE, OBOE_RANGE, HORN_RANGE = (60, 93), (58, 91), (53, 72)
VN2_LOW, VA_LOW = 55, 48
_SUFFIX = {'M': '', 'm': 'm', 'd': 'dim', 'A': 'aug', '7': '7', 'm7': 'm7', 'M7': 'maj7',
           'h7': 'm7b5', 'o7': 'dim7'}
_DEFAULT_FORM = {1: 'A', 2: 'AB', 3: 'ABA', 4: 'ABAB'}


class _Dead(Exception):
    pass


def split_ql(d: float) -> List[str]:
    """时值 → 可记谱时值名序列（贪心）。"""
    out, d = [], round(d * 8) / 8
    while d > 1e-6:
        for q, nm in DUR_NAMES:
            if q <= d + 1e-6:
                out.append(nm)
                d = round(d - q, 4)
                break
        else:
            break
    return out


def _pick(rng: random.Random, items: Sequence[Tuple[Any, float]]):
    tot = sum(max(w, 0.0) for _x, w in items)
    if tot <= 0:
        return items[0][0]
    r = rng.random() * tot
    for x, w in items:
        r -= max(w, 0.0)
        if r <= 0:
            return x
    return items[-1][0]


def _gumbel(rng: random.Random) -> float:
    return -math.log(-math.log(rng.random() or 1e-12))


def is_tonic(tok: str) -> bool:
    r, q = tok_chord(tok)
    return r == 0 and q in ('M', 'm', 'M7', 'm7')


def _lse(a: np.ndarray, axis: int) -> np.ndarray:
    m = np.max(a, axis=axis, keepdims=True)
    m = np.where(m < NEG / 2, 0.0, m)
    with np.errstate(divide='ignore'):
        s = np.log(np.sum(np.exp(a - m), axis=axis, keepdims=True))
    return np.maximum(s + m, NEG).squeeze(axis)


def _sample_log(rng: random.Random, lp: np.ndarray, tau: float) -> int:
    ok = lp > NEG / 2
    if not ok.any():
        raise _Dead('无可行状态')
    if tau <= 1e-6:
        return int(np.argmax(lp))
    x = np.where(ok, (lp - lp[ok].max()) / tau, -np.inf)
    p = np.exp(x)
    p /= p.sum()
    r, acc = rng.random(), 0.0
    for i in np.flatnonzero(ok):
        acc += p[i]
        if r <= acc:
            return int(i)
    return int(np.flatnonzero(ok)[-1])


# ======================================================================== 语法封装
class SubGrammar:
    def __init__(self, script: Dict[str, Any], sub: str, mode: str):
        if sub not in script['subs']:
            raise ValueError(f'脚本里没有子风格 {sub}（可用：{"、".join(script["subs"])}）')
        s = script['subs'][sub]
        if mode not in s['vocab']:
            raise ValueError(f'{sub} 没有 {mode} 调式的规则（语料不足）')
        self.style, self.sub, self.mode, self.s = script['grammar'], sub, mode, s
        self.melody_instrument = script.get('melody_instrument', 'violin')
        self.texture = s.get('texture', 'melody_piano')
        self.vocab = sorted(s['vocab'][mode])
        self.roman = s['vocab'][mode]
        self.idx = {t: i for i, t in enumerate(self.vocab)}
        self.V = len(self.vocab)
        self.model = model_from_rules(s['harmony'][mode], self.vocab, s.get('harmony_floor', 0.0))
        self.bar_ql, self.beat_ql = float(s['bar_ql']), float(s['beat_ql'])
        self.beats = int(round(self.bar_ql / self.beat_ql))
        self.meter = s['meter']
        l1 = self.model.t['L1']
        self.att = np.zeros((self.V, self.V), bool)
        for i, a in enumerate(self.vocab):
            cnt = l1.get((a,))
            if cnt:
                for j, b in enumerate(self.vocab):
                    self.att[i, j] = cnt.get(b, 0) > 0
        self._bg: Dict[Tuple, np.ndarray] = {}
        self.rule_of: Dict[Tuple, str] = {}
        for lv, rules in s['harmony'][mode].items():
            for r in rules:
                w = r['when']
                key = {'L3': (w.get('p2'), w.get('p1'), w.get('pos')),
                       'L2': (w.get('p1'), w.get('pos')), 'L1': (w.get('p1'),),
                       'L0': (w.get('pos'),)}[lv]
                self.rule_of[(lv, key)] = r['id']
        mel = s['melody']
        self.cls_lp = {st: {c: math.log(max(p, 1e-3)) for c, p, _n in d}
                       for st, d in mel['class_by_strength'].items()}
        self.iv_lp = {int(iv): math.log(max(p, 1e-4)) for iv, p, _n in mel['intervals']}
        cs = dict((k, p) for k, p, _n in mel['class_by_strength'].get('S', []))
        self.strict_r01 = cs.get('CT', 0) >= 0.7
        self.strict_r02 = mel['nct_step_either'] >= 0.85
        self.max_leap = int(mel['max_leap'])
        self.forbidden = set(int(x) for x in mel['forbidden_leaps'])
        self.p_rec = float(mel['leap_recovery_prob'])
        rh = s['rhythm']
        self.cell_ctx: Dict[Tuple[str, str], List] = {
            (r['prev'], r['beat']): r['then'] for r in rh['cells']['by_prev']}

    def attested(self, a: str, b: str) -> bool:
        ia, ib = self.idx.get(a), self.idx.get(b)
        return ia is not None and ib is not None and bool(self.att[ia, ib])

    def bigram(self, p1: str, pos: str) -> np.ndarray:
        key = (p1, pos)
        if key not in self._bg:
            self._bg[key] = np.array([math.log(max(self.model.prob('?', p1, pos, c), 1e-12))
                                      for c in self.vocab])
        return self._bg[key]

    def trigram(self, p2: str, p1: str, pos: str, c: str) -> float:
        return math.log(max(self.model.prob(p2, p1, pos, c), 1e-12))

    def rule_id(self, p2, p1, pos) -> str:
        for lv, key in (('L3', (p2, p1, pos)), ('L2', (p1, pos)), ('L1', (p1,)), ('L0', (pos,))):
            rid = self.rule_of.get((lv, key))
            if rid:
                return rid
        return '-'

    def chord_symbol(self, tok: str, tonic: str) -> str:
        r, q = tok_chord(tok)
        nm = chord_tone_names((r, q, 0), tonic, self.mode)[r]
        return nm + _SUFFIX.get(q, q)


# ======================================================================== 曲式
# 段落角色（来自人工段落标注的关系类型，见 score_learning/relation/）
ROLE_ZH = {'introduce': '引入', 'sequence': '递进变体', 'quote': '引用',
           'contrast': '对比', 'coda': '尾声'}


def _relation_form(g: 'SubGrammar', n_units: int, rng: random.Random,
                   total_bars: int = 0) -> Optional[Dict[str, Any]]:
    """若规则脚本带有 `form.form_plan`（人工段落关系编译而来），按它规划曲式。

    与下面的 `templates` 路径的区别：form_plan 里每段带**角色**（引入/递进/引用/尾声）、
    **真实小节数**与**引用来源**，因此 `letters` 不再是抽象的 'AABA'，
    而是 'A1A2B1A3' 这样带编号的段落序列。
    """
    plan = (g.s.get('form') or {}).get('form_plan')
    if not plan:
        return None
    # 注意：段数键在 plan['policies'] 之下，不是 plan 顶层
    pol = (plan.get('policies') or {}).get(str(n_units)) or \
          (plan.get('policies') or {}).get(n_units)
    if not pol:
        return None
    # p>0 的模式里挑一个（_pick 接受 [(item, p)] ）
    pick = _pick(rng, [(it, float(it.get('p') or 0)) for it in pol
                       if (it.get('p') or 0) > 0])
    if not pick:
        return None
    segs = pick.get('segments') or []
    if not segs:
        return None
    # 生成器按 UNIT 小节一段写谱；人工标注的段长（8/10/13…）只作参考保留在 bars_annotated。
    segs = [dict(s, bars=UNIT, bars_annotated=s.get('bars')) for s in segs]
    letters = ''.join(s['label'] for s in segs)
    detail = ' → '.join(
        f"{s['label']}({ROLE_ZH.get(s.get('role'), s.get('role'))}"
        f"{'←' + s['ref'] if s.get('ref') else ''})" for s in segs)
    rel = pick.get('relations') or []
    return {
        'form': letters,
        'form_rule': (f'人工段落标注的 {len(segs)} 段曲式（{detail}）'
                      + (f'；段间关系 {len(rel)} 条' if rel else '')),
        'units': len(segs),
        'bars': len(segs) * UNIT,
        'segments': segs,
        'sections': [_section(s['label'], s.get('family'), s.get('role'), s.get('ref'))
                     for s in segs],
        'source': 'form_plan',
    }


def _section(label: str, family: Optional[str] = None, role: Optional[str] = None,
             ref: Optional[str] = None) -> Dict[str, Any]:
    fam = family or ''.join(c for c in label if not c.isdigit()) or label
    return {'label': label, 'family': fam, 'role': role or 'introduce', 'ref': ref}


def _letter_sections(letters: str) -> List[Dict[str, Any]]:
    """字母曲式（AABA）→ 逐段列表：首次出现为引入，再次出现为原样再现。"""
    seen, out = set(), []
    for L in letters:
        out.append(_section(L, L, 'quote' if L in seen else 'introduce', L if L in seen else None))
        seen.add(L)
    return out


def _section_must_close(label: str, mem: List[Dict[str, Any]], sections: List[Dict[str, Any]],
                        last_label: str, sketch: Optional[Dict[str, Any]]) -> bool:
    """末段要落到主音。草图若把整段引用放在最后，源段生成时就按终止段来写。"""
    if label == last_label and (not sketch or mem[-1]['kind'] != 'quote'):
        return True
    if not sketch:
        return False
    return any(i == len(sections) - 1 and m.get('kind') == 'quote' and m.get('src') == label
               for i, m in enumerate(mem))


def _sketch_memory(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """草图段落：完整引用走照抄，其他变形走算子，陈述走新材料。"""
    out: List[Dict[str, Any]] = []
    seen: Dict[str, Dict[str, Any]] = {}
    for sec in sections:
        label, ref = sec['label'], sec.get('ref')
        transform = sec.get('transform') or 'original'
        if ref in seen and sec.get('role') == 'quote' and transform == 'original':
            # 只带回主题前四小节。整段再放一遍，听审里会变成“没有离开”。
            src = seen[ref]
            m = {'kind': 'variant', 'src': ref, 'head': src['head'], 'tail': label,
                 'transform': 'original'}
        elif ref in seen and transform != 'original':
            m = {'kind': 'transform', 'src': ref, 'head': label, 'tail': label,
                 'transform': transform}
        elif label in seen and transform == 'original':
            m = dict(seen[label], kind='repeat', src=label, transform='original')
        else:
            m = {'kind': 'new', 'src': None, 'head': label, 'tail': label,
                 'transform': 'original'}
        if m['kind'] != 'repeat':
            seen[label] = m
        out.append(m)
    return out


def _memory_plan(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """逐段决定"记忆"方式：
    repeat  同标签再现（整段照抄）；
    quote   角色为引用、标签不同（整段照抄来源段）；
    variant 有来源（ref，或同族先出现的段）但角色不是引用：沿用来源段前半，后半重写；
    new     全新材料。
    head / tail 记下本段开头 / 结尾实际出自哪个新写的段，供段间衔接检查用。"""
    out: List[Dict[str, Any]] = []
    seen: Dict[str, Dict[str, Any]] = {}
    fam_first: Dict[str, str] = {}
    for sec in sections:
        L, fam = sec['label'], sec['family']
        if L in seen:
            m = dict(seen[L], kind='repeat', src=L)
        else:
            src = sec.get('ref') if sec.get('ref') in seen else fam_first.get(fam)
            if src is None:
                m = {'kind': 'new', 'src': None, 'head': L, 'tail': L}
            elif sec['role'] == 'quote':
                m = {'kind': 'quote', 'src': src, 'head': seen[src]['head'],
                     'tail': seen[src]['tail']}
            else:
                m = {'kind': 'variant', 'src': src, 'head': seen[src]['head'], 'tail': L}
            seen[L] = m
            fam_first.setdefault(fam, L)
        out.append(m)
    return out


def _sketch_form(g: SubGrammar, rng: random.Random, layout: str,
                 sketch: Dict[str, Any]) -> Dict[str, Any]:
    """外部作曲草图直接成为段落表，不再从字母曲式里抽样。"""
    sections = [dict(s) for s in sketch['sections']]
    detail = ' → '.join(
        f"{s['label']}({ROLE_ZH.get(s['role'], s['role'])}"
        f"/{s['transform']}{'←' + s['ref'] if s.get('ref') else ''})" for s in sections)
    pk = g.s['rhythm']['pickup']
    if layout == 'auto':
        pickup = bool(pk['patterns']) and rng.random() < pk['prob']
    else:
        pickup = layout == 'pickup' and bool(pk['patterns'])
    pick_pat = None
    if pickup:
        pick_pat = _pick(rng, [((float(ql), pat), p) for ql, pat, p, _n in pk['patterns']
                               if split_ql(float(ql)) and pat])
    return {'form': ''.join(s['label'] for s in sections),
            'form_rule': f'作曲草图（{detail}）',
            'units': len(sections), 'bars': len(sections) * UNIT,
            'sections': sections, 'source': 'composer_sketch',
            'composer_sketch': sketch,
            'layout': 'pickup' if pick_pat else 'downbeat', 'pickup': pick_pat}


def plan_form(g: SubGrammar, rng: random.Random, total_bars: int, layout: str,
              sketch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if sketch:
        return _sketch_form(g, rng, layout, sketch)
    #段数上限放宽到 12：人工标注里有 9-12 段的长曲式（Weimar 的 postbop 常见），
    # 原先 min(4, …) 会把它们一律截成 4 段。
    n_units = max(1, min(12, int(round(total_bars / UNIT))))
    form = g.s['form']

    # 优先用人工段落关系编译出的 form_plan（含角色/长度/引用链）
    rel = _relation_form(g, n_units, rng, total_bars)
    if rel is not None:
        pk = g.s['rhythm']['pickup']
        if layout == 'auto':
            pickup = bool(pk['patterns']) and rng.random() < pk['prob']
        else:
            pickup = layout == 'pickup' and bool(pk['patterns'])
        pick_pat = None
        if pickup:
            pick_pat = _pick(rng, [((float(ql), pat), p) for ql, pat, p, _n in pk['patterns']
                                   if split_ql(float(ql)) and pat])
        if layout == 'pickup' and not pk['patterns']:
            rel['form_rule'] += '；语料里没有弱起开头，按强拍起写'
        rel.update({'layout': 'pickup' if pick_pat else 'downbeat', 'pickup': pick_pat})
        return rel

    cands = [(t, p) for t, p, _n in form['templates'] if len(t) == n_units]
    rep = float(form.get('section_repeat_prob') or 0.0)
    if rep >= 0.2 and n_units % 2 == 0:
        for t, p, _n in form['templates']:
            if len(t) == n_units // 2:
                cands.append((''.join(c * 2 for c in t), p * rep * 2))
    opening = (form.get('openings') or {}).get(n_units) or \
        (form.get('openings') or {}).get(str(n_units))
    if cands and (sum(p for _t, p in cands) >= 0.15 or not opening):
        letters = _pick(rng, cands)
        rule = f'学到的曲式 {letters}' + ('（段落反复展开）' if len(set(letters)) * 2 == len(letters)
                                          and letters[::2] == letters[1::2] else '')
    elif opening:
        letters = _pick(rng, [(t, p) for t, p, _n in opening])
        rule = f'学到的长曲前 {n_units} 段曲式 {letters}'
    else:
        letters = _DEFAULT_FORM[n_units]
        rule = f'语料没有 {n_units} 段的曲式，用默认 {letters}'
    pk = g.s['rhythm']['pickup']
    if layout == 'auto':
        pickup = bool(pk['patterns']) and rng.random() < pk['prob']
    else:
        pickup = layout == 'pickup' and bool(pk['patterns'])
    pick_pat = None
    if pickup:
        pick_pat = _pick(rng, [((float(ql), pat), p) for ql, pat, p, _n in pk['patterns']
                               if split_ql(float(ql)) and pat])
    if layout == 'pickup' and not pk['patterns']:
        rule += '；语料里没有弱起开头，按强拍起写'
    return {'form': letters, 'form_rule': rule, 'units': n_units, 'bars': n_units * UNIT,
            'sections': _letter_sections(letters),
            'layout': 'pickup' if pick_pat else 'downbeat', 'pickup': pick_pat}


# ======================================================================== 和声
def chord_runs(slots: List[Dict], carry: Tuple[Optional[str], int] = (None, 0)) -> int:
    """最长的"同一和弦占满整小节"连续小节数（carry = 上一段末尾的和弦与已连续小节数）。"""
    per_bar: Dict[int, List[str]] = {}
    for s in slots:
        per_bar.setdefault(s['bar'], []).append(s['tok'])
    prev, run = carry
    best = run
    for bar in sorted(per_bar):
        toks = per_bar[bar]
        run = run + 1 if len(set(toks)) == 1 and prev == toks[0] else 1
        prev = toks[-1]
        best = max(best, run)
    return best


def tail_run(slots: List[Dict], carry: Tuple[Optional[str], int]) -> Tuple[str, int]:
    per_bar: Dict[int, List[str]] = {}
    for s in slots:
        per_bar.setdefault(s['bar'], []).append(s['tok'])
    prev, run = carry
    for bar in sorted(per_bar):
        toks = per_bar[bar]
        run = run + 1 if len(set(toks)) == 1 and prev == toks[0] else 1
        prev = toks[-1]
    return prev, run


def harmony_unit(g: SubGrammar, rng: random.Random, temp: float, *, first: bool, final: bool,
                 prev: Tuple[str, str],
                 carry: Tuple[Optional[str], int] = (None, 0),
                 next_tok: Optional[str] = None, bars_from: int = 0,
                 cadence_dir: Optional[str] = None, varied: bool = False) -> Dict[str, Any]:
    """bars_from > 0：只写第 bars_from 小节起的和声（前面的小节沿用来源段，prev/carry 接其末尾）。"""
    s = g.s
    hr = s['harmonic_rhythm']
    slots = []
    for i in range(bars_from, UNIT):
        last_bar = final and i == UNIT - 1
        if last_bar:
            beats = [0]
        else:
            dist = hr.get(str(i)) or [['0', 1.0, 1]]
            pat = _pick(rng, [(p, w) for p, w, _n in dist])
            beats = sorted({0, *[int(x) for x in str(pat).split(',') if x != '']})
            beats = [b for b in beats if b < g.beats]
        for b in beats:
            slots.append({'bar': i, 'beat': b, 'pos': pos_label(i, last_bar, b), 'mid': b > 0})
    cads = s['cadences'][g.mode]
    pool = cads['final'] if final else (cads['mid'] or cads['final'])
    if final:
        pool = [c for c in pool if is_tonic(c['chords'][1])]
    pool = [c for c in pool if all(t in g.idx for t in c['chords'])]
    if next_tok is not None:
        pool = [c for c in pool if g.attested(c['chords'][1], next_tok)]
    if cadence_dir:
        directed = [c for c in pool if cadence_direction(c['chords']) == cadence_dir]
        if directed:
            pool = directed
    formula = _pick(rng, [(c, c['p']) for c in pool]) if pool else None
    S, V = len(slots), g.V
    unary = np.zeros((S, V))
    if first:
        fc = {t: p for t, p, _n in s['first_chord'][g.mode] if t in g.idx}
        unary[0] = np.array([math.log(fc[t]) if t in fc else NEG for t in g.vocab])
        if not fc:
            unary[0] = np.array([0.0 if tok_chord(t)[0] == 0 else NEG for t in g.vocab])
    if formula is not None:
        a, b = formula['chords']
        unary[S - 1] = NEG
        unary[S - 1, g.idx[b]] = 0.0
        if S >= 2:
            unary[S - 2] = NEG
            unary[S - 2, g.idx[a]] = 0.0
    elif final:
        unary[S - 1] = np.array([0.0 if is_tonic(t) else NEG for t in g.vocab])
    if next_tok is not None:
        unary[S - 1] = np.where(g.att[:, g.idx[next_tok]], unary[S - 1], NEG)
    half = {t: p for t, p, _n in cads.get('half') or [] if t in g.idx}
    half_slot = max((k for k, sl in enumerate(slots) if sl['bar'] == 3), default=None)
    use_half = half and half_slot is not None and rng.random() < 0.6
    if use_half:
        unary[half_slot] += np.array([1.5 * math.log(1 + 4 * half[t]) if t in half else 0.0
                                      for t in g.vocab])

    def trans(k: int) -> np.ndarray:
        """k-1 → k 的转移矩阵（V×V）。"""
        pos = slots[k]['pos']
        M = np.stack([g.bigram(c, pos) for c in g.vocab])
        M = np.where(g.att, M, NEG)
        if slots[k]['mid']:
            M[np.arange(V), np.arange(V)] = NEG
        return M

    Ms = [None] + [trans(k) for k in range(1, S)]
    p2, p1 = prev
    if p1 == 'BOS':
        init = g.bigram('BOS', slots[0]['pos'])
    else:
        init = np.where(g.att[g.idx[p1]], g.bigram(p1, slots[0]['pos']), NEG)
    beta = np.zeros((S, V))
    beta[S - 1] = unary[S - 1]
    for k in range(S - 2, -1, -1):
        beta[k] = unary[k] + _lse(Ms[k + 1] + beta[k + 1][None, :], axis=1)
    tau = max(temp, 0.35)
    max_run = int(s['form'].get('max_same_chord_bars') or 99)
    if varied:
        max_run = min(max_run, 2)
    best, best_key = None, -1e18
    for _ in range(64 if varied else 32):
        try:
            seq = [_sample_log(rng, init + beta[0], tau)]
            for k in range(1, S):
                seq.append(_sample_log(rng, Ms[k][seq[-1]] + beta[k], tau))
        except _Dead:
            raise _Dead('和声约束无解')
        toks = [g.vocab[i] for i in seq]
        # 重要性权重：样本来自二元提议分布，按 三元 / 二元 重新加权才是在三元模型下抽样
        sc, a2, a1 = 0.0, p2, p1
        for k, t in enumerate(toks):
            sc += g.trigram(a2, a1, slots[k]['pos'], t) - \
                float(g.bigram(a1, slots[k]['pos'])[seq[k]])
            a2, a1 = a1, t
        if chord_runs([dict(sl, tok=t) for sl, t in zip(slots, toks)], carry) > max_run:
            sc -= 1e6
        if varied:
            roots = [tok_chord(t)[0] for sl, t in zip(slots, toks) if sl['beat'] == 0]
            need = min(4, len(roots))
            sc -= 8.0 * max(0, need - len(set(roots)))
        key = sc / temp + _gumbel(rng) if temp > 0 else sc
        if key > best_key:
            best, best_key = toks, key
    a2, a1 = p2, p1
    for sl, t in zip(slots, best):
        sl['tok'] = t
        sl['rule'] = g.rule_id(a2, a1, sl['pos'])
        a2, a1 = a1, t
    if formula is not None:
        slots[-1]['rule'] = formula['id']
        if S >= 2:
            slots[-2]['rule'] = formula['id']
    return {'slots': slots, 'formula': formula, 'half': use_half}


# ======================================================================== 节奏
def parse_pattern(pat: str, length: float) -> List[List]:
    """'0n 0.5n 1r' → [[on, dur, is_rest]]；首个起音前补休止。"""
    toks = [(float(x[:-1]), x[-1] == 'r') for x in pat.split() if x]
    toks = [(on, r) for on, r in toks if on < length - 1e-6]
    if not toks or toks[0][0] > 1e-6:
        toks.insert(0, (0.0, True))
    out = []
    for k, (on, r) in enumerate(toks):
        end = toks[k + 1][0] if k + 1 < len(toks) else length
        if end - on > 1e-6:
            out.append([on, end - on, r])
    return out


def rhythm_bars(g: SubGrammar, rng: random.Random, final: bool,
                prefix: Optional[List[Dict[str, Any]]] = None,
                theme_lock: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """prefix：沿用来源段的前几小节节奏；其后的小节仍可按学到的间隔照抄它们。
    theme_lock：主题开头若干小节固定为指定节奏模板。"""
    rh = g.s['rhythm']
    bars: List[Dict[str, Any]] = [dict(b) for b in prefix or []]
    prev_cell = 'BOS'
    for i in range(len(bars), UNIT):
        last = final and i == UNIT - 1
        if theme_lock and i < int(theme_lock['bars']) and not last:
            bars.append({'pattern': theme_lock['pattern'], 'rule': theme_lock['rule'],
                         'copy': None})
            continue
        cls = rhythm_class(i, last)
        src = None
        if not last:
            reps = rh['repeat'].get(str(i)) or {}
            for lag, p in sorted(reps.items(), key=lambda kv: -kv[1]):
                j = i - int(lag)
                if j >= 0 and rng.random() < p:
                    src = j
                    break
        prev_empty = bool(bars) and 'n' not in bars[-1]['pattern']
        if src is not None and not (prev_empty and 'n' not in bars[src]['pattern']):
            bars.append({'pattern': bars[src]['pattern'], 'rule': bars[src]['rule'],
                         'copy': src})
            continue
        if rh['mode'] == 'bar' or last:
            items = (rh['templates'].get(cls) or {}).get('items') or \
                (rh['templates'].get('mid') or {}).get('items') or []
            if last:
                items = [it for it in items if it['pattern'].startswith('0n')]
            if items:
                it = _pick(rng, [(it, it['p']) for it in items])
                bars.append({'pattern': it['pattern'], 'rule': it['id'], 'copy': None})
            else:
                bars.append({'pattern': '0n', 'rule': '末小节长音', 'copy': None})
            continue
        start_cell = prev_cell
        # 不允许连续两小节全是休止：重抽
        for _try in range(12):
            cells, prev_cell = [], start_cell
            for k in range(g.beats):
                key = str(k)
                dist = g.cell_ctx.get((prev_cell, key)) or rh['cells']['by_beat'].get(key) \
                    or [['-', 1, 1]]
                c = _pick(rng, [(c, p) for c, p, _n in dist])
                cells.append(c)
                prev_cell = c
            if not (i == 0 or prev_empty) or any('n' in c for c in cells):
                break
        toks = []
        for k, c in enumerate(cells):
            if c == '-':
                continue
            for j, x in enumerate(c.split()):
                # 拍内短休止是断奏记法，并入前一个音；整拍起的休止保留（换气 / 留白）
                if x.endswith('r') and j > 0:
                    continue
                toks.append(f'{round(float(x[:-1]) + k * g.beat_ql, 3):g}{x[-1]}')
        bars.append({'pattern': ' '.join(toks) or '0r', 'rule': '节奏单元链', 'copy': None})
    return bars


def apply_learned_motif_rhythm(g: SubGrammar, rng: random.Random,
                               bars: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Instantiate one relation sampled from the learned within-phrase model."""
    relation = plan_intra_phrase(getattr(g, 'theme_policy', {}), rng)
    if relation is None:
        return None
    span, src = relation['span_bars'], relation['source_bar']
    targets = relation.get('target_bars') or [relation['target_bar']]
    if (src < 0 or src + span > len(bars) or any(
            dst <= src or dst + span > len(bars) for dst in targets)):
        return None
    # Condition source rhythm density on the learned aggregate profile. Exact rhythm remains
    # sampled from this style's learned template distribution; no corpus fragment is stored.
    learned_rhythm = relation.get('core_rhythm') or []
    for off, count in enumerate(relation.get('source_note_counts') or []):
        candidates = []
        for group in g.s['rhythm'].get('templates', {}).values():
            for it in (group or {}).get('items', []):
                n = sum(not rest for _on, _dur, rest in parse_pattern(it['pattern'], g.bar_ql))
                if n == count:
                    candidates.append(it)
        if off == 0 and learned_rhythm and candidates:
            def rhythm_code(it):
                es = [(0, d) for _on, d, rest in parse_pattern(it['pattern'], g.bar_ql)
                      if not rest][:len(learned_rhythm)]
                total = sum(d for _m, d in es)
                return [max(1, min(8, round(8 * d / max(total, 1e-9)))) for _m, d in es]
            matched = [it for it in candidates if rhythm_code(it) == learned_rhythm]
            candidates = matched or candidates
        if off < span and candidates:
            it = _pick(rng, [(it, float(it.get('p') or 0)) for it in candidates])
            bars[src + off] = {'pattern': it['pattern'], 'rule': it['id'], 'copy': None,
                               'theme_role': 'learned_source'}
    for dst in targets:
        for off in range(span):
            source = src + off
            target = dst + off
            bars[target] = {'pattern': bars[source]['pattern'], 'rule': bars[source]['rule'],
                            'copy': source, 'theme_role': 'learned_answer',
                            'motif_source': source}
    return relation


def apply_learned_motif_harmony(g: SubGrammar, slots: List[Dict[str, Any]],
                                relation: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Condition target harmony on the learned motif relation and root shift."""
    if relation is None:
        return slots
    span, src = relation['span_bars'], relation['source_bar']
    targets = relation.get('target_bars') or [relation['target_bar']]
    shifts = relation.get('harmony_shifts') or [relation.get('harmony_shift') or 0]
    source = [s for s in slots if src <= s['bar'] < src + span]
    if not source:
        raise _Dead('学习到的主题关系没有来源和声')
    replacement = []
    for dst, shift0 in zip(targets, shifts):
        shift = int(shift0)
        for s in source:
            r, q = tok_chord(s['tok'])
            tok = f'{(r + shift) % 12}:{q}'
            if tok not in g.vocab:
                raise _Dead('学习到的主题和声移调不在当前词表')
            replacement.append(dict(s, bar=s['bar'] - src + dst, tok=tok))
    out = [s for s in slots if not any(dst <= s['bar'] < dst + span for dst in targets)] + replacement
    out.sort(key=lambda s: (s['bar'], s['beat']))
    if any(not g.attested(a['tok'], b['tok']) for a, b in zip(out, out[1:])):
        raise _Dead('学习到的主题和声关系与上下文转移不兼容')
    return out


# ======================================================================== 旋律
def melody_range(g: SubGrammar, instrument: str) -> Tuple[int, int]:
    _nm, ilo, ihi, center = INSTRUMENTS.get(instrument, INSTRUMENTS['violin'])
    r = g.s['melody']['range']
    shift = 12 * round((center - r['mean']) / 12)
    lo, hi = max(ilo, r['low'] + shift), min(ihi, r['high'] + shift)
    while hi - lo < 14:
        lo, hi = max(ilo, lo - 1), min(ihi, hi + 1)
        if lo == ilo and hi == ihi:
            break
    return lo, hi


def leap_ok(g: SubGrammar, a: int, b: int) -> bool:
    return abs(b - a) <= g.max_leap and abs(b - a) not in g.forbidden


def melody_dp(g: SubGrammar, rng: random.Random, temp: float, notes: List[Dict], tonic_pc: int,
              lo: int, hi: int, prev: Optional[Tuple[int, int]], end_tonic: bool,
              next_midi: Optional[int] = None) -> List[int]:
    """notes: [{'tok', 'st', 'target', 'force'}] → MIDI 序列。状态 = (音高, 待解决, 跳进方向)。"""
    R = np.arange(lo, hi + 1)
    nR = len(R)
    N = len(notes)
    cls_code = {'CT': 0, 'ST': 1, 'CH': 2}
    ems, need, sres = [], [], []
    for k, n in enumerate(notes):
        cl = np.array([cls_code[note_class(int((m - tonic_pc) % 12), n['tok'], g.mode)] for m in R])
        lp = g.cls_lp.get(n['st']) or g.cls_lp.get('W') or {}
        e = np.array([lp.get(c, math.log(1e-3)) for c in ('CT', 'ST', 'CH')])[cl]
        # 一般轮廓是软偏好；主题回答的来源轮廓需要更强的身份约束，但仍让和声、
        # 非和弦音解决和大跳规则拥有最终否决权。
        target_weight = 40.0 if n.get('motif_target') else 0.5
        e = e - target_weight * ((R - n['target']) / CONTOUR_SIGMA) ** 2
        nct = cl != 0
        nd = nct if g.strict_r02 else (cl == 2)
        strong = n['st'] == 'S'
        sr = strong & (nct if g.strict_r01 else (cl == 2))
        if n.get('force') is not None:
            e = np.where(R == n['force'], e, NEG)
        if end_tonic and k == N - 1:
            e = np.where(((R - tonic_pc) % 12 == 0) & (cl == 0), e, NEG)
        if next_midi is not None and k == N - 1:
            e = np.where([leap_ok(g, int(m), next_midi) for m in R], e, NEG)
        ems.append(e)
        need.append(nd)
        sres.append(sr)
    iv = R[None, :] - R[:, None]
    base = np.vectorize(lambda x: g.iv_lp.get(int(x), NEG) if abs(x) <= g.max_leap
                        and abs(x) not in g.forbidden else NEG)(iv).astype(float)
    step = (np.abs(iv) >= 1) & (np.abs(iv) <= 2)
    leap_b = np.where(iv >= 5, 1, np.where(iv <= -5, 2, 0))
    lr, lf = math.log(max(g.p_rec, 0.02)), math.log(max(1 - g.p_rec, 0.02))
    rec = {1: np.where((iv < 0) | (np.abs(iv) <= 2), lr, lf),
           2: np.where((iv > 0) | (np.abs(iv) <= 2), lr, lf)}
    S = nR * 6
    ra, rb = np.meshgrid(np.arange(nR), np.arange(nR), indexing='ij')

    def trans(k: int) -> np.ndarray:
        pb = (need[k][None, :] & ~step) | sres[k][None, :]
        M = np.full((nR, 2, 3, nR, 2, 3), NEG)
        for pa in (0, 1):
            for la in (0, 1, 2):
                val = base + (rec[la] if la else 0.0)
                desired = notes[k].get('motif_interval')
                if desired is not None:
                    val = val - 2.5 * np.minimum(np.abs(iv - desired), 12)
                if pa:
                    val = np.where(step, val, NEG)
                M[ra, pa, la, rb, pb.astype(int), leap_b] = val
        return M.reshape(S, S)

    def em_state(k: int, last: bool) -> np.ndarray:
        e = np.repeat(ems[k], 6).reshape(nR, 2, 3).copy()
        if last:
            e[:, 1, :] = NEG
        return e.reshape(S)

    Ms = [trans(k) for k in range(N)]
    if prev is not None and lo <= prev[0] <= hi:
        st0 = np.full(S, NEG)
        st0[(prev[0] - lo) * 6 + prev[1]] = 0.0
        init = _lse(st0[:, None] + Ms[0], axis=0)
    else:
        init = np.full((nR, 2, 3), NEG)
        pb0 = (need[0] | sres[0]).astype(int)
        init[np.arange(nR), pb0, 0] = 0.0
        init = init.reshape(S)
    alpha = np.zeros((N, S))
    alpha[0] = init + em_state(0, N == 1)
    for k in range(1, N):
        alpha[k] = _lse(alpha[k - 1][:, None] + Ms[k], axis=0) + em_state(k, k == N - 1)
    if alpha[-1].max() < NEG / 2:
        raise _Dead('旋律约束无解')
    tau = max(temp, 0.3)
    best, best_key = None, -1e18
    for _ in range(10):
        path = [_sample_log(rng, alpha[-1], tau)]
        for k in range(N - 1, 0, -1):
            path.append(_sample_log(rng, alpha[k - 1] + Ms[k][:, path[-1]], tau))
        path.reverse()
        # 样本已是动态规划分布的精确抽样，只对"同音三连"降权，其余均匀挑
        mids = [int(R[s // 6]) for s in path]
        runs = sum(1 for a, b, c in zip(mids, mids[1:], mids[2:]) if a == b == c)
        sc = -1.5 * runs
        key = sc / temp + _gumbel(rng) if temp > 0 else sc
        if key > best_key:
            best, best_key = mids, key
    return best


def _leap_state(a: Optional[int], b: int) -> int:
    if a is None:
        return 0
    return 1 if b - a >= 5 else 2 if b - a <= -5 else 0


# ======================================================================== 伴奏
class _Mel:
    """旋律时间线查询：某时刻发声的音 / 恰在某时刻起音的音 / 某时刻之前一瞬的音。"""

    def __init__(self, line):
        self.line = [(on, d, m) for on, d, m, *_x in line]

    def at(self, t):
        for on, d, m in self.line:
            if on <= t + 1e-6 < on + d:
                return m
        return None

    def onset(self, t):
        for on, _d, m in self.line:
            if abs(on - t) < 1e-6:
                return m
        return None

    def before(self, t):
        return self.at(t - 1e-3)

    def low(self, t0, t1):
        ms = [m for on, d, m in self.line if m is not None and on < t1 - 1e-6 and on + d > t0 + 1e-6]
        return min(ms) if ms else None


def _moves_parallel(mel: _Mel, t: float, x0: int, x1: int) -> bool:
    """t 时刻伴奏音 x0 → x1，若旋律也在 t 起音且同向进入纯五 / 纯八度则为真。"""
    a1 = mel.onset(t)
    a0 = mel.before(t)
    if a1 is None or a0 is None:
        return False
    return parallel_motion([a0], [a1], [x0], [x1]) is not None


def _bass_line(g: SubGrammar, slots: List[Dict], mel: _Mel) -> List[int]:
    cand = []
    for sl in slots:
        r, q = tok_chord(sl['tok'])
        ivs = QUALITIES[q]
        opts = []
        for role, cost in ((0, 0.0), (2, 1.2), (1, 1.6)):
            if role >= len(ivs):
                continue
            pc = (r + ivs[role] + g.tonic_pc) % 12
            for m in range(36, 56):
                if m % 12 == pc:
                    opts.append((m, cost))
        cand.append(opts)
    n = len(slots)
    low0 = mel.at(slots[0]['t'])
    cost = [np.array([c + (0 if low0 is None or m < low0 else 1e6) for m, c in cand[0]])]
    back = []
    for k in range(1, n):
        prev, cur = cand[k - 1], cand[k]
        t = slots[k]['t']
        m_now = mel.at(t)
        C = np.full((len(prev), len(cur)), 1e9)
        for i, (ma, _ca) in enumerate(prev):
            for j, (mb, cb) in enumerate(cur):
                c = cost[-1][i] + cb + abs(mb - ma) * 0.25 + (1.0 if abs(mb - ma) > 7 else 0)
                if m_now is not None and mb >= m_now:
                    c += 1e6
                if ma != mb and _moves_parallel(mel, t, ma, mb):
                    c += 1e6
                C[i, j] = c
        back.append(C.argmin(axis=0))
        cost.append(C.min(axis=0))
    j = int(np.argmin(cost[-1]))
    if cost[-1][j] >= 1e6:
        raise _Dead('低音无法避开平行五八度')
    out = [j]
    for k in range(n - 2, -1, -1):
        j = int(back[k][j])
        out.append(j)
    out.reverse()
    return [cand[k][j][0] for k, j in enumerate(out)]


def _voicing_cands(g: SubGrammar, tok: str, lo: int, hi: int) -> List[List[int]]:
    r, q = tok_chord(tok)
    ivs = list(QUALITIES[q])
    if g.style == 'jazz':
        ivs = [ivs[1], ivs[3]] if len(ivs) == 4 else [ivs[1], ivs[2]]
    elif len(ivs) == 4:
        ivs = [ivs[0], ivs[1], ivs[3]]
    pcs = [(r + i + g.tonic_pc) % 12 for i in ivs]
    n = len(pcs)
    span = 12 if n == 2 else 16
    out = []
    for perm in itertools.permutations(pcs):
        for start in range(lo, hi + 1):
            if start % 12 != perm[0]:
                continue
            v = [start]
            for pc in perm[1:]:
                m = v[-1] + 1
                while m % 12 != pc:
                    m += 1
                v.append(m)
            if v[-1] <= hi and v[-1] - v[0] <= span:
                out.append(v)
    return out


def _voicings(g: SubGrammar, slots: List[Dict], bass: List[int], mel: _Mel,
              final_t: float) -> List[List[int]]:
    """右手配位动态规划：最高音不高过旋律（容差大二度），避开与低音 / 旋律的平行五八度，
    其余按声部移动最小。"""
    if g.texture in ('quartet', 'orchestra'):
        return _quartet_voicings(g, slots, bass, mel, final_t)
    lo, hi, mid = 48, 76, 62
    cands, costs0 = [], []
    for k, sl in enumerate(slots):
        t0 = sl['t']
        t1 = slots[k + 1]['t'] if k + 1 < len(slots) else final_t
        low = mel.low(t0, t1)
        cs = _voicing_cands(g, sl['tok'], lo, hi)
        thin = []
        if g.style != 'jazz':
            r, q = tok_chord(sl['tok'])
            third = (r + QUALITIES[q][1] + g.tonic_pc) % 12
            for v in cs:
                for drop in range(len(v)):
                    d = v[:drop] + v[drop + 1:]
                    if any(x % 12 == third for x in d) and d[-1] - d[0] <= 9 and d not in thin:
                        thin.append(d)
        full = len(cs)
        cs = cs + thin
        ok = [v for v in cs if (low is None or v[-1] <= low + 2) and v[0] > bass[k]]
        if not ok:
            cs = _voicing_cands(g, sl['tok'], 40, hi)
            full, thin = len(cs), []
            ok = [v for v in cs if (low is None or v[-1] <= low + 2) and v[0] > bass[k]]
        extra = [0.0] * full + [40.0] * len(thin)
        # 窗口内无解时右手在这个和弦上休止（空配位）
        pairs = [(v, e) for v, e in zip(cs, extra) if v in ok] or [([], 60.0)]
        cands.append([v for v, _e in pairs])
        costs0.append([(abs(sum(v) / len(v) - mid) * 0.3 if v else 0.0) + e for v, e in pairs])
    cost = [np.array(costs0[0])]
    back = []
    for k in range(1, len(slots)):
        t = slots[k]['t']
        C = np.full((len(cands[k - 1]), len(cands[k])), 1e12)
        for i, va in enumerate(cands[k - 1]):
            for j, vb in enumerate(cands[k]):
                c = cost[-1][i] + costs0[k][j]
                c += sum(abs(a - b) for a, b in match_voices(va, vb)) * 0.4
                if parallel_motion(va, vb, [bass[k - 1]], [bass[k]]):
                    c += 500
                if _moves_parallel_chord(mel, t, va, vb):
                    c += 500
                C[i, j] = c
        back.append(C.argmin(axis=0))
        cost.append(C.min(axis=0))
    j = int(np.argmin(cost[-1]))
    out = [j]
    for k in range(len(slots) - 2, -1, -1):
        j = int(back[k][j])
        out.append(j)
    out.reverse()
    return [cands[k][j] for k, j in enumerate(out)]


def _quartet_voicings(g: SubGrammar, slots: List[Dict], bass: List[int], mel: _Mel,
                      final_t: float) -> List[List[int]]:
    """第二小提琴 + 中提琴的双音配位动态规划：[中提琴, 第二小提琴]，第二小提琴不高过旋律，
    中提琴高过大提琴；四条声部按各自的线条（不是就近配对）两两避开平行五八度。"""
    cands, costs0 = [], []
    for k, sl in enumerate(slots):
        t0 = sl['t']
        t1 = slots[k + 1]['t'] if k + 1 < len(slots) else final_t
        low = mel.low(t0, t1)
        r, q = tok_chord(sl['tok'])
        ivs = QUALITIES[q]
        pcs = [(r + i + g.tonic_pc) % 12 for i in ivs]
        third = pcs[1]
        cap = min(84, (low - 1) if low is not None else 84)
        opts = []
        for a in range(max(VA_LOW, bass[k] + 1), cap):
            if a % 12 not in pcs:
                continue
            for b in range(max(VN2_LOW, a + 3), min(cap, a + 12) + 1):
                if b % 12 not in pcs or b % 12 == a % 12:
                    continue
                c = abs((a + b) / 2 - 64) * 0.2
                c += 0 if third in (a % 12, b % 12) else 4.0
                if len(pcs) == 4 and pcs[3] not in (a % 12, b % 12, bass[k] % 12):
                    c += 2.0
                opts.append(([a, b], c))
        if not opts:
            opts = [([], 60.0)]
        cands.append([v for v, _c in opts])
        costs0.append([c for _v, c in opts])
    cost = [np.array(costs0[0])]
    back = []
    for k in range(1, len(slots)):
        t = slots[k]['t']
        a1, a0 = mel.onset(t), mel.before(t)
        C = np.full((len(cands[k - 1]), len(cands[k])), 1e12)
        for i, va in enumerate(cands[k - 1]):
            for j, vb in enumerate(cands[k]):
                c = cost[-1][i] + costs0[k][j]
                if va and vb:
                    c += (abs(va[0] - vb[0]) + abs(va[1] - vb[1])) * 0.4
                    la = [va[1], va[0], bass[k - 1]]
                    lb = [vb[1], vb[0], bass[k]]
                    if a0 is not None and a1 is not None:
                        la, lb = la + [a0], lb + [a1]
                    for x in range(len(la)):
                        for y in range(x + 1, len(la)):
                            if parallel_motion([la[x]], [lb[x]], [la[y]], [lb[y]]):
                                c += 500
                C[i, j] = c
        back.append(C.argmin(axis=0))
        cost.append(C.min(axis=0))
    j = int(np.argmin(cost[-1]))
    out = [j]
    for k in range(len(slots) - 2, -1, -1):
        j = int(back[k][j])
        out.append(j)
    out.reverse()
    return [cands[k][j] for k, j in enumerate(out)]


def _moves_parallel_chord(mel: _Mel, t: float, va: List[int], vb: List[int]) -> bool:
    a1, a0 = mel.onset(t), mel.before(t)
    if a1 is None or a0 is None:
        return False
    return parallel_motion([a0], [a1], va, vb) is not None


def accompaniment(g: SubGrammar, slots: List[Dict], bass: List[int], n_bars: int,
                  mel: _Mel, final_t: float):
    """→ (rh_bars, lh_bars)：每小节 [(on, dur, [midi…]|None)]。"""
    bq, beat = g.bar_ql, g.beat_ql
    voic = [v or None for v in _voicings(g, slots, bass, mel, final_t)]
    last_lh = [bass[0]]

    def pick_lh(t: float, opts: List[int], then: Optional[Tuple[float, int]] = None) -> int:
        """按偏好顺序取第一个不与旋律平行、不高过旋律的低音；then=(下一个低音起音时刻, 音高)
        时连同走向下一个低音的那一步一起检查。"""
        m_now = mel.at(t)
        for x in opts:
            if m_now is not None and x >= m_now:
                continue
            if x != last_lh[0] and _moves_parallel(mel, t, last_lh[0], x):
                continue
            if then and then[1] != x and _moves_parallel(mel, then[0], x, then[1]):
                continue
            return x
        return opts[0]
    segs = []
    for k, sl in enumerate(slots):
        end = slots[k + 1]['t'] if k + 1 < len(slots) else final_t
        segs.append((sl['t'], end, k))
    rh = [[] for _ in range(n_bars)]
    lh = [[] for _ in range(n_bars)]

    def seg_at(t):
        for s0, s1, k in segs:
            if s0 - 1e-6 <= t < s1 - 1e-6:
                return s0, s1, k
        return segs[-1]

    def tones(k, roles=(0, 1, 2, 3)):
        r, q = tok_chord(slots[k]['tok'])
        ivs = QUALITIES[q]
        return [(r + ivs[i] + g.tonic_pc) % 12 for i in roles if i < len(ivs)]

    def near(pcs, ref, lo=36, hi=57):
        return sorted((x for x in range(lo, hi + 1) if x % 12 in pcs), key=lambda x: abs(x - ref))
    for bi in range(n_bars):
        t0 = bi * bq
        last_bar = bi == n_bars - 1
        if last_bar:
            _s0, _s1, k = seg_at(t0)
            rh[bi].append((0.0, bq, voic[k]))
            lh[bi].append((0.0, bq, [bass[k]]))
            continue
        if g.style == 'folk':
            strong = {0, 2} if g.beats == 4 else {0}
            for b in range(g.beats):
                t = t0 + b * beat
                s0, _s1, k = seg_at(t)
                if abs(t - s0) < 1e-6 or b in strong:
                    if abs(t - s0) < 1e-6 or b == 0:
                        m = bass[k]
                    else:
                        then = None
                        for b2 in range(b + 1, g.beats + 1):
                            t2 = t0 + b2 * beat
                            s2, _e2, k2 = seg_at(t2)
                            if b2 == g.beats or abs(t2 - s2) < 1e-6:
                                then = (t2, bass[k2])
                                break
                            if b2 in strong:
                                break
                        m = pick_lh(t, near(tones(k, (2,)), bass[k]) + near(tones(k, (0,)), bass[k])
                                    + near(tones(k, (1,)), bass[k]), then)
                    last_lh[0] = m
                    lh[bi].append((b * beat, beat, [m]))
                    # 弱拍上换和弦：低音与右手和弦同时进
                    rh[bi].append((b * beat, beat, None if b in strong else voic[k]))
                else:
                    lh[bi].append((b * beat, beat, None))
                    rh[bi].append((b * beat, beat, voic[k]))
        elif g.style == 'jazz':
            for b in range(g.beats):
                t = t0 + b * beat
                s0, s1, k = seg_at(t)
                prev_m = last_lh[0]
                if abs(t - s0) < 1e-6:
                    m = bass[k]
                    rh[bi].append((b * beat, min(2 * beat, s1 - t, bq - b * beat), voic[k]))
                else:
                    nxt_start = abs(t + beat - s1) < 1e-6 and k + 1 < len(slots)
                    opts = []
                    if nxt_start:
                        tgt = bass[k + 1]
                        # 走动低音：换和弦前一拍用半音 / 全音趋近下一个根音
                        opts += sorted([tgt - 1, tgt + 1], key=lambda x: abs(x - prev_m))
                        opts += [tgt - 2, tgt + 2]
                    opts += [x for x in near(tones(k), prev_m) if x != prev_m]
                    opts = [x for x in opts if 36 <= x <= 57] or [prev_m]
                    m = pick_lh(t, opts, (t + beat, bass[k + 1]) if nxt_start else None)
                last_lh[0] = m
                lh[bi].append((b * beat, beat, [m]))
            # 右手：和弦起点写三七和弦，其余休止
            filled = []
            cur = 0.0
            for on, d, v in rh[bi]:
                if on > cur + 1e-6:
                    filled.append((cur, on - cur, None))
                filled.append((on, d, v))
                cur = on + d
            if cur < bq - 1e-6:
                filled.append((cur, bq - cur, None))
            rh[bi] = filled
        elif g.style == 'pop':
            for s0, s1, k in segs:
                a, b_ = max(s0, t0), min(s1, t0 + bq)
                if b_ - a < 1e-6:
                    continue
                lh[bi].append((a - t0, b_ - a, [bass[k]]))
                t = a
                while t < b_ - 1e-6:
                    d = min(beat, b_ - t)
                    rh[bi].append((t - t0, d, voic[k]))
                    t += d
        else:
            for s0, s1, k in segs:
                a, b_ = max(s0, t0), min(s1, t0 + bq)
                if b_ - a < 1e-6:
                    continue
                lh[bi].append((a - t0, b_ - a, [bass[k]]))
                rh[bi].append((a - t0, b_ - a, voic[k]))
    return rh, lh


def _bar_segments(slots: List[Dict], n_bars: int, bq: float, final_t: float):
    """和弦槽按小节线切开 → 每小节 [(起, 止, 槽号)]（绝对时间）。"""
    segs = [(sl['t'], slots[k + 1]['t'] if k + 1 < len(slots) else final_t, k)
            for k, sl in enumerate(slots)]
    out = []
    for bi in range(n_bars):
        t0, t1 = bi * bq, (bi + 1) * bq
        out.append([(max(a, t0), min(b, t1), k) for a, b, k in segs if min(b, t1) - max(a, t0) > 1e-6])
    return out


def _to_bars(flat, n_bars: int, bq: float):
    bars = [[] for _ in range(n_bars)]
    for t, d, v in flat:
        bi = min(n_bars - 1, int(t / bq + 1e-6))
        bars[bi].append((t - bi * bq, d, v))
    return bars


def piano_figure(g: SubGrammar) -> str:
    """左手音型：3/4 低音-和弦-和弦（小步舞曲 / 玛祖卡），6/8 分解三和弦，其余阿尔贝蒂低音。"""
    return {'3/4': 'waltz', '6/8': 'broken'}.get(g.meter, 'alberti')


def accompaniment_piano(g: SubGrammar, slots: List[Dict], bass: List[int], n_bars: int,
                        mel: _Mel, final_t: float) -> List[List]:
    """钢琴织体：右手就是旋律，左手按音型逐段贪心配位，每个候选都用与复核同口径的
    逐起音平行检测（含走向下一段低音的那一步）；没有候选时退回长音低音（低音线
    动态规划已保证它与旋律无平行）。→ 左手每小节 [(on, dur, [midi…]|None)]。"""
    bq, beat = g.bar_ql, g.beat_ql
    kind = piano_figure(g)
    nv = 2 if kind == 'waltz' else 1
    mel_ev = [[on, d, [m]] for on, d, m in mel.line if m is not None]
    bar_segs = _bar_segments(slots, n_bars, bq, final_t)
    seq = [s for bs in bar_segs for s in bs]
    flat: List[List] = []
    prev_shape = (52, 57)

    def roles(a, b):
        out, t, j = [], a, 0
        while t < b - 1e-6:
            if kind == 'waltz':
                d = min(beat, b - t)
                out.append((t, d, 'B' if j == 0 else 'C'))
            else:
                d = min(0.5, b - t)
                cyc = ('B', 'H', 'M', 'H') if kind == 'alberti' else ('B', 'M', 'H')
                out.append((t, d, cyc[j % len(cyc)]))
            t += d
            j += 1
        return out

    def ok(seg_ev, nxt):
        tmp = flat[-6:] + seg_ev + ([nxt] if nxt else [])
        lo_t, hi_t = tmp[0][0], tmp[-1][0] + 1e-6
        mw = [e for e in mel_ev if e[0] + e[1] > lo_t - 1e-6 and e[0] <= hi_t]
        streams = split_streams(tmp, nv)
        hits = stream_parallels([mw] + streams, [0] + [1] * len(streams))
        return not any(t >= seg_ev[0][0] - 1e-6 for t, _i, _j in hits)

    for n, (a, b, k) in enumerate(seq):
        bm = bass[k]
        if n == len(seq) - 1 or a >= (n_bars - 1) * bq - 1e-6:
            flat.append([a, b - a, [bm]])
            continue
        na, _nb, nk = seq[n + 1]
        nxt = [na, beat, [bass[nk]]]
        low = mel.low(a, b)
        cap = min(67, (low - 1) if low is not None else 67)
        r, q = tok_chord(slots[k]['tok'])
        pcs = [(r + i + g.tonic_pc) % 12 for i in QUALITIES[q]]
        shapes = []
        for m_ in range(bm + 3, cap + 1):
            if m_ % 12 not in pcs:
                continue
            for h in range(m_ + 3, min(cap, m_ + 9) + 1):
                if h % 12 not in pcs or h % 12 == m_ % 12 or (kind != 'waltz' and h - bm > 12):
                    continue
                c = 0.0 if pcs[1] in (m_ % 12, h % 12) else 4.0
                if len(pcs) == 4 and pcs[3] not in (m_ % 12, h % 12, bm % 12):
                    c += 1.5
                c += (abs(m_ - prev_shape[0]) + abs(h - prev_shape[1])) * 0.5
                c += abs((m_ + h) / 2 - 57) * 0.15
                shapes.append((c, m_, h))
        rl = roles(a, b)
        chosen = None
        for _c, m_, h in sorted(shapes):
            pick = {'B': [bm], 'M': [m_], 'H': [h], 'C': [m_, h]}
            seg_ev = [[t, d, pick[ro]] for t, d, ro in rl]
            if ok(seg_ev, nxt):
                chosen, prev_shape = seg_ev, (m_, h)
                break
        flat += chosen or [[a, b - a, [bm]]]
    return _to_bars(flat, n_bars, bq)


def _chord_pcs(g: SubGrammar, tok: str) -> set:
    r, q = tok_chord(tok)
    return {(r + i + g.tonic_pc) % 12 for i in QUALITIES[q]}


def _other_tone(prev: Optional[int], options: List[int]) -> Optional[int]:
    if not options:
        return None
    for p in options:
        if p != prev:
            return p
    return options[0]


def _register_pair(g: SubGrammar, tok: str, v: List[int], bass_pitch: int):
    """只用已经配好的内声部音，避免第二小提琴冲到旋律上面。低音在根音和五音间交替。"""
    pcs = _chord_pcs(g, tok)
    ordered = sorted({int(p) for p in (v or []) if p is not None})
    if len(ordered) >= 2:
        lower, high_a = ordered[0], ordered[-1]
    elif ordered:
        lower, high_a = min(ordered[0] - 5, bass_pitch + 5), ordered[0]
    else:
        lower, high_a = bass_pitch + 7, bass_pitch + 12
    high_b = ordered[-2] if len(ordered) >= 3 else high_a
    if high_b <= lower:
        high_b = high_a
    if high_b == high_a and high_a - 12 > lower:
        high_b = high_a - 12
    # 大提琴最低音是 C2。再低一个八度会变成听不见音高的撞击。
    cello_lo, cello_hi = 36, 55
    below = []
    for p in (bass_pitch, bass_pitch + 7, bass_pitch - 5, bass_pitch + 12, bass_pitch - 12):
        if cello_lo <= p <= cello_hi and p < lower and p % 12 in pcs and p not in below:
            below.append(p)
    if not below:
        anchored = min(cello_hi, max(cello_lo, bass_pitch))
        below = [anchored]
    return high_a, high_b, lower, below[0], below[1] if len(below) > 1 else below[0]


def _quartet_by_duty(g: SubGrammar, slots: List[Dict], bass: List[int], n_bars: int,
                     final_t: float, voic: List[List[int]], duties: Dict[str, str]):
    """按草图职责写三个伴奏声部：应答在拍后，持续和声换音，低音只在强拍且根音/五音交替。"""
    bq, beat = g.bar_ql, g.beat_ql
    role = {'violin2': duties.get('violin2', 'answer'),
            'viola': duties.get('viola', 'sustain'),
            'cello': duties.get('cello', 'bass')}
    streams = {k: [] for k in role}
    prev_sustain = {'violin2': None, 'viola': None, 'cello': None}
    bar_segs = _bar_segments(slots, n_bars, bq, final_t)

    def at(t, segs):
        for a, b, k in segs:
            if a - 1e-6 <= t < b - 1e-6:
                return k
        return segs[-1][2] if segs else 0

    for bi, segs in enumerate(bar_segs):
        t0 = bi * bq
        last = bi == n_bars - 1
        if last or not segs:
            k = segs[0][2] if segs else 0
            high_a, _high_b, lower, root, _fifth = _register_pair(
                g, slots[k]['tok'], voic[k] if k < len(voic) else [], bass[k])
            streams['violin2'].append([t0, bq, [high_a]])
            streams['viola'].append([t0, bq, [lower]])
            streams['cello'].append([t0, bq, [root]])
            continue
        step = {'violin2': 0, 'viola': 0, 'cello': 0}
        for name, duty in role.items():
            if duty == 'sustain':
                for a, b, k in segs:
                    high_a, high_b, lower, root, fifth = _register_pair(
                        g, slots[k]['tok'], voic[k] if k < len(voic) else [], bass[k])
                    pool = {'violin2': (high_a, high_b), 'viola': (lower,),
                            'cello': (root, fifth)}[name]
                    p = pool[0] if pool[0] != prev_sustain[name] else pool[min(1, len(pool) - 1)]
                    streams[name].append([a, b - a, [p]])
                    prev_sustain[name] = p
            elif duty == 'bass':
                # 强拍上的二分音符。八分音符点低音听起来像在敲。
                for half_i, off in enumerate((0.0, 2.0 * beat)):
                    t = round(t0 + off, 4)
                    if t >= t0 + bq - 1e-6:
                        break
                    d = min(2.0 * beat, t0 + bq - t)
                    k = at(t, segs)
                    _a, _b, _lo, root, fifth = _register_pair(
                        g, slots[k]['tok'], voic[k] if k < len(voic) else [], bass[k])
                    streams[name].append([t, d, [root if half_i % 2 == 0 else fifth]])
            elif duty == 'answer':
                # 第二拍进来，保持到小节结束。不再每拍后半拍戳同一个音。
                k = at(min(t0 + beat, t0 + bq - 0.01), segs)
                high_a, high_b, _lo, _root, _fifth = _register_pair(
                    g, slots[k]['tok'], voic[k] if k < len(voic) else [], bass[k])
                pool = tuple(dict.fromkeys(p for p in (high_a, high_b) if p is not None))
                p = pool[bi % len(pool)] if pool else None
                if p is None or beat >= bq - 1e-6:
                    streams[name].append([t0, bq, None if p is None else [p]])
                else:
                    streams[name].append([t0, beat, None])
                    streams[name].append([round(t0 + beat, 4), bq - beat, [p]])
            else:
                t = t0
                while t < t0 + bq - 1e-6:
                    d = min(beat / 2.0, t0 + bq - t)
                    k = at(t, segs)
                    high_a, high_b, lower, root, fifth = _register_pair(
                        g, slots[k]['tok'], voic[k] if k < len(voic) else [], bass[k])
                    pool = (high_a, high_b)
                    p = pool[step[name] % len(pool)]
                    step[name] += 1
                    streams[name].append([t, d, [p]])
                    t = round(t + d, 4)
    order = ('violin2', 'viola', 'cello')
    return tuple(_to_bars(streams[k], n_bars, bq) for k in order)


def accompaniment_quartet(g: SubGrammar, slots: List[Dict], bass: List[int], n_bars: int,
                          mel: _Mel, final_t: float, voic: Optional[List[List[int]]] = None,
                          duties: Optional[Dict[str, str]] = None):
    """弦乐四重奏伴奏。

    4/4 中第二小提琴在后半拍作短应答，中提琴保持和声长音，避免两个中声部由同一个
    半拍脉冲模板驱动。3/4 与 6/8 保留各自拍号的历史织体。
    duties 给出时改为按草图职责写谱，不再使用共享起音模板。→ (vn2, va, vc)。
    """
    bq, beat = g.bar_ql, g.beat_ql
    if voic is None:
        voic = _voicings(g, slots, bass, mel, final_t)
    if duties:
        return _quartet_by_duty(g, slots, bass, n_bars, final_t, voic, duties)
    vn2, va, vc = [], [], []
    bar_segs = _bar_segments(slots, n_bars, bq, final_t)
    for bi, segs in enumerate(bar_segs):
        t0 = bi * bq
        last = bi == n_bars - 1
        for a, b, k in segs:
            v = voic[k]
            if last:
                vn2.append([a, b - a, [v[1]] if v else None])
                va.append([a, b - a, [v[0]] if v else None])
                vc.append([a, b - a, [bass[k]]])
                continue
            if g.meter == '4/4':
                # 角色分工：中提琴承担和声支点；第二小提琴只在每拍后半拍应答。
                # 休止事件仍填满声部时间轴，导出时不会产生错位。
                va.append([a, b - a, [v[0]] if v else None])
                t = a
                while t < b - 1e-6:
                    in_beat = (t - t0) % beat
                    d = min(beat - in_beat, b - t)
                    vc.append([t, d, [bass[k]]])
                    lead = min(0.5, d)
                    vn2.append([t, lead, None])
                    if d > lead + 1e-6:
                        vn2.append([t + lead, d - lead, [v[1]] if v else None])
                    t += d
                continue
            t = a
            while t < b - 1e-6:
                in_beat = (t - t0) % beat
                d = min(beat - in_beat, b - t)
                if g.meter == '3/4':
                    vc.append([t, d, [bass[k]] if t == a else None])
                    play = abs(t - t0) > 1e-6
                    vn2.append([t, d, [v[1]] if v and play else None])
                    va.append([t, d, [v[0]] if v and play else None])
                else:
                    vc.append([t, d, [bass[k]]])
                    step = 0.5
                    u = t
                    while u < t + d - 1e-6:
                        e = min(step, t + d - u)
                        rest = g.meter == '6/8' and abs((u - t0) % beat) < 1e-6
                        vn2.append([u, e, [v[1]] if v and not rest else None])
                        va.append([u, e, [v[0]] if v and not rest else None])
                        u += e
                t += d
    return tuple(_to_bars(x, n_bars, bq) for x in (vn2, va, vc))


def orchestra_winds(g: SubGrammar, slots: List[Dict], bass: List[int], voic: List[List[int]],
                    n_bars: int, mel: _Mel, final_t: float, tutti: set, vc_bars: List[List]):
    """古典双管编制：全奏小节里长笛（高八度）/ 双簧管（同度）加倍旋律、大管加倍大提琴；
    圆号（自然号）只奏主音 / 属音上的和弦音长音，换音时与四个弦乐声部都避开平行五八度；
    定音鼓调成主 / 属两音，根音是主 / 属的小节在第一拍敲一下，末小节长音。
    → (fl, ob, hn, bn, tp) 每小节事件；非全奏小节休止。"""
    bq, beat = g.bar_ql, g.beat_ql
    rest_bar = [(0.0, bq, None)]
    by_bar: List[List] = [[] for _ in range(n_bars)]
    for on, d, m in mel.line:
        if on >= -1e-6:
            by_bar[min(n_bars - 1, int(on / bq + 1e-6))].append((on - int(on / bq + 1e-6) * bq, d, m))

    def double(bi, shift_hi, rng):
        ns = by_bar[bi]
        ms = [m for _o, _d, m in ns if m is not None]
        if bi not in tutti or not ms:
            return rest_bar
        shift = 12 if shift_hi and max(ms) + 12 <= rng[1] else 0
        if min(ms) + shift < rng[0] or max(ms) + shift > rng[1]:
            return rest_bar
        return [(o, d, None if m is None else [m + shift]) for o, d, m in ns]
    fl = [double(bi, True, FLUTE_RANGE) for bi in range(n_bars)]
    ob = [double(bi, False, OBOE_RANGE) for bi in range(n_bars)]
    bn = [vc_bars[bi] if bi in tutti else rest_bar for bi in range(n_bars)]
    dom = (g.tonic_pc + 7) % 12
    hn_flat: List[List] = []
    prev_h: Optional[int] = None
    for bi, segs in enumerate(_bar_segments(slots, n_bars, bq, final_t)):
        for a, b, k in segs:
            if bi not in tutti:
                hn_flat.append([a, b - a, None])
                prev_h = None
                continue
            r, q = tok_chord(slots[k]['tok'])
            pcs = {(r + i + g.tonic_pc) % 12 for i in QUALITIES[q]}
            opts = [x for x in range(HORN_RANGE[0], HORN_RANGE[1] + 1)
                    if x % 12 in pcs and x % 12 in (g.tonic_pc, dom)]
            opts.sort(key=lambda x: (abs(x - prev_h) if prev_h is not None else abs(x - 62)))
            t = slots[k]['t']
            moves = []
            if k and abs(a - t) < 1e-6:
                a0, a1 = mel.before(t), mel.onset(t)
                if a0 is not None and a1 is not None:
                    moves.append((a0, a1))
                moves.append((bass[k - 1], bass[k]))
                if voic[k - 1] and voic[k]:
                    moves += [(voic[k - 1][0], voic[k][0]), (voic[k - 1][1], voic[k][1])]
            h = next((x for x in opts if prev_h is None or x == prev_h or not any(
                parallel_motion([prev_h], [x], [y0], [y1]) for y0, y1 in moves)), None)
            hn_flat.append([a, b - a, [h] if h is not None else None])
            prev_h = h
    hn = _to_bars(hn_flat, n_bars, bq)
    tonic_t = next(x for x in range(43, 55) if x % 12 == g.tonic_pc)
    drums = {0: tonic_t, 7: tonic_t - 5}
    tp = []
    for bi, segs in enumerate(_bar_segments(slots, n_bars, bq, final_t)):
        root = tok_chord(slots[segs[0][2]]['tok'])[0]
        if bi not in tutti or root not in drums:
            tp.append(rest_bar)
        elif bi == n_bars - 1:
            tp.append([(0.0, bq, [drums[root]])])
        else:
            tp.append([(0.0, beat, [drums[root]]), (beat, bq - beat, None)])
    return fl, ob, hn, bn, tp


# ======================================================================== 主流程
def _one_clean(g, seed, temperature, total_bars, layout, tonic, tonic_pc, key_sharps,
               title, tempo, instrument, max_tries, sketch, round_no):
    last = None
    for attempt in range(max_tries):
        sd = f'{seed}/{attempt}' if attempt else str(seed)
        if round_no:
            sd = f'{sd}/r{round_no}'
        try:
            res = _compose_once(g, sd, float(temperature), int(total_bars), layout, tonic,
                                tonic_pc, int(key_sharps), title, tempo, instrument, sketch)
        except _Dead as e:
            last = str(e)
            continue
        if not res['violations']:
            res['seed_used'] = sd
            res['attempts'] = attempt + 1
            return res, None
        last = '；'.join(f"{v['rule']} 第{v['bar']}小节 {v['msg']}" for v in res['violations'][:3])
    return None, last


def compose(script: Dict[str, Any], sub: str, mode: str = 'major', key_sharps: int = 0,
            total_bars: int = 32, seed: Any = 0, temperature: float = 1.0,
            layout: str = 'auto', title: str = '', tempo: Optional[int] = None,
            instrument: Optional[str] = None, max_tries: int = 40,
            theme_memory: Optional[bool] = None,
            composer_sketch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """按规则脚本作一首带钢琴伴奏的旋律曲，返回 {'spec', 'plan', 'units', 'slots',
    'violations', 'seed_used', 'attempts'}；所有硬规则 0 违例才返回。

    composer_sketch 给出时，曲式、主题约束和四重奏声部职责来自草图。听审不及格就按
    评语改草图并重写乐谱，及格才返回。"""
    g = SubGrammar(script, sub, mode)
    g.theme_policy = dict(g.s.get('theme_memory') or {})
    if theme_memory is not None:
        g.theme_policy['enabled'] = theme_memory
    instrument = instrument or g.melody_instrument
    tonic = tonic_from_sharps(int(key_sharps), mode)
    _l, tonic_pc = tonic_letter_pc(tonic)
    g.tonic_pc = tonic_pc
    sketch = composer_sketch
    history: List[Dict[str, Any]] = []
    reviser_rng = random.Random(f'composer-revise|{seed}')
    # 先把第一句听完。对照参照句输掉，就只改这一句，不往下铺。
    if sketch and sketch.get('phrase') and int(sketch.get('bars') or total_bars) > UNIT:
        probe_src = sketch
        for rnd in range(4):
            probe = copy_sketch(probe_src)
            probe['bars'] = UNIT
            probe['sections'] = [dict(probe_src['sections'][0])]
            res, last = _one_clean(g, seed, temperature, UNIT, layout, tonic, tonic_pc,
                                   int(key_sharps), title, tempo, instrument, max_tries, probe, rnd)
            if res is None:
                probe_src = next_sketch(probe_src, {'ok': False, 'compose_failed': True,
                                                    'jury': {'standard': 'pairwise-listening',
                                                             'pass': False}}, reviser_rng)
                continue
            report = assess_realization(res['spec'], res['units'], probe, g.bar_ql)
            history.append({'round': rnd + 1, 'sketch': copy_sketch(probe_src), 'report': report})
            if report['ok']:
                sketch = copy_sketch(probe_src)
                sketch['phrase'] = probe['phrase']
                break
            if rnd == 3:
                comment = (report.get('jury') or {}).get('comment') or '更想听参照句'
                res['spec']['composer'] = {
                    'enabled': True, 'ok': False, 'rounds': history, 'fallback': None,
                    'stopped': '第一句没有胜过参照，只留下这八小节。' + comment,
                }
                return res
            probe_src = next_sketch(probe_src, report, reviser_rng)
        else:
            raise RuntimeError('第一句没有留下，不往下写。')
    # 听审不及格不交卷。上限只是防止模型一直否决时停不下来。
    rounds = 1 if sketch is None else 6
    last = None
    last_report = None
    for rnd in range(rounds):
        res, last = _one_clean(g, seed, temperature, total_bars, layout, tonic, tonic_pc,
                               int(key_sharps), title, tempo, instrument, max_tries, sketch, rnd)
        if res is None:
            if sketch is None or rnd == rounds - 1:
                break
            sketch = next_sketch(sketch, {'ok': False, 'compose_failed': True,
                                          'has_return': False, 'transform_relaxed': True,
                                          'jury': last_report.get('jury') if last_report else {}},
                                 reviser_rng)
            continue
        if sketch is None:
            return res
        report = assess_realization(res['spec'], res['units'], sketch, g.bar_ql)
        last_report = report
        history.append({'round': rnd + 1, 'sketch': copy_sketch(sketch), 'report': report})
        res['spec']['composer'] = {'enabled': True, 'ok': report['ok'],
                                   'rounds': history, 'fallback': None}
        if report['ok']:
            return res
        if rnd == rounds - 1:
            break
        sketch = next_sketch(sketch, report, reviser_rng)
    if last_report is not None:
        jury = last_report.get('jury') or {}
        raise RuntimeError(
            '听审未通过，不交付乐谱。'
            f"否决 {jury.get('veto') or '平均分'}，评语：{jury.get('comment') or '无'}")
    raise RuntimeError(f'{max_tries} 个种子分支都未能生成零违例的乐曲：{last}')


def copy_sketch(sketch: Dict[str, Any]) -> Dict[str, Any]:
    return {'key_sharps': sketch.get('key_sharps'), 'mode': sketch.get('mode'),
            'bars': sketch.get('bars'), 'theme': dict(sketch.get('theme') or {}),
            'phrase': None if not sketch.get('phrase') else {
                'bars': sketch['phrase'].get('bars'), 'degree': sketch['phrase'].get('degree'),
                'notes': [dict(n) for n in sketch['phrase'].get('notes') or []]},
            'sections': [dict(s) for s in sketch.get('sections') or []],
            'voices': dict(sketch.get('voices') or {})}


def _theme_lock(g: SubGrammar, pref: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not pref:
        return None
    want = pref.get('rhythm_template')
    for block in (g.s.get('rhythm') or {}).get('templates', {}).values():
        for it in block.get('items') or []:
            if it['id'] == want:
                # 只锁前两小节。四小节同一个节奏型听起来像在原地踏步。
                return {'pattern': it['pattern'], 'rule': it['id'],
                        'bars': min(2, int(pref.get('bars') or 2))}
    return None


def _theme_fit(unit: Dict[str, Any], pref: Dict[str, Any]) -> int:
    score = 0
    formula = unit.get('formula') or {}
    chords = formula.get('chords')
    if chords and cadence_direction(chords) == pref.get('cadence'):
        score += 3
    if unit.get('contours') and unit['contours'][0] == pref.get('contour'):
        score += 2
    n = int(pref.get('bars') or 0)
    if n and all(b.get('rule') == pref.get('rhythm_template') for b in unit['bars'][:n]):
        score += 2
    durs = {x['d'] for x in unit['notes'] if not x['rest'] and 0 <= x.get('bar', -1) < n}
    if len(durs) >= 2:
        score += 1
    return score


def _compose_once(g: SubGrammar, seed: str, temp: float, total_bars: int, layout: str,
                  tonic: str, tonic_pc: int, key_sharps: int, title: str,
                  tempo: Optional[int], instrument: str,
                  sketch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tag = f'leadsheet|{g.style}|{g.sub}|{g.mode}|{seed}'
    rng = random.Random(tag)
    plan = plan_form(g, rng, total_bars, layout, sketch=sketch)
    lo, hi = melody_range(g, instrument)
    center = (lo + hi) / 2
    bq = g.bar_ql
    pickup_ql = plan['pickup'][0] if plan['pickup'] else 0.0
    contours = g.s['melody']['contour_templates'] or [{'id': '-', 'shape': [0.0] * 8, 'p': 1,
                                                       'name': '平'}]
    first_deg = {int(k): p for k, p, _n in g.s['melody']['first_degree']}
    sections = plan['sections']
    if sketch:
        mem = _sketch_memory(sections)
    elif g.s.get('section_memory_enabled', True):
        mem = _memory_plan(sections)
    else:
        mem = [{'kind': 'new', 'src': None, 'head': s['label'], 'tail': s['label']}
               for s in sections]
    policy = getattr(g, 'theme_policy', {})
    # 草图已经规定段间关系；主题记忆不再另抽一小节引用。
    refs = ([None] * len(sections) if sketch else
            plan_references(len(sections), policy, rng))
    theme_bars = min(2, max(1, round(policy.get('duration_median_ql', bq) / bq)))
    theme_trace = []
    done: Dict[str, Dict[str, Any]] = {}
    units: List[Dict[str, Any]] = []
    prev_ch: Tuple[str, str] = ('BOS', 'BOS')
    prev_note: Optional[Tuple[int, int]] = None
    carry: Tuple[Optional[str], int] = (None, 0)
    last_label = sections[-1]['label']
    for u, sec in enumerate(sections):
        L = sec['label']
        kind, src_label = mem[u]['kind'], mem[u]['src']
        # Existing whole-section memory owns these units. Do not report an
        # unused v1 reference as a successfully realized new-module plan.
        if kind != 'new':
            refs[u] = None
        t_base = u * UNIT * bq
        if kind in ('repeat', 'quote'):
            src = done[src_label]
            unit = dict(src, letter=L, copy_of=src['index'], variant_of=None,
                        transform='original', transform_status='realized')
            if kind == 'quote':
                done[L] = dict(unit, index=u)
        elif kind == 'transform':
            src = done[src_label]
            final = _section_must_close(L, mem, sections, last_label, sketch)
            nxt = done.get(mem[u + 1]['head']) if u + 1 < len(sections) else None
            next_tok = nxt['slots'][0]['tok'] if nxt else None
            next_midi = next((x['midi'] for x in nxt['notes']
                              if not x['rest'] and not x.get('pick')), None) if nxt else None
            span = int((sketch or {}).get('theme', {}).get('bars') or 4)
            unit = None
            for _local in range(6):
                try:
                    cand = _new_unit(g, rng, temp, u, L, final, plan, prev_ch, carry, next_tok,
                                     next_midi, prev_note, contours, center, lo, hi, tonic_pc,
                                     first_deg, pickup_ql, pool=units,
                                     transform=(src, mem[u]['transform'], span),
                                     varied=bool(sketch))
                except _Dead:
                    continue
                unit = cand
                unit['transform_status'] = 'realized'
                break
            if unit is None:
                try:
                    unit = _new_unit(g, rng, temp, u, L, final, plan, prev_ch, carry, next_tok,
                                     next_midi, prev_note, contours, center, lo, hi, tonic_pc,
                                     first_deg, pickup_ql, pool=units, varied=bool(sketch))
                except _Dead as e:
                    raise _Dead(f'第 {u + 1} 段变形失败：{e}') from e
                unit['transform_status'] = 'relaxed'
            unit['transform'] = mem[u]['transform']
            unit['variant_of'] = None
            done[L] = unit
        else:
            src = done[src_label] if kind == 'variant' else None
            final = _section_must_close(L, mem, sections, last_label, sketch)
            # 下一段的开头若已确定（再现 / 引用 / 变奏都沿用来源段开头），本段末尾要能接上它
            nxt = done.get(mem[u + 1]['head']) if u + 1 < len(sections) else None
            next_tok = nxt['slots'][0]['tok'] if nxt else None
            next_midi = next((x['midi'] for x in nxt['notes']
                              if not x['rest'] and not x.get('pick')), None) if nxt else None
            self_follow = any(mem[i]['tail'] == L and mem[i + 1]['head'] == mem[u]['head']
                              for i in range(len(sections) - 1))
            unit = None
            ref = refs[u]
            theme_head = (units[ref], theme_bars) if ref is not None and src is None else None
            pref = None
            if u == 0 and sketch and src is None:
                pref = dict(sketch.get('theme') or {})
                if sketch.get('phrase'):
                    pref['phrase'] = sketch['phrase']
            tries = 4 if pref else 6
            best, best_score = None, -1
            for _local in range(tries):
                try:
                    cand = _new_unit(g, rng, temp, u, L, final, plan, prev_ch, carry, next_tok,
                                     next_midi, prev_note, contours, center, lo, hi, tonic_pc,
                                     first_deg, pickup_ql, head=src, pool=units,
                                     theme_head=theme_head if _local < 5 else None,
                                     theme_pref=pref, varied=bool(sketch))
                except _Dead:
                    continue
                if self_follow:
                    ps = [x for x in cand['notes'] if not x['rest'] and not x.get('pick')]
                    if not (g.attested(cand['slots'][-1]['tok'], cand['slots'][0]['tok'])
                            and leap_ok(g, ps[-1]['midi'], ps[0]['midi'])):
                        continue
                if pref:
                    score = _theme_fit(cand, pref)
                    if score > best_score:
                        best, best_score = cand, score
                    if best_score >= 7:
                        break
                    continue
                unit = cand
                break
            if pref:
                unit = best
                if unit is not None:
                    unit['theme_fit'] = best_score
            if unit is None:
                raise _Dead(f'第 {u + 1} 段无法与自身再现衔接')
            unit['variant_of'] = src['index'] if src is not None else None
            done[L] = unit
        theme_trace.append({
            'section': u + 1, 'source_section': None if refs[u] is None else refs[u] + 1,
            'inherited_source_label': src_label if kind != 'new' else None,
            'status': ('section_memory' if kind != 'new' else
                       'realized' if unit.get('theme_bars') else
                       'relaxed' if refs[u] is not None else 'new'),
            'bars': unit.get('theme_bars', 0), 'transpose': unit.get('theme_shift'),
            'reason': ('bounded theme/harmony/melody search exhausted'
                       if kind == 'new' and refs[u] is not None and not unit.get('theme_bars')
                       else None),
        })
        units.append(dict(unit, index=u, t_base=t_base, label=L, role=sec['role'],
                          memory=kind, memory_src=src_label,
                          transform=unit.get('transform') or sec.get('transform') or 'original'))
        last_slot = unit['slots'][-1]['tok']
        prev2 = unit['slots'][-2]['tok'] if len(unit['slots']) > 1 else prev_ch[1]
        prev_ch = (prev2, last_slot)
        carry = tail_run(unit['slots'], carry)
        ps = [x for x in unit['notes'] if not x['rest']]
        prev_note = (ps[-1]['midi'], _leap_state(ps[-2]['midi'] if len(ps) > 1 else None,
                                                 ps[-1]['midi']))
    result = _assemble(g, plan, units, tonic, tonic_pc, key_sharps, title, tempo, instrument,
                       lo, hi, pickup_ql)
    result['theme_memory'] = {'version': int(policy.get('version', 5)),
        'enabled': bool(policy.get('enabled')),
        'relations': theme_trace,
        'intra_phrase': units[0].get('learned_motif') if units else None,
        'evaluation': evaluate_phrases(phrases_from_spec(
            result['spec'], [(pickup_ql + i * UNIT * bq, pickup_ql + (i + 1) * UNIT * bq)
                             for i in range(len(units))],
            part_index=5 if g.texture == 'orchestra' else 0))}
    result['spec']['theme_memory'] = result['theme_memory']
    return result


def _motif_from_unit(unit: Dict[str, Any], span_bars: int) -> Optional[Motif]:
    notes = [x for x in unit['notes']
             if not x.get('pick') and not x['rest'] and 0 <= x.get('bar', -1) < span_bars]
    notes = notes[:16]
    if len(notes) < 2:
        return None
    return Motif.from_midis([x['midi'] for x in notes], [x['d'] for x in notes], 'theme')


def _place_transformed(g, motif: Motif, slots: List[Dict], lo: int, hi: int,
                       tonic_pc: int) -> Optional[List[Tuple[float, float, int]]]:
    """把变形后的音程落到本次和声上。强拍必须是和弦音；放不进就换起始音。"""
    bq = g.bar_ql
    budget = UNIT * bq
    center = (lo + hi) // 2
    starts = list(range(max(lo, center - 12), min(hi, center + 12) + 1))
    for start in starts:
        ev, t, prev, ok = [], 0.0, None, True
        for midi, dur in motif.notes_from(start):
            if t >= budget - 1e-6:
                break
            dur = max(0.25, round(min(float(dur), budget - t) * 4) / 4)
            if t + dur > budget + 1e-6:
                dur = round((budget - t) * 4) / 4
            if dur < 0.25 - 1e-6:
                break
            on = round(t % bq, 4)
            tok = _tok_at(slots, t)
            st = strength(on if on < bq else 0.0, bq, g.beat_ql)
            if not lo <= int(midi) <= hi:
                ok = False
                break
            cl = note_class(int((midi - tonic_pc) % 12), tok, g.mode)
            pitch = int(midi)
            if g.strict_r01 and st == 'S' and cl != 'CT':
                # 挪到两度以内的和弦音，保住变形的大致位置。
                alts = [pitch + d for d in (0, 1, -1, 2, -2)
                        if lo <= pitch + d <= hi and note_class(
                            int((pitch + d - tonic_pc) % 12), tok, g.mode) == 'CT']
                if not alts:
                    ok = False
                    break
                pitch = min(alts, key=lambda p: abs(p - midi))
            if prev is not None and not leap_ok(g, prev, pitch):
                ok = False
                break
            ev.append((round(t, 4), dur, pitch))
            prev = pitch
            t = round(t + dur, 4)
        if ok and len(ev) >= 2 and t >= 1.0:
            return ev
    return None


def _locked_skeleton(events: List[Tuple[float, float, int]], bq: float):
    skel = []
    t = 0.0
    for on, dur, midi in events:
        if on > t + 1e-6:
            skel.append({'t': t, 'd': round(on - t, 4), 'rest': True,
                         'bar': int(t // bq), 'on': round(t % bq, 4)})
        skel.append({'t': on, 'd': dur, 'rest': False, 'bar': int(on // bq),
                     'on': round(on % bq, 4), 'fixed': midi, 'transform': True})
        t = round(on + dur, 4)
    end = math.ceil(t / bq - 1e-9) * bq
    end = min(end, UNIT * bq)
    if end > t + 1e-6:
        skel.append({'t': t, 'd': round(end - t, 4), 'rest': True,
                     'bar': int(t // bq), 'on': round(t % bq, 4)})
        t = end
    return skel, min(UNIT, int(round(t / bq)))


def _pattern_of(skel: List[Dict], bar: int) -> str:
    bits = []
    for x in skel:
        if x.get('bar') != bar:
            continue
        on = round(float(x.get('on') or 0), 3)
        bits.append(f"{on:g}{'r' if x.get('rest') else 'n'}")
    return ' '.join(bits) or '0r'


_PHRASE_QL = {'whole': 4.0, 'dotted_half': 3.0, 'half': 2.0, 'dotted_quarter': 1.5,
              'quarter': 1.0, 'dotted_eighth': 0.75, 'eighth': 0.5, '16th': 0.25}
_SCALE_STEPS = {'major': [0, 2, 4, 5, 7, 9, 11], 'minor': [0, 2, 3, 5, 7, 8, 10]}


def _realize_phrase(g, phrase, slots, tonic_pc, lo, hi, bq):
    """把音级进行放进已经排好的和弦。强拍不是和弦音时，就近挪到和弦音上。"""
    scale = _SCALE_STEPS[g.mode]
    center = (lo + hi) / 2.0
    # 全音域的小提琴高把位在这套音色里是尖叫。一句只在中央音附近的十度里走。
    sing_lo = max(lo, int(round(center)) - 5)
    sing_hi = min(hi, int(round(center)) + 7)
    index = int(phrase['degree']) - 1
    octave0 = 0
    t = 0.0
    prev = None
    out = []
    first = True
    for ev in phrase['notes']:
        dur = _PHRASE_QL[ev['dur']]
        bar = int(t // bq + 1e-6)
        on = round(t - bar * bq, 4)
        if ev.get('rest'):
            out.append({'t': t, 'd': dur, 'rest': True, 'bar': bar, 'on': on})
            t = round(t + dur, 4)
            continue
        if not first:
            index += int(ev.get('step') or 0)
        tok = _tok_at(slots, t)
        strong = strength(on, bq, g.beat_ql) == 'S'

        def candidates(idx):
            pc = (tonic_pc + scale[idx % 7]) % 12
            return [m for m in range(sing_lo, sing_hi + 1) if m % 12 == pc]

        step = 0 if first else int(ev.get('step') or 0)
        pool = candidates(index) or [int(center)]
        if first:
            midi = min(pool, key=lambda m: abs(m - center))
            first = False
        else:
            def rank(m):
                dist = m - prev
                wrong = (step > 0 and dist < 0) or (step < 0 and dist > 0)
                return (wrong, abs(dist))
            midi = min(pool, key=rank)
        if strong and note_class((midi - tonic_pc) % 12, tok, g.mode) != 'CT':
            best = None
            for delta in (1, -1, 2, -2, 3, -3):
                trial_i = index + delta
                near = candidates(trial_i)
                if not near:
                    continue
                trial = min(near, key=lambda m: abs(m - midi))
                if abs(trial - midi) > 4:
                    continue
                if note_class((trial - tonic_pc) % 12, tok, g.mode) == 'CT':
                    best = (trial_i, trial)
                    break
            if best is None:
                raise _Dead('强拍音级对不上和弦')
            index, midi = best
        if prev is not None and abs(midi - prev) > 12:
            raise _Dead('旋律出现超过八度的坠落')
        if not lo <= midi <= hi:
            raise _Dead('音级超出音域')
        out.append({'t': t, 'd': dur, 'rest': False, 'bar': bar, 'on': on,
                    'phrase_target': int(midi)})
        prev = midi
        t = round(t + dur, 4)
    return out


def _new_unit(g, rng, temp, u, L, final, plan, prev_ch, carry, next_tok, next_midi, prev_note,
              contours, center, lo, hi, tonic_pc, first_deg, pickup_ql, head=None, pool=(),
              theme_head=None, theme_pref=None, transform=None, varied: bool = False):
    """head：变奏段的来源段——前 HEAD_BARS 小节的和声 / 节奏 / 音高原样沿用，其后重写。
    pool：已写好的段落，供跨段动机回忆取材。"""
    bq = g.bar_ql
    H = HEAD_BARS if head is not None else 0
    T = theme_head[1] if theme_head is not None else 0
    cadence_dir = theme_pref.get('cadence') if theme_pref and not final else None
    theme_lock = _theme_lock(g, theme_pref) if theme_pref and head is None and theme_head is None else None
    if head is not None:
        head_slots = [dict(sl) for sl in head['slots'] if sl['bar'] < H]
        p2 = head_slots[-2]['tok'] if len(head_slots) > 1 else prev_ch[1]
        hu = harmony_unit(g, rng, temp, first=False, final=final,
                          prev=(p2, head_slots[-1]['tok']), carry=tail_run(head_slots, carry),
                          next_tok=next_tok, bars_from=H, cadence_dir=cadence_dir,
                          varied=varied)
        hu['slots'] = head_slots + hu['slots']
        bars = rhythm_bars(g, rng, final, prefix=head['bars'][:H])
    else:
        hu = harmony_unit(g, rng, temp, first=(u == 0), final=final, prev=prev_ch, carry=carry,
                          next_tok=next_tok, cadence_dir=cadence_dir, varied=varied)
        bars = rhythm_bars(g, rng, final,
                           prefix=theme_head[0]['bars'][:T] if theme_head else None,
                           theme_lock=theme_lock)
    learned_motif = (apply_learned_motif_rhythm(g, rng, bars)
                     if u == 0 and getattr(g, 'theme_policy', {}).get('enabled')
                     and theme_pref is None else None)
    slots = apply_learned_motif_harmony(g, hu['slots'], learned_motif)
    hu['slots'] = slots
    for sl in slots:
        sl['t_rel'] = sl['bar'] * bq + sl['beat'] * g.beat_ql
    locked_skel, locked_bars = [], 0
    if transform is not None:
        src_unit, transform_kind, span = transform
        motif = _motif_from_unit(src_unit, min(int(span), 4))
        if motif is None:
            raise _Dead('来源主题太短，无法变形')
        placed = _place_transformed(g, transform_motif(motif, transform_kind), slots, lo, hi,
                                    tonic_pc)
        if placed is None:
            raise _Dead('变形与本次和声不兼容')
        locked_skel, locked_bars = _locked_skeleton(placed, bq)
        covered = sum(x['d'] for x in locked_skel)
        if locked_bars < 1 or abs(covered - locked_bars * bq) > 1e-3:
            raise _Dead('变形时值没有铺满小节')
        for i in range(min(locked_bars, len(bars))):
            bars[i] = {'pattern': _pattern_of(locked_skel, i),
                       'rule': f'composer:{transform_kind}', 'copy': None}
    recall = _recall_bars(g, rng, bars, slots, pool, max(H + T, locked_bars), tonic_pc, lo, hi) \
        if pool else {}
    # 音符骨架：(相对段首时间, 时值, 是否休止)
    skel = []
    if u == 0 and plan['pickup']:
        for on, d, r in parse_pattern(plan['pickup'][1], pickup_ql):
            skel.append({'t': on - pickup_ql, 'd': d, 'rest': r, 'bar': -1, 'pick': True})
    if head is not None:
        skel += [dict(x, fixed=None if x['rest'] else x['midi'])
                 for x in head['notes'] if not x.get('pick') and 0 <= x['bar'] < H]
    theme_shift = None
    if theme_head is not None:
        source = [x for x in theme_head[0]['notes'] if not x.get('pick') and 0 <= x['bar'] < T]
        sounded = [x for x in source if not x['rest']]
        dst = [{'tok': _tok_at(slots, x['t']), 'st': strength(x['on'], bq, g.beat_ql)}
               for x in sounded]
        theme_shift = next((shift for shift in (0, 2, -2, 5, -5, 7, -7)
                            if _shift_ok(g, [x['midi'] for x in sounded],
                                         [x['tok'] for x in sounded], dst, shift,
                                         tonic_pc, lo, hi)), None)
        if theme_shift is None or not sounded:
            raise _Dead('主题与本次和声候选不兼容，重新搜索和声')
        skel += [dict(x, fixed=None if x['rest'] else x['midi'] + theme_shift)
                 for x in source]
    if locked_skel:
        skel += locked_skel
    for i, b in enumerate(bars):
        if i < H + T or i < locked_bars:
            continue
        ms = iter(recall.get(i) or ())
        for on, d, r in parse_pattern(b['pattern'], bq):
            x = {'t': i * bq + on, 'd': d, 'rest': r, 'bar': i, 'on': on}
            if i in recall and not r:
                x['fixed'] = next(ms)
                x['recall'] = True
            skel.append(x)
    phrase = (theme_pref or {}).get('phrase') if u == 0 and head is None and not locked_skel else None
    if phrase:
        skel = [x for x in skel if x.get('pick')] + _realize_phrase(
            g, phrase, slots, tonic_pc, lo, hi, bq)
    phr = [_pick(rng, [(c, c['p']) for c in contours]) for _ in range(UNIT // 4)]
    if head is not None:
        by_id = {c['id']: c for c in contours}
        phr[0] = by_id.get(head['contours'][0], phr[0])
    elif theme_pref and theme_pref.get('contour'):
        by_id = {c['id']: c for c in contours}
        picked = by_id.get(theme_pref['contour'], phr[0])
        span = (max(picked['shape']) - min(picked['shape'])) if picked.get('shape') else 0
        if span < 5:
            picked = max(contours, key=lambda c: (max(c['shape']) - min(c['shape']))
                         if c.get('shape') else 0)
        phr[0] = picked
    pitched = [x for x in skel if not x['rest']]
    if not pitched:
        raise _Dead('整段没有音符')
    if varied:
        for i in range(UNIT):
            if not any(x['bar'] == i and not x['rest'] for x in skel):
                raise _Dead('段内出现空小节')
    for x in pitched:
        t = x['t']
        x['tok'] = _tok_at(slots, t)
        x['st'] = 'W' if x.get('pick') else strength(x['on'], bq, g.beat_ql)
        ph = max(0, min(len(phr) - 1, int(max(t, 0) // (4 * bq))))
        frac = (max(t, 0) - ph * 4 * bq) / (4 * bq)
        shape = phr[ph]['shape']
        pos = frac * (len(shape) - 1)
        i0 = int(pos)
        i1 = min(i0 + 1, len(shape) - 1)
        if x.get('phrase_target') is not None:
            x['target'] = x['phrase_target']
            x['motif_target'] = True
        else:
            x['target'] = center + shape[i0] + (shape[i1] - shape[i0]) * (pos - i0)
    if learned_motif is not None and learned_motif.get('core_shape'):
        src = [x for x in pitched
               if learned_motif['source_bar'] <= x['bar'] <
               learned_motif['source_bar'] + learned_motif['span_bars']]
        # The learner stores only a five-symbol contour alphabet. Convert it to
        # representative motions; harmony and legality still choose actual notes.
        representative = {-2: -5, -1: -2, 0: 0, 1: 2, 2: 5}
        for x, symbol in zip(src[1:], learned_motif['core_shape']):
            x['motif_interval'] = representative[int(symbol)]
    # 照抄：节奏照抄的小节按学到的概率连音高一起照抄（pitch_same），
    # 或保持音程、整体移高 / 移低（模进，interval_same 中超出原样照抄的那部分）
    mc = g.s['rhythm']['melodic_copy']
    copy_pitch: Dict[int, Tuple[int, str]] = {}
    for i, b in enumerate(bars):
        if i >= H and b['copy'] is not None:
            st = mc.get(str(i - b['copy'])) or {}
            ps = st.get('pitch_same', 0.0)
            r = rng.random()
            if r < ps:
                copy_pitch[i] = (b['copy'], 'same')
            elif r < ps + max(0.0, st.get('interval_same', 0.0) - ps):
                copy_pitch[i] = (b['copy'], 'shift')
    if learned_motif is not None:
        for dst in learned_motif.get('target_bars') or [learned_motif['target_bar']]:
            for off in range(learned_motif['span_bars']):
                copy_pitch[dst + off] = (learned_motif['source_bar'] + off, 'motif')
    mids, realised = None, {}
    # 求解失败时依次放弃：段内照抄 → 跨段回忆的音高（节奏保留）→ 与上一段末音的衔接（仅变奏段）
    attempts = [(copy_pitch, prev_note, True), ({}, prev_note, True), ({}, prev_note, False)]
    if head is not None:
        attempts.append(({}, None, False))
    kept_recall = True
    for cp, pn, keep in attempts:
        if not keep and recall:
            for x in pitched:
                if x.pop('recall', False):
                    x['fixed'] = None
            kept_recall = False
        try:
            mids, realised = _melody_with_copies(
                g, rng, temp, pitched, cp, tonic_pc, lo, hi, pn, end_tonic=final,
                first_deg=first_deg if u == 0 else None, next_midi=next_midi)
            break
        except _Dead:
            continue
    if mids is None:
        raise _Dead(f'第 {u + 1} 段旋律无解')
    for x, m in zip(pitched, mids):
        # 音级句已经定了音。动态规划再抽样会走出调外音和高把位。
        x['midi'] = x['phrase_target'] if x.get('phrase_target') is not None else m
    if final and pitched and (pitched[-1]['midi'] - tonic_pc) % 12 != 0:
        prev = pitched[-2]['midi'] if len(pitched) > 1 else pitched[-1]['midi']
        cands = [m for m in range(max(lo, prev - 7), min(hi, prev + 7) + 1)
                 if (m - tonic_pc) % 12 == 0]
        if cands:
            pitched[-1]['midi'] = min(cands, key=lambda m: abs(m - prev))
    if varied:
        seq = [x['midi'] for x in pitched if x.get('bar', -1) >= 0]
        if any(abs(a - b) > 12 for a, b in zip(seq, seq[1:])):
            raise _Dead('旋律出现超过八度的坠落')
    if learned_motif is not None:
        def motif_events(start: int):
            end = start + learned_motif['span_bars']
            return [(x['midi'], x['d']) for x in pitched if start <= x['bar'] < end]
        targets = learned_motif.get('target_bars') or [learned_motif['target_bar']]
        motif_scores = [similarity(motif_events(learned_motif['source_bar']), motif_events(dst))
                        for dst in targets]
        if min(motif_scores) < float(getattr(g, 'theme_policy', {}).get('match_threshold', .82)):
            raise _Dead('生成的主题回答未达到训练模型的相似度阈值')
        learned_motif = dict(learned_motif,
                             realized_similarity=round(min(motif_scores), 6),
                             realized_similarities=[round(x, 6) for x in motif_scores])
    for x in skel:
        x.pop('fixed', None)
        x.pop('recall', None)
    for i, b in enumerate(bars):
        b['pitch_copy'] = realised.get(i)
        b['head'] = i < H
        if b.get('recall') and not kept_recall:
            b['recall'] = (b['recall'][0], None)
    if learned_motif is not None:
        learned_motif = dict(learned_motif)
        learned_motif['pitch_relations'] = {
            str(dst + off): realised.get(dst + off)
            for dst in (learned_motif.get('target_bars') or [learned_motif['target_bar']])
            for off in range(learned_motif['span_bars'])}
    return {'letter': L, 'copy_of': None, 'slots': slots, 'bars': bars, 'notes': skel,
            'formula': hu['formula'], 'contours': [c['id'] for c in phr],
            'half': hu['half'], 'index': u, 'head_bars': H,
            'theme_bars': T, 'theme_shift': theme_shift,
            'learned_motif': learned_motif}


def _memory_say(un: Dict[str, Any]) -> str:
    kind = un.get('memory', 'new')
    if kind == 'repeat':
        return f'再现第 {un["copy_of"] + 1} 段'
    if kind == 'quote':
        return f'引用第 {un["copy_of"] + 1} 段（{un["memory_src"]}）'
    if kind == 'variant':
        h = un.get('head_bars', 0)
        return (f'变奏第 {un["variant_of"] + 1} 段（{un["memory_src"]}）：'
                f'前 {h} 小节沿用，后 {UNIT - h} 小节重写')
    if kind == 'transform':
        status = '已实现' if un.get('transform_status') == 'realized' else '已放宽'
        return f"变形 {un.get('transform')} 自 {un.get('memory_src')}（{status}）"
    return '新材料'


def _bar_say(b: Dict[str, Any], b0: int, variant_of: Optional[int], i: int, head: int) -> str:
    """单小节的节奏规则 + 记忆来源（小节号为全曲编号）。"""
    if variant_of is not None and i < head:
        return f'{b["rule"]}（沿用第 {variant_of * UNIT + i + 1} 小节）'
    s = b['rule']
    rc = b.get('recall')
    if rc:
        say = '仅节奏' if rc[1] is None else '原样' if rc[1] == 0 else f'模进{rc[1]:+d}'
        return f'{s}（回忆第 {rc[0] + 1} 小节，{say}）'
    if b['copy'] is not None:
        s += f'←{b0 + b["copy"] + 1}'
        pc = b.get('pitch_copy')
        if pc is not None:
            s += '（音高照抄）' if pc[1] == 0 else f'（模进{pc[1]:+d}）'
    return s


def _tok_at(slots: List[Dict], t: float) -> str:
    tok = slots[0]['tok']
    for sl in slots:
        if sl['t_rel'] <= t + 1e-6:
            tok = sl['tok']
    return tok


def _recall_pool(pool) -> List[Dict[str, Any]]:
    """已写好的段落里可供回忆的小节（同节奏同音高的只留第一次出现）。"""
    out, seen = [], set()
    for un in pool:
        for b in range(UNIT):
            xs = [x for x in un['notes'] if x['bar'] == b and not x['rest'] and not x.get('pick')]
            key = (un['bars'][b]['pattern'], tuple(x['midi'] for x in xs))
            if len(xs) < 2 or key in seen:
                continue
            seen.add(key)
            out.append({'bar': un['index'] * UNIT + b, 'pattern': key[0],
                        'rule': un['bars'][b]['rule'], 'midis': list(key[1]),
                        'toks': [x['tok'] for x in xs]})
    return out


def _recall_bars(g, rng, bars, slots, pool, first, tonic_pc, lo, hi) -> Dict[int, List[int]]:
    """跨段动机回忆：段内第 first..UNIT-2 小节（未在段内照抄的）按学到的概率换成前面段落某小节的
    节奏与音高（原样或模进）。只取放到本小节和弦下仍守强拍和弦音、不新增半音的来源。
    返回 {小节: 固定音高}，并就地改写 bars（段内照抄这些小节的也跟着换节奏）。"""
    mr = g.s['rhythm'].get('motif_recall') or {}
    p_same, p_shift = float(mr.get('p_same', 0.0)), float(mr.get('p_shift', 0.0))
    if p_same + p_shift <= 0:
        return {}
    cands = _recall_pool(pool)
    bq = g.bar_ql
    shifts = sorted((k for k in range(-7, 8) if k), key=lambda k: (abs(k), k < 0))
    out: Dict[int, List[int]] = {}
    for i in range(first, UNIT - 1):
        if bars[i]['copy'] is not None:
            continue
        r = rng.random()
        if r >= p_same + p_shift:
            continue
        ks = [0] if r < p_same else shifts
        order = list(cands)
        rng.shuffle(order)
        for c in order:
            ons = [on for on, _d, rest in parse_pattern(c['pattern'], bq) if not rest]
            if len(ons) != len(c['midis']):
                continue
            dst = [{'tok': _tok_at(slots, i * bq + on), 'st': strength(on, bq, g.beat_ql)}
                   for on in ons]
            k = next((k for k in ks
                      if _shift_ok(g, c['midis'], c['toks'], dst, k, tonic_pc, lo, hi)), None)
            if k is None:
                continue
            bars[i] = {'pattern': c['pattern'], 'rule': c['rule'], 'copy': None,
                       'recall': (c['bar'], k)}
            out[i] = [m + k for m in c['midis']]
            break
    for b in bars:
        if b['copy'] is not None:
            b['pattern'], b['rule'] = bars[b['copy']]['pattern'], bars[b['copy']]['rule']
    return out


def _shift_ok(g, src: List[int], src_toks: List[str], dst: List[Dict], k: int, tonic_pc: int,
              lo: int, hi: int) -> bool:
    """来源音高移 k 个半音、放到目标和弦下：仍在音域内、强拍仍守和弦音规则、不新增半音外音。"""
    for m, st, x in zip(src, src_toks, dst):
        n = m + k
        if not lo <= n <= hi:
            return False
        cl = note_class(int((n - tonic_pc) % 12), x['tok'], g.mode)
        if cl == 'CH' and note_class(int((m - tonic_pc) % 12), st, g.mode) != 'CH':
            return False
        if g.strict_r01 and x['st'] == 'S' and cl != 'CT':
            return False
    return True


def _melody_with_copies(g, rng, temp, pitched, copy_pitch, tonic_pc, lo, hi, prev_note,
                        end_tonic, first_deg, next_midi=None):
    """返回 (音高序列, {小节: 实际的照抄方式})。pitched 里带 fixed 的音（变奏段沿用的开头）
    在两轮求解中都固定。"""
    by_bar: Dict[int, List[Dict]] = {}
    for x in pitched:
        by_bar.setdefault(x['bar'], []).append(x)
    # 先整段求解一次；需要照抄音高的小节，在源小节确定后固定音高再求一次
    notes = [{'tok': x['tok'], 'st': x['st'], 'target': x['target'], 'force': x.get('fixed'),
              'motif_interval': x.get('motif_interval'),
              'motif_target': x.get('motif_target')}
             for x in pitched]
    if first_deg and notes[0]['force'] is None:
        best = max(first_deg, key=first_deg.get)
        notes[0]['target'] = notes[0]['target'] * 0.5 + 0.5 * (
            tonic_pc + best + 12 * round((notes[0]['target'] - tonic_pc - best) / 12))
    mids = melody_dp(g, rng, temp, notes, tonic_pc, lo, hi, prev_note, end_tonic, next_midi)
    if not copy_pitch:
        return mids, {}
    pos = {id(x): k for k, x in enumerate(pitched)}
    realised: Dict[int, Tuple[int, int]] = {}
    for dst in sorted(copy_pitch):
        srcb, kind = copy_pitch[dst]
        a, b = by_bar.get(srcb, []), by_bar.get(dst, [])
        if not a or len(a) != len(b) or any(x.get('fixed') is not None for x in b):
            continue
        # 源小节若本身也被照抄，用照抄后的音高
        src = [notes[pos[id(xa)]]['force'] if notes[pos[id(xa)]]['force'] is not None
               else mids[pos[id(xa)]] for xa in a]
        k = 0
        if kind in ('shift', 'motif'):
            ks = ([0] if kind == 'motif' else []) + sorted(
                (k for k in range(-7, 8) if k), key=lambda k: (abs(k), k < 0))
            k = next((k for k in ks if _shift_ok(g, src, [xa['tok'] for xa in a], b, k,
                                                  tonic_pc, lo, hi)), None)
            if k is None:
                if kind == 'motif':
                    # 强拍和声使整段固定移调无解时，仍把来源轮廓作为强目标交给旋律 DP；
                    # 移调量取两个小节首和弦根音的最短距离，DP 只调整不兼容的个别音。
                    sr = tok_chord(a[0]['tok'])[0]
                    dr = tok_chord(b[0]['tok'])[0]
                    k = (dr - sr + 6) % 12 - 6
                    for idx, (m, xb) in enumerate(zip(src, b)):
                        n = notes[pos[id(xb)]]
                        n['target'] = m + k
                        n['motif_target'] = True
                        if idx:
                            n['motif_interval'] = src[idx] - src[idx - 1]
                    realised[dst] = (srcb, k)
                continue
        for m, xb in zip(src, b):
            notes[pos[id(xb)]]['force'] = m + k
        if kind == 'motif':
            # 同一次 DP 会因后文约束重新调整来源小节；冻结首轮已经合法的来源音高，
            # 才能保证回答确实保持训练模型所要求的关系。
            for m, xa in zip(src, a):
                notes[pos[id(xa)]]['force'] = m
        realised[dst] = (srcb, k)
    for k in range(len(notes)):
        if notes[k]['force'] is None:
            old = 0.2 if notes[k].get('motif_target') else 0.6
            notes[k]['target'] = old * mids[k] + (1.0 - old) * notes[k]['target']
    return melody_dp(g, rng, temp, notes, tonic_pc, lo, hi, prev_note, end_tonic, next_midi), \
        realised


def _name(g: SubGrammar, midi: int, tok: Optional[str], tonic: str, tonic_pc: int) -> str:
    rel = (midi - tonic_pc) % 12
    names = {}
    if tok is not None:
        r, q = tok_chord(tok)
        names = chord_tone_names((r, q, 0), tonic, g.mode)
    nm = names.get(rel) or scale_names(tonic, g.mode).get(rel)
    if nm is None:
        from music21 import pitch
        return pitch.Pitch(midi=midi).nameWithOctave
    s = name_with_octave(nm, midi)
    return s[0] + s[1:].replace('b', '-')


def _legal_onset_patterns(g) -> Optional[set]:
    rh = g.s.get('rhythm') or {}
    if rh.get('mode') != 'bar':
        return None
    out = set()
    for cls in (rh.get('templates') or {}).values():
        for it in cls.get('items') or []:
            out.add(' '.join(x for x in str(it.get('pattern') or '').split() if x.endswith('n')))
    return out


def _onset_key(mel_line, bi: int, bq: float) -> str:
    start = bi * bq
    ons = [round(t - start, 4) for t, _d, m, _tok in mel_line
           if m is not None and start - 1e-9 <= t < start + bq - 1e-9]
    return ' '.join(f'{on:g}n' for on in ons)


def _silence_windows(n_bars: int, bq: float) -> List[Tuple[float, float]]:
    """每四小节的最后一拍空出来，末小节留给收束。"""
    beat = bq / 4.0
    out = []
    for bar in range(4, n_bars, 4):
        out.append(((bar - 1) * bq + (bq - beat), bar * bq))
    return out


def _silence_melody(mel_line, windows):
    segs = list(mel_line)
    for a, b in windows:
        nxt = []
        for t0, d0, m0, tok0 in segs:
            t1 = t0 + d0
            if d0 <= 1e-6 or m0 is None or t1 <= a + 1e-9 or t0 >= b - 1e-9:
                nxt.append((t0, d0, m0, tok0))
                continue
            if t0 < a - 1e-9:
                nxt.append((t0, a - t0, m0, tok0))
            lo, hi = max(t0, a), min(t1, b)
            if hi - lo > 1e-6:
                nxt.append((lo, hi - lo, None, tok0))
            if t1 > b + 1e-9:
                nxt.append((b, t1 - b, m0, tok0))
        segs = nxt
    return segs


def _silence_bar(events, cut: float, bq: float):
    out = []
    for on, d, v in events:
        t1 = on + d
        if d <= 1e-6 or v is None or t1 <= cut + 1e-9 or on >= bq - 1e-9:
            out.append((on, d, v))
            continue
        if on < cut - 1e-9:
            out.append((on, cut - on, v))
        lo, hi = max(on, cut), min(t1, bq)
        if hi - lo > 1e-6:
            out.append((lo, hi - lo, None))
    return out


def _hold_ending(mel_line, n_bars: int, bq: float):
    """末音若不到一拍半，就把它拉长到小节结束。音高不动，避免把终止音换成别的音。"""
    start = (n_bars - 1) * bq
    end = n_bars * bq
    last_i = None
    for i, (t, _d, m, _tok) in enumerate(mel_line):
        if m is not None and start - 1e-9 <= t < end - 1e-9:
            last_i = i
    if last_i is None:
        return mel_line
    t, d, m, tok = mel_line[last_i]
    if d >= 1.5 or end - t < 1.5:
        return mel_line
    new = []
    for t0, d0, m0, tok0 in mel_line:
        if t - 1e-9 <= t0 < end - 1e-9:
            continue
        if t0 < t < t0 + d0:
            new.append((t0, t - t0, m0, tok0))
            continue
        new.append((t0, d0, m0, tok0))
    new.append((t, end - t, m, tok))
    new.sort(key=lambda ev: ev[0])
    return new


def _assemble(g, plan, units, tonic, tonic_pc, key_sharps, title, tempo, instrument, lo, hi,
              pickup_ql):
    bq = g.bar_ql
    n_bars = plan['bars']
    slots, mel_line = [], []
    for un in units:
        tb = un['t_base']
        for sl in un['slots']:
            slots.append({'t': tb + sl['t_rel'], 'bar': un['index'] * UNIT + sl['bar'] + 1,
                          'beat': sl['beat'], 'tok': sl['tok'], 'mid': sl['mid'],
                          'rule': sl['rule'], 'pos': sl['pos'], 'unit': un['index']})
        for x in un['notes']:
            if x.get('pick') and un['index'] != 0:
                continue
            mel_line.append((tb + x['t'], x['d'], None if x['rest'] else x['midi'], x.get('tok')))
    mel_line.sort(key=lambda e: e[0])
    final_t = n_bars * bq
    mel = _Mel(mel_line)
    bass = _bass_line(g, slots, mel)
    for sl, b in zip(slots, bass):
        sl['bass'] = b
    if g.texture == 'piano':
        acc = [accompaniment_piano(g, slots, bass, n_bars, mel, final_t)]
    elif g.texture == 'quartet':
        duties = (plan.get('composer_sketch') or {}).get('voices')
        acc = list(accompaniment_quartet(g, slots, bass, n_bars, mel, final_t, duties=duties))
    elif g.texture == 'orchestra':
        voic = _voicings(g, slots, bass, mel, final_t)
        acc = list(accompaniment_quartet(g, slots, bass, n_bars, mel, final_t, voic))
        # 全奏：每两段里的第二段（B 段 / 再现段）与末段
        tutti = {un['index'] * UNIT + i for un in units for i in range(UNIT)
                 if un['index'] % 2 == 1 or un['index'] == len(units) - 1}
        acc += list(orchestra_winds(g, slots, bass, voic, n_bars, mel, final_t, tutti, acc[2]))
    else:
        acc = list(accompaniment(g, slots, bass, n_bars, mel, final_t))
    if plan.get('composer_sketch') and bq >= 2:
        legal = _legal_onset_patterns(g)
        breathed = []
        for a, b in _silence_windows(n_bars, bq):
            trial = _silence_melody(mel_line, [(a, b)])
            bi = int(a // bq)
            pat = _onset_key(trial, bi, bq)
            if legal is not None and pat not in legal:
                continue
            mel_line = trial
            breathed.append(bi)
        held = _hold_ending(mel_line, n_bars, bq)
        pat = _onset_key(held, n_bars - 1, bq)
        if legal is None or pat in legal:
            mel_line = held
        mel = _Mel(mel_line)
        beat = bq / 4.0
        for bi in breathed:
            for part in acc:
                if bi < len(part):
                    part[bi] = _silence_bar(part[bi], bq - beat, bq)
    # 旋律事件：按小节切开（不跨小节线），无法记谱的时值把尾巴写成休止
    mel_ev = []
    for on, d, m, tok in mel_line:
        if m is None:
            mel_ev += [[None, nm] for nm in split_ql(d)]
        else:
            parts = split_ql(d)
            mel_ev.append([_name(g, m, tok, tonic, tonic_pc), parts[0]])
            mel_ev += [[None, nm] for nm in parts[1:]]

    def tok_at(t):
        cur = slots[0]['tok']
        for sl in slots:
            if sl['t'] <= t + 1e-6:
                cur = sl['tok']
        return cur
    acc_ev = [[] for _ in acc]
    if pickup_ql:
        for out in acc_ev:
            out += [[None, nm] for nm in split_ql(pickup_ql)]
    for bi in range(n_bars):
        for part_bars, out in zip(acc, acc_ev):
            for on, d, v in part_bars[bi]:
                tok = tok_at(bi * bq + on)
                for k, nm in enumerate(split_ql(d)):
                    if v is None:
                        out.append([None, nm])
                    else:
                        out.append([[_name(g, m, tok, tonic, tonic_pc) for m in v]
                                    if len(v) > 1 else _name(g, v[0], tok, tonic, tonic_pc), nm])
    ins_name = INSTRUMENTS.get(instrument, INSTRUMENTS['violin'])[0]
    if g.texture == 'piano':
        ins_name = 'Piano RH'
    elif g.texture in ('quartet', 'orchestra'):
        ins_name = 'Violin I'
    parts = [{'name': ins_name, 'program': 40 if g.texture in ('quartet', 'orchestra') else
              0 if g.texture == 'piano' else None, 'clef': 'treble', 'events': mel_ev}]
    acc_defs = TEXTURE_ACC[g.texture] + (ORCH_WINDS if g.texture == 'orchestra' else [])
    for (nm, prog, clef), ev in zip(acc_defs, acc_ev):
        parts.append({'name': nm, 'program': prog, 'clef': clef, 'events': ev})
    if g.texture == 'orchestra':
        # 总谱次序：木管、铜管、定音鼓在上，弦乐在下
        parts = parts[4:] + parts[:4]
    groups = []
    if g.texture == 'melody_piano':
        parts[1]['staff'], parts[2]['staff'] = 1, 2
        groups = [{'parts': [1, 2], 'symbol': 'brace', 'name': 'Piano'}]
    elif g.texture == 'piano':
        parts[0]['staff'], parts[1]['staff'] = 1, 2
        groups = [{'parts': [0, 1], 'symbol': 'brace', 'name': 'Piano'}]
    harmony = {}
    for sl in slots:
        if sl['beat'] == 0:
            r, q = tok_chord(sl['tok'])
            nm = chord_tone_names((r, q, 0), tonic, g.mode)
            harmony[sl['bar']] = [n.replace('b', '-') if len(n) > 1 else n for n in nm.values()]
    info = STYLES[g.style]
    sub_zh = g.s['name']
    key_zh = f'{tonic}{"大调" if g.mode == "major" else "小调"}'
    spec = {
        'title': title or f'{sub_zh}（学习自{info["name"]} · {key_zh}）',
        'key_sharps': key_sharps, 'mode': g.mode, 'time_signature': g.meter,
        'tempo': int(tempo or g.s.get('tempo') or 120), 'bars': n_bars, 'voices': len(parts),
        'parts': parts,
        'staff_groups': groups,
        'harmony': harmony, 'tempo_marks': [], 'meter_changes': [], 'key_changes': [],
        'style_notes': [f'grammar:{g.style}/{g.sub}'], 'spelling_locked': True,
    }
    if pickup_ql:
        spec['pickup_ql'] = pickup_ql
    if (plan.get('composer_sketch') or {}).get('phrase'):
        spec['phrase_rhythm'] = True
    if plan.get('composer_sketch') and n_bars >= 12:
        terrace = [[1, 'mp'], [n_bars // 3 + 1, 'mf'], [n_bars // 2 + 1, 'f'],
                   [3 * n_bars // 4 + 1, 'mp']]
        for part in spec['parts']:
            part['dynamics'] = [list(x) for x in terrace]
    violations = check_piece(g.s, g.mode, spec, slots, tonic_pc, lo, hi, g.attested)
    trace_units = []
    for un in units:
        us = [s for s in slots if s['unit'] == un['index']]
        by_bar: Dict[int, List[str]] = {}
        for s in us:
            by_bar.setdefault(s['bar'], []).append(g.chord_symbol(s['tok'], tonic))
        f = un['formula']
        b0 = un['index'] * UNIT
        vo = un.get('variant_of')
        trace_units.append({
            'unit': un['index'] + 1, 'letter': un['letter'],
            'label': un.get('label', un['letter']), 'role': un.get('role'),
            'copy_of': None if un['copy_of'] is None else un['copy_of'] + 1,
            'variant_of': None if vo is None else vo + 1,
            'head_bars': un.get('head_bars', 0) if vo is not None else 0,
            'memory': _memory_say(un),
            'transform': un.get('transform'),
            'transform_status': un.get('transform_status'),
            'bars': [b0 + 1, b0 + UNIT],
            'cadence': f['id'] if f else '-', 'cadence_say': f['say'] if f else '',
            'contours': un['contours'],
            'rhythm': [_bar_say(b, b0, vo, i, un.get('head_bars', 0))
                       for i, b in enumerate(un['bars'])],
            'chords': ' | '.join(' '.join(v) for _b, v in sorted(by_bar.items())),
            'roman': ' '.join(g.roman.get(s['tok'], s['tok']) for s in us),
        })
    return {'spec': spec, 'plan': plan, 'units': trace_units, 'violations': violations,
            'slots': [{'bar': s['bar'], 'beat': s['beat'] + 1, 'tok': s['tok'], 'pos': s['pos'],
                       'chord': g.chord_symbol(s['tok'], tonic),
                       'roman': g.roman.get(s['tok'], s['tok']), 'rule': s['rule'],
                       'bass': s['bass']} for s in slots],
            'range': [lo, hi]}
