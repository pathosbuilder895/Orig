"""validation.adversarial — offline red-team measurement harness (SP1).

Implements the threat model in
docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md
against committed public-domain and CC0 corpora. It scores through the real
app in-process (FastAPI TestClient, a throwaway SQLite file per process):
no network, no deployment, no Postgres. Not under the original/ 98%
coverage gate.

Modules: profiles.py (victims), generators.py (mechanical obfuscation and
the cached LLM attack readers), poisoning.py (baseline poisoning),
fetch_riddell_juola.py (the CC0 human obfuscation/imitation corpus),
runner.py (scores one profile under one attack), report.py (the full
harness run and the reducers behind gates G-A1…G-A6 in
validation/calibration_gate.py), gen_llm_attacks.py (offline LLM attack
generation; needs an API key, never runs in tests or CI).
"""
