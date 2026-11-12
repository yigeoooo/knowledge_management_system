"""Provider-independent contracts for model output; evidence is verified separately."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AnswerBlock(Contract):
    text: str = Field(min_length=1, max_length=18000)
    evidence_ids: list[str] = Field(min_length=1, max_length=40)


class AnswerDraft(Contract):
    answerable: bool
    blocks: list[AnswerBlock] = Field(max_length=12)


class EvidenceCheck(Contract):
    id: str
    supported: bool


class Review(Contract):
    checks: list[EvidenceCheck]
    complete: bool


class SuggestionReview(Contract):
    checks: list[EvidenceCheck]


class SuggestedQuestion(Contract):
    question: str
    evidence_ids: list[str]


class Suggestions(Contract):
    questions: list[SuggestedQuestion]


class Summary(Contract):
    summary: str = Field(min_length=1, max_length=4000)


class ResolvedQuestion(Contract):
    resolved_question: str = Field(min_length=1, max_length=4000)
    clarification: str | None = None


class RobotInteraction(Contract):
    kind: Literal["knowledge", "chat", "general", "realtime", "clarification"]
    answer: str | None = Field(default=None, max_length=300)
    realtime_topic: Literal["weather", "other"] | None = None
