"""单曲乐谱生成 CLI —— 供 MuseScore Studio 插件 / 命令行调用。

确定性风格骨架 → MusicXML（+ 可选 MIDI）。不调 LLM。

用法:
    python generate_score.py --pack fugue --bars 16 --out out.musicxml
    python generate_score.py --request request.json
    python generate_score.py --list-packs

--request 模式（插件用）读取 JSON，写出同目录 result.json：
    {"ok": true, "musicxml": "...", "midi": "...", "title": "...", ...}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

import composition_skills as skill_lib
import style_skeleton
from compose_kernel import run_program

try:
    from llm_compose import spec_to_music21
except Exception:  # pragma: no cover
    spec_to_music21 = None


PACKS = [
    'fugue', 'piano-prelude', 'classical-sonata', 'piano-sonata',
    'string-quartet', 'symphony', 'mazurka', 'waltz', 'british-folk-tune',
    'celtic-jig', 'swing-standard', 'pop-standard', 'chopin-piano',
    'chorale', 'madrigal',
]


def list_packs() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for g in skill_lib.list_genres():
        pid = str(g.get('pack_id') or '')
        if not pid or not g.get('enabled', True):
            continue
        out.append({
            'pack_id': pid,
            'name': g.get('name') or pid,
            'family': g.get('family') or '',
            'gid': g.get('id'),
        })
    return out


def _safe_name(s: str) -> str:
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in s)[:80]


def generate(
    pack: str = 'chorale',
    *,
    bars: int = 16,
    voices: Optional[int] = None,
    seed: Optional[str] = None,
    title: Optional[str] = None,
    tempo: Optional[int] = None,
    meter: Optional[str] = None,
    key: Optional[str] = None,
    fugue: str = 'auto',
    out: Optional[str] = None,
    midi: bool = True,
    out_dir: Optional[str] = None,
) -> Dict[str, Any]:
    if spec_to_music21 is None:
        raise RuntimeError('spec_to_music21 不可用（llm_compose 导入失败）')

    packs = {p['pack_id']: p for p in list_packs()}
    if pack not in packs:
        # 允许用名称 / 家族模糊匹配
        low = pack.lower()
        match = next(
            (p for p in packs.values()
             if low in p['pack_id'].lower()
             or low in str(p['name']).lower()
             or low == str(p.get('gid') or '').lower()),
            None,
        )
        if not match:
            known = ', '.join(sorted(packs))
            raise ValueError(f'未知风格包: {pack!r}；可用: {known}')
        pack = match['pack_id']
        gid = match.get('gid')
    else:
        gid = packs[pack].get('gid')

    seed = seed or f'musescore-{pack}-{datetime.now().strftime("%Y%m%d%H%M%S")}'
    kw: Dict[str, Any] = {
        'bars': int(bars),
        'seed': seed,
        'fugue': fugue or 'auto',
    }
    if voices is not None:
        kw['voices'] = int(voices)
    if title:
        kw['title'] = title
    if tempo is not None:
        kw['tempo'] = int(tempo)
    if meter:
        kw['meter'] = meter
    if key:
        kw['key'] = key

    calls = style_skeleton.build_skeleton_calls(gid or pack, **kw)
    spec = run_program(calls)
    score = spec_to_music21(spec)

    if out_dir is None:
        out_dir = os.path.join(_ROOT, 'scores', 'musescore_out')
    os.makedirs(out_dir, exist_ok=True)

    if out:
        xml_path = os.path.abspath(out)
        os.makedirs(os.path.dirname(xml_path) or '.', exist_ok=True)
    else:
        base = _safe_name(f'{pack}__{_safe_name(seed)}')
        xml_path = os.path.join(out_dir, base + '.musicxml')

    score.write('musicxml', fp=xml_path)
    mid_path = None
    if midi:
        mid_path = os.path.splitext(xml_path)[0] + '.mid'
        score.write('midi', fp=mid_path)

    return {
        'ok': True,
        'pack_id': pack,
        'seed': seed,
        'title': spec.get('title'),
        'bars': spec.get('bars'),
        'voices': spec.get('voices') or len(spec.get('parts') or []),
        'musicxml': os.path.abspath(xml_path),
        'midi': os.path.abspath(mid_path) if mid_path else None,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
    }


def _write_result(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def run_request(request_path: str) -> Dict[str, Any]:
    with open(request_path, 'r', encoding='utf-8') as f:
        req = json.load(f)
    result_path = req.get('result_path') or os.path.join(
        os.path.dirname(os.path.abspath(request_path)), 'result.json')
    try:
        result = generate(
            pack=str(req.get('pack') or 'chorale'),
            bars=int(req.get('bars') or 16),
            voices=int(req['voices']) if req.get('voices') not in (None, '') else None,
            seed=req.get('seed') or None,
            title=req.get('title') or None,
            tempo=int(req['tempo']) if req.get('tempo') not in (None, '') else None,
            meter=req.get('meter') or None,
            key=req.get('key') or None,
            fugue=str(req.get('fugue') or 'auto'),
            out=req.get('out') or None,
            midi=bool(req.get('midi', True)),
            out_dir=req.get('out_dir') or None,
        )
    except Exception as e:
        result = {
            'ok': False,
            'error': f'{type(e).__name__}: {e}',
            'traceback': traceback.format_exc(),
        }
    _write_result(result_path, result)
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description='ComposerChat 单曲生成（MusicXML）')
    ap.add_argument('--list-packs', action='store_true', help='列出可用风格包')
    ap.add_argument('--request', default=None, help='读取请求 JSON（插件模式）')
    ap.add_argument('--pack', default='chorale', help='风格包 id')
    ap.add_argument('--bars', type=int, default=16)
    ap.add_argument('--voices', type=int, default=None)
    ap.add_argument('--seed', default=None)
    ap.add_argument('--title', default=None)
    ap.add_argument('--tempo', type=int, default=None)
    ap.add_argument('--meter', default=None)
    ap.add_argument('--key', default=None)
    ap.add_argument('--fugue', default='auto', choices=['auto', 'full', 'off'])
    ap.add_argument('--out', default=None, help='输出 MusicXML 路径')
    ap.add_argument('--out-dir', default=None)
    ap.add_argument('--no-midi', action='store_true')
    ap.add_argument('--json', action='store_true', help='stdout 打印 JSON 结果')
    args = ap.parse_args(argv)

    if args.list_packs:
        packs = list_packs()
        if args.json:
            print(json.dumps(packs, ensure_ascii=False, indent=2))
        else:
            for p in packs:
                print(f"{p['pack_id']:24}  {p.get('family') or '':12}  {p['name']}")
        return 0

    if args.request:
        result = run_request(args.request)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('ok') else 1

    try:
        result = generate(
            pack=args.pack,
            bars=args.bars,
            voices=args.voices,
            seed=args.seed,
            title=args.title,
            tempo=args.tempo,
            meter=args.meter,
            key=args.key,
            fugue=args.fugue,
            out=args.out,
            midi=not args.no_midi,
            out_dir=args.out_dir,
        )
    except Exception as e:
        err = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
        print(json.dumps(err, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"OK  {result['title']}")
        print(f"MusicXML: {result['musicxml']}")
        if result.get('midi'):
            print(f"MIDI:     {result['midi']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
