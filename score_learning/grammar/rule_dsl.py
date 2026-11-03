# -*- coding: utf-8 -*-
"""读取 handwritten_rules.dsl，按其中的句子判断全部手写规则。

检查器与写作器共用这一份：R01–R09 与 R04、R05 的成品检查，
以及 R10、R11 只在写作时生效的约束。"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'handwritten_rules.dsl')
RULE_IDS = ('R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08', 'R09', 'R10', 'R11')

VOICE_INDEX = {'女高音': 0, '中音': 1, '次中音': 2, '低音': 3}
ROLE_NAME = {'根音': 'R', '三音': '3', '五音': '5', '七音': '7'}

_SECTION = {'必须', '例外'}
_CACHE: Optional[Dict[str, dict]] = None


def rules_path() -> str:
    return _PATH


def load(text: Optional[str] = None, path: Optional[str] = None) -> Dict[str, dict]:
    """解析定义文件。text 优先，便于测试临时改一句。"""
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
        if line.startswith('规则 '):
            rid = line.split()[1]
            cur = {'id': rid, '必须': [], '例外': [], '参数': {}}
            rules[rid] = cur
            section = None
            continue
        if cur is None:
            continue
        body = line.strip()
        header = body[:-1].strip() if body.endswith((':', '：')) else ''
        if header in _SECTION and not body.split(':', 1)[-1].split('：', 1)[-1].strip():
            section = header
            continue
        if body in _SECTION:
            section = body
            continue
        if section in _SECTION and not _is_field(body):
            cur[section].append(body)
            continue
        section = None
        key, value = _field(body)
        if key == '名称':
            cur['名称'] = value
        elif key == '说明':
            cur['说明'] = value
        elif key == '检查':
            cur['检查'] = value
        elif key == '报告':
            cur['报告'] = value
        elif key == '报告编号':
            cur['报告编号'] = value
        elif key == '匹配':
            cur['匹配'] = value
        else:
            cur['参数'][key] = _numbers_or_text(value)
    missing = [r for r in RULE_IDS if r not in rules]
    if missing:
        raise ValueError(f'手写规则定义缺少 {missing}')
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
    return name in get(rule_id, book)['例外']


def _is_field(body: str) -> bool:
    return ':' in body or '：' in body


def _field(body: str):
    for sep in (':', '：'):
        if sep in body:
            key, value = body.split(sep, 1)
            return key.strip(), value.strip()
    raise ValueError(f'无法读取这一行：{body}')


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
    return {int(spec['参数']['纯五度']), int(spec['参数']['纯八度'])}


def parallel_perfect(a1: int, b1: int, a2: int, b2: int,
                     book: Optional[Dict[str, dict]] = None) -> bool:
    """R01。a 为上方声部，b 为下方声部。"""
    spec = get('R01', book)
    i1, i2 = (a1 - b1) % 12, (a2 - b2) % 12
    ctx = {
        '上方声部移动': a1 != a2,
        '下方声部移动': b1 != b2,
        '音程种类不变': i1 == i2,
        '音程种类是纯五度或纯八度': i1 == i2 and i1 in _interval_classes(spec),
    }
    return _match(spec, ctx)


def hidden_perfect_outer(s1: int, b1: int, s2: int, b2: int,
                         book: Optional[Dict[str, dict]] = None) -> bool:
    """R02 的核心条件。同一和弦、低音八度移位这两条例外由检查器另看。"""
    spec = get('R02', book)
    ds, db = s2 - s1, b2 - b1
    leap = int(spec['参数']['女高音跳进超过'])
    arrived = (s2 - b2) % 12 in _interval_classes(spec)
    ctx = {
        '到达的音程是纯五度或纯八度': arrived,
        '两个声部都移动': ds != 0 and db != 0,
        '两个声部同向': ds != 0 and db != 0 and (ds > 0) == (db > 0),
        '女高音跳进超过规定半音': abs(ds) > leap,
    }
    return _match(spec, ctx)


def bad_melodic(a: int, b: int, book: Optional[Dict[str, dict]] = None) -> bool:
    """R08。"""
    spec = get('R08', book)
    d = abs(b - a)
    bad = spec['参数']['不良半音']
    if isinstance(bad, int):
        bad = [bad]
    limit = int(spec['参数']['大于'])
    ctx = {'旋律音程属于不良音程': d in set(bad) or d > limit}
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
    return _match(spec, {'声部发生超越': crossed})


def overlap_refined(prev: Sequence[int], cur: Sequence[int],
                    prev_half: Optional[Sequence[int]] = None,
                    book: Optional[Dict[str, dict]] = None) -> bool:
    """R03。定义文件里列出的例外才会放行。"""
    if '声部发生超越' not in get('R03', book)['必须']:
        return False
    last = list(prev_half) if prev_half is not None else list(prev)
    skip_unison = has_exception('R03', '从同音分开不计', book)
    need_last = has_exception('R03', '只越过拍点未越过前一音不计', book)
    for i in range(min(3, len(prev) - 1, len(cur) - 1)):
        if skip_unison and prev[i] == prev[i + 1]:
            continue
        over_up = cur[i + 1] > prev[i] and (not need_last or cur[i + 1] > last[i])
        over_dn = cur[i] < prev[i + 1] and (not need_last or cur[i] < last[i + 1])
        if over_up or over_dn:
            return True
    return False


def voices_of(rule_id: str, book: Optional[Dict[str, dict]] = None) -> List[int]:
    names = get(rule_id, book)['参数'].get('声部', '女高音, 低音')
    if isinstance(names, str):
        names = [p.strip() for p in names.replace('，', ',').split(',') if p.strip()]
    return [VOICE_INDEX[n] for n in names]


def leading_unresolved(prev_is_leading: bool, delta: int,
                       book: Optional[Dict[str, dict]] = None) -> bool:
    """R06：该声部是导音，且没有按文件里的半音数上行。"""
    spec = get('R06', book)
    step = int(spec['参数']['解决上行半音'])
    ctx = {
        '该声部是导音': prev_is_leading,
        '没有按指定半音上行解决': delta != step,
    }
    return _match(spec, ctx)


def seventh_unresolved(is_seventh: bool, delta: int, held_in_chord: bool,
                       book: Optional[Dict[str, dict]] = None) -> bool:
    """R07。held_in_chord：停住且下一和弦仍含该音。"""
    spec = get('R07', book)
    downs = spec['参数']['下行解决']
    if isinstance(downs, int):
        downs = [downs]
    ok = delta in set(downs) or (delta == 0 and held_in_chord)
    ctx = {
        '该声部是七音': is_seventh,
        '没有级进下行或保持为和弦音': not ok,
    }
    return _match(spec, ctx)


def chord_faults(leading_count: int, roles: set, is_seventh: bool,
                 book: Optional[Dict[str, dict]] = None) -> List[str]:
    """R09。返回要报告的短句；空列表表示通过。匹配方式见文件里的「匹配」。"""
    spec = get('R09', book)
    cap = int(spec['参数']['导音最多出现'])
    need = {ROLE_NAME[n.strip()] for n in _as_names(spec['参数']['必须有'])}
    if is_seventh:
        need |= {ROLE_NAME[n.strip()] for n in _as_names(spec['参数']['七和弦还要'])}
    missing = need - roles
    ctx = {
        '导音出现次数超过规定': leading_count > cap,
        '缺少规定的和弦音': bool(missing),
    }
    fired = _which(spec, ctx)
    out = []
    if '导音出现次数超过规定' in fired:
        out.append('导音重复')
    if '缺少规定的和弦音' in fired:
        out.append(f'和弦不完整（缺 {sorted(missing)}）')
    return out


def _yes(value) -> bool:
    return str(value).strip() in ('是', '1', 'true', 'True', 'yes')


def gap_limits(tb_max: Optional[int] = None, book: Optional[Dict[str, dict]] = None):
    """R04 的三个间距上限。tb_max 只覆盖次中音与低音，供评测把这一档放宽。"""
    p = get('R04', book)['参数']
    sa = int(p['女高音与中音不超过'])
    at = int(p['中音与次中音不超过'])
    tb = int(p['次中音与低音不超过']) if tb_max is None else int(tb_max)
    return sa, at, tb


def spacing_violation(v: Sequence[int], tb_max: Optional[int] = None,
                      book: Optional[Dict[str, dict]] = None) -> bool:
    """R04。真表示交叉或间距超过定义文件。"""
    spec = get('R04', book)
    s, a, t, b = v
    sa, at, tb = gap_limits(tb_max, book)
    if _yes(spec['参数'].get('允许同度', '是')):
        crossed = not (s >= a >= t >= b)
    else:
        crossed = not (s > a > t > b)
    wide = (s - a) > sa or (a - t) > at or (t - b) > tb
    return _match(spec, {'声部交叉': crossed, '相邻间距超过规定': wide})


def writer_forbids_unison(book: Optional[Dict[str, dict]] = None) -> bool:
    return _yes(get('R04', book)['参数'].get('写作候选禁止同度', '是'))


def out_of_range(pitch: int, lo: int, hi: int, book: Optional[Dict[str, dict]] = None) -> bool:
    """R05。界限来自调用方传入的习得音域，含不含边界由定义文件决定。"""
    spec = get('R05', book)
    if '音高超出该声部音域' not in spec['必须']:
        return False
    if _yes(spec['参数'].get('含上下限', '是')):
        return not (lo <= pitch <= hi)
    return not (lo < pitch < hi)


def range_enforced(book: Optional[Dict[str, dict]] = None) -> bool:
    return '音高超出该声部音域' in get('R05', book)['必须']


def melodic_limits(book: Optional[Dict[str, dict]] = None):
    """R08：不良半音列表，以及「大于」这个上限。"""
    p = get('R08', book)['参数']
    bad = p['不良半音']
    if isinstance(bad, int):
        bad = [bad]
    return [int(x) for x in bad], int(p['大于'])


def seventh_steps(book: Optional[Dict[str, dict]] = None) -> List[int]:
    downs = get('R07', book)['参数']['下行解决']
    if isinstance(downs, int):
        downs = [downs]
    return [int(x) for x in downs]


def leading_step(book: Optional[Dict[str, dict]] = None) -> int:
    return int(get('R06', book)['参数']['解决上行半音'])


def forbid_doubled_seventh(book: Optional[Dict[str, dict]] = None) -> bool:
    return _yes(get('R09', book)['参数'].get('写作时七音不重复', '是'))


def leading_cap(book: Optional[Dict[str, dict]] = None) -> int:
    return int(get('R09', book)['参数']['导音最多出现'])


def unattested_forbidden(book: Optional[Dict[str, dict]] = None) -> bool:
    return '未出现的和弦连接禁止使用' in get('R10', book)['必须']


def cadence_lock_beats(book: Optional[Dict[str, dict]] = None) -> int:
    if '乐句末尾使用终止公式' not in get('R11', book)['必须']:
        return 0
    return int(get('R11', book)['参数']['锁定末尾拍数'])


def soprano_lock_beats(book: Optional[Dict[str, dict]] = None) -> int:
    if '乐句末尾使用终止公式' not in get('R11', book)['必须']:
        return 0
    return int(get('R11', book)['参数']['女高音锁定末尾度数'])


def structural_step(book: Optional[Dict[str, dict]] = None) -> int:
    spec = (book or default_rules()).get('共同') or {}
    return int((spec.get('参数') or {}).get('级进不超过', 2))


def structural_on(book: Optional[Dict[str, dict]] = None) -> bool:
    spec = (book or default_rules()).get('共同')
    return bool(spec) and '拍点挂留按解决音判断' in spec['必须']


def tritone_recovered(a: int, b: int, nxt: Optional[int],
                      book: Optional[Dict[str, dict]] = None) -> bool:
    """R08 例外：下行三全音（6 个半音）之后反向级进。"""
    if not has_exception('R08', '下行三全音后反向级进', book):
        return False
    return b - a == -6 and nxt is not None and 1 <= nxt - b <= 2


def _as_names(value) -> List[str]:
    if isinstance(value, str):
        return [p.strip() for p in value.replace('，', ',').split(',') if p.strip()]
    return [str(value)]


def _match(spec: dict, ctx: dict) -> bool:
    return bool(_which(spec, ctx))


def _which(spec: dict, ctx: dict) -> List[str]:
    unknown = [c for c in spec['必须'] if c not in ctx]
    if unknown:
        raise ValueError(f"{spec['id']} 有未定义的条件：{unknown}")
    if spec.get('匹配') == '任一':
        return [c for c in spec['必须'] if ctx[c]]
    if all(ctx[c] for c in spec['必须']):
        return list(spec['必须'])
    return []


def musician_text(book: Optional[Dict[str, dict]] = None) -> str:
    """教程和界面用的纯文本，不含内部半音编号以外的程序细节。"""
    book = book or default_rules()
    blocks = []
    order = list(RULE_IDS) + [rid for rid in book if rid not in RULE_IDS]
    for rid in order:
        spec = book[rid]
        lines = [f"{rid}  {spec.get('名称', '')}", spec.get('说明', ''), f"检查：{spec.get('检查', '')}"]
        if spec['必须']:
            lines.append('满足下面每一句才记违例：' if spec.get('匹配') != '任一'
                         else '下面任何一句成立就记违例：')
            lines.extend(f'  · {c}' for c in spec['必须'])
        params = spec['参数']
        if params:
            lines.append('可改的数：')
            for k, v in params.items():
                shown = ', '.join(str(x) for x in v) if isinstance(v, list) else v
                lines.append(f'  · {k} = {shown}')
        if spec['例外']:
            lines.append('可以放过：')
            lines.extend(f'  · {e}' for e in spec['例外'])
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)
