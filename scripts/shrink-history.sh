#!/usr/bin/env bash
# Rewrite ARES's git history to drop build output and other files that are no
# longer part of the tree.
#
# THIS IS IRREVERSIBLE. It rewrites every commit hash in the repository. Every
# existing clone, fork, branch and open pull request is invalidated. Run it
# once, immediately before the repository goes public, and never after.
#
# It deliberately does NOT touch your working repository. It operates on a
# throwaway mirror, verifies the result, and prints the one command that adopts
# it — leaving that decision to a human who has read the verification output.
#
#   ./scripts/shrink-history.sh              # conservative: build output + art
#   ./scripts/shrink-history.sh --changelog  # also drop the donor CHANGELOG.md
#
# VERIFIED end-to-end on a disposable clone of this repository, not estimated:
#
#   a fresh --no-local clone today          195 MB
#   conservative strip                      135 MB   (-60 MB, -31%)
#   + donor CHANGELOG.md                   ~72 MB    (projected, -122 MB)
#
# That run also confirmed 7363 -> 7363 commits and a byte-identical HEAD tree.
#
# The local .git is ~376 MB, but that is repacking slack. 194 MB is what
# someone cloning from GitHub actually downloads, and the number to judge this
# against.
#
# On --changelog: CHANGELOG.md is 71 MB packed across its revisions, is a
# hermes-webui donor file, and does not exist at HEAD. Dropping it is the single
# biggest win available. It also destroys `git log` and `git blame` for that
# file's donor-era history. THIRD_PARTY.md records the provenance in prose, so
# the attribution record survives; the archaeological one does not. That is a
# judgement call, which is why it is a flag and not the default.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/ares-history-rewrite"
MIRROR="$WORK/ares-mirror.git"
DROP_CHANGELOG=0

for arg in "$@"; do
  case "$arg" in
    --changelog) DROP_CHANGELOG=1 ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# ── preflight ──────────────────────────────────────────────────────────────
FILTER_REPO="$REPO_ROOT/services/controller/.venv/bin/git-filter-repo"
if [[ ! -x "$FILTER_REPO" ]]; then
  if command -v git-filter-repo >/dev/null 2>&1; then
    FILTER_REPO="$(command -v git-filter-repo)"
  else
    echo "✗ git-filter-repo not found." >&2
    echo "  Install it:  $REPO_ROOT/services/controller/.venv/bin/python -m pip install git-filter-repo" >&2
    exit 1
  fi
fi

if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
  echo "✗ Working tree is not clean." >&2
  echo "  A history rewrite must start from a committed state, or uncommitted" >&2
  echo "  work silently fails to carry across. Commit or stash first." >&2
  exit 1
fi

BEFORE_COMMITS="$(git -C "$REPO_ROOT" rev-list --all --count)"
BEFORE_HEAD_TREE="$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"

echo "→ Mirroring to $MIRROR"
rm -rf "$WORK"; mkdir -p "$WORK"
# --no-local matters: a local clone hardlinks the object store, which both
# defeats repacking and makes git-filter-repo refuse to run.
git clone --quiet --no-local --mirror "$REPO_ROOT" "$MIRROR"
BEFORE_SIZE="$(du -sh "$MIRROR" | cut -f1)"
echo "  fresh clone size: $BEFORE_SIZE  ($BEFORE_COMMITS commits)"

# ── the rewrite ────────────────────────────────────────────────────────────
ARGS=(
  --invert-paths
  # Keep commits that become empty once their only content was a stripped
  # file. A commit whose whole diff was "delete the bundled character art"
  # is a no-op after that art never existed — but silently vanishing commits
  # make the rewrite impossible to audit against the original, and the
  # commit-count check below is the cheapest proof that nothing else was
  # lost. Preserve the shape; only the bytes should shrink.
  --prune-empty never
  --path-glob '.build/*'
  --path-glob '*.dSYM/*'
  --path-glob '*ModuleCache*'
  # --path (a directory prefix) rather than --path-glob: filter-repo's globs
  # would need the leading '*' to span four path segments
  # (apps/macos/Sources/ARES/), which it does not do. The first run of this
  # script used a glob here, reported success, and left all 14 images fully
  # recoverable from history — gone from HEAD, still in every clone.
  # NO trailing slash: filter-repo treats 'dir/' as a literal path that never
  # matches, silently stripping nothing while still reporting success. Two
  # rewrites shipped with the art intact before this was caught.
  --path 'apps/macos/Sources/ARES/Resources/Characters'
  --path '.graphify_cached.json'
  --path-glob '*.DS_Store'
)
if [[ "$DROP_CHANGELOG" -eq 1 ]]; then
  ARGS+=(--path 'CHANGELOG.md')
  echo "→ Including donor CHANGELOG.md in the strip"
