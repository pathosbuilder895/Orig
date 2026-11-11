"""Manifest schema for the scholarly corpus (style of validation/manifest_schema.py).

Only usable papers of usable authors may appear; the model refuses anything
else, so a thin author cannot be written into a manifest by accident.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, List

from pydantic import BaseModel, Field, field_validator, model_validator

from . import policy

_SHA = re.compile(r"^[0-9a-f]{64}$")


class ScholarlyPaper(BaseModel):
    source: str = Field(..., description="Catalogue the id comes from, e.g. 'openalex'.")
    source_paper_id: str
    author_id: str = Field(..., description="Persistent author id (OpenAlex id, ORCID-linked).")
    year: int
    field: str = Field(..., description="OpenAlex field id of the paper's primary topic.")
    licence: str = Field(..., description="A permitted CC/public-domain licence, or 'arxiv-tou-research'.")
    url: str
    word_count: int = Field(..., description="Words of prose after cleaning.")
    text_sha256: str = Field(..., description="SHA-256 of the cleaned text (UTF-8).")
    partition: str
    cleaner_version: str = "1"  # clean.CLEAN_VERSION that produced text_sha256; papers that predate the field are v1

    @field_validator("text_sha256")
    @classmethod
    def _sha(cls, v: str) -> str:
        if not _SHA.match(v):
            raise ValueError("text_sha256 must be 64 lowercase hex characters")
        return v

    @field_validator("licence")
    @classmethod
    def _licence(cls, v: str) -> str:
        if v not in policy.PERMITTED_LICENCES and v != policy.ARXIV_TOU:
            raise ValueError(f"licence {v!r} does not permit local research use under policy")
        return v

    @field_validator("word_count")
    @classmethod
    def _words(cls, v: int) -> int:
        if v < policy.MIN_PROSE_WORDS:
            raise ValueError(f"word_count {v} below the {policy.MIN_PROSE_WORDS}-word floor: not a usable paper")
        return v

    @field_validator("partition")
    @classmethod
    def _part(cls, v: str) -> str:
        if v not in policy.PARTITIONS:
            raise ValueError(f"partition must be one of {policy.PARTITIONS}")
        return v

    @model_validator(mode="after")
    def _partition_matches_hash(self):
        if self.partition != policy.partition_of(self.author_id):
            raise ValueError("partition does not match the hash of the author id")
        return self


class ScholarlyManifest(BaseModel):
    version: str = "1"
    policy_version: str = policy.POLICY_VERSION
    collection: str
    created_at: str
    papers: List[ScholarlyPaper]

    @field_validator("collection")
    @classmethod
    def _coll(cls, v: str) -> str:
        if v not in ("humanities", "science"):
            raise ValueError("collection must be 'humanities' or 'science'")
        return v

    @model_validator(mode="after")
    def _authors_complete(self):
        ids = Counter((p.source, p.source_paper_id) for p in self.papers)
        dup = [k for k, n in ids.items() if n > 1]
        if dup:
            raise ValueError(f"duplicate papers: {dup[:3]}")
        hashes = Counter(p.text_sha256 for p in self.papers)
        same = [h for h, n in hashes.items() if n > 1]
        if same:
            raise ValueError("two papers share one text hash (a duplicate version)")
        per = Counter(p.author_id for p in self.papers)
        thin = sorted(a for a, n in per.items() if n < policy.MIN_USABLE_PAPERS)
        if thin:
            raise ValueError(
                f"{len(thin)} author(s) have fewer than {policy.MIN_USABLE_PAPERS} usable papers "
                f"(e.g. {thin[:3]}); drop them from the manifest"
            )
        return self

    def authors(self) -> Dict[str, List[ScholarlyPaper]]:
        out: Dict[str, List[ScholarlyPaper]] = defaultdict(list)
        for p in self.papers:
            out[p.author_id].append(p)
        return dict(out)

    def authors_in(self, partition: str) -> List[str]:
        return sorted(a for a, ps in self.authors().items() if ps[0].partition == partition)
