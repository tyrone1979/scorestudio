# -*- coding: utf-8 -*-
"""作曲草图：LLM 或确定性过程只决定曲式、变形和声部职责，不写绝对音高。

校验失败时调用方退回普通 /compose-grammar。实现仍由 leadsheet 语法完成。
"""
from __future__ import annotations

import contextvars
import copy
import os
import random
from typing import Any, Dict, List, Optional, Tuple

from music21 import pitch as m21pitch

from narrative import MOTIF_TRANSFORMS
from score_learning.leadsheet.learn import UNIT, tok_chord
from score_learning.theme_memory import similarity

SECTION_ROLES = ('introduce', 'sequence', 'quote', 'contrast', 'coda')
CADENCE_DIRS = ('HC', 'PAC', 'IAC', 'DC')
VOICE_DUTIES = ('melody', 'answer', 'sustain', 'bass')
VOICE_NAMES = ('violin1', 'violin2', 'viola', 'cello')
_QL = {'whole': 4.0, 'dotted_half': 3.0, 'half': 2.0, 'dotted_quarter': 1.5,
       'quarter': 1.0, 'dotted_eighth': 0.75, 'eighth': 0.5, '16th': 0.25, '32nd': 0.125}

SKETCH_REVISER = contextvars.ContextVar('composer_sketch_reviser', default=None)
LISTENING_JUDGE = contextvars.ContextVar('composer_listening_judge', default=None)

# 作曲主科听审。评的是听完之后的印象，不评习题对错。
# 及格线按主科常用的百分制 70：六项平均不低于 3.5；单项 ≤2 视为明显缺陷，一票否决。
JURY_ITEMS = ('theme', 'breath', 'arc', 'contrast', 'layers', 'ending')
JURY_MEAN_MIN = 3.5
JURY_VETO = 2
JURY_RUBRIC = """你是音乐学院作曲主科的听审老师。只根据下面的听感材料打分，不评乐理对错。
平行五度、和弦外音、声部超越、终止式名称是否正确，都不在本表里；那些已由语法检查。
六项各打整数 1–5。3 分是及格边缘：听得懂，但不出色。2 分及以下是明显缺陷。
拿不准时打低分。
材料里的 melody_by_section 是各段实际旋律，chord_roots_by_section 是各段每小节的和弦根音。
只有两段音高进行几乎一样，才能说“原样再放”；音高已经离开就不要把 contrast 打到 2。
同一和弦连续四小节以上，arc 打 2。旋律连续四小节绕着同一个音，theme 打 2。

- theme 主题记忆：听完能否哼出开头。5=开头清楚而且后面认得出；2=只有一两小节有印象，或根本没有句头。
- breath 句法呼吸：乐句有没有收住、有没有停顿。5=大约每四小节能换一口气；2=从头铺到尾，没有气口。
- arc 起伏：力度、音区、疏密有没有弧线。5=前后有弱有强，中段托得起来；2=整曲一样平。
- contrast 对比与回归：中段是否真的离开，回归时听得出是回来而不是再放一遍。5=离开清楚、回来认得出；2=几段听起来是同一段，或回来时完全对不上。
- layers 层次：旋律是否站在前面，伴奏是否让路。5=主旋律听得见，其他人不是同一密度；2=四件乐器一样密、一样响。
- ending 收束：结束有没有落地。5=最后有到达、能停住；2=像被截断，或还在往前赶。

只返回 JSON：
{"scores":{"theme":3,"breath":3,"arc":3,"contrast":3,"layers":3,"ending":3},"comment":"一两句听感，不要写规则编号"}
"""

PAIRWISE_RUBRIC = """你在听两段各八小节的音乐，只决定更想把哪一段听完。
不要评乐理，不要因为知道某一种体裁就打分。甲是参照，乙是新写的一句。
绵延的歌唱句不必每四小节休止。后半拍反复戳同一个音、旋律绕着一个音打转、听完不想继续，都算输。
只返回 JSON：{"prefer":"reference","comment":"一句听感"} 或 {"prefer":"candidate","comment":"一句听感"}
reference 表示更想听甲，candidate 表示更想听乙。拿不准就选 reference。
"""

PHRASE_DURS = {
    'whole': 4.0, 'dotted_half': 3.0, 'half': 2.0, 'dotted_quarter': 1.5,
    'quarter': 1.0, 'dotted_eighth': 0.75, 'eighth': 0.5, '16th': 0.25,
}

RETURN_SIMILARITY = 0.82
ONSET_JACCARD_MAX = 0.5
REPEAT_MAX = 0.80


def cadence_direction(chords: Tuple[str, str] | List[str]) -> str:
    """终止公式的方向：半终止、正格、变格、阻碍。只看根音，不看具体音高。"""
    _a, b = chords[0], chords[1]
    rb = tok_chord(b)[0]
    ra = tok_chord(_a)[0]
    if rb == 7:
        return 'HC'
    if rb == 0 and ra == 7:
        return 'PAC'
    if rb == 0:
        return 'IAC'
    return 'DC'


