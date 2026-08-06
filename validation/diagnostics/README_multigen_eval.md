# Multi-generator in-domain AI-detector eval

Status as of 2026-07-10: **not done.** This document explains what exists,
what the harness in this directory does, and what is calendar-gated and
cannot be shortcut.

## The gap this closes

The pilot runbook (`docs/PILOT_RUNBOOK.md`) and `MODEL_CARD.md` require a
**genuine multi-generator, in-domain** eval before the AI-likelihood
detector's enablement gate can be trusted. Two properties, both required:

- **in-domain** — seminary/theology-register text, the pilot's actual
  register (not generic academic prose)
- **multi-generator** — AI samples from more than one provider, so a
  "detector" that's really just "detects Claude's style" doesn't pass by
  accident

The two historical files that sound like they satisfy this don't, each for
a different reason (both files now carry an explanatory field saying so):

| File | In-domain? | Multi-generator? | Why it falls short |
|---|---|---|---|
| `ai_detector_eval_seminary_v2_multigen_2026-07-02.json` | Yes | **No** | `per_ai_provider` shows `claude` only, n=20. Filename says "multigen"; it isn't. Mislabeled at generation time by a hand-chosen `--report` path. |
| `ai_detector_eval_m4_v2_multigen_2026-07-02.json` | **No** | Yes (chatgpt/cohere/davinci, see `per_generator_tpr`) | Genuinely multi-generator, but M4 is generic academic text, not seminary essays. Filename is accurate; it just doesn't cover the in-domain half of the gate. |

**Do not cite either file as "the multi-generator in-domain eval."** Neither
is. There isn't one yet.

## What the harness does

`generators.py` defines a `Generator` interface — a named source of
AI-written text samples:

```python
class Generator(ABC):
    name: str
    configured: bool          # can this generator produce samples right now?
    def skip_reason() -> str | None
    def load_samples(prompts: list[str]) -> list[GeneratedSample]
```

Concrete generators:

- `ClaudeStaticGenerator` — replays the 20 already-committed Claude essays
  in `validation/corpus/` (manifest `label=ai_generated`,
  `ai_provider=claude`). Always configured, makes no network call. This is
  how the harness runs today with zero setup.
- `OpenAIGenerator` — live, needs `OPENAI_API_KEY` + the `openai` package.
- `GeminiGenerator` — live, needs `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) +
  the `google-generativeai` package.
- `CohereGenerator` — live, needs `COHERE_API_KEY` + the `cohere` package.

`multigen_harness.py` walks the registry, and for each generator:

- **unconfigured** → reports `SKIPPED` with the exact missing piece (env
  var name or package name). It never invents placeholder samples or fake
  scores for a generator that isn't set up.
- **configured, live** → calls it against the same 20 seminary prompts the
  Claude essays use (for an apples-to-apples comparison), and stages the
  output as `.txt` files under `validation/diagnostics/generated_essays/<provider>/`.
  Staging is deliberately separate from ingestion — the harness prints the
  exact `scripts/add_ai_essays.py ... --provider <name>` command to pull
  staged essays into the versioned corpus (`validation/corpus/` +
  `validation/manifest.json`) as a reviewed, manual step.
- **configured, static (claude)** → samples are already in the corpus;
  nothing to stage.

It then runs `scripts/train_ai_detector.py eval-seminary` against whatever
is currently in the corpus, reads the `per_ai_provider` breakdown back out,
and computes `actually_multigen = len(providers_with_n>0_samples) >= 2` —
**this boolean, not a hand-picked filename, decides the output name.** A
run with only Claude configured writes
`ai_detector_eval_seminary_v3_single_gen_claude_<date>.json` and says so
explicitly in `generator_harness.single_generator_caveat`. Only a run where
≥2 providers actually contributed samples produces a file whose name
contains `multigen`.

Run it:

```bash
.venv/bin/python validation/diagnostics/multigen_harness.py
```

## Adding a new generator

1. Subclass `Generator` (or `_LiveAPIGenerator` if it's a live completion
   API) in `generators.py`. Implement `_complete(prompt) -> str` (for
   `_LiveAPIGenerator` subclasses) or `configured`/`skip_reason`/
   `load_samples` directly.
2. Set `env_var` and `package` (for `_LiveAPIGenerator` subclasses) so the
   harness can report a precise skip reason when unconfigured.
3. Append an instance to `default_registry()`.
4. No changes needed in `multigen_harness.py` — it iterates the registry.

## Configuring provider API keys

Set the relevant env var before running the harness. None of these are
required for the harness to run — unconfigured generators are skipped, not
faked:

| Provider | Env var | Package |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | `openai` |
| Gemini | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | `google-generativeai` |
| Cohere | `COHERE_API_KEY` | `cohere` |

As of this writing, none of these keys or packages are present in this
environment, so a harness run here is honestly single-generator
(claude-only, static replay). Getting a second provider configured and
re-running is what turns the eval genuinely multi-generator — that part is
pure setup (an API key + `pip install`), not something this harness needs
further code changes for.

## What is calendar-gated and cannot be shortcut by this harness

Two later steps in the runbook are **not** buildable by running more code
today:

1. **4-week shadow-mode data collection** on live pilot traffic
   (`docs/PILOT_RUNBOOK.md` §3, `AI_LIKELIHOOD_SHADOW=1`). This requires an
   actual deployed pilot receiving real student submissions over real
   weeks. The pilot has not been deployed as of 2026-07-10. There is no
   synthetic substitute — the whole point of the shadow period is
   real-world false-positive measurement on submissions nobody can
   pre-label.
2. **≥30 instructor-labeled corrections** feeding the week-5 go/no-go
   (`docs/PILOT_RUNBOOK.md` §3 checklist). These come from professors
   reviewing real flagged submissions during the shadow period above —
   they don't exist until step 1 has been running for weeks.

Both are downstream of a pilot deployment that hasn't happened yet. This
harness closes the eval-methodology gap (a real multi-generator, in-domain
number to look at before enabling further); it does not and cannot
accelerate the calendar-gated soak.
