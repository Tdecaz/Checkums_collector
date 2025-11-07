"""PDF parsing utilities for checksum collector."""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import pdfplumber

from .models import AmbiguousEntry, MatchResult

# Allowed extensions that indicate valid filenames.
ALLOWED_EXTENSIONS = (
    "jar",
    "hs",
    "class",
    "xml",
    "csv",
    "conf",
    "a",
    "rps",
    "dll",
    "php",
    "node",
    "sql",
    "so",
    "cc",
    "h",
    "yaml",
    "war",
    "json",
    "js",
    "ts",
)

FILENAME_PATTERN = re.compile(
    r"(?i)(?:[A-Za-z]:)?[\\/]?(?:[\w\-().]+[\\/])*[\w\-().]+\.(?:" + "|".join(ALLOWED_EXTENSIONS) + ")"
)
SHA1_TOKEN = re.compile(r"[0-9a-fA-F]{40}")
HEX_CHARS = re.compile(r"[0-9a-fA-F]")
RTP_PATTERN = re.compile(r"\bRTP\s+\d+(?:[.,]\d+)?\b", re.IGNORECASE)
PAYTABLE_PATTERN = re.compile(r"\bPaytable\b", re.IGNORECASE)


@dataclass
class LineItem:
    """Represents a parsed item from a PDF line."""

    value: str
    page: int
    pdf_name: str
    pdf_path: str
    context: str
    confidence: str


def clean_token(token: str) -> str:
    """Normalize a token by stripping surrounding punctuation."""

    return token.strip().strip(",;:\n\r\t")


def combine_fragments(fragments: Iterable[str]) -> str:
    """Combine fragments into a single value using simple heuristics."""

    parts = [frag.strip() for frag in fragments if frag and frag.strip()]
    if not parts:
        return ""
    no_space = "".join(parts)
    with_space = " ".join(parts)

    if SHA1_TOKEN.fullmatch(re.sub(r"[^0-9a-fA-F]", "", no_space)) and len(re.sub(r"[^0-9a-fA-F]", "", no_space)) == 40:
        return re.sub(r"[^0-9a-fA-F]", "", no_space)
    if FILENAME_PATTERN.search(no_space):
        return FILENAME_PATTERN.search(no_space).group(0)
    if FILENAME_PATTERN.search(with_space):
        return FILENAME_PATTERN.search(with_space).group(0)
    if RTP_PATTERN.search(with_space):
        match = RTP_PATTERN.search(with_space)
        if match:
            return match.group(0).replace(",", ".")
    if PAYTABLE_PATTERN.search(with_space):
        return PAYTABLE_PATTERN.search(with_space).group(0)
    return with_space


