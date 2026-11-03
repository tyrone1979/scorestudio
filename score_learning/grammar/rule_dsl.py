# -*- coding: utf-8 -*-
"""Read handwritten_rules.dsl and judge every handwritten rule from its sentences.

The checker and the writer share this file. R10 and R11 apply only while writing."""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'handwritten_rules.dsl')
RULE_IDS = ('R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08', 'R09', 'R10', 'R11')

VOICE_INDEX = {'soprano': 0, 'alto': 1, 'tenor': 2, 'bass': 3}
ROLE_NAME = {'root': 'R', 'third': '3', 'fifth': '5', 'seventh': '7'}

_SECTION = {'all': 'must', 'except': 'except'}
_CACHE: Optional[Dict[str, dict]] = None


def rules_path() -> str:
    return _PATH


def load(text: Optional[str] = None, path: Optional[str] = None) -> Dict[str, dict]:
    """Parse the definition file. Pass text to try one edited copy in a test."""
    if text is None:
        with open(path or _PATH, encoding='utf-8') as f:
            text = f.read()
    rules: Dict[str, dict] = {}
    cur: Optional[dict] = None
    section: Optional[str] = None
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].rstrip()
        if not line.strip():
            section = None
            continue
        if line.startswith('rule '):
            rid = line.split()[1]
            cur = {'id': rid, 'must': [], 'except': [], 'params': {}}
            rules[rid] = cur
            section = None
            continue
        if cur is None:
            continue
        body = line.strip()
        header = body[:-1].strip() if body.endswith(':') else ''
        if header in _SECTION and not body.split(':', 1)[-1].strip():
            section = _SECTION[header]
            continue
        if body in _SECTION:
            section = _SECTION[body]
            continue
        if section in _SECTION.values() and not _is_field(body):
            cur[section].append(body)
            continue
        section = None
        key, value = _field(body)
        if key == 'name':
            cur['name'] = value
        elif key == 'means':
            cur['means'] = value
        elif key == 'where':
            cur['where'] = value
        elif key == 'report':
            cur['report'] = value
        elif key == 'report id':
            cur['report_id'] = value
        elif key == 'match':
            cur['match'] = value
        else:
            cur['params'][key] = _numbers_or_text(value)
    missing = [r for r in RULE_IDS if r not in rules]
    if missing:
        raise ValueError(f'handwritten rules file is missing {missing}')
    return rules


def default_rules() -> Dict[str, dict]:
    global _CACHE
    if _CACHE is None:
        _CACHE = load()
    return _CACHE


def reload() -> Dict[str, dict]:
    global _CACHE
    _CACHE = load()
    return _CACHE


def get(rule_id: str, book: Optional[Dict[str, dict]] = None) -> dict:
    return (book or default_rules())[rule_id]


def has_exception(rule_id: str, name: str, book: Optional[Dict[str, dict]] = None) -> bool:
    return name in get(rule_id, book)['except']


def _is_field(body: str) -> bool:
    return ':' in body or '：' in body


def _field(body: str):
    for sep in (':', '：'):
        if sep in body:
            key, value = body.split(sep, 1)
            return key.strip(), value.strip()
    raise ValueError(f'cannot read this line: {body}')


def _numbers_or_text(value: str):
    parts = [p.strip() for p in value.replace('，', ',').split(',') if p.strip()]
    nums = []
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            return value
    if len(parts) == 1 and nums:
        return nums[0]
    return nums


def _interval_classes(spec: dict) -> set:
    return {int(spec['params']['perfect fifth']), int(spec['params']['perfect octave'])}


def parallel_perfect(a1: int, b1: int, a2: int, b2: int,
                     book: Optional[Dict[str, dict]] = None) -> bool:
    """R01。a 为上方声部，b 为下方声部。"""
    spec = get('R01', book)
    i1, i2 = (a1 - b1) % 12, (a2 - b2) % 12
    ctx = {
        'the upper voice moves': a1 != a2,
        'the lower voice moves': b1 != b2,
        'the interval class stays the same': i1 == i2,
        'the interval class is a perfect fifth or octave': i1 == i2 and i1 in _interval_classes(spec),
    }
    return _match(spec, ctx)


def hidden_perfect_outer(s1: int, b1: int, s2: int, b2: int,
                         book: Optional[Dict[str, dict]] = None) -> bool:
    """R02 的核心条件。同一和弦、低音八度移位这两条例外由检查器另看。"""
    spec = get('R02', book)
    ds, db = s2 - s1, b2 - b1
    leap = int(spec['params']['soprano leap exceeds'])
    arrived = (s2 - b2) % 12 in _interval_classes(spec)
    ctx = {
        'the arrival is a perfect fifth or octave': arrived,
        'both voices move': ds != 0 and db != 0,
        'both voices move the same way': ds != 0 and db != 0 and (ds > 0) == (db > 0),
        'the soprano leap exceeds the limit': abs(ds) > leap,
    }
    return _match(spec, ctx)