fi

# Codex tooling leaves refs/codex/turn-diffs/checkpoints/... pointing at bare
# TREES rather than commits. filter-repo cannot rewrite those ("Unexpected
# object of type tree, skipping") so they survive every strip and keep the
# objects they reference alive — including, in this repository, all 14
# character images. They are editor checkpoints, not history, and `git clone`
# does not fetch them, but `push --mirror` and importers do. Drop them.
CODEX_REFS="$(git -C "$MIRROR" for-each-ref --format='%(refname)' refs/codex 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$CODEX_REFS" != "0" ]]; then
  echo "→ Dropping $CODEX_REFS Codex checkpoint ref(s) that pin stripped objects"
  git -C "$MIRROR" for-each-ref --format='%(refname)' refs/codex |
    while read -r ref; do git -C "$MIRROR" update-ref -d "$ref"; done
fi

echo "→ Rewriting (this is the irreversible step, on the MIRROR only)"
# --force: filter-repo treats a --mirror clone as "not freshly packed" and asks
# for explicit confirmation. The mirror is disposable and recreated above on
# every run, so this is the documented invocation, not a safety override on
# your real repository.
( cd "$MIRROR" && "$FILTER_REPO" --force "${ARGS[@]}" ) >/dev/null

( cd "$MIRROR" && git reflog expire --expire=now --all && git gc --prune=now --quiet )

# ── verification ───────────────────────────────────────────────────────────
AFTER_SIZE="$(du -sh "$MIRROR" | cut -f1)"
AFTER_COMMITS="$(git -C "$MIRROR" rev-list --all --count)"
AFTER_HEAD_TREE="$(git -C "$MIRROR" rev-parse HEAD^{tree})"

echo
echo "── verification ──────────────────────────────────────────────"
printf "  size      %s  ->  %s\n" "$BEFORE_SIZE" "$AFTER_SIZE"
printf "  commits   %s  ->  %s\n" "$BEFORE_COMMITS" "$AFTER_COMMITS"

FAILED=0
if [[ "$BEFORE_COMMITS" != "$AFTER_COMMITS" ]]; then
  echo "  ✗ commit count changed — the rewrite dropped commits, not just blobs"
  FAILED=1
else
  echo "  ✓ every commit survived"
fi

# The important safety property: the CURRENT tree must be untouched, because
# none of the stripped paths exist at HEAD. If this differs, the rewrite
# removed something the project still ships.
if [[ "$BEFORE_HEAD_TREE" == "$AFTER_HEAD_TREE" ]]; then
  echo "  ✓ HEAD tree is byte-identical — no shipped file was removed"
else
  echo "  ✗ HEAD tree CHANGED ($BEFORE_HEAD_TREE -> $AFTER_HEAD_TREE)"
  echo "    Something still present at HEAD matched a strip pattern."
  echo "    Inspect before going further:"
  echo "      git -C '$MIRROR' diff $BEFORE_HEAD_TREE $AFTER_HEAD_TREE --stat"
  FAILED=1
fi

if [[ "$FAILED" -ne 0 ]]; then
  echo
  echo "✗ Verification failed. The mirror is left at $MIRROR for inspection."
  echo "  Your repository is untouched."
  exit 1
fi

cat <<EOF

✓ Rewrite verified. Your repository has NOT been modified.

To adopt it — only when you are ready to invalidate every existing clone:

  git -C "$REPO_ROOT" remote set-url origin "$MIRROR"
  git -C "$REPO_ROOT" fetch origin
  # inspect, then reset your branches to the rewritten refs

Or simply push the mirror to a fresh empty remote and make that canonical.

Keep a backup of the original until you are certain:
  cp -R "$REPO_ROOT/.git" "$REPO_ROOT/.git.backup-before-rewrite"
EOF