class PDFParser:
    """Parse PDFs and extract filename to checksum matches."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Request the current parse operation to stop."""

        self._stop_event.set()

    def reset(self) -> None:
        """Reset the stop flag for a new parse run."""

        self._stop_event.clear()

    def parse_folder(
        self,
        folder: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Tuple[List[MatchResult], List[AmbiguousEntry], List[str]]:
        """Parse every PDF in the provided folder."""

        matches: List[MatchResult] = []
        ambiguous: List[AmbiguousEntry] = []
        errors: List[str] = []

        pdf_files = [
            os.path.join(folder, name)
            for name in sorted(os.listdir(folder))
            if name.lower().endswith(".pdf")
        ]

        total = len(pdf_files)
        for index, pdf_path in enumerate(pdf_files, start=1):
            if self._stop_event.is_set():
                break
            if progress_callback:
                progress_callback(index, total, pdf_path)
            try:
                file_matches, file_ambiguous = self.parse_pdf(pdf_path)
                matches.extend(file_matches)
                ambiguous.extend(file_ambiguous)
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(f"{os.path.basename(pdf_path)}: {exc}")
        return matches, ambiguous, errors

    def parse_pdf(self, pdf_path: str) -> Tuple[List[MatchResult], List[AmbiguousEntry]]:
        """Parse an individual PDF file."""

        matches: List[MatchResult] = []
        ambiguous_entries: List[AmbiguousEntry] = []

        with pdfplumber.open(pdf_path) as pdf:
            pending_filenames: List[LineItem] = []
            pending_hashes: List[LineItem] = []

            for page_number, page in enumerate(pdf.pages, start=1):
                if self._stop_event.is_set():
                    break
                words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
                if not words:
                    text = page.extract_text() or ""
                    raw_lines = [line for line in text.splitlines() if line.strip()]
                    lines = [
                        (raw_line.split(), raw_line)
                        for raw_line in raw_lines
                    ]
                else:
                    lines = list(self._build_lines_from_words(words))

                for line_tokens, context_text in lines:
                    if self._stop_event.is_set():
                        break
                    line_filenames, split_filename_entries = self._extract_filenames(
                        line_tokens,
                        page_number,
                        pdf_path,
                        context_text,
                    )
                    line_hashes, split_hash_entries = self._extract_hashes(
                        line_tokens,
                        page_number,
                        pdf_path,
                        context_text,
                    )

                    ambiguous_entries.extend(split_filename_entries)
                    ambiguous_entries.extend(split_hash_entries)

                    pairs = min(len(line_filenames), len(line_hashes))
                    for idx in range(pairs):
                        filename_item = line_filenames[idx]
                        hash_item = line_hashes[idx]
                        matches.append(
                            MatchResult(
                                pdf_path=pdf_path,
                                pdf_name=os.path.basename(pdf_path),
                                page=page_number,
                                filename=filename_item.value,
                                checksum=hash_item.value.lower(),
                                notes=f"Matched within line: {context_text}",
                                confidence="line",
                            )
                        )

                    remaining_filenames = line_filenames[pairs:]
                    remaining_hashes = line_hashes[pairs:]

                    pending_filenames.extend(remaining_filenames)
                    pending_hashes.extend(remaining_hashes)

                    while pending_filenames and pending_hashes:
                        filename_item = pending_filenames.pop(0)
                        hash_item = pending_hashes.pop(0)
                        matches.append(
                            MatchResult(
                                pdf_path=pdf_path,
                                pdf_name=os.path.basename(pdf_path),
                                page=filename_item.page,
                                filename=filename_item.value,
                                checksum=hash_item.value.lower(),
                                notes=f"Sequential pairing across lines/pages. Context: {filename_item.context} | {hash_item.context}",
                                confidence="sequential",
                            )
                        )

            for leftover_filename in pending_filenames:
                ambiguous_entries.append(
                    AmbiguousEntry(
                        entry_id=self._entry_id(pdf_path, leftover_filename.page, leftover_filename.value, "filename"),
                        pdf_path=pdf_path,
                        pdf_name=os.path.basename(pdf_path),
                        page=leftover_filename.page,
                        filename_fragments=[leftover_filename.value],
                        filename_value=leftover_filename.value,
                        notes=f"Filename without checksum. Context: {leftover_filename.context}",
                    )
                )
            for leftover_hash in pending_hashes:
                ambiguous_entries.append(
                    AmbiguousEntry(
                        entry_id=self._entry_id(pdf_path, leftover_hash.page, leftover_hash.value, "checksum"),
                        pdf_path=pdf_path,
                        pdf_name=os.path.basename(pdf_path),
                        page=leftover_hash.page,
                        checksum_fragments=[leftover_hash.value],
                        checksum_value=leftover_hash.value.lower(),
                        notes=f"Checksum without filename. Context: {leftover_hash.context}",
                    )
                )

        return matches, ambiguous_entries

    def _build_lines_from_words(self, words: List[Dict[str, str]]) -> Iterable[Tuple[List[str], str]]:
        """Group words into lines maintaining reading order."""

        lines: List[Tuple[List[str], str]] = []
        current_line: List[str] = []
        current_top: Optional[float] = None
        tolerance = 3.0
        for word in sorted(words, key=lambda w: (w.get("top", 0.0), w.get("x0", 0.0))):
            top = float(word.get("top", 0.0))
            text = word.get("text", "")
            if current_top is None:
                current_top = top
            if top - current_top > tolerance:
                if current_line:
                    context_text = " ".join(current_line)
                    lines.append((current_line[:], context_text))
                current_line = [text]
                current_top = top
            else:
                current_line.append(text)
        if current_line:
            context_text = " ".join(current_line)
            lines.append((current_line[:], context_text))
        return lines

    def _extract_filenames(
        self,
        tokens: List[str],
        page: int,
        pdf_path: str,
        context_text: str,
    ) -> Tuple[List[LineItem], List[AmbiguousEntry]]:
        """Extract filename candidates from tokens."""

        pdf_name = os.path.basename(pdf_path)
        valid_filenames: List[LineItem] = []
        ambiguous: List[AmbiguousEntry] = []
        cleaned_tokens = [clean_token(tok) for tok in tokens]

        idx = 0
        while idx < len(cleaned_tokens):
            token = cleaned_tokens[idx]
            if not token:
                idx += 1
                continue

            match = FILENAME_PATTERN.search(token)
            if match:
                value = match.group(0)
                valid_filenames.append(
                    LineItem(
                        value=value,
                        page=page,
                        pdf_name=pdf_name,
                        pdf_path=pdf_path,
                        context=context_text,
                        confidence="direct",
                    )
                )
                idx += 1
                continue

            # Handle filenames split at a dot (e.g. "file." + "jar" or "file" + ".jar").
            if idx + 1 < len(cleaned_tokens):
                next_token = cleaned_tokens[idx + 1]
                combined = token + next_token
                combined_match = FILENAME_PATTERN.search(combined)
                if combined_match:
                    value = combined_match.group(0)
                    valid_filenames.append(
                        LineItem(
                            value=value,
                            page=page,
                            pdf_name=pdf_name,
                            pdf_path=pdf_path,
                            context=context_text,
                            confidence="combined",
                        )
                    )
                    idx += 2
                    continue

            idx += 1

        line_text = " ".join(cleaned_tokens)
        for rtp_match in RTP_PATTERN.finditer(line_text):
            value = rtp_match.group(0).replace(",", ".")
            valid_filenames.append(
                LineItem(
                    value=value,
                    page=page,
                    pdf_name=pdf_name,
                    pdf_path=pdf_path,
                    context=context_text,
                    confidence="rtp",
                )
            )
        paytable_match = PAYTABLE_PATTERN.search(line_text)
        if paytable_match:
            valid_filenames.append(
                LineItem(
                    value=paytable_match.group(0),
                    page=page,
                    pdf_name=pdf_name,
                    pdf_path=pdf_path,
                    context=context_text,
                    confidence="paytable",
                )
            )

        # Remove duplicates while preserving order.
        seen: set[Tuple[str, str]] = set()
        unique_filenames: List[LineItem] = []
        for item in valid_filenames:
            key = (item.value.lower(), item.context)
            if key not in seen:
                unique_filenames.append(item)
                seen.add(key)
        return unique_filenames, ambiguous

    def _extract_hashes(
        self,
        tokens: List[str],
        page: int,
        pdf_path: str,
        context_text: str,
    ) -> Tuple[List[LineItem], List[AmbiguousEntry]]:
        """Extract checksum candidates from tokens."""

        pdf_name = os.path.basename(pdf_path)
        valid_hashes: List[LineItem] = []
        ambiguous: List[AmbiguousEntry] = []

        cleaned_tokens = [clean_token(tok) for tok in tokens]

        idx = 0
        while idx < len(cleaned_tokens):
            token = cleaned_tokens[idx]
            if not token:
                idx += 1
                continue
            # Reject tokens that contain characters outside the hexadecimal alphabet.
            # This prevents ordinary words such as "DATA" or "APPENDIX" from being
            # interpreted as checksum fragments simply because they share the letters
            # A-F with hexadecimal digits.
            sanitized = token.strip()
            if not sanitized or any(
                ch not in "0123456789abcdefABCDEF-" for ch in sanitized
            ):
                idx += 1
                continue

            cleaned = re.sub(r"[^0-9a-fA-F]", "", sanitized)
            if len(cleaned) == 40 and HEX_CHARS.search(cleaned):
                valid_hashes.append(
                    LineItem(
                        value=cleaned.lower(),
                        page=page,
                        pdf_name=pdf_name,
                        pdf_path=pdf_path,
                        context=context_text,
                        confidence="direct",
                    )
                )
                idx += 1
                continue

            if 0 < len(cleaned) < 40:
                fragments = [token]
                combined = cleaned
                lookahead = idx + 1
                while lookahead < len(cleaned_tokens) and len(combined) < 40:
                    next_token = cleaned_tokens[lookahead]
                    next_sanitized = next_token.strip()
                    if not next_sanitized or any(
                        ch not in "0123456789abcdefABCDEF-" for ch in next_sanitized
                    ):
                        break
                    next_clean = re.sub(r"[^0-9a-fA-F]", "", next_sanitized)
                    if not next_clean:
                        break
                    combined += next_clean
                    fragments.append(next_token)
                    lookahead += 1
                if len(combined) == 40:
                    valid_hashes.append(
                        LineItem(
                            value=combined.lower(),
                            page=page,
                            pdf_name=pdf_name,
                            pdf_path=pdf_path,
                            context=context_text,
                            confidence="combined",
                        )
                    )
                    idx = lookahead
                    continue
                if len(fragments) > 1 and len(combined) >= 32 and HEX_CHARS.search(combined):
                    ambiguous.append(
                        AmbiguousEntry(
                            entry_id=self._entry_id(pdf_path, page, combined, "checksum_split"),
                            pdf_path=pdf_path,
                            pdf_name=pdf_name,
                            page=page,
                            checksum_fragments=fragments,
                            notes=f"Possible checksum fragments. Context: {context_text}",
                        )
                    )
            idx += 1

        # De-duplicate hashes.
        seen: set[Tuple[str, str]] = set()
        unique_hashes: List[LineItem] = []
        for item in valid_hashes:
            key = (item.value.lower(), item.context)
            if key not in seen:
                unique_hashes.append(item)
                seen.add(key)
        return unique_hashes, ambiguous

    @staticmethod
    def _entry_id(pdf_path: str, page: int, value: str, suffix: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", value)[:30]
        return f"{os.path.basename(pdf_path)}_{page}_{suffix}_{sanitized}"
