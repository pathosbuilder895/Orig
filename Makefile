# Makefile — task runner that hard-codes .venv/bin/python so the system-python
# / 3.9-vs-3.11 trap (CLAUDE.md, WS-2 task 2.7) stops mattering.

.PHONY: test test-quantum run bundle e2e lint preflight backup setup

test:
	.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q

test-quantum:
	.venv/bin/python -m pytest tests/quantum/ -v

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
