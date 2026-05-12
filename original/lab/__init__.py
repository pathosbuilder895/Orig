"""
original/lab — Calibration Lab.

Bridges the offline ``validation/calibration.py`` CLI with the live API +
dashboard. Three subsystems:

- ``runner``        — thread-based async orchestrator that runs a calibration
                      and persists the result to ``calibration_runs`` (PR 8a)
- ``suggestions``   — analyzes a finished run + corrections feedback to
                      recommend threshold + tier-weight adjustments (PR 8b)
- ``datasets``      — registry of named datasets the lab can run against
                      (Federalist, multi-author, custom)

The lab is opt-in: nothing here runs unless an instructor explicitly
clicks "Run Calibration" in the dashboard. No env flags.
"""
