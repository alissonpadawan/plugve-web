from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TextViews:
    original: str
    canonical: str
    segmented: str
    compact: str
    tokens: frozenset[str]
    atoms: frozenset[str]
    char_ngrams: frozenset[str]


@dataclass(frozen=True)
class TechnicalEvidence:
    displacements: frozenset[float] = frozenset()
    valves: frozenset[int] = frozenset()
    cylinders: frozenset[int] = frozenset()
    turbo: bool | None = None
    transmission_family: str | None = None
    transmission_subtype: str | None = None
    gears: int | None = None
    drives: frozenset[str] = frozenset()
    bodies: frozenset[str] = frozenset()
    propulsion: str | None = None
    fuel: str | None = None
    year: int | None = None
    zero_km: bool = False
    model_years: frozenset[int] = frozenset()


@dataclass
class CandidateScore:
    record: dict[str, Any]
    score: float
    model_affinity: float
    version_affinity: float
    text_affinity: float
    technical_affinity: float
    year_affinity: float
    hard_blocks: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    query_views: TextViews | None = None
    record_views: TextViews | None = None
    query_tech: TechnicalEvidence | None = None
    record_tech: TechnicalEvidence | None = None
    suggestion: dict[str, Any] | None = None
    flags_ok: bool = True
    flag_blocks: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.hard_blocks and self.flags_ok and bool(self.suggestion)
