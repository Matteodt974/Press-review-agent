"""Accès au LLM via LangChain (sortie structurée Pydantic)."""
from __future__ import annotations

import logging
import time
from typing import Literal, Protocol, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
Role = Literal["classify", "write"]


class LLMClient(Protocol):
    def structured(self, role: Role, schema: type[T], system: str, user: str) -> T: ...


def build_chat_model(provider: str, model: str, api_key: str, effort: str | None):
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs = {}
        if effort:
            kwargs["output_config"] = {"effort": effort}
        # Pas de temperature : refusée par les modèles Claude récents.
        return ChatAnthropic(model=model, api_key=api_key, max_tokens=16000,
                             max_retries=3, timeout=300, **kwargs)
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, api_key=api_key, max_retries=3, timeout=300)
    raise ValueError(f"Fournisseur LLM inconnu : {provider!r} (attendu : anthropic ou openai)")


class LangChainLLM:
    """Deux modèles : un bon marché pour le tri, un plus fort pour la rédaction."""

    def __init__(self, llm_cfg: dict, api_key: str):
        p = llm_cfg["provider"]
        self.models = {
            "classify": build_chat_model(p, llm_cfg["model_classify"], api_key, llm_cfg.get("effort_classify")),
            "write": build_chat_model(p, llm_cfg["model_write"], api_key, llm_cfg.get("effort_write")),
        }
        self.calls = 0

    def structured(self, role: Role, schema: type[T], system: str, user: str) -> T:
        # json_schema = sortie structurée native (pas d'appel d'outil forcé,
        # refusé par certains modèles Claude récents).
        runnable = self.models[role].with_structured_output(schema, method="json_schema")
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                self.calls += 1
                out = runnable.invoke([SystemMessage(content=system), HumanMessage(content=user)])
                if isinstance(out, dict):
                    out = schema.model_validate(out)
                return out
            except Exception as exc:  # erreurs de parsing ou réseau non récupérées par le SDK
                last_exc = exc
                log.warning("Appel LLM (%s) échoué, tentative %d/3 : %s", role, attempt + 1, exc)
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Le LLM a échoué 3 fois ({role}) : {last_exc}") from last_exc
