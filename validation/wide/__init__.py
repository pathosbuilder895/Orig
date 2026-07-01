"""
validation/wide/ — Public-dataset benchmark adapters.

Each adapter (``raid.py``, ``pan_av.py``, ``m4.py``) converts a cached
public dataset into the corpus + ``ValidationManifest`` shape that
``validation/calibration.py::run_calibration`` already consumes. The
orchestrator in ``run.py`` builds the corpus, runs calibration, and
writes the report family from ``validation/benchmark/``.

The math (Born-rule scoring, 103-feature pipeline, density matrix) is
unchanged — these adapters only provide a richer + more public corpus
to test it against.
"""