def bad_melodic(a: int, b: int, book: Optional[Dict[str, dict]] = None) -> bool:
    """R08。"""
    spec = get('R08', book)
    d = abs(b - a)
    bad = spec['params']['forbidden semitones']
    if isinstance(bad, int):
        bad = [bad]
    limit = int(spec['params']['wider than'])
    ctx = {'the melodic interval is forbidden': d in set(bad) or d > limit}
    return _match(spec, ctx)


def overlap(prev: Sequence[int], cur: Sequence[int],
            book: Optional[Dict[str, dict]] = None) -> bool:
    """R03 的基本定义。教材例外见 overlap_refined。"""
    spec = get('R03', book)
    crossed = False
    for i in range(min(3, len(prev) - 1, len(cur) - 1)):
        if cur[i + 1] > prev[i] or cur[i] < prev[i + 1]:
            crossed = True
            break
    return _match(spec, {'a voice overlaps': crossed})


def overlap_refined(prev: Sequence[int], cur: Sequence[int],
                    prev_half: Optional[Sequence[int]] = None,
                    book: Optional[Dict[str, dict]] = None) -> bool:
    """R03。定义文件里列出的例外才会放行。"""
    if 'a voice overlaps' not in get('R03', book)['must']:
        return False
    last = list(prev_half) if prev_half is not None else list(prev)
    skip_unison = has_exception('R03', 'voices part from a unison', book)
    need_last = has_exception('R03', 'it does not pass the note immediately before', book)
    for i in range(min(3, len(prev) - 1, len(cur) - 1)):
        if skip_unison and prev[i] == prev[i + 1]:
            continue
        over_up = cur[i + 1] > prev[i] and (not need_last or cur[i + 1] > last[i])
        over_dn = cur[i] < prev[i + 1] and (not need_last or cur[i] < last[i + 1])
        if over_up or over_dn:
            return True
    return False


def voices_of(rule_id: str, book: Optional[Dict[str, dict]] = None) -> List[int]:
    names = get(rule_id, book)['params'].get('voices', 'soprano, bass')
    if isinstance(names, str):
        names = [p.strip() for p in names.replace('，', ',').split(',') if p.strip()]
    return [VOICE_INDEX[n] for n in names]


def leading_unresolved(prev_is_leading: bool, delta: int,
                       book: Optional[Dict[str, dict]] = None) -> bool:
    """R06：该声部是导音，且没有按文件里的半音数上行。"""
    spec = get('R06', book)
    step = int(spec['params']['rises by semitones'])
    ctx = {
        'this voice has the leading tone': prev_is_leading,
        'it does not rise by the required semitones': delta != step,
    }
    return _match(spec, ctx)


def seventh_unresolved(is_seventh: bool, delta: int, held_in_chord: bool,
                       book: Optional[Dict[str, dict]] = None) -> bool:
    """R07。held_in_chord：停住且下一和弦仍含该音。"""
    spec = get('R07', book)
    downs = spec['params']['resolves down by']
    if isinstance(downs, int):
        downs = [downs]
    ok = delta in set(downs) or (delta == 0 and held_in_chord)
    ctx = {
        'this voice has the seventh': is_seventh,
        'it neither falls by step nor holds a chord tone': not ok,
    }
    return _match(spec, ctx)


def chord_faults(leading_count: int, roles: set, is_seventh: bool,
                 book: Optional[Dict[str, dict]] = None) -> List[str]:
    """R09。返回要报告的短句；空列表表示通过。匹配方式见文件里的「匹配」。"""
    spec = get('R09', book)
    cap = int(spec['params']['leading tone at most'])
    need = {ROLE_NAME[n.strip()] for n in _as_names(spec['params']['must include'])}
    if is_seventh:
        need |= {ROLE_NAME[n.strip()] for n in _as_names(spec['params']['a seventh chord also needs'])}
    missing = need - roles
    ctx = {
        'the leading tone is doubled': leading_count > cap,
        'a required chord tone is missing': bool(missing),
    }
    fired = _which(spec, ctx)
    out = []
    if 'the leading tone is doubled' in fired:
        out.append('leading tone doubled')
    if 'a required chord tone is missing' in fired:
        shown = ', '.join(sorted(str(x) for x in missing if x))
        out.append(f'chord incomplete (missing {shown})')
    return out


def _yes(value) -> bool:
    return str(value).strip().lower() in ('yes', '1', 'true')


def gap_limits(tb_max: Optional[int] = None, book: Optional[Dict[str, dict]] = None):
    """R04 的三个间距上限。tb_max 只覆盖次中音与低音，供评测把这一档放宽。"""
    p = get('R04', book)['params']
    sa = int(p['soprano to alto at most'])
    at = int(p['alto to tenor at most'])
    tb = int(p['tenor to bass at most']) if tb_max is None else int(tb_max)
    return sa, at, tb


def spacing_violation(v: Sequence[int], tb_max: Optional[int] = None,
                      book: Optional[Dict[str, dict]] = None) -> bool:
    """R04。真表示交叉或间距超过定义文件。"""
    spec = get('R04', book)
    s, a, t, b = v
    sa, at, tb = gap_limits(tb_max, book)
    if _yes(spec['params'].get('unison allowed', 'yes')):
        crossed = not (s >= a >= t >= b)
    else:
        crossed = not (s > a > t > b)
    wide = (s - a) > sa or (a - t) > at or (t - b) > tb
    return _match(spec, {'the voices cross': crossed, 'adjacent voices stand too far apart': wide})


