"""Rule-based source credibility: provenance, corroboration, structure."""

from src.scoring.credibility import (
    DEFAULT_THRESHOLD,
    CredibilityScore,
    ScoreLine,
    SourceEvidence,
    accepted_names,
    score,
)
from src.scoring.domains import Tier, classify
from src.scoring.health import HealthRecord

__all__ = ["DEFAULT_THRESHOLD", "CredibilityScore", "ScoreLine", "SourceEvidence",
           "accepted_names", "score", "Tier", "classify", "HealthRecord"]
