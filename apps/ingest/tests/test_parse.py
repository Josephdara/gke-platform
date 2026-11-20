import pytest

from ingest.parse import ParseError, parse_markdown

PAGE = b"""---
title: Liveness probes
weight: 20
---
<!-- overview -->
A {{< glossary_tooltip text="Pod" term_id="pod" >}} runs containers. See [probes](/docs/probes/).

{{< note >}}
Probes run on the <b>kubelet</b>.
{{< /note >}}

## Configure probes

### Liveness

A failing liveness probe restarts the container.

```yaml
livenessProbe:
  httpGet:
    path: /healthz
```

## Readiness

Readiness removes the Pod from Service endpoints.
"""


def test_front_matter_shortcodes_comments_tags_and_links_are_removed():
    sections = parse_markdown(PAGE, 5)
    text = "\n".join(p for s in sections for p in s.paragraphs)
    assert "title:" not in text and "overview" not in text and "{{" not in text and "<b>" not in text
    assert "A Pod runs containers. See probes." in text
    assert "Probes run on the kubelet." in text


def test_paragraphs_keep_their_heading_path():
    sections = {s.heading_path: s.paragraphs for s in parse_markdown(PAGE, 5)}
    assert sections["Configure probes > Liveness"][0] == "A failing liveness probe restarts the container."
    assert sections["Readiness"] == ["Readiness removes the Pod from Service endpoints."]


def test_fenced_code_is_kept_as_written_and_not_read_as_headings():
    raw = b"## Example\n\n```sh\n# not a heading\nkubectl get pods\n```\n"
    section, = parse_markdown(raw, 5)
    assert section.heading_path == "Example"
    assert section.paragraphs == ["```sh\n# not a heading\nkubectl get pods\n```"]


def test_non_utf8_is_refused():
    with pytest.raises(ParseError, match="UTF-8"):
        parse_markdown(b"\xff\xfe binary", 5)


def test_time_limit():
    with pytest.raises(ParseError, match="time limit"):
        parse_markdown(b"line\n" * 1000, 0)
