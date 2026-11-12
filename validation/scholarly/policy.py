"""Single home for the numbers every stage of the scholarly corpus shares.

Changing a value here changes what "usable" means, so the manifest and the
candidate lists record the policy they were built under (``POLICY_VERSION``).
"""
from __future__ import annotations

import hashlib

POLICY_VERSION = "1"

# --- what counts as a usable author / paper ---------------------------------
MIN_USABLE_PAPERS = 6        # 4 past papers + 2 held-out new papers
MAX_USABLE_PAPERS = 12       # stop fetching an author once this many are in hand (fetch.py --max-papers may lower it)
MIN_SCREEN_CANDIDATES = 8    # metadata screen margin: MIN_USABLE_PAPERS + 2
MIN_PROSE_WORDS = 1500       # per paper, after cleaning

# --- metadata screen --------------------------------------------------------
MIN_PAGES_WHEN_KNOWN = 6     # exclude short notes / abstracts when paginated
MAX_AUTHOR_SPAN_YEARS = 40   # wrong-author-merge guard
MIN_DOMINANT_SUBFIELD_SHARE = 0.5
MAX_DISTINCT_ORCIDS = 1      # more than one observed ORCID on an id = merge

PERMITTED_LICENCES = frozenset(
    {"cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa", "cc-by-nd", "cc-by-nc-nd",
     "cc0", "public-domain"}
)
# arXiv's API terms (https://info.arxiv.org/help/api/tou.html) allow storing
# and using e-print content "for research purposes" whatever the per-paper
# licence is; the manifest records this class instead of a licence.
ARXIV_TOU = "arxiv-tou-research"
ARXIV_SOURCE_ID = "S4306400194"

# --- partitions (author-disjoint, fixed by a hash of the author id) ---------
PARTITION_SALT = "scholarly-v1"
PARTITIONS = ("development", "calibration", "locked_test")
# cumulative bucket edges out of 1000: dev 40%, calibration 30%, locked 30%
_EDGES = (400, 700, 1000)


def partition_of(author_id: str) -> str:
    """Deterministic, author-level partition. Never depends on paper counts."""
    h = hashlib.sha256(f"{PARTITION_SALT}:{author_id}".encode("utf-8")).digest()
    bucket = int.from_bytes(h[:8], "big") % 1000
    for name, edge in zip(PARTITIONS, _EDGES):
        if bucket < edge:
            return name
    raise AssertionError("unreachable")  # pragma: no cover


# Hosts (journals / repositories) whose papers were observed, in the 2026-11-11 humanities
# smoke run (top 50 screened authors), to fail almost always: bodies not in English although
# the catalogue says "en", or full text refused to automated clients. Rule: at least 10
# attempts and at most 15 percent usable. Excluding them at screen time costs no downloads; it
# is a metadata screen tightened by measured evidence, as the task requires, not a quality
# judgement about the journals.
EXCLUDED_HOSTS = frozenset([
    "Acta Theologica",
    "DigitalCommons@UNO",
    "Dostoevsky and World Culture Philological journal",
    "Folia Orientalia",
    "Image & narrative",
    "Index of Texas Archaeology Open Access Grey Literature from the Lone Star State",
    "Islam in the modern world",
    "Journal of Religion & Film",
    "National Academy of Managerial Staff of Culture and Arts Herald",
    "Two centuries of the Russian classics",
    "Ukrainian Religious Studies"
])

# Second round, science collection only: measured in the 2026-11-11 science smoke run (top 50
# screened authors). URL hosts with at least 10 attempts and at most 15 percent usable (landing
# pages instead of PDFs, or automated clients refused), and arXiv-hosted OpenAlex subfields with
# at least 10 attempts and under 20 percent usable (formula-dominated: too little prose left).
EXCLUDED_URL_HOSTS_SCIENCE = frozenset([
    "downloads.hindawi.com",
    "earthlinepublishers.com",
    "journals.flvc.org",
    "journals.pan.pl",
    "link.aps.org",
    "link.springer.com",
    "www.degruyter.com",
    "www.granthaalayahpublication.org",
    "www.sciencedirect.com"
])
EXCLUDED_SUBFIELDS_SCIENCE = frozenset(["2607"])
