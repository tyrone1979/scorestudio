#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python}"

"$PYTHON" -m score_learning.experiments \
  e1 e1b e1c e1d e1g e1h e1i e2e e7 e8
"$PYTHON" -m score_learning.grammar.range_ablation
"$PYTHON" -m score_learning.grammar.rule_ablation
"$PYTHON" -m score_learning.grammar.rule_ablation --r02-case
"$PYTHON" -m score_learning.grammar.fault_inject
"$PYTHON" -m score_learning.leadsheet.eval_memory
"$PYTHON" -m pytest -q
