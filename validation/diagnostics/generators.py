"""
validation/diagnostics/generators.py — pluggable AI-text sample sources for
the multi-generator in-domain eval harness (see multigen_harness.py).

Why this exists: the historical files
    validation/diagnostics/ai_detector_eval_seminary_v2_multigen_2026-07-02.json
    validation/diagnostics/ai_detector_eval_m4_v2_multigen_2026-07-02.json
are misleadingly named. The seminary one is IN-DOMAIN (the pilot's actual
register) but SINGLE-GENERATOR — all 20 AI essays are Claude, as its own
"per_ai_provider" section admits. The M4 one IS genuinely multi-generator
(chatgpt/cohere/davinci) but is OUT-OF-DOMAIN academic text, not seminary
theology essays. Neither file is "the genuine multi-generator in-domain
eval" the pilot runbook's enablement gate calls for. See
README_multigen_eval.md for the full explanation.

This module defines the `Generator` interface so that closing the gap is a
matter of plugging in more providers, not re-deriving the eval each time.

Two kinds of generator:
  - A *static* generator that reuses already-produced, already-committed
    text (no API key, no network call — e.g. the existing 20 Claude essays
    in validation/corpus/). This is how the harness can run TODAY.
  - A *live* generator that calls a provider's completion API. It reports
    itself unconfigured (and is skipped, never faked) unless its API key
    env var is set AND its SDK package is importable.

Nothing here is invoked unless multigen_harness.py imports it — the module
performs no network I/O or file mutation at import time.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
SEMINARY_CORPUS = _ROOT / "validation" / "corpus"
SEMINARY_MANIFEST = _ROOT / "validation" / "manifest.json"


@dataclass
class GeneratedSample:
    prompt: str
    text: str


class Generator(ABC):
    """One named source of AI-written text samples for the eval corpus."""

    name: str

    @property
    @abstractmethod
    def configured(self) -> bool:
        """True iff this generator can produce samples right now (static
        generators are always configured; live generators require an API
        key env var to be set AND their SDK to be importable)."""

    @abstractmethod
    def skip_reason(self) -> str | None:
        """Human-readable reason this generator is unavailable, or None if
        `configured` is True. Never fabricate a reason — state exactly
        what's missing (env var name, package name)."""

    @abstractmethod
    def load_samples(self, prompts: list[str]) -> list[GeneratedSample]:
        """Return real samples for the given prompts. Only called when
        `configured` is True. Must raise rather than return placeholder or
        fabricated text on failure — the harness treats an exception as a
        hard failure for this generator, not a silent skip."""


def _seminary_prompts() -> list[str]:
    """The 20 prompts already used for the existing Claude essays, reused
    for apples-to-apples comparison across generators."""
    manifest = json.loads(SEMINARY_MANIFEST.read_text())
    prompts = [
        e["prompt"]
        for e in manifest["entries"]
        if e.get("label") == "ai_generated" and e.get("prompt")
    ]
    # Preserve order, de-dupe.
    seen: set[str] = set()
    out = []
    for p in prompts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


class ClaudeStaticGenerator(Generator):
    """Reuses the 20 Claude theology essays already committed to
    validation/corpus/ (manifest label=ai_generated, ai_provider=claude).

    This is deliberately NOT a live API generator: it makes no network
    call and needs no API key, so the harness can execute this generator
    end-to-end today. It is honestly a *replay* of prior Claude output,
    not a fresh generation — the harness's honesty check counts it as one
    generator ("claude"), same as any other.
    """

    name = "claude"

    @property
    def configured(self) -> bool:
        return SEMINARY_MANIFEST.exists() and SEMINARY_CORPUS.exists()

    def skip_reason(self) -> str | None:
        if self.configured:
            return None
        return f"manifest or corpus dir missing ({SEMINARY_MANIFEST}, {SEMINARY_CORPUS})"

    def load_samples(self, prompts: list[str]) -> list[GeneratedSample]:
        manifest = json.loads(SEMINARY_MANIFEST.read_text())
        out = []
        for e in manifest["entries"]:
            if e.get("label") != "ai_generated" or e.get("ai_provider") != "claude":
                continue
            path = SEMINARY_CORPUS / e["filename"]
            if not path.exists():
                continue
            out.append(
                GeneratedSample(
                    prompt=e.get("prompt", ""),
                    text=path.read_text(encoding="utf-8", errors="replace"),
                )
            )
        return out


