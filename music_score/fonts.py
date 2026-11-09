# -*- coding: utf-8 -*-
"""Load UI / music symbol fonts so palette + score glyphs are not tofu boxes."""
from __future__ import annotations

import os
import sys
from typing import List

_LOADED = False
_FAMILIES: List[str] = []


def ensure_music_fonts() -> List[str]:
    """Register Segoe UI Symbol / Segoe UI / YaHei when present.

    Offscreen Qt (QT_QPA_PLATFORM=offscreen) starts with an empty font
    database; without this, Musical Symbols (U+1D1xx) and ♯♭♮ render as
    empty rectangles.
    """
    global _LOADED, _FAMILIES
    if _LOADED:
        return list(_FAMILIES)
    try:
        from PyQt5.QtGui import QFontDatabase
    except Exception:
        return []

    candidates = []
    if sys.platform.startswith('win'):
        windir = os.environ.get('WINDIR', r'C:\Windows')
        fontdir = os.path.join(windir, 'Fonts')
        candidates = [
            os.path.join(fontdir, 'seguisym.ttf'),   # Segoe UI Symbol
            os.path.join(fontdir, 'segoeui.ttf'),    # Segoe UI
            os.path.join(fontdir, 'segoeuib.ttf'),
            os.path.join(fontdir, 'msyh.ttc'),       # Microsoft YaHei
            os.path.join(fontdir, 'msyhbd.ttc'),
            os.path.join(fontdir, 'arial.ttf'),
        ]
    elif sys.platform == 'darwin':
        candidates = [
            '/System/Library/Fonts/Apple Symbols.ttf',
            '/Library/Fonts/Arial Unicode.ttf',
        ]
    else:
        candidates = [
            '/usr/share/fonts/truetype/noto/NotoMusic-Regular.ttf',
            '/usr/share/fonts/opentype/noto/NotoMusic-Regular.otf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]

    fams: List[str] = []
    for path in candidates:
        if not os.path.isfile(path):
            continue
        fid = QFontDatabase.addApplicationFont(path)
        if fid >= 0:
            fams.extend(QFontDatabase.applicationFontFamilies(fid))
    _FAMILIES = fams
    _LOADED = True
    return list(_FAMILIES)


def music_ui_font(point_size: int = 13):
    """QFont for palette / toolbar music glyphs."""
    from PyQt5.QtGui import QFont, QFontDatabase
    fams = set(ensure_music_fonts())
    # Prefer real symbol fonts; never lead with missing Noto Music.
    for family in ('Segoe UI Symbol', 'Apple Symbols', 'Noto Music', 'Segoe UI', 'Microsoft YaHei'):
        if fams and family not in fams and family not in QFontDatabase().families():
            continue
        f = QFont(family, point_size)
        f.setStyleHint(QFont.SansSerif)
        return f
    return QFont('Sans Serif', point_size)
