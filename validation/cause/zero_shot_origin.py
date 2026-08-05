"""External AI-origin diagnostic using Fast-DetectGPT probability curvature.

This is deliberately validation-only.  The default ``gpt2`` model is a small
same-model approximation used to test whether probability geometry transfers
between corpora; it is not represented as the published multi-billion-
parameter Fast-DetectGPT configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Sequence

import numpy as np
from sklearn.metrics import roc_auc_score

from validation.cause.padben import DIRECT_AI, HUMAN, HUMANIZED_AI, bundle_padben_records


def analytic_sampling_discrepancy(logits: "object", labels: "object") -> "object":
    """Official Fast-DetectGPT analytic statistic for a same-model detector."""

    import torch

    labels = labels.unsqueeze(-1)
    log_probabilities = torch.log_softmax(logits, dim=-1)
    probabilities = torch.softmax(logits, dim=-1)
    observed = log_probabilities.gather(dim=-1, index=labels).squeeze(-1)
    expected = (probabilities * log_probabilities).sum(dim=-1)
    variance = (probabilities * log_probabilities.square()).sum(dim=-1) - expected.square()
    return (observed.sum(dim=-1) - expected.sum(dim=-1)) / variance.sum(dim=-1).sqrt()


def score_texts(
    texts: Sequence[str],
    *,
    model_name: str,
    cache_path: Path,
    device: str,
    max_tokens: int = 512,
) -> np.ndarray:
    """Score texts with a content-addressed cache and deterministic truncation."""

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    hashes = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
    cache_key = hashlib.sha256(
        json.dumps([model_name, max_tokens, hashes], separators=(",", ":")).encode()
    ).hexdigest()
    scores = np.full(len(texts), np.nan, dtype=np.float64)
    if cache_path.exists():
        cached = np.load(cache_path, allow_pickle=False)
        if str(cached["cache_key"].item()) == cache_key:
            scores = cached["scores"]
            if np.isfinite(scores).all():
                return scores

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(model_name).to(device).eval()
    started = time.monotonic()
    pending = np.flatnonzero(~np.isfinite(scores))
    for completed, index in enumerate(pending, start=1):
        text = texts[index]
        encoded = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=max_tokens,
            return_token_type_ids=False,
        ).to(device)
        if encoded.input_ids.shape[1] < 3:
            scores[index] = 0.0
            continue
        with torch.inference_mode():
            logits = model(**encoded).logits[:, :-1]
            statistic = analytic_sampling_discrepancy(logits, encoded.input_ids[:, 1:])
        scores[index] = float(statistic.detach().cpu().item())
        if completed % 10 == 0 or completed == len(pending):
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(cache_path, cache_key=np.asarray(cache_key), scores=scores)
            elapsed = time.monotonic() - started
            print(
                f"scored {completed}/{len(pending)} pending texts "
                f"({elapsed / completed:.2f}s/text)",
                flush=True,
            )
    return scores


def threshold_at_fpr(human_scores: np.ndarray, target_fpr: float = 0.01) -> float:
    """Conservative empirical threshold; equality is treated as selected."""

    raw_scores = np.asarray(human_scores)
    score_dtype = (
        raw_scores.dtype
        if np.issubdtype(raw_scores.dtype, np.floating)
        else np.dtype(np.float64)
    )
    human_scores = np.sort(raw_scores.astype(score_dtype, copy=False))
    if human_scores.size == 0:
        raise ValueError("human calibration scores are required")
    allowed = int(np.floor(target_fpr * human_scores.size))
    infinity = score_dtype.type(np.inf)
    if allowed == 0:
        return float(np.nextafter(human_scores[-1], infinity))
    return float(np.nextafter(human_scores[-allowed], infinity))


def summarize(labels: Sequence[str], scores: np.ndarray, threshold: float) -> dict:
    labels = np.asarray(labels, dtype=object)
    scores = np.asarray(scores, dtype=np.float64)
    ai = np.isin(labels, [DIRECT_AI, HUMANIZED_AI])
    selected = scores >= threshold
    return {
        "n": len(labels),
        "auc_ai_vs_human": round(float(roc_auc_score(ai, scores)), 4),
        "threshold": threshold,
        "human_fpr": round(float(selected[~ai].mean()), 4),
        "direct_ai_recall": round(float(selected[labels == DIRECT_AI].mean()), 4),
        "humanized_ai_recall": round(float(selected[labels == HUMANIZED_AI].mean()), 4),
        "selected": int(selected.sum()),
        "counts": dict(Counter(labels.tolist())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raid-data", required=True, type=Path)
    parser.add_argument("--padben-data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default="gpt2")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-tokens", type=int, default=512)
    args = parser.parse_args()

    raid_rows = json.loads(args.raid_data.read_text(encoding="utf-8"))["rows"]
    # Llama rows calibrate the threshold; Mistral is the generator-held lock.
    raid_labels = [HUMAN if row["model"] == "human" else (DIRECT_AI if row["attack"] == "none" else HUMANIZED_AI) for row in raid_rows]
    raid_texts = [str(row["generation"]) for row in raid_rows]
    raid_scores = score_texts(
        raid_texts,
        model_name=args.model,
        cache_path=args.output.with_suffix(".raid_scores.npz"),
        device=args.device,
        max_tokens=args.max_tokens,
    )
    def root_bucket(row: dict) -> int:
        root = str(row["id"] if row["attack"] == "none" else row["adv_source_id"])
        return int(hashlib.sha256(f"zero-shot-origin:{root}".encode()).hexdigest()[:8], 16) % 2

    development = np.asarray(
        [row["model"] == "llama-chat" or (row["model"] == "human" and root_bucket(row) == 0) for row in raid_rows]
    )
    human_development = np.asarray(raid_labels, dtype=object)[development] == HUMAN
    threshold = threshold_at_fpr(raid_scores[development][human_development])
    locked = np.asarray(
        [row["model"] == "mistral-chat" or (row["model"] == "human" and root_bucket(row) == 1) for row in raid_rows]
    )

    records = json.loads(args.padben_data.read_text(encoding="utf-8"))
    bundles = bundle_padben_records(records, max_bundles_per_source_variant=40)
    padben_texts = [bundle.text for bundle in bundles]
    padben_labels = [bundle.cause for bundle in bundles]
    padben_scores = score_texts(
        padben_texts,
        model_name=args.model,
        cache_path=args.output.with_suffix(".padben_scores.npz"),
        device=args.device,
        max_tokens=args.max_tokens,
    )
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "Fast-DetectGPT analytic same-model probability-curvature diagnostic",
        "model": args.model,
        "published_configuration": False,
        "published_model_pair": args.model == "EleutherAI/gpt-neo-2.7B",
        "configuration_note": (
            "The GPT-Neo same-model pair appears in the official implementation; "
            "the 256-token truncation and local evaluation protocol differ."
            if args.model == "EleutherAI/gpt-neo-2.7B"
            else "Small-model approximation outside the published model pairs."
        ),
        "scope": "validation-only; threshold calibrated solely on RAID llama-chat human controls",
        "raid_sha256": hashlib.sha256(args.raid_data.read_bytes()).hexdigest(),
        "padben_sha256": hashlib.sha256(args.padben_data.read_bytes()).hexdigest(),
        "raid_generator_held_lock": summarize(np.asarray(raid_labels)[locked], raid_scores[locked], threshold),
        "padben_external": summarize(padben_labels, padben_scores, threshold),
    }
    failures = []
    for name in ("raid_generator_held_lock", "padben_external"):
        result = payload[name]
        if result["human_fpr"] > 0.01:
            failures.append(f"{name}:human_fpr>0.01")
        if min(result["direct_ai_recall"], result["humanized_ai_recall"]) < 0.50:
            failures.append(f"{name}:recall<0.50")
    payload["promotion_gate"] = {"passed": not failures, "failures": failures}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