def writer_forbids_unison(book: Optional[Dict[str, dict]] = None) -> bool:
    return _yes(get('R04', book)['params'].get('writer forbids unison', 'yes'))


def out_of_range(pitch: int, lo: int, hi: int, book: Optional[Dict[str, dict]] = None) -> bool:
    """R05。界限来自调用方传入的习得音域，含不含边界由定义文件决定。"""
    spec = get('R05', book)
    if 'the pitch is outside the voice range' not in spec['must']:
        return False
    if _yes(spec['params'].get('bounds included', 'yes')):
        return not (lo <= pitch <= hi)
    return not (lo < pitch < hi)


def range_enforced(book: Optional[Dict[str, dict]] = None) -> bool:
    return 'the pitch is outside the voice range' in get('R05', book)['must']


def melodic_limits(book: Optional[Dict[str, dict]] = None):
    """R08：不良半音列表，以及「大于」这个上限。"""
    p = get('R08', book)['params']
    bad = p['forbidden semitones']
    if isinstance(bad, int):
        bad = [bad]
    return [int(x) for x in bad], int(p['wider than'])


def seventh_steps(book: Optional[Dict[str, dict]] = None) -> List[int]:
    downs = get('R07', book)['params']['resolves down by']
    if isinstance(downs, int):
        downs = [downs]
    return [int(x) for x in downs]


def leading_step(book: Optional[Dict[str, dict]] = None) -> int:
    return int(get('R06', book)['params']['rises by semitones'])


def forbid_doubled_seventh(book: Optional[Dict[str, dict]] = None) -> bool:
    return _yes(get('R09', book)['params'].get('writer forbids a doubled seventh', 'yes'))


def leading_cap(book: Optional[Dict[str, dict]] = None) -> int:
    return int(get('R09', book)['params']['leading tone at most'])


def unattested_forbidden(book: Optional[Dict[str, dict]] = None) -> bool:
    return 'an unattested chord pair is forbidden' in get('R10', book)['must']


def cadence_lock_beats(book: Optional[Dict[str, dict]] = None) -> int:
    if 'the phrase ending uses the cadence formula' not in get('R11', book)['must']:
        return 0
    return int(get('R11', book)['params']['beats locked at the end'])


def soprano_lock_beats(book: Optional[Dict[str, dict]] = None) -> int:
    if 'the phrase ending uses the cadence formula' not in get('R11', book)['must']:
        return 0
    return int(get('R11', book)['params']['soprano degrees locked'])


def structural_step(book: Optional[Dict[str, dict]] = None) -> int:
    spec = (book or default_rules()).get('shared') or {}
    return int((spec.get('params') or {}).get('step no wider than', 2))


def structural_on(book: Optional[Dict[str, dict]] = None) -> bool:
    spec = (book or default_rules()).get('shared')
    return bool(spec) and 'a beat suspension is judged by its resolution' in spec['must']


def tritone_recovered(a: int, b: int, nxt: Optional[int],
                      book: Optional[Dict[str, dict]] = None) -> bool:
    """R08 例外：下行三全音（6 个半音）之后反向级进。"""
    if not has_exception('R08', 'a descending tritone steps back', book):
        return False
    return b - a == -6 and nxt is not None and 1 <= nxt - b <= 2


def _as_names(value) -> List[str]:
    if isinstance(value, str):
        return [p.strip() for p in value.replace('，', ',').split(',') if p.strip()]
    return [str(value)]


def _match(spec: dict, ctx: dict) -> bool:
    return bool(_which(spec, ctx))


def _which(spec: dict, ctx: dict) -> List[str]:
    unknown = [c for c in spec['must'] if c not in ctx]
    if unknown:
        raise ValueError(f"{spec['id']} has an unknown condition: {unknown}")
    if spec.get('match') == 'any':
        return [c for c in spec['must'] if ctx[c]]
    if all(ctx[c] for c in spec['must']):
        return list(spec['must'])
    return []


def musician_text(book: Optional[Dict[str, dict]] = None) -> str:
    """教程和界面用的纯文本，不含内部半音编号以外的程序细节。"""
    book = book or default_rules()
    blocks = []
    order = list(RULE_IDS) + [rid for rid in book if rid not in RULE_IDS]
    for rid in order:
        spec = book[rid]
        lines = [f"{rid}  {spec.get('name', '')}", spec.get('means', ''), f"Checked: {spec.get('where', '')}"]
        if spec['must']:
            lines.append('A fault when every line below is true:' if spec.get('match') != 'any'
                         else 'A fault when any line below is true:')
            lines.extend(f'  · {c}' for c in spec['must'])
        params = spec['params']
        if params:
            lines.append('Numbers you can change:')
            for k, v in params.items():
                shown = ', '.join(str(x) for x in v) if isinstance(v, list) else v
                lines.append(f'  · {k} = {shown}')
        if spec['except']:
            lines.append('Allowed through:')
            lines.extend(f'  · {e}' for e in spec['except'])
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)