def grammar_options(script: Dict[str, Any], sub: str, mode: str) -> Dict[str, Any]:
    """提示词用的封闭选项：轮廓、节奏、终止方向。不包含转移概率表。"""
    g = script['subs'][sub]
    contours = [{'id': c['id'], 'name': c.get('name') or c['id']}
                for c in (g['melody'].get('contour_templates') or [])[:8]]
    rhythms = []
    seen = set()
    for block in (g.get('rhythm') or {}).get('templates', {}).values():
        for it in block.get('items') or []:
            if it['id'] in seen:
                continue
            seen.add(it['id'])
            pat = str(it.get('pattern') or '')
            if pat.count('n') < 2:
                continue
            rhythms.append({'id': it['id'], 'say': it.get('say') or pat})
            if len(rhythms) >= 8:
                break
        if len(rhythms) >= 8:
            break
    return {'contours': contours, 'rhythms': rhythms,
            'cadences': list(CADENCE_DIRS), 'roles': list(SECTION_ROLES),
            'transforms': list(MOTIF_TRANSFORMS), 'voices': list(VOICE_DUTIES)}


def _rhythm_index(sub: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for block in (sub.get('rhythm') or {}).get('templates', {}).values():
        for it in block.get('items') or []:
            out.setdefault(it['id'], it)
    return out


def _as_int(v: Any, name: str) -> Tuple[Optional[int], Optional[str]]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None, f'{name} 必须是整数'
    return int(v), None


def validate_sketch(raw: Any, script: Dict[str, Any], sub: str, mode: str,
                    bars: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """封闭词表校验。成功返回规范化草图，失败返回原因。"""
    if not isinstance(raw, dict):
        return None, '草图不是 JSON 对象'
    if sub not in script.get('subs', {}):
        return None, f'没有子风格 {sub}'
    gsub = script['subs'][sub]
    if mode not in gsub.get('vocab', {}):
        return None, f'{sub} 没有调式 {mode}'
    got_mode = str(raw.get('mode') or mode)
    if got_mode != mode:
        return None, f'草图调式 {got_mode} 与命令 {mode} 不一致'
    sharps, err = _as_int(raw.get('key_sharps', 0), 'key_sharps')
    if err:
        return None, err
    if not -7 <= sharps <= 7:
        return None, 'key_sharps 超出 -7..7'
    got_bars, err = _as_int(raw.get('bars', bars), 'bars')
    if err:
        return None, err
    if got_bars != int(bars):
        return None, f'草图小节数 {got_bars} 与命令 {bars} 不一致'
    if got_bars % UNIT or got_bars < UNIT:
        return None, '小节数必须是 8 的倍数'
    theme = raw.get('theme')
    if not isinstance(theme, dict):
        return None, '缺少 theme'
    theme_bars, err = _as_int(theme.get('bars'), 'theme.bars')
    if err:
        return None, err
    if theme_bars not in (4, 8):
        return None, '主题长度只能是 4 或 8 小节'
    contours = {c['id'] for c in (gsub['melody'].get('contour_templates') or [])}
    contour = str(theme.get('contour') or '')
    if contour not in contours:
        return None, f'未知轮廓 {contour}'
    rhythms = _rhythm_index(gsub)
    rhythm = str(theme.get('rhythm_template') or '')
    item = rhythms.get(rhythm)
    if item is None:
        return None, f'未知节奏模板 {rhythm}'
    if str(item.get('pattern') or '').count('n') < 2:
        return None, '节奏模板至少要有两个音符，才能形成节奏身份'
    cadence = str(theme.get('cadence') or '')
    if cadence not in CADENCE_DIRS:
        return None, f'未知终止方向 {cadence}'
    phrase, err = _normalize_phrase(raw.get('phrase'), 4.0)
    if err:
        return None, err
    sections = raw.get('sections')
    if not isinstance(sections, list) or not sections:
        return None, '缺少 sections'
    if sum(int(s.get('bars') or 0) for s in sections if isinstance(s, dict)) != got_bars:
        return None, '各段小节数之和必须等于全曲'
    norm_sections = []
    seen: List[str] = []
    for i, sec in enumerate(sections):
        if not isinstance(sec, dict):
            return None, '段落不是对象'
        label = str(sec.get('label') or '')
        role = str(sec.get('role') or '')
        transform = str(sec.get('transform') or '')
        ref = sec.get('ref')
        ref = None if ref in (None, '', 'null') else str(ref)
        sec_bars, err = _as_int(sec.get('bars'), 'section.bars')
        if err:
            return None, err
        if not label:
            return None, '段落缺少 label'
        if sec_bars != UNIT:
            return None, '每一段必须是 8 小节'
        if role not in SECTION_ROLES:
            return None, f'未知段落角色 {role}'
        if transform not in MOTIF_TRANSFORMS:
            return None, f'未知变形 {transform}'
        if ref is not None and ref not in seen:
            return None, f'{label} 引用了尚未出现的 {ref}'
        if i == 0 and (role != 'introduce' or transform != 'original' or ref is not None):
            return None, '第一段必须是无引用的 original 陈述'
        if role == 'quote' and ref is None:
            return None, f'{label} 是引用但没有 ref'
        norm_sections.append({'label': label, 'role': role, 'bars': UNIT,
                              'ref': ref, 'transform': transform})
        seen.append(label)
    voices = raw.get('voices')
    if not isinstance(voices, dict):
        return None, '缺少 voices'
    if set(voices) != set(VOICE_NAMES):
        return None, 'voices 必须正好是 violin1、violin2、viola、cello'
    duties = {k: str(voices[k]) for k in VOICE_NAMES}
    if sorted(duties.values()) != sorted(VOICE_DUTIES):
        return None, '四个声部职责必须各出现一次：旋律、应答、持续和声、低音'
    if duties['violin1'] != 'melody':
        return None, '第一小提琴承担旋律'
    return {
        'key_sharps': sharps, 'mode': mode, 'bars': got_bars,
        'theme': {'bars': theme_bars, 'contour': contour,
                  'rhythm_template': rhythm, 'cadence': cadence},
        'phrase': phrase,
        'sections': norm_sections, 'voices': duties,
    }, None


def _duration_pieces(ql: float) -> List[str]:
    """把一段时值拆成能记谱的时值名。"""
    left = round(ql, 4)
    out = []
    guard = 0
    while left > 1e-6 and guard < 16:
        guard += 1
        pick = next((name for name, q in PHRASE_DURS.items() if q <= left + 1e-6), None)
        if pick is None:
            return []
        out.append(pick)
        left = round(left - PHRASE_DURS[pick], 4)
    return out if left <= 1e-6 else []


def _normalize_phrase(raw: Any, bar_ql: float) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """八小节一句：第一个音是音级，后面每个音是相对前一个音的音级步数。"""
    if not isinstance(raw, dict):
        return None, '缺少 phrase：八小节的节奏和音级进行'
    degree, err = _as_int(raw.get('degree'), 'phrase.degree')
    if err:
        return None, err
    if degree < 1 or degree > 7:
        return None, 'phrase.degree 必须是 1 到 7'
    notes = raw.get('notes')
    if not isinstance(notes, list) or not notes:
        return None, 'phrase.notes 不能为空'
    norm = []
    filled = 0.0
    sounded = 0.0
    for i, ev in enumerate(notes):
        if not isinstance(ev, dict):
            return None, 'phrase 里有不是对象的音'
        dur = str(ev.get('dur') or '')
        ql = PHRASE_DURS.get(dur)
        if ql is None:
            return None, f'未知时值 {dur}'
        rest = bool(ev.get('rest'))
        step, err = _as_int(0 if rest else ev.get('step', 0), 'phrase.step')
        if err:
            return None, err
        if not rest and (step < -7 or step > 7):
            return None, '音级步数只能是 -7 到 7'
        if i == 0 and rest:
            return None, '一句的第一个音不能是休止'
        left = ql
        first_piece = True
        while left > 1e-6:
            bar_end = (int(filled / bar_ql) + 1) * bar_ql
            room = round(bar_end - filled, 4)
            chunk = min(left, room)
            pieces = _duration_pieces(chunk)
            if not pieces:
                return None, f'时值 {dur} 无法记谱'
            for j, name in enumerate(pieces):
                norm.append({'dur': name,
                             'step': 0 if (i == 0 and first_piece) or rest or j or not first_piece else step,
                             'rest': rest})
                filled = round(filled + PHRASE_DURS[name], 4)
                if not rest:
                    sounded += PHRASE_DURS[name]
                first_piece = False
                if abs(filled / bar_ql - round(filled / bar_ql)) < 1e-3:
                    if sounded < 0.5:
                        return None, '每一小节至少要有一个音'
                    sounded = 0.0
            left = round(left - chunk, 4)
    target = 8 * bar_ql
    if filled > target + 1e-3:
        kept, acc = [], 0.0
        for note in norm:
            q = PHRASE_DURS[note['dur']]
            if acc + q > target + 1e-3:
                break
            kept.append(note)
            acc = round(acc + q, 4)
        norm, filled = kept, acc
    cycle = list(norm)
    k = 0
    while filled < target - 1e-3 and cycle and k < 64:
        if abs(filled / bar_ql - round(filled / bar_ql)) > 1e-3:
            room = round((int(filled / bar_ql) + 1) * bar_ql - filled, 4)
            for name in _duration_pieces(min(room, round(target - filled, 4))):
                norm.append({'dur': name, 'step': 0, 'rest': True})
                filled = round(filled + PHRASE_DURS[name], 4)
            continue
        src = cycle[k % len(cycle)]
        q = PHRASE_DURS[src['dur']]
        if filled + q > target + 1e-3:
            for name in _duration_pieces(round(target - filled, 4)):
                norm.append({'dur': name, 'step': 0, 'rest': True})
                filled = round(filled + PHRASE_DURS[name], 4)
            break
        norm.append(dict(src, step=0 if k == 0 else src.get('step') or 0))
        filled = round(filled + q, 4)
        k += 1
    if abs(filled - target) > 1e-3 or not norm:
        return None, 'phrase 必须正好写满 8 小节'
    return {'bars': 8, 'degree': degree, 'notes': norm}, None


def opening_phrase() -> Dict[str, Any]:
    """没有模型时用的一句：级进上下，第四和第八小节落到长音。"""
    degrees = [5, 6, 7, 6, 5, 4, 3, 4, 5, 6, 5, 4, 3, 2, 1,
               2, 3, 4, 5, 6, 5, 4, 3, 4, 5, 6, 5, 4, 2, 1]
    durs = (['quarter'] * 4) * 3 + ['half', 'quarter', 'quarter']
    durs += (['quarter'] * 4) * 3 + ['half', 'quarter', 'quarter']
    notes = []
    prev = degrees[0]
    for i, (deg, dur) in enumerate(zip(degrees, durs)):
        notes.append({'dur': dur, 'step': 0 if i == 0 else deg - prev, 'rest': False})
        prev = deg
    return {'bars': 8, 'degree': degrees[0], 'notes': notes}


def _pick_rhythm(sub: Dict[str, Any], rng: random.Random) -> str:
    cands = []
    for it in _rhythm_index(sub).values():
        if str(it.get('pattern') or '').count('n') >= 2:
            cands.append((it['id'], float(it.get('p') or 0)))
    if not cands:
        raise ValueError('语法里没有可用的节奏模板')
    cands.sort(key=lambda x: -x[1])
    head = cands[:5]
    tot = sum(p for _i, p in head) or 1
    r = rng.random() * tot
    for i, p in head:
        r -= p
        if r <= 0:
            return i
    return head[0][0]


def deterministic_sketch(script: Dict[str, Any], sub: str, mode: str, bars: int,
                         key_sharps: int, rng: random.Random) -> Dict[str, Any]:
    """无 LLM 时的作曲草图：陈述、模进应答、对比、完整回归。"""
    gsub = script['subs'][sub]
    contours = gsub['melody'].get('contour_templates') or [{'id': '-'}]
    contour = str(contours[int(rng.random() * min(4, len(contours)))]['id'])
    n = max(1, int(bars) // UNIT)
    # 末段必须能落到主和弦。两段时回归本身就是末段，所以陈述用正格终止；
    # 更长时把完整回归放在末段之前，末段另写尾声。
    opening_cadence = 'PAC' if n < 3 else 'HC'
    sections = []
    for i in range(n):
        if i == 0:
            label, role, transform, ref = 'A', 'introduce', 'original', None
        elif n >= 3 and i == n - 1:
            label, role, transform, ref = 'Coda', 'coda', 'original', None
        elif n >= 3 and i == n - 2:
            label, role, transform, ref = 'Ar', 'quote', 'original', 'A'
        elif i == 1 and n >= 3:
            label, role, transform, ref = 'A2', 'sequence', 'sequence', 'A'
        elif i == n - 1:
            label, role, transform, ref = 'Ar', 'quote', 'original', 'A'
        else:
            label, role, transform, ref = 'B', 'contrast', 'fragment', 'A'
        sections.append({'label': label, 'role': role, 'bars': UNIT,
                         'ref': ref, 'transform': transform})
    sketch = {
        'key_sharps': int(key_sharps), 'mode': mode, 'bars': int(bars),
        'theme': {'bars': 4, 'contour': contour, 'rhythm_template': _pick_rhythm(gsub, rng),
                  'cadence': opening_cadence},
        'phrase': opening_phrase(),
        'sections': sections,
        'voices': {'violin1': 'melody', 'violin2': 'answer', 'viola': 'sustain', 'cello': 'bass'},
    }
    ok, err = validate_sketch(sketch, script, sub, mode, bars)
    if ok is None:
        raise ValueError(err or '确定性草图未通过校验')
    return ok


def revise_sketch(sketch: Dict[str, Any], report: Dict[str, Any],
                  rng: random.Random) -> Dict[str, Any]:
    """只改草图：补上完整回归、把失败的变形收成碎片、把声部职责重置开。"""
    s = copy.deepcopy(sketch)
    first = s['sections'][0]['label']
    if not report.get('has_return') or (report.get('return_similarity') or 0) < RETURN_SIMILARITY:
        last = s['sections'][-1]
        last['role'] = 'quote'
        last['transform'] = 'original'
        last['ref'] = first
        if last['label'] == first:
            last['label'] = first + 'r'
    veto = set((report.get('jury') or {}).get('veto') or [])
    if 'contrast' in veto or 'arc' in veto:
        _depart_middle(s, first)
    if (report.get('jury') or {}).get('standard') == 'pairwise-listening' and s.get('phrase'):
        _nudge_phrase(s['phrase'], rng)
    if report.get('transform_relaxed'):
        for sec in s['sections']:
            if sec['transform'] not in ('original', 'fragment') and sec['role'] != 'quote':
                sec['transform'] = 'fragment' if rng.random() < 0.5 else 'invert'
                sec['ref'] = first
                sec['role'] = 'sequence'
                break
    if ((report.get('onset_jaccard') or 0) >= ONSET_JACCARD_MAX
            or (report.get('vn2_repeat') or 0) >= REPEAT_MAX
            or (report.get('cello_repeat') or 0) >= REPEAT_MAX
            or report.get('compose_failed')):
        s['voices'] = {'violin1': 'melody', 'violin2': 'answer',
                       'viola': 'sustain', 'cello': 'bass'}
    return s


_DEPART = ('invert', 'retrograde', 'transpose', 'augment', 'sequence', 'fragment')


def _nudge_phrase(phrase: Dict[str, Any], rng: random.Random) -> None:
    """对照听审输掉时，改一句里的音级步数，让下一稿不是同一句。"""
    for ev in phrase.get('notes') or []:
        if ev.get('rest'):
            continue
        ev['step'] = max(-5, min(5, int(ev.get('step') or 0) + (1 if rng.random() < 0.5 else -1)))
        return


def _depart_middle(sketch: Dict[str, Any], first: str) -> None:
    """听审说没离开时，中段必须换成另一种变形。多出来的原样引用改回尾声。"""
    moved = False
    for sec in sketch['sections'][1:]:
        if sec.get('role') == 'quote' and sec.get('transform') == 'original':
            continue
        cur = sec.get('transform')
        nxt = _DEPART[(_DEPART.index(cur) + 1) % len(_DEPART)] if cur in _DEPART else 'invert'
        sec['transform'] = nxt
        sec['role'] = 'sequence'
        sec['ref'] = first
        moved = True
        break
    if not moved and len(sketch['sections']) > 1:
        sec = sketch['sections'][1]
        sec['transform'] = 'invert'
        sec['role'] = 'sequence'
        sec['ref'] = first
    seen = 0
    for sec in sketch['sections']:
        if sec.get('role') == 'quote' and sec.get('transform') == 'original':
            seen += 1
            if seen > 1:
                sec['role'] = 'coda'
                sec['transform'] = 'fragment'
                sec['ref'] = first


def _middle_plan(sketch: Dict[str, Any], first: str):
    return [(sec.get('role'), sec.get('transform'), sec.get('ref'))
            for sec in sketch['sections'][1:]
            if not (sec.get('role') == 'quote' and sec.get('transform') == 'original'
                    and sec.get('ref') == first)]


def revision_answers(prev: Dict[str, Any], nxt: Dict[str, Any],
                     report: Dict[str, Any]) -> bool:
    """修订必须对着不及格项改。对比不及格时，中段变形得变，且不能再加一段原样引用。"""
    if not isinstance(nxt, dict) or not nxt.get('sections'):
        return False
    if (report.get('jury') or {}).get('standard') == 'pairwise-listening':
        return (prev.get('phrase') or {}) != (nxt.get('phrase') or {})
    veto = set((report.get('jury') or {}).get('veto') or [])
    quotes = [s for s in nxt['sections']
              if s.get('role') == 'quote' and s.get('transform') == 'original']
    if len(quotes) > 1:
        return False
    if 'contrast' in veto or 'arc' in veto:
        return _middle_plan(prev, prev['sections'][0]['label']) != _middle_plan(
            nxt, nxt['sections'][0]['label'])
    return [(s.get('role'), s.get('transform'), s.get('ref')) for s in prev['sections']] != [
        (s.get('role'), s.get('transform'), s.get('ref')) for s in nxt['sections']]


def next_sketch(sketch: Dict[str, Any], report: Dict[str, Any],
                rng: random.Random) -> Dict[str, Any]:
    """优先用外部修订器（LLM）。没按听审意见改到中段时，退回确定性修订。"""
    reviser = SKETCH_REVISER.get()
    if reviser is not None:
        try:
            proposed = reviser(sketch, report)
        except Exception:
            proposed = None
        if isinstance(proposed, dict) and revision_answers(sketch, proposed, report):
            return proposed
    return revise_sketch(sketch, report, rng)


def _midi_of(name: Any) -> Optional[int]:
    if name is None:
        return None
    if isinstance(name, list):
        if not name:
            return None
        name = name[0]
    try:
        return int(m21pitch.Pitch(str(name).replace('-', 'b')).midi)
    except Exception:
        return None


def _walk(events: List, pickup: float, bar_ql: float, n_bars: int):
    """事件流 → 每小节的 (midi, ql) 以及全部起音时刻。"""
    bars: List[List[Tuple[int, float]]] = [[] for _ in range(n_bars)]
    onsets = []
    t = 0.0
    for ev in events or []:
        if not ev or len(ev) < 2:
            continue
        ql = _QL.get(str(ev[1]))
        if ql is None:
            continue
        midi = _midi_of(ev[0])
        if midi is not None and t + 1e-6 >= pickup:
            bi = int((t - pickup + 1e-6) // bar_ql)
            if 0 <= bi < n_bars:
                bars[bi].append((midi, ql))
                onsets.append(round(t - pickup, 4))
        t += ql
    return bars, onsets


def _repeat_fraction(bars: List[List[Tuple[int, float]]]) -> float:
    seq = [m for bar in bars for m, _d in bar]
    if len(seq) < 2:
        return 0.0
    return sum(a == b for a, b in zip(seq, seq[1:])) / (len(seq) - 1)


def _jaccard(a: List[float], b: List[float]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / max(len(sa | sb), 1)


def jury_pass(scores: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """及格线：六项都在，单项不低于 3 分以上的否决线，平均不低于 3.5。"""
    if not isinstance(scores, dict):
        return False, list(JURY_ITEMS)
    vals = []
    veto = []
    for item in JURY_ITEMS:
        raw = scores.get(item)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            veto.append(item)
            continue
        mark = int(raw)
        if mark < 1 or mark > 5:
            veto.append(item)
            continue
        vals.append(mark)
        if mark <= JURY_VETO:
            veto.append(item)
    if len(vals) != len(JURY_ITEMS):
        return False, veto or list(JURY_ITEMS)
    if veto or (sum(vals) / len(vals)) < JURY_MEAN_MIN - 1e-9:
        return False, veto
    return True, []


def _silence_in_last_beat(events: List, pickup: float, bar_ql: float, beat: float,
                          n_bars: int) -> List[float]:
    """每小节最后一拍里休止占了多少四分音符。"""
    silent = [0.0] * n_bars
    t = 0.0
    for ev in events or []:
        if not ev or len(ev) < 2:
            continue
        ql = _QL.get(str(ev[1]))
        if ql is None:
            continue
        midi = _midi_of(ev[0])
        cursor, remain = t, ql
        while remain > 1e-6:
            if cursor < pickup - 1e-9:
                step = min(remain, pickup - cursor)
                cursor += step
                remain -= step
                continue
            bi = int((cursor - pickup) // bar_ql)
            if bi < 0 or bi >= n_bars:
                break
            bar_pos = (cursor - pickup) - bi * bar_ql
            room = bar_ql - bar_pos
            step = min(remain, room)
            cut = bar_ql - beat
            if midi is None and bar_pos + step > cut + 1e-6:
                silent[bi] += min(bar_pos + step, bar_ql) - max(bar_pos, cut)
            cursor += step
            remain -= step
        t += ql
    return silent


def listening_facts(spec: Dict[str, Any], report: Dict[str, Any], bar_ql: float) -> Dict[str, Any]:
    """把谱面收成听审能用的听感材料，不列规则违例。"""
    parts = spec.get('parts') or []
    n_bars = int(spec.get('bars') or 0)
    pickup = float(spec.get('pickup_ql') or 0.0)
    beat = bar_ql / 4.0 if bar_ql else 1.0
    mel = (parts[0].get('events') if parts else []) or []
    mel_bars, _ = _walk(mel, pickup, bar_ql, n_bars) if n_bars else ([], [])
    silent = _silence_in_last_beat(mel, pickup, bar_ql, beat, n_bars) if n_bars else []
    phrases = max(1, n_bars // 4)
    breaths = 0
    checked = 0
    for p in range(phrases):
        bi = p * 4 + 3
        if bi >= n_bars - 1:
            continue
        checked += 1
        if bi < len(silent) and silent[bi] >= beat - 0.05:
            breaths += 1
    dyn = set()
    for part in parts:
        for item in part.get('dynamics') or []:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                dyn.add(str(item[1]))
    ranges = []
    for i in range(0, max(0, n_bars - 1), 2):
        notes = [m for m, _d in (mel_bars[i] if i < len(mel_bars) else [])]
        if i + 1 < len(mel_bars):
            notes += [m for m, _d in mel_bars[i + 1]]
        ranges.append(0 if len(notes) < 2 else max(notes) - min(notes))
    peak = max(ranges) if ranges else 0
    second = sorted(ranges)[-2] if len(ranges) > 1 else 0
    sigs = [tuple((m, round(d, 3)) for m, d in bar) for bar in mel_bars]
    copied = False
    for i in range(0, max(0, n_bars - 15)):
        window = tuple(sigs[i:i + 8])
        if not any(window):
            continue
        for j in range(i + 8, n_bars - 7):
            if tuple(sigs[j:j + 8]) == window:
                copied = True
                break
        if copied:
            break
    attacks = []
    for part in parts:
        _bars, onsets = _walk(part.get('events') or [], pickup, bar_ql, n_bars)
        attacks.append(len(onsets))
    last = mel_bars[-1] if mel_bars else []
    holds = [d for _m, d in last]
    melody = []
    for i in range(0, n_bars, UNIT):
        chunk = []
        for bar in mel_bars[i:i + UNIT]:
            if not bar:
                chunk.append('休')
            else:
                chunk.append(' '.join(m21pitch.Pitch(m).nameWithOctave for m, _d in bar[:8]))
        melody.append(' | '.join(chunk))
    harm = spec.get('harmony') or {}
    roots = []
    for b in range(1, n_bars + 1):
        names = harm.get(str(b)) or harm.get(b) or []
        roots.append(str(names[0]) if names else '?')
    chord_sections = [' '.join(roots[i:i + UNIT]) for i in range(0, n_bars, UNIT)]
    return {
        'phrase_breaths': breaths,
        'phrase_ends_checked': checked,
        'breath_ratio': round(breaths / checked, 3) if checked else 0.0,
        'dynamic_levels': sorted(dyn),
        'eight_bar_copy': copied,
        'two_bar_ranges': ranges,
        'interest_concentrated': bool(peak >= 7 and second * 2 < peak),
        'attacks': attacks,
        'ending_hold_ql': round(max(holds) if holds else 0.0, 3),
        'return_similarity': report.get('return_similarity'),
        'melody_by_section': melody,
        'chord_roots_by_section': chord_sections,
    }


def proxy_scores(facts: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, int]:
    """没有模型时，用同一张表的听感门槛打分，不另立标准。"""
    theme = 4 if (report.get('return_similarity') or 0) >= RETURN_SIMILARITY else 2
    breath = 4 if (facts.get('breath_ratio') or 0) >= 0.5 else 2
    arc = 4 if len(facts.get('dynamic_levels') or []) >= 3 else 2
    contrast = 2 if facts.get('eight_bar_copy') else 4
    attacks = [n for n in (facts.get('attacks') or []) if n]
    layers = 4
    if len(attacks) >= 2 and min(attacks) / max(attacks) > 0.85:
        layers = 2
    if (report.get('onset_jaccard') or 1) >= ONSET_JACCARD_MAX:
        layers = 2
    ending = 4 if (facts.get('ending_hold_ql') or 0) >= 1.5 else 2
    return {'theme': theme, 'breath': breath, 'arc': arc, 'contrast': contrast,
            'layers': layers, 'ending': ending}


def _melody_text(spec: Dict[str, Any], bar_ql: float, n_bars: int) -> str:
    parts = spec.get('parts') or []
    if not parts or n_bars <= 0:
        return ''
    pickup = float(spec.get('pickup_ql') or 0.0)
    mel_bars, _ = _walk(parts[0].get('events') or [], pickup, bar_ql, n_bars)
    lines = []
    for i, bar in enumerate(mel_bars[:n_bars], start=1):
        if not bar:
            lines.append(f'{i}: 休')
        else:
            lines.append(f"{i}: " + ' '.join(m21pitch.Pitch(m).nameWithOctave for m, _d in bar[:8]))
    return ' | '.join(lines)


_BACH_OPENING: Optional[str] = None


def bach_opening_melody() -> str:
    """参照句：巴赫《G 弦上的咏叹调》前八小节的小提琴，不在提示里写作者。"""
    global _BACH_OPENING
    if _BACH_OPENING is not None:
        return _BACH_OPENING
    path = os.path.join(os.path.dirname(__file__), '..', 'runs',
                        'orchestral_four_voice', 'source', 'bach-air-score.mid')
    text = ''
    if os.path.exists(path):
        try:
            from music21 import converter
            score = converter.parse(path)
            part = score.parts[0]
            ev, t = [], 0.0
            for el in part.flatten().notesAndRests:
                off = float(el.getOffsetInHierarchy(part))
                if off > t + 1e-3:
                    t = off
                if el.isRest or float(el.quarterLength) <= 0:
                    t = off + float(el.quarterLength)
                    continue
                name = el.pitches[-1].nameWithOctave if el.isChord else el.pitch.nameWithOctave
                ev.append((off, name))
                t = off + float(el.quarterLength)
            bars: List[List[str]] = [[] for _ in range(8)]
            for off, name in ev:
                bi = int(off // 4)
                if 0 <= bi < 8:
                    bars[bi].append(name)
            text = ' | '.join(f"{i}: {' '.join(ns) if ns else '休'}" for i, ns in enumerate(bars, start=1))
        except Exception:
            text = ''
    _BACH_OPENING = text or '1: F#5 A5 | 2: D5 C#5 | 3: B4 A4 | 4: G4 F#4 | 5: E5 D5 | 6: C#5 B4 | 7: A4 G4 | 8: F#4'
    return _BACH_OPENING


def _phrase_proxy(spec: Dict[str, Any], bar_ql: float) -> bool:
    """没有模型时，一句要有音区、要有长音，才算没输给参照。"""
    parts = spec.get('parts') or []
    if not parts:
        return False
    n = min(8, int(spec.get('bars') or 0))
    mel_bars, _ = _walk(parts[0].get('events') or [], float(spec.get('pickup_ql') or 0), bar_ql, n)
    pitches = [m for bar in mel_bars for m, _d in bar]
    durs = [d for bar in mel_bars for _m, d in bar]
    if len(pitches) < 4 or not durs:
        return False
    return (max(pitches) - min(pitches)) >= 5 and max(durs) >= 1.5


def pairwise_review(spec: Dict[str, Any], bar_ql: float) -> Dict[str, Any]:
    """八小节对照听审。更想把新的一句听完才通过。"""
    n = min(8, int(spec.get('bars') or 0))
    payload = {'reference': bach_opening_melody(), 'candidate': _melody_text(spec, bar_ql, n)}
    prefer, comment, source = None, '', 'proxy'
    judge = LISTENING_JUDGE.get()
    if judge is not None:
        try:
            verdict = judge(payload)
        except Exception:
            verdict = None
        if isinstance(verdict, dict) and verdict.get('prefer') in ('reference', 'candidate'):
            prefer = verdict['prefer']
            comment = str(verdict.get('comment') or '')
            source = 'llm'
        elif isinstance(verdict, dict) and isinstance(verdict.get('scores'), dict):
            passed, veto = jury_pass(verdict['scores'])
            return {'standard': 'pairwise-listening', 'pass': passed, 'prefer':
                    'candidate' if passed else 'reference', 'veto': veto,
                    'scores': verdict['scores'], 'comment': str(verdict.get('comment') or ''),
                    'source': 'llm', 'facts': payload}
    if prefer is None:
        prefer = 'candidate' if _phrase_proxy(spec, bar_ql) else 'reference'
    return {'standard': 'pairwise-listening', 'pass': prefer == 'candidate',
            'prefer': prefer, 'comment': comment, 'source': source,
            'veto': [] if prefer == 'candidate' else ['phrase'], 'facts': payload}


def jury_review(spec: Dict[str, Any], report: Dict[str, Any], bar_ql: float) -> Dict[str, Any]:
    """听审结论。有模型时用模型的分数；及格与否一律按主科分数线计算。"""
    facts = listening_facts(spec, report, bar_ql)
    scores = proxy_scores(facts, report)
    source, comment = 'proxy', ''
    judge = LISTENING_JUDGE.get()
    if judge is not None:
        try:
            verdict = judge(facts)
        except Exception:
            verdict = None
        got = (verdict or {}).get('scores') if isinstance(verdict, dict) else None
        if isinstance(got, dict) and all(k in got for k in JURY_ITEMS):
            scores = {k: int(got[k]) for k in JURY_ITEMS}
            source = 'llm'
            comment = str((verdict or {}).get('comment') or '')
    passed, veto = jury_pass(scores)
    try:
        mean = round(sum(int(scores[k]) for k in JURY_ITEMS) / len(JURY_ITEMS), 2)
    except (KeyError, TypeError, ValueError):
        mean = None
    return {'standard': 'conservatory-composition-jury',
            'mean_min': JURY_MEAN_MIN, 'veto_at': JURY_VETO,
            'scores': {k: scores.get(k) for k in JURY_ITEMS},
            'mean': mean, 'veto': veto, 'pass': passed,
            'source': source, 'comment': comment, 'facts': facts}


def assess_realization(spec: Dict[str, Any], units: List[Dict[str, Any]],
                       sketch: Dict[str, Any], bar_ql: float) -> Dict[str, Any]:
    """结构指标：主题完整回归、内声部起音是否分开、相邻同音是否还像同一脉冲。"""
    parts = spec.get('parts') or []
    n_bars = int(spec.get('bars') or sketch['bars'])
    pickup = float(spec.get('pickup_ql') or 0.0)
    mel_bars, _ = _walk(parts[0]['events'], pickup, bar_ql, n_bars) if parts else ([], [])
    first = sketch['sections'][0]['label']
    ret_i = next((i for i, sec in enumerate(sketch['sections'])
                  if sec['role'] == 'quote' and sec['transform'] == 'original'
                  and sec.get('ref') == first), None)
    ret_sim = None
    if ret_i is not None and mel_bars:
        # 回归听的是主题句头。整段八小节对不上，不代表开头没回来。
        head = int((sketch.get('theme') or {}).get('bars') or 4)
        head = max(1, min(4, head))
        src = [ev for bar in mel_bars[0:head] for ev in bar]
        dst = [ev for bar in mel_bars[ret_i * UNIT:ret_i * UNIT + head] for ev in bar]
        ret_sim = float(similarity(src, dst)) if src and dst else 0.0
    vn2 = _walk(parts[1]['events'], pickup, bar_ql, n_bars)[1] if len(parts) > 1 else []
    va = _walk(parts[2]['events'], pickup, bar_ql, n_bars)[1] if len(parts) > 2 else []
    vn2_bars = _walk(parts[1]['events'], pickup, bar_ql, n_bars)[0] if len(parts) > 1 else []
    vc_bars = _walk(parts[3]['events'], pickup, bar_ql, n_bars)[0] if len(parts) > 3 else []
    relaxed = any(u.get('transform_status') == 'relaxed' for u in units)
    report = {
        'has_return': ret_i is not None,
        'return_similarity': None if ret_sim is None else round(ret_sim, 4),
        'onset_jaccard': round(_jaccard(vn2, va), 4),
        'vn2_repeat': round(_repeat_fraction(vn2_bars), 4),
        'cello_repeat': round(_repeat_fraction(vc_bars), 4),
        'transform_relaxed': relaxed,
        'violations': 0,
    }
    if sketch.get('phrase'):
        jury = pairwise_review(spec, bar_ql)
    else:
        jury = jury_review(spec, report, bar_ql)
    report['jury'] = jury
    # 有第一句时，对照听审通过才算通过。六项分不能单独放行。
    report['ok'] = bool(jury['pass'])
    return report


def prompt_block(options: Dict[str, Any], bars: int, mode: str, key_sharps: int) -> str:
    contours = '、'.join(f"{c['id']}（{c['name']}）" for c in options['contours']) or '（无）'
    rhythms = '、'.join(f"{r['id']}（{r['say']}）" for r in options['rhythms']) or '（无）'
    return f"""你是作曲家，只输出一首弦乐四重奏的作曲草图 JSON。不要写音名。
第一句 phrase 要一次写完 8 小节：degree 是起音的音级 1–7，之后每个音的 step 是相对前一个音的音级步数（-7 到 7）。
时值只能用 whole、dotted_half、half、dotted_quarter、quarter、dotted_eighth、eighth、16th。
每小节的时值加起来正好是 4 拍，音符不能跨小节，每小节至少一个音。第四或第八小节用一个不少于二分音符的音收住。
全曲 {bars} 小节，{mode}，key_sharps={key_sharps}。每段固定 8 小节。后面的段落只写角色和变形，不要再写音。
只使用这些词：
- role: introduce, sequence, quote, contrast, coda
- transform: {', '.join(options['transforms'])}
- cadence: HC, PAC, IAC, DC
- voices 的职责各一次: melody, answer, sustain, bass
- contour 必须是: {contours}
- rhythm_template 必须是: {rhythms}
第一段 role=introduce、transform=original、ref=null。第一小提琴必须是 melody。
引用段的 ref 必须是前面已经出现的 label。至少有一段 quote + original，表示回到第一段的主题句头；后半段会重写，不要把整段八小节再放一遍。
JSON 形状：
{{"key_sharps":{key_sharps},"mode":"{mode}","bars":{bars},
  "phrase":{{"degree":5,"notes":[{{"dur":"quarter","step":0}},{{"dur":"quarter","step":1}}]}},
  "theme":{{"bars":4,"contour":"…","rhythm_template":"…","cadence":"HC"}},
  "sections":[{{"label":"A","role":"introduce","bars":8,"ref":null,"transform":"original"}}],
  "voices":{{"violin1":"melody","violin2":"answer","viola":"sustain","cello":"bass"}}}}
"""
