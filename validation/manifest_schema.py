"""
validation/manifest_schema.py — Schema for the validation corpus manifest.

The manifest.json maps filenames to ground truth labels for the calibration study.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AuthorshipLabel(str, Enum):
    """Ground truth label for a validation essay."""

    AUTHENTIC = "authentic"  # Written entirely by the claimed author
    AI_GENERATED = "ai_generated"  # Written entirely by an AI
    MIXED = "mixed"  # Partially human, partially AI
    GHOSTWRITTEN = "ghostwritten"  # Written by a different human
    PARAPHRASED = "paraphrased"  # Authentic content paraphrased by AI


class AIProvider(str, Enum):
    """AI provider used for AI-generated or mixed content."""

    CHATGPT = "chatgpt"
    CLAUDE = "claude"
    GEMINI = "gemini"
    OTHER = "other"  # open models / unnamed providers (add_ai_essays.py)
    NONE = "none"


class Provenance(str, Enum):
    """Where a corpus document actually came from — never inferred silently."""

    REAL_HISTORICAL = "real_historical"  # published human prose (Gutenberg etc.)
    SYNTHETIC_AI = "synthetic_ai"        # AI-generated or AI-transformed
    STUDENT_PILOT = "student_pilot"      # consented student writing


class CorpusEntry(BaseModel):
    """A single essay in the validation corpus."""

    filename: str = Field(..., description="Path relative to corpus/ directory.")
    author_id: str = Field(..., description="Pseudonymised author identifier (e.g. 'author_01').")
    label: AuthorshipLabel
    prompt: str = Field(..., description="The essay prompt or topic.")
    word_count: int
    is_baseline: bool = Field(
        False,
        description="If True, this essay is used to build the author's baseline (not scored).",
    )
    ai_provider: AIProvider = AIProvider.NONE
    theological_tradition: Optional[str] = Field(
        None,
        description="Author's theological tradition (Reformed, Catholic, Wesleyan, etc.).",
    )
    native_english: Optional[bool] = Field(
        None,
        description="Whether the author is a native English speaker.",
    )
    notes: Optional[str] = None
    genre: Optional[str] = Field(
        None, description="Genre/register tag (e.g. 'philosophy', 'sermon', 'student_essay')."
    )
    # Renamed from `register` (FIX 4): that name shadows
    # ABCMeta.register/BaseModel.register, which pydantic v2 warns about at
    # every import of this module (`UserWarning: Field name "register" in
    # "CorpusEntry" shadows an attribute in parent "BaseModel"`). Confirmed
    # via repo-wide grep (including every manifest.json) that nothing reads
    # a "register" key or `.register` attribute on a CorpusEntry — the field
    # was added recently and has no consumers — so a plain rename is safe;
    # no wire-format alias is needed.
    register_label: Optional[str] = Field(
        None,
        description="Linguistic register tag (e.g. 'formal', 'academic', 'colloquial'), "
        "distinct from `genre` (document type/topic).",
    )
    provenance: Optional[Provenance] = Field(
        None,
        description="Document provenance; if unset, effective_provenance derives it from label.",
    )

    @property
    def effective_provenance(self) -> Provenance:
        if self.provenance is not None:
            return self.provenance
        if self.label in (
            AuthorshipLabel.AI_GENERATED,
            AuthorshipLabel.MIXED,
            AuthorshipLabel.PARAPHRASED,
        ):
            return Provenance.SYNTHETIC_AI
        return Provenance.REAL_HISTORICAL


class ValidationManifest(BaseModel):
    """Top-level manifest for the validation corpus."""

    version: str = "1.0"
    created_at: str
    description: str = "Original authorship verification validation corpus"
    authors: Dict[str, dict] = Field(
        default_factory=dict,
        description="Author metadata keyed by author_id.",
    )
    entries: List[CorpusEntry]

    def baseline_entries(self, author_id: str) -> List[CorpusEntry]:
        """Get baseline entries for an author."""
        return [e for e in self.entries if e.author_id == author_id and e.is_baseline]

    def scoring_entries(self, author_id: str) -> List[CorpusEntry]:
        """Get non-baseline entries for an author (to be scored)."""
        return [e for e in self.entries if e.author_id == author_id and not e.is_baseline]

    def all_authors(self) -> List[str]:
        """Get unique author IDs."""
        return list(set(e.author_id for e in self.entries))
