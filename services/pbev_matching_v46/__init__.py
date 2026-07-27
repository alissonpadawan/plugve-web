"""Motor multivisão FIPE × PBEV da V46.

O pacote é deliberadamente isolado da camada web. Ele recebe a consulta FIPE e
os registros PBEV já carregados pelo serviço atual e devolve uma resposta
compatível com o contrato usado pela Simular.
"""

from .matcher import PbevMultiviewMatcher

__all__ = ["PbevMultiviewMatcher"]
