from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from langchain_core.messages import BaseMessage

from research_agent.report_schema import (
    AgentReport,
    AgentType,
    ReferenceItem,
    ReportMetadata,
    SectionResult,
)

_REFERENCE_HEADING_RE = re.compile(r"^#{1,6}\s+References\s*$", re.IGNORECASE | re.MULTILINE)
_SECTION_HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$", re.MULTILINE)
_REFERENCE_LINE_RE = re.compile(r"^\[(\d+)\]\s*(.+?)\s*$")
_URL_RE = re.compile(r"https?://\S+")
_DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)


def extract_text(message: BaseMessage) -> str:
    """Extract plain text from LangChain messages, including Gemini's block format."""
    if isinstance(message.content, list):
        text = "".join(
            block["text"]
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    else:
        text = str(message.content)

    return text.replace("\\n", "\n").strip()


def build_agent_report_from_markdown(
    markdown_text: str,
    *,
    agent_type: AgentType,
    query: str | None = None,
    target: str | None = None,
    indication: str | None = None,
    model_name: str | None = None,
    source_markdown_file: str | None = None,
) -> AgentReport:
    body_text, references = _split_references(markdown_text)
    sections = _parse_sections(body_text)
    executive_summary = _derive_executive_summary(body_text, sections)

    metadata = ReportMetadata(
        agent_type=agent_type,
        target=target,
        indication=indication,
        model_name=model_name,
        source_markdown_file=source_markdown_file,
        query=query,
    )

    return AgentReport(
        metadata=metadata,
        executive_summary=executive_summary,
        sections=sections,
        references=references,
    )


def save_report_outputs(
    report: AgentReport,
    markdown_text: str,
    *,
    markdown_path: str | Path | None = None,
    json_path: str | Path | None = None,
) -> None:
    if markdown_path is not None:
        md_path = Path(markdown_path)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown_text.rstrip() + "\n", encoding="utf-8")

    if json_path is not None:
        report_path = Path(json_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = report.model_dump(mode="json")
        report_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _split_references(markdown_text: str) -> tuple[str, list[ReferenceItem]]:
    match = _REFERENCE_HEADING_RE.search(markdown_text)
    if not match:
        return markdown_text.strip(), []

    body = markdown_text[: match.start()].strip()
    refs_block = markdown_text[match.end() :].strip()
    references = [_parse_reference_line(line) for line in _iter_nonempty_lines(refs_block)]
    return body, [ref for ref in references if ref is not None]


def _parse_sections(body_text: str) -> list[SectionResult]:
    matches = list(_SECTION_HEADING_RE.finditer(body_text))
    if not matches:
        summary = _first_meaningful_paragraph(body_text)
        if not summary:
            return []
        return [
            SectionResult(
                section_key="report_body",
                title="Report Body",
                summary=summary,
                content_markdown=body_text.strip(),
                bullets=_extract_bullets(body_text),
            )
        ]

    sections: list[SectionResult] = []
    for index, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body_text)
        section_body = body_text[start:end].strip()
        sections.append(
            SectionResult(
                section_key=_slugify_title(title),
                title=title,
                summary=_first_meaningful_paragraph(section_body),
                content_markdown=section_body,
                bullets=_extract_bullets(section_body),
            )
        )
    return sections


def _derive_executive_summary(body_text: str, sections: list[SectionResult]) -> str:
    intro = _text_before_first_heading(body_text)
    if intro:
        return intro
    if sections:
        return sections[0].summary
    return _first_meaningful_paragraph(body_text)


def _text_before_first_heading(body_text: str) -> str:
    match = _SECTION_HEADING_RE.search(body_text)
    if not match:
        return _first_meaningful_paragraph(body_text)
    intro = body_text[: match.start()].strip()
    return _first_meaningful_paragraph(intro)


def _first_meaningful_paragraph(text: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    for paragraph in paragraphs:
        cleaned_lines = [
            line.strip()
            for line in paragraph.splitlines()
            if line.strip() and not _is_bullet_line(line)
        ]
        if cleaned_lines:
            return " ".join(cleaned_lines)
    for paragraph in paragraphs:
        if paragraph:
            return " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
    return ""


def _extract_bullets(text: str) -> list[str]:
    bullets: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if _is_bullet_line(stripped):
            bullets.append(re.sub(r"^[-*]\s+", "", stripped))
    return bullets


def _is_bullet_line(line: str) -> bool:
    return bool(re.match(r"^[-*]\s+", line.strip()))


def _slugify_title(title: str) -> str:
    normalized = re.sub(r"^\d+[\.\)]\s*", "", title).strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_") or "section"


def _parse_reference_line(line: str) -> ReferenceItem | None:
    match = _REFERENCE_LINE_RE.match(line)
    if not match:
        return None

    ref_id = int(match.group(1))
    raw_text = match.group(2).strip()
    url_match = _URL_RE.search(raw_text)
    doi_match = _DOI_RE.search(raw_text)

    return ReferenceItem(
        ref_id=ref_id,
        raw_text=raw_text,
        url=url_match.group(0) if url_match else None,
        doi=doi_match.group(1) if doi_match else None,
    )


def _iter_nonempty_lines(text: str) -> Iterable[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            yield stripped
