"""Splits sections into chunks of about chunk_tokens, overlapping by about overlap_tokens.

Sizes come from the embedding model's own tokenizer. A chunk never crosses a heading, so its
heading path describes all of it. Paragraphs stay whole unless one alone is too long.
"""

from collections.abc import Callable
from dataclasses import dataclass
import math

from .parse import Section

Counter = Callable[[list[str]], list[int]]


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    heading_path: str
    text: str
    token_count: int


def split_long(paragraph: str, tokens: int, limit: int) -> list[tuple[str, int]]:
    words = paragraph.split()
    pieces = math.ceil(tokens / limit)
    size = math.ceil(len(words) / pieces)
    parts = [" ".join(words[i:i + size]) for i in range(0, len(words), size)]
    return [(part, math.ceil(tokens * len(part.split()) / len(words))) for part in parts]


def tail(text: str, tokens: int, words_per_token: float) -> str:
    words = text.split()
    keep = min(len(words), round(tokens * words_per_token))
    return " ".join(words[-keep:]) if keep else ""


def chunk_sections(sections: list[Section], count: Counter, chunk_tokens: int, overlap_tokens: int) -> list[Chunk]:
    paragraphs = [p for section in sections for p in section.paragraphs]
    if not paragraphs:
        return []
    counts = iter(count(paragraphs))
    total_words = sum(len(p.split()) for p in paragraphs)
    drafts: list[tuple[str, str]] = []
    words_per_token = 1.0

    for section in sections:
        units: list[tuple[str, int]] = []
        for paragraph in section.paragraphs:
            tokens = next(counts)
            units.extend(split_long(paragraph, tokens, chunk_tokens) if tokens > chunk_tokens else [(paragraph, tokens)])
        section_words = sum(len(text.split()) for text, _ in units)
        section_tokens = sum(tokens for _, tokens in units) or 1
        words_per_token = section_words / section_tokens if section_words else words_per_token

        current: list[str] = []
        size = 0
        for text, tokens in units:
            if current and size + tokens > chunk_tokens:
                body = "\n\n".join(current)
                drafts.append((section.heading_path, body))
                overlap = tail(body, overlap_tokens, words_per_token)
                current, size = ([overlap] if overlap else []), overlap_tokens if overlap else 0
            current.append(text)
            size += tokens
        if current:
            drafts.append((section.heading_path, "\n\n".join(current)))

    exact = count([text for _, text in drafts]) if drafts and total_words else []
    return [Chunk(n, heading, text, tokens) for n, ((heading, text), tokens) in enumerate(zip(drafts, exact))]
