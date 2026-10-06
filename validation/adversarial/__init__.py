"""validation.adversarial — offline red-team measurement harness (SP1).

Implements the threat model in
docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md
against the corpora already built for validation/public_authors/. This
package is entirely offline (no live scoring, no Postgres) and is not
under the original/ 98% coverage gate.

Task 13 (this module's first task) is victim-profile construction only —
see profiles.py. Later tasks add adversarial generators, poisoning
strategies, a runner, and gate wiring; they are out of scope here.
"""
