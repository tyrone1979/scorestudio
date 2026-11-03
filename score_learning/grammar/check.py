# -*- coding: utf-8 -*-
"""四部和声手写规则。

R01–R11 与「共同」例外的定义在 ``handwritten_rules.dsl``。
作曲器的搜索约束与成品检查共用 ``rule_dsl`` 读到的同一份定义。
R10、R11 只在写作时生效。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from . import rule_dsl
from .theory import scale_of

VOICE_NAMES = ('Soprano', 'Alto', 'Tenor', 'Bass')
PAIRS = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]


def parallel_perfect(a1: int, b1: int, a2: int, b2: int) -> bool:
    """R01，条件见 handwritten_rules.dsl。"""
    return rule_dsl.parallel_perfect(a1, b1, a2, b2)


def hidden_perfect_outer(s1: int, b1: int, s2: int, b2: int) -> bool:
    """R02，条件见 handwritten_rules.dsl。同一和弦与低音八度移位的例外在检查循环里。"""
    return rule_dsl.hidden_perfect_outer(s1, b1, s2, b2)


def bad_melodic(a: int, b: int) -> bool:
    """R08，不良半音与「大于」见 handwritten_rules.dsl。"""
    return rule_dsl.bad_melodic(a, b)


def spacing_ok(v: Sequence[int], tb_max: Optional[int] = None) -> bool:
    """R04，间距与是否允许同度见 handwritten_rules.dsl。

    tb_max 只覆盖次中音与低音的上限；不传则用定义文件里的数。
    """
    return not rule_dsl.spacing_violation(v, tb_max)


def overlap(prev: Sequence[int], cur: Sequence[int]) -> bool:
    """R03，定义见 handwritten_rules.dsl。"""
    return rule_dsl.overlap(prev, cur)


def structural_pitches(b: Dict, half: Optional[Sequence[int]]) -> List[int]:
    """拍点上的非和弦音（挂留、倚音）若在本拍后半拍级进到和弦音，以解决音代表该声部。"""
    if half is None:
        return list(b['midi'])
    out = []
    for vi, m in enumerate(b['midi']):
        h = half[vi]
        if (b['rel'][vi] not in b['members'] and 1 <= abs(h - m) <= rule_dsl.structural_step()
                and (b['rel'][vi] + h - m) % 12 in b['members']):
            out.append(h)
        else:
            out.append(m)
    return out


def check_satb(grid: List[Tuple[float, List[int]]], beats: List[Dict],
               ranges: Dict[str, Dict[str, int]], tb_max: Optional[int] = None,
               refined: bool = True) -> List[Dict]:
    """成品检查。

    grid：八分音网格 [(t, [S,A,T,B midi])]，每个时间点各声部当时发声的音；
    beats：拍级信息 [{'t', 'midi', 'members': {pc: role}, 'lt_pc', 'res_root_tonic',
                      'seventh_pc', 'fermata_after'}]；可选 'chord'、'root'、'quality'。
    refined：启用教材允许的例外与副导音检查（见 ``REFINEMENTS``，默认开启）；
             False 复现专家评审前的原检查器。
    返回违例 [{'rule', 't', 'msg'}]。
    """
    out: List[Dict] = []
    halves = {t: v for t, v in grid}
    chord_at = {b['t']: ((b['root'], b.get('quality')) if b.get('root') is not None else None)
                for b in beats}

    def half_of(b: Dict) -> Optional[List[int]]:
        return halves.get(b['t'] + 0.5)

    def chord_of(t: float):
        return chord_at.get(t, chord_at.get(t - 0.5))

    use_struct = refined and rule_dsl.structural_on()
    if use_struct:
        struct = {b['t']: structural_pitches(b, half_of(b)) for b in beats}
        grid = [(t, struct.get(t, v)) for t, v in grid]
    else:
        struct = {b['t']: list(b['midi']) for b in beats}

    # R01 / R02：相邻八分点 + 相邻拍点
    def scan(points):
        for (t1, v1), (t2, v2) in zip(points, points[1:]):
            for i, j in PAIRS:
                if parallel_perfect(v1[i], v1[j], v2[i], v2[j]):
                    fifth = int(rule_dsl.get('R01')['params']['perfect fifth'])
                    kind = 'fifths' if (v2[i] - v2[j]) % 12 == fifth else 'octaves'
                    out.append({'rule': 'R01', 't': t2,
                                'msg': f'{VOICE_NAMES[i]} and {VOICE_NAMES[j]} '
                                       f'move in parallel perfect {kind}'})
            if hidden_perfect_outer(v1[0], v1[3], v2[0], v2[3]):
                same_chord = chord_of(t1) is not None and chord_of(t1) == chord_of(t2)
                skip_same = (refined and rule_dsl.has_exception('R02', 'same chord, voices exchange')
                             and same_chord)
                skip_oct = (refined and rule_dsl.has_exception('R02', 'bass moves by an octave')
                            and (v1[3] - v2[3]) % 12 == 0)
                if skip_same or skip_oct:
                    continue
                out.append({'rule': 'R02', 't': t2,
                            'msg': rule_dsl.get('R02').get(
                                'report', 'hidden fifth or octave between the outer voices')})
    scan(grid)
    beat_pts = [(b['t'], struct[b['t']] if use_struct else b['midi']) for b in beats]
    seen = {(o['rule'], o['t'], o['msg']) for o in out}
    before = len(out)
    scan(beat_pts)
    out[before:] = [o for o in out[before:] if (o['rule'], o['t'], o['msg']) not in seen]
    lo = {k: v['low'] for k, v in ranges.items()}
    hi = {k: v['high'] for k, v in ranges.items()}
    for k, b in enumerate(beats):
        v = b['midi']
        if rule_dsl.spacing_violation(v, tb_max):
            label = rule_dsl.get('R04').get('report_id', 'R03/R04')
            out.append({'rule': label, 't': b['t'],
                        'msg': f'voices cross or stand too far apart {v}'})
        for vi, nm in enumerate('SATB'):
            if rule_dsl.out_of_range(v[vi], lo[nm], hi[nm]):
                out.append({'rule': 'R05', 't': b['t'],
                            'msg': f'{VOICE_NAMES[vi]} is outside its range ({v[vi]})'})
        if k and not b.get('phrase_start'):
            pb = beats[k - 1]
            pv = pb['midi']
            ph = half_of(pb)
            hit = (rule_dsl.overlap_refined(pv, v, ph) if refined else overlap(pv, v))
            if hit:
                out.append({'rule': 'R03', 't': b['t'],
                            'msg': rule_dsl.get('R03').get('report', 'voice overlap')})
            nxt = _next_note(beats, k, half_of(b))
            for vi in range(4):
                if bad_melodic(pv[vi], v[vi]):
                    if refined and rule_dsl.tritone_recovered(pv[vi], v[vi], nxt[vi]):
                        continue
                    out.append({'rule': 'R08', 't': b['t'],
                                'msg': f'{VOICE_NAMES[vi]} forbidden melodic interval '
                                       f'{v[vi] - pv[vi]:+d}'})
            # R06：外声部导音解决，声部与上行半音数来自定义文件
            r06_voices = rule_dsl.voices_of('R06')
            if pb.get('lt_pc') is not None and b.get('tonic_chord'):
                for vi in r06_voices:
                    if rule_dsl.leading_unresolved(pb['rel'][vi] == pb['lt_pc'], v[vi] - pv[vi]):
                        out.append({'rule': 'R06', 't': b['t'],
                                    'msg': f'{VOICE_NAMES[vi]} leading tone does not rise'})
            elif refined and rule_dsl.has_exception('R06', 'a secondary leading tone must rise too'):
                slt = _secondary_lt(pb, b)
                if slt is not None:
                    for vi in r06_voices:
                        if rule_dsl.leading_unresolved(pb['rel'][vi] == slt, v[vi] - pv[vi]):
                            out.append({'rule': 'R06', 't': b['t'],
                                        'msg': f'{VOICE_NAMES[vi]} secondary leading tone does not rise'})
            # R07：七音解决，下行半音数来自定义文件
            if pb.get('seventh_pc') is not None:
                pp = beats[k - 2]['midi'] if k >= 2 and not pb.get('phrase_start') else None
                hb = half_of(b)
                for vi in range(4):
                    held = b['rel'][vi] in b['members']
                    if not rule_dsl.seventh_unresolved(
                            pb['rel'][vi] == pb['seventh_pc'], v[vi] - pv[vi], held):
                        continue
                    if refined and _seventh_licensed(vi, pv, v, ph, hb, pp):
                        continue
                    out.append({'rule': 'R07', 't': b['t'],
                                'msg': f'{VOICE_NAMES[vi]} seventh does not fall by step'})
        # R09：导音不重复 / 完整性
        rel = b['rel']
        if use_struct:
            tpc = (b['midi'][3] - b['rel'][3]) % 12
            rel = [(m - tpc) % 12 for m in struct[b['t']]]
        roles = {b['members'].get(r) for r in rel}
        lt_count = rel.count(b['lt_pc']) if b.get('lt_pc') is not None else 0
        for msg in rule_dsl.chord_faults(lt_count, roles, bool(b.get('is_seventh'))):
            out.append({'rule': 'R09', 't': b['t'], 'msg': msg})
    return out


#: refined=True 时启用的修订；每条对应教材允许的写法或一类漏报。
REFINEMENTS = {
    'structural': '拍点上的挂留/倚音若在本拍内级进解决到和弦音，R01/R02/R09 按解决音判断',
    'R02_same_chord': '同一和弦内换位、或低音八度移位，不计隐伏五/八度',
    'R03_unison': '两声部从同音分开不计超越；只越过前一拍拍点、未越过紧邻前一音的不计',
    'R07_licences': '七音在本拍或下一拍的后半拍级进下行解决；V43→I6 式七音随低音上行；'
                    '级进经过的七音',
    'R08_tritone': '下行三全音之后反向级进，不计不良旋律音程',
    'R06_secondary': '副属和弦（大三度的 V/x 进到 x）的外声部导音须上行半音',
}


def _overlap_refined(prev: Sequence[int], prev_half: Optional[Sequence[int]],
                     cur: Sequence[int]) -> bool:
    return rule_dsl.overlap_refined(prev, cur, prev_half)


def _next_note(beats: List[Dict], k: int, half: Optional[Sequence[int]]) -> List[Optional[int]]:
    """每声部在第 k 拍之后紧接的下一个音（本拍后半拍或下一拍），不跨乐句。"""
    v = beats[k]['midi']
    nb = beats[k + 1]['midi'] if k + 1 < len(beats) and not beats[k + 1].get('phrase_start') else None
    out: List[Optional[int]] = []
    for vi in range(4):
        if half is not None and half[vi] != v[vi]:
            out.append(half[vi])
        else:
            out.append(nb[vi] if nb is not None else None)
    return out


def _tritone_recovered(a: int, b: int, nxt: Optional[int]) -> bool:
    return rule_dsl.tritone_recovered(a, b, nxt)


def secondary_lt(root: Optional[int], quality: Optional[str], root_next: Optional[int],
                 mode: Optional[str]) -> Optional[int]:
    """R06 副导音：本和弦是副属（属七，或三音为调外变化音的大三和弦）、下一和弦根音在其下五度
    且不是主和弦时，返回本和弦三音（调内坐标）；否则 None。调内大三和弦下五度进行
    （如 I→IV、IV→♭VII）不算。生成器与检查器共用。"""
    if root is None or root_next is None or quality not in ('M', '7'):
        return None
    if root_next != (root + 5) % 12 or root_next == 0:
        return None
    lt = (root + 4) % 12
    if quality == 'M' and (mode is None or lt in scale_of(mode)):
        return None
    return lt


def _secondary_lt(pb: Dict, b: Dict) -> Optional[int]:
    return secondary_lt(pb.get('root'), pb.get('quality'), b.get('root'), pb.get('mode'))


def _seventh_licensed(vi: int, pv: Sequence[int], v: Sequence[int],
                      ph: Optional[Sequence[int]], hb: Optional[Sequence[int]],
                      pp: Optional[Sequence[int]]) -> bool:
    """R07 的放过条件。定义文件里没有的那一行，这里就不生效。"""
    s = pv[vi]
    downs = rule_dsl.get('R07')['params']['resolves down by']
    if isinstance(downs, int):
        downs = [downs]
    downs = set(downs)
    ups = {-d for d in downs}
    if rule_dsl.has_exception('R07', 'it falls by step on the half beat'):
        if ph is not None and ph[vi] - s in downs:
            return True
        if v[vi] == s and hb is not None and hb[vi] - s in downs:
            return True
    if rule_dsl.has_exception('R07', 'the seventh rises with the bass'):
        d = v[vi] - s
        db = v[3] - pv[3]
        if vi != 3 and d in ups and db in ups and (v[3] - s) % 12 in (11, 10):
            return True
    if rule_dsl.has_exception('R07', 'the seventh is only a passing tone') and pp is not None:
        d = v[vi] - s
        d0 = s - pp[vi]
        if d0 * d > 0 and abs(d0) <= 2 and abs(d) <= 2:
            return True
    return False


#: 每条规则的判据牵涉多少个音（谓词的「支撑」）：R05 只看一个音；R06/R07/R08 看同一声部
#: 相邻两音；R03/R04 看两个声部；R01/R02 看两声部两拍共四个音；R09 看整个和弦。
#: 一处改动往往同时触发多条规则，支撑越小的违例越可能就是被改动的那个音本身。
ROOT_CAUSE_SUPPORT = {'R05': 1, 'R06': 2, 'R07': 2, 'R08': 2, 'R03': 3, 'R03/R04': 3,
                      'R01': 4, 'R02': 4, 'R09': 5}


def rank_violations(viol: List[Dict]) -> List[Dict]:
    """按根因可能性排序：支撑小者在前，同支撑保持检查器原顺序。"""
    order = sorted(range(len(viol)),
                   key=lambda i: (ROOT_CAUSE_SUPPORT.get(viol[i]['rule'], 9), i))
    return [viol[i] for i in order]
