"""Motor V2 de record linkage FIPE × PBEV.

O pacote é deliberadamente local, determinístico e auditável. A recuperação
textual nunca autoriza consumo sozinha: o autofill depende também de
compatibilidade técnica e ausência de contradições duras.
"""

from .identity import TechnicalIdentity, build_query_identity, build_record_identity
from .matcher import PbevMatcherV2, RankedCandidate, V2RankingResult
from .normalizer import AutomotiveNormalizer, NormalizedText

__all__ = [
    "AutomotiveNormalizer",
    "NormalizedText",
    "TechnicalIdentity",
    "build_query_identity",
    "build_record_identity",
    "PbevMatcherV2",
    "RankedCandidate",
    "V2RankingResult",
]
