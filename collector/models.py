"""Data models for checksum collector."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MatchResult:
    """Represents a confirmed filename to checksum match."""

    pdf_path: str
    pdf_name: str
    page: int
    filename: str
    checksum: str
    notes: str = ""
    confidence: str = ""


@dataclass
class AmbiguousEntry:
    """Represents an entry that requires manual review."""

    entry_id: str
    pdf_path: str
    pdf_name: str
    page: int
    filename_fragments: List[str] = field(default_factory=list)
    checksum_fragments: List[str] = field(default_factory=list)
    filename_value: Optional[str] = None
    checksum_value: Optional[str] = None
    notes: str = ""
    status: str = "pending"

    def describe_fragments(self, fragments: List[str]) -> str:
        """Return a human readable representation of fragments."""

        if not fragments:
            return ""
        return " | ".join(fragments)

    def filename_fragment_text(self) -> str:
        """Textual representation of filename fragments."""

        return self.describe_fragments(self.filename_fragments)

    def checksum_fragment_text(self) -> str:
        """Textual representation of checksum fragments."""

        return self.describe_fragments(self.checksum_fragments)


__all__ = ["MatchResult", "AmbiguousEntry"]
