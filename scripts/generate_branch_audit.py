"""Generate the reproducible branch inventory required by Campaign Plan 05 M2."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "superpowers" / "plans" / "2026-08-26-branch-audit.md"
KEEP = {"backup-155-full", "codex/pre-sync-backup"}
LIVE = {
    "claude/gates-all-evaluable": "Plan 01 (content applied on codex/campaign-completion)",
    "claude/topic-sensitivity-derivation": "Plan 02 (content applied on codex/campaign-completion)",
    "claude/typing-cadence-benchmarks-fdb276": "Plan 05; PR #160 awaits human NORM_BOUNDS approval",
    "claude/consent-retention-model": "Plan 05 (documents applied on codex/campaign-completion)",
    "codex/campaign-completion": "active campaign branch",
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> None:
    refs = git("for-each-ref", "--sort=refname",
               "--format=%(refname:short)|%(committerdate:short)|%(objectname:short)",
               "refs/heads").splitlines()
    lines = ["# Branch audit — 2026-08-26", "",
             "Generated from local refs. `git cherry main <branch>` supplies the unique-commit count; "
             "a zero count is direct ancestry/content evidence. Rows with unique patch content remain "
             "human-review items rather than speculative merge recommendations.", "",
             "| Branch | Last commit | Not on main | Verdict | Evidence / recommendation |",
             "|---|---:|---:|---|---|"]
    for record in refs:
        branch, date, sha = record.split("|")
        cherry = git("cherry", "main", branch).splitlines() if branch != "main" else []
        unique = sum(line.startswith("+") for line in cherry)
        if branch == "main":
            verdict, evidence = "base", f"tip `{sha}`; keep"
        elif branch in KEEP:
            verdict, evidence = "backup", "keep unless the human explicitly says otherwise"
        elif branch in LIVE:
            verdict, evidence = "live", LIVE[branch]
        elif unique == 0:
            verdict, evidence = "landed-via-squash/ancestry", "`git cherry` has no `+` commits; deletion recommended"
        else:
            verdict = "unknown — human review"
            evidence = f"`git cherry` reports {unique} unique patch(es); retain until content review"
        lines.append(f"| `{branch}` | {date} | {unique} | {verdict} | {evidence} |")
    OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
