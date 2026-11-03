#!/usr/bin/env bash
# Publish main to GitHub (tyrone1979/scorestudio) without the papers and
# without anything unrelated to the Score Studio software itself.
#
# Gitee (origin) carries the full repository and history. GitHub gets a
# separate public history: each run takes the tree of local HEAD, drops the
# excluded paths and commits it on top of GitHub's main. Paper history is
# therefore never pushed there.
#
#   bash scripts/dev/push_github.sh ["commit message"]
#   RESET=1 bash scripts/dev/push_github.sh   # rebuild a fresh one-commit history
set -euo pipefail

cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
REMOTE="${GITHUB_REMOTE:-github}"
MSG="${1:-Sync from $(git rev-parse --short HEAD)}"

# Paths stripped from the public GitHub snapshot. Everything here is either a
# paper (manuscript, review materials, expert adjudication, audit reports) or
# an artefact that only the paper's experiments produce.
EXCLUDE=(
  # --- papers (manuscripts + cover letters + figures) ---
  papers
  # --- paper-only code and tests ---
  runs/induction/paper
  score_learning/induction/paper.py
  tests/test_induction_paper.py
  score_learning/grammar/cadence_audit.py
  score_learning/grammar/cadence_recheck.py
  score_learning/grammar/cadence_review_xlsx.py
  score_learning/grammar/cadence_score_export.py
  # --- paper audit / review / annotation docs ---
  "docs/论文同行评审_2026-10-06.md"
  "docs/论文同行评审_第二轮_2026-10-06.md"
  "docs/实验重设计与消融_2026-10-04.md"
  "docs/人工标注边界分析_2026-10-04.md"
  "docs/手工先验普查_2026-10-06.md"
  "docs/代码审计修复报告_2026-10-04.md"
  "docs/学习算法框架_2026-10-04.md"
  "docs/learn_算法分析_2026-10-04.md"
  "docs/compose-grammar体裁测试清单_2026-10-04.md"
  "docs/关系结果接入compose-grammar_2026-10-04.md"
  "docs/小节关系提取报告_2026-10-04.md"
  "docs/统一学习命令learn-all_2026-10-04.md"
  "docs/对比分析_符号音乐调研报告.md"
  "docs/机器vs人_客观评估_2026-10-05.md"
  "docs/听审量表.md"
  "docs/风格提示词大全.md"
  "docs/终止式人工评审指南_2026-10-04.md"
  "docs/评审材料_说明_2026-10-05.md"
  "docs/cadence_review"
  "docs/expert_review"
  # --- paper review/audit artefacts under runs/ ---
  "runs/listening_rubric.yaml"
  "runs/master_audit_20260929_053852.md"
  "runs/master_audit_20260929_055024.md"
  "runs/master_audit_latest.md"
  "runs/prior_census.json"
  "runs/experiments/cadence_audit.json"
  "runs/experiments/cadence_occurrences.json"
  "runs/experiments/cadence_recheck.json"
  "runs/exploratory"
  # --- earlier, paper-unrelated LLM-composition artefacts under runs/ ---
  "runs/专业提示词_单乐章交响曲.md"
  "runs/专业提示词_单乐章交响曲_v2.md"
  "runs/专业提示词_命运交响曲.md"
  "runs/旋律生成逻辑诊断.md"
  "runs/验收样例_摇摆标准曲_编辑者版.md"
  "runs/验收样例_摇摆标准曲_编辑者版_dev.md"
)

INDEX="$(mktemp)"
trap 'rm -f "$INDEX"' EXIT
GIT_INDEX_FILE="$INDEX" git read-tree HEAD
GIT_INDEX_FILE="$INDEX" git rm -r -q --cached --ignore-unmatch -- "${EXCLUDE[@]}"
TREE="$(GIT_INDEX_FILE="$INDEX" git write-tree)"

for f in "${EXCLUDE[@]}"; do
  if git ls-tree -r --name-only "$TREE" -- "$f" | grep -q .; then
    echo "excluded path still present: $f" >&2
    exit 1
  fi
done

# RESET=1 starts a fresh one-commit history (force push), e.g. after
# extending EXCLUDE so that earlier GitHub commits no longer carry the files.
if [ "${RESET:-0}" = 1 ]; then
  COMMIT="$(git commit-tree "$TREE" -m "$MSG")"
  git push --force "$REMOTE" "${COMMIT}:refs/heads/main"
  exit 0
fi

git fetch -q "$REMOTE" main
PARENT="$(git rev-parse FETCH_HEAD)"
if [ "$(git rev-parse "$PARENT^{tree}")" = "$TREE" ]; then
  echo "GitHub is already up to date"
  exit 0
fi

COMMIT="$(git commit-tree "$TREE" -p "$PARENT" -m "$MSG")"
git push "$REMOTE" "${COMMIT}:refs/heads/main"
