# Makefile — task runner that hard-codes .venv/bin/python so the system-python
# / 3.9-vs-3.11 trap (CLAUDE.md, WS-2 task 2.7) stops mattering.

.PHONY: test test-quantum test-postgres db-up db-down run bundle e2e lint preflight backup setup test-security test-cert test-known-red openapi-snapshot test-fast test-shard-core test-shard-api test-shard-rest

test:
	.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -m "not blocker and not certification" -q

# ---------------------------------------------------------------------------
# CI shards (T-46). scripts/shard_paths.py is the single source of truth for
# which paths belong to which shard — the three shard jobs in
# .github/workflows/test.yml call it with the same argument, so these targets
# reproduce a red CI shard exactly. tests/test_shard_partition.py proves the
# three selections partition the full blocking collection (no test un-run, no
# test run twice).
#
# `eval` because shard_paths.py shell-quotes its output: the gitignored macOS
# Finder duplicates ("test_tier1 2.py") give --ignore arguments containing
# spaces in a local worktree. A CI checkout has none of those files, so the
# same command needs no quoting there.
# ---------------------------------------------------------------------------

# The inner-loop target: the `rest` shard minus `slow`, no Postgres needed.
test-fast:
	eval ".venv/bin/python -m pytest $$(.venv/bin/python scripts/shard_paths.py rest) -m 'not blocker and not certification and not slow' -q"

test-shard-core:
	eval ".venv/bin/python -m pytest $$(.venv/bin/python scripts/shard_paths.py core) -m 'not blocker and not certification' -q --durations=25"

# CI gives this shard a Postgres service; locally run `make db-up` and export
# DATABASE_URL=$$(bash scripts/local_postgres.sh url) first, or the
# postgres-marked tests in it self-skip.
test-shard-api:
	eval ".venv/bin/python -m pytest $$(.venv/bin/python scripts/shard_paths.py api) -m 'not blocker and not certification' -q --durations=25"

test-shard-rest:
	eval ".venv/bin/python -m pytest $$(.venv/bin/python scripts/shard_paths.py rest) -m 'not blocker and not certification' -q --durations=25"

test-security:
	.venv/bin/python -m pytest tests/ -m security -q

test-cert:
	.venv/bin/python -m pytest tests/ -m certification -q

test-known-red:
	.venv/bin/python scripts/known_red.py

test-quantum:
	.venv/bin/python -m pytest tests/quantum/ -v

# Regenerate the committed OpenAPI schema snapshot (tests/snapshots/openapi.json)
# after a deliberate API change; review the resulting diff before committing.
openapi-snapshot:
	.venv/bin/python scripts/update_openapi_snapshot.py

# Local Postgres 16 (Docker) mirroring CI's service container, so the 166
# postgres-marked tests run for real locally instead of self-skipping.
db-up:
	bash scripts/local_postgres.sh up

db-down:
	bash scripts/local_postgres.sh down

test-postgres: db-up
	DATABASE_URL=$$(bash scripts/local_postgres.sh url) \
		.venv/bin/python -m pytest tests/ -m postgres -q

run:
	.venv/bin/python run.py --demo --frontend-dir demo/ --port 8001

bundle:
	cd demo/bluebook && npm run build

e2e:
	cd demo/bluebook && npx playwright test

# Scoped to original/ (the live package) -- tests/, validation/, scripts/,
# and alembic/ were never swept for lint compliance and are out of WS-2's
# scope; widen this once/if they're brought in line.
lint:
	.venv/bin/ruff check original/ && .venv/bin/ruff format --check original/

preflight:
	.venv/bin/python scripts/preflight.py

backup:
	scripts/backup_db.sh

setup:
	.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
	.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
