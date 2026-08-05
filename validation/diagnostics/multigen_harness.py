#!/usr/bin/env python
"""
validation/diagnostics/multigen_harness.py — the genuine multi-generator,
in-domain AI-detector eval harness.

Fixes the mislabeling in the historical files: nothing here is allowed to
call itself "multigen" unless samples from >=2 distinct generators actually
went into the eval. The output filename and the JSON body's
`actually_multigen` field are both derived from what really ran, not chosen
by hand.

What this does, end to end:
  1. Asks every Generator in validation/diagnostics/generators.py whether
     it's configured (has an API key + SDK, or — for the static Claude
     generator — has committed samples to reuse). Unconfigured generators
     are reported as SKIPPED with the exact missing piece; they never
     contribute fabricated or placeholder samples.
  2. For each configured LIVE generator, calls it against the 20 existing
     seminary essay prompts and stages the output under
     validation/diagnostics/generated_essays/<provider>/ as .txt files,
     printing the exact `scripts/add_ai_essays.py` command to ingest them
     into the versioned corpus. Staging is separate from ingestion on
     purpose — ingestion mutates validation/manifest.json and
     validation/corpus/, which should be a deliberate, reviewed step, not
     something this script does silently.
  3. Runs `scripts/train_ai_detector.py eval-seminary` against whatever is
     currently in the corpus (unchanged by this script unless essays were
     separately ingested), and reads back the resulting per_ai_provider
     breakdown.
  4. Writes a relabeled report: filename and `actually_multigen` reflect
     the real provider count, and a `generator_harness` section records
     exactly what ran vs. what was skipped and why.

Usage:
    .venv/bin/python validation/diagnostics/multigen_harness.py

This can be run today with zero configuration — it will honestly report
itself as single-generator (claude only, from the static replay generator)
because no other provider's API key is set in this environment. That is
the correct, non-fabricated result; it is not a bug in the harness.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

from validation.diagnostics.generators import (  # noqa: E402
    Generator,
    default_registry,
)

DIAG_DIR = _ROOT / "validation" / "diagnostics"
STAGING_DIR = DIAG_DIR / "generated_essays"
TRAIN_SCRIPT = _ROOT / "scripts" / "train_ai_detector.py"


def _seminary_prompts() -> list[str]:
    from validation.diagnostics.generators import _seminary_prompts as _p

    return _p()


def _stage_live_samples(gen: Generator, prompts: list[str]) -> Path:
    """Call a configured live generator and write its output to disk as
    staged .txt files (NOT ingested into the corpus). Returns the staging
    directory."""
    out_dir = STAGING_DIR / gen.name
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = gen.load_samples(prompts)
    if not samples:
        raise RuntimeError(f"generator {gen.name!r} is configured but returned zero samples")
    for i, s in enumerate(samples, start=1):
        (out_dir / f"{gen.name}_{i:03d}.txt").write_text(s.text, encoding="utf-8")
    prompt_map = {f"{gen.name}_{i:03d}.txt": s.prompt for i, s in enumerate(samples, start=1)}
    (out_dir / "_prompt_map.json").write_text(json.dumps(prompt_map, indent=2) + "\n")
    return out_dir


def run_harness() -> dict:
    registry = default_registry()
    prompts = _seminary_prompts()
    harness_log: dict[str, dict] = {}

    for gen in registry:
        if not gen.configured:
            harness_log[gen.name] = {
                "status": "skipped",
                "reason": gen.skip_reason(),
                "live_api": gen.name != "claude",
            }
            print(f"[multigen] SKIP {gen.name}: {gen.skip_reason()}", file=sys.stderr)
            continue

        if gen.name == "claude":
            # Static replay — no staging needed, samples already live in
            # validation/corpus/ and are picked up by eval-seminary itself.
            samples = gen.load_samples(prompts)
            harness_log[gen.name] = {
                "status": "ok",
                "mode": "static_replay",
                "n_samples": len(samples),
                "note": "reused existing committed essays; no live API call made",
            }
            print(f"[multigen] OK {gen.name}: {len(samples)} samples (static replay)")
            continue

        try:
            out_dir = _stage_live_samples(gen, prompts)
            harness_log[gen.name] = {
                "status": "ok",
                "mode": "live_api",
                "staged_dir": str(out_dir),
                "next_step": (
                    f".venv/bin/python scripts/add_ai_essays.py {out_dir} "
                    f"--provider {gen.name} --prompt-map {out_dir}/_prompt_map.json"
                ),
            }
            print(f"[multigen] OK {gen.name}: staged samples in {out_dir}")
        except Exception as exc:  # noqa: BLE001 — a live-call failure is not a skip
            harness_log[gen.name] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            print(f"[multigen] ERROR {gen.name}: {exc}", file=sys.stderr)

    # Run the actual in-domain eval against whatever is currently in the
    # corpus (unchanged by this run unless a prior invocation's staged
    # essays were separately ingested via add_ai_essays.py).
    tmp_report = DIAG_DIR / "_multigen_harness_tmp.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(TRAIN_SCRIPT),
            "eval-seminary",
            "--report",
            str(tmp_report),
        ],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
    )
    print(proc.stdout, file=sys.stderr)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"eval-seminary failed (exit {proc.returncode})")

    report = json.loads(tmp_report.read_text())
    tmp_report.unlink(missing_ok=True)

    providers_with_samples = sorted(
        p for p, block in report.get("per_ai_provider", {}).items() if (block.get("n") or 0) > 0
    )
    actually_multigen = len(providers_with_samples) >= 2

    report["generator_harness"] = {
        "harness_script": "validation/diagnostics/multigen_harness.py",
        "generators": harness_log,
        "providers_with_samples_in_eval": providers_with_samples,
        "actually_multigen": actually_multigen,
        "honesty_note": (
            "This field, not a filename chosen by hand, is what determines "
            "whether the report is allowed to claim multi-generator "
            "evidence. See README_multigen_eval.md."
        ),
    }
    if not actually_multigen:
        report["generator_harness"]["single_generator_caveat"] = (
            "Only "
            + (providers_with_samples[0] if providers_with_samples else "no")
            + " generator(s) contributed samples to this in-domain eval. "
            "Do not cite this report as multi-generator evidence for the "
            "AI_LIKELIHOOD_ENABLED enablement gate. Configure another "
            "provider's API key (see README_multigen_eval.md) and re-run."
        )
    return report


def main() -> int:
    report = run_harness()
    today = datetime.now(timezone.utc).date().isoformat()
    providers = report["generator_harness"]["providers_with_samples_in_eval"]
    if report["generator_harness"]["actually_multigen"]:
        label = "multigen_" + "-".join(providers)
    elif providers:
        label = f"single_gen_{providers[0]}"
    else:
        label = "no_providers"
    out_path = DIAG_DIR / f"ai_detector_eval_seminary_v3_{label}_{today}.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n")

    print(f"\n[multigen] actually_multigen={report['generator_harness']['actually_multigen']}")
    print(f"[multigen] providers_with_samples={providers}")
    print(f"[multigen] report -> {out_path}")
    if not report["generator_harness"]["actually_multigen"]:
        print(f"[multigen] {report['generator_harness']['single_generator_caveat']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
