"""Markdown to sections: front matter, Hugo shortcodes, comments, and HTML tags are removed, and
each paragraph keeps the path of headings above it. Fenced code is kept as written."""

from dataclasses import dataclass
import re
import time

HEADING = re.compile(r"(#{1,6})\s+(.+?)\s*#*\s*\Z")
FENCE = re.compile(r"\s*(```|~~~)")
COMMENT = re.compile(r"<!--.*?-->", re.S)
# {{< glossary_tooltip text="Pod" term_id="pod" >}} keeps its visible text; every other
# shortcode, paired or not, is removed while the text between paired ones is kept.
TOOLTIP = re.compile(r"\{\{[<%]\s*glossary_tooltip\b[^}]*?\btext=\"([^\"]*)\"[^}]*?[%>]\}\}")
SHORTCODE = re.compile(r"\{\{[<%].*?[%>]\}\}", re.S)
TAG = re.compile(r"</?[A-Za-z][^>]{0,500}>")
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


class ParseError(Exception):
    """The file is not text, or parsing took longer than its time limit."""


@dataclass(frozen=True)
class Section:
    heading_path: str
    paragraphs: list[str]


def strip_front_matter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5:]
    return text


def clean(text: str) -> str:
    text = COMMENT.sub("", text)
    text = TOOLTIP.sub(r"\1", text)
    text = SHORTCODE.sub("", text)
    return text


def parse_markdown(raw: bytes, time_limit: float) -> list[Section]:
    deadline = time.monotonic() + time_limit
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ParseError("file is not UTF-8 text") from None
    text = clean(strip_front_matter(text.replace("\r\n", "\n")))

    sections: list[Section] = []
    # (level, title) pairs from the outermost heading in.
    headings: list[tuple[int, str]] = []
    paragraphs: list[str] = []
    current: list[str] = []
    in_code = False

    def end_paragraph():
        block = "\n".join(current).strip()
        if block:
            paragraphs.append(block)
        current.clear()

    def end_section():
        end_paragraph()
        if paragraphs:
            sections.append(Section(" > ".join(title for _, title in headings), list(paragraphs)))
        paragraphs.clear()

    for line in text.split("\n"):
        if time.monotonic() > deadline:
            raise ParseError("parsing took longer than the time limit")
        if FENCE.match(line):
            in_code = not in_code
            current.append(line)
            continue
        if in_code:
            current.append(line)
            continue
        heading = HEADING.fullmatch(line.strip())
        if heading:
            end_section()
            level = len(heading.group(1))
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, LINK.sub(r"\1", heading.group(2))))
            continue
        if not line.strip():
            end_paragraph()
            continue
        current.append(LINK.sub(r"\1", TAG.sub("", line)).rstrip())
    end_section()
    return sections
