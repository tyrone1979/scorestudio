#!/usr/bin/env python3
"""Build the explainable Bach-keyboard grammar from the licensed WTC II corpus."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from score_learning.leadsheet.analyze import analyze_style
from score_learning.leadsheet.learn import learn
from score_learning.leadsheet import script


def main():
    pieces = analyze_style('bach_keyboard', progress=True)
    learned = learn(pieces, 'bach_keyboard')
    path = script.save(learned, 'bach_keyboard')
    print(f"pieces/regions={len(pieces)} subs={list(learned['subs'])} saved={path}")


if __name__ == '__main__':
    main()
