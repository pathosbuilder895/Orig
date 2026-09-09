"""Certification suite — three-valued behavioural gates (pass/fail/uninformative).

These tests certify product-level claims through the live API, the way the
product actually runs, rather than through the unit scoring path. Each one
records a verdict to ``CERT_REPORT_PATH`` (see ``conftest.record_verdict``)
whether it passes, fails, or is uninformative for want of sample size.
"""