class _LiveAPIGenerator(Generator):
    """Common skeleton for a provider whose samples require a live API
    call. Subclasses set `name`, `env_var`, `package`, and implement
    `_complete(prompt) -> str`.
    """

    env_var: str = ""
    package: str = ""

    def _package_importable(self) -> bool:
        try:
            __import__(self.package)
            return True
        except ImportError:
            return False

    @property
    def configured(self) -> bool:
        return bool(os.environ.get(self.env_var, "").strip()) and self._package_importable()

    def skip_reason(self) -> str | None:
        if self.configured:
            return None
        missing = []
        if not os.environ.get(self.env_var, "").strip():
            missing.append(f"env var {self.env_var} not set")
        if not self._package_importable():
            missing.append(f"package {self.package!r} not installed")
        return "; ".join(missing)

    def _complete(self, prompt: str) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def load_samples(self, prompts: list[str]) -> list[GeneratedSample]:
        return [GeneratedSample(prompt=p, text=self._complete(p)) for p in prompts]


class OpenAIGenerator(_LiveAPIGenerator):
    """Live adapter for OpenAI chat completions. Requires OPENAI_API_KEY
    and the `openai` package. Not run in this environment (neither is
    present) — see README_multigen_eval.md for how to configure it."""

    name = "openai"
    env_var = "OPENAI_API_KEY"
    package = "openai"
    model = os.environ.get("OPENAI_EVAL_MODEL", "gpt-4o")

    def _complete(self, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ[self.env_var])
        essay_prompt = (
            f"Write a ~600-word seminary-level theology essay on: {prompt}. "
            "Plain academic prose, no headers or bullet points."
        )
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": essay_prompt}],
        )
        return resp.choices[0].message.content or ""


class GeminiGenerator(_LiveAPIGenerator):
    """Live adapter for Google Gemini. Requires GEMINI_API_KEY (or
    GOOGLE_API_KEY) and the `google-generativeai` package."""

    name = "gemini"
    env_var = "GEMINI_API_KEY"
    package = "google.generativeai"
    model = os.environ.get("GEMINI_EVAL_MODEL", "gemini-1.5-pro")

    @property
    def configured(self) -> bool:
        has_key = bool(
            os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
        )
        return has_key and self._package_importable()

    def skip_reason(self) -> str | None:
        if self.configured:
            return None
        missing = []
        if not (
            os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
        ):
            missing.append("env var GEMINI_API_KEY (or GOOGLE_API_KEY) not set")
        if not self._package_importable():
            missing.append(f"package {self.package!r} not installed")
        return "; ".join(missing)

    def _complete(self, prompt: str) -> str:
        import google.generativeai as genai

        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        genai.configure(api_key=key)
        model = genai.GenerativeModel(self.model)
        essay_prompt = (
            f"Write a ~600-word seminary-level theology essay on: {prompt}. "
            "Plain academic prose, no headers or bullet points."
        )
        resp = model.generate_content(essay_prompt)
        return resp.text or ""


class CohereGenerator(_LiveAPIGenerator):
    """Live adapter for Cohere chat/generate. Requires COHERE_API_KEY and
    the `cohere` package."""

    name = "cohere"
    env_var = "COHERE_API_KEY"
    package = "cohere"
    model = os.environ.get("COHERE_EVAL_MODEL", "command-r-plus")

    def _complete(self, prompt: str) -> str:
        import cohere

        client = cohere.Client(os.environ[self.env_var])
        essay_prompt = (
            f"Write a ~600-word seminary-level theology essay on: {prompt}. "
            "Plain academic prose, no headers or bullet points."
        )
        resp = client.chat(model=self.model, message=essay_prompt)
        return getattr(resp, "text", "") or ""


def default_registry() -> list[Generator]:
    """The full set of generators the harness knows about. Add a new
    provider by writing a Generator subclass and appending it here."""
    return [
        ClaudeStaticGenerator(),
        OpenAIGenerator(),
        GeminiGenerator(),
        CohereGenerator(),
    ]
