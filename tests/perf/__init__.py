"""Performance, concurrency, and reliability tests (docs/testing/07-performance-reliability.md).

These build their own clients so warm-up state is controlled, and every
time-based assertion here follows §9: budgets are >= 3x the value measured at
authoring time (recorded in the test's docstring), there is no ``time.sleep``
polling, and a runner that cannot support the measurement produces a recorded
``uninformative`` skip rather than a pass.
"""
