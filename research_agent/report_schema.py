from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    MEDICAL_EVAL = "medical_eval"
    RESEARCH_EVAL = "research_eval"
    SYNTHESIS = "synthesis"


class EvidenceLevel(str, Enum):
    CLINICAL = "clinical_human"
    IN_VIVO = "in_vivo"
    IN_VITRO = "in_vitro"
    REVIEW = "review"
    UNKNOWN = "unknown"


class FindingDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class ReferenceItem(BaseModel):
    ref_id: int = Field(description="Matches inline citation numbers like [1]")
    title: str | None = None
    url: str | None = None
    doi: str | None = None
    raw_text: str = Field(description="Original reference string as shown in the report")


class EvidenceItem(BaseModel):
    claim: str = Field(description="Atomic finding or conclusion")
    dimension: str = Field(
        description="Examples: disease_burden, soc_gap, biological_rationale, tox_risk"
    )
    evidence_level: EvidenceLevel = EvidenceLevel.UNKNOWN
    direction: FindingDirection = FindingDirection.UNKNOWN
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    population_or_model: str | None = None
    notes: str | None = None
    citation_ids: list[int] = Field(default_factory=list)


class SectionResult(BaseModel):
    section_key: str = Field(
        description="Stable machine key, for example epidemiology or target_medical_value"
    )
    title: str = Field(description="Human-readable section title")
    summary: str = Field(description="Short summary of the section")
    content_markdown: str = Field(
        default="",
        description="Original markdown content for the section body",
    )
    bullets: list[str] = Field(default_factory=list)
    findings: list[EvidenceItem] = Field(default_factory=list)


class ReportMetadata(BaseModel):
    agent_type: AgentType
    target: str | None = None
    indication: str | None = None
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    model_name: str | None = None
    source_markdown_file: str | None = None
    query: str | None = None


class AgentReport(BaseModel):
    metadata: ReportMetadata
    executive_summary: str = ""
    sections: list[SectionResult] = Field(default_factory=list)
    references: list[ReferenceItem] = Field(default_factory=list)
    overall_assessment: str | None = None
    key_risks: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
