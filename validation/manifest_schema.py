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
    AUTHENTIC = "authentic"           # Written entirely by the claimed author
    AI_GENERATED = "ai_generated"     # Written entirely by an AI
    MIXED = "mixed"                   # Partially human, partially AI
    GHOSTWRITTEN = "ghostwritten"     # Written by a different human
    PARAPHRASED = "paraphrased"       # Authentic content paraphrased by AI


class AIProvider(str, Enum):
    """AI provider used for AI-generated or mixed content."""
    CHATGPT = "chatgpt"
    CLAUDE = "claude"
    GEMINI = "gemini"
    OTHER = "other"    # open models / unnamed providers (add_ai_essays.py)
    NONE = "none"


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
