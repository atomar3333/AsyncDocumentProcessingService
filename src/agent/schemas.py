from __future__ import annotations

from pydantic import BaseModel, Field


class SummarySection(BaseModel):
    heading: str
    content: str
    confidence: float = Field(ge=0, le=1)


class SummaryResult(BaseModel):
    title: str
    sections: list[SummarySection] = Field(min_length=1)
    overall_confidence: float = Field(ge=0, le=1)
    word_count: int
    key_topics: list[str]


class ExtractedEntity(BaseModel):
    type: str
    value: str
    confidence: float = Field(ge=0, le=1)


class KeyValuePair(BaseModel):
    key: str
    value: str
    confidence: float = Field(ge=0, le=1)


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(min_length=1)
    key_value_pairs: list[KeyValuePair]
    metadata: dict = Field(default_factory=lambda: {"schema_version": "1.0"})


class AlternativeCategory(BaseModel):
    category: str
    confidence: float = Field(ge=0, le=1)


class ClassificationResult(BaseModel):
    category: str
    sub_category: str
    reasoning: str
    confidence: float = Field(ge=0, le=1)
    alternative_categories: list[AlternativeCategory]
