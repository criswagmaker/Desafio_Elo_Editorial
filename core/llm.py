import os
from dataclasses import dataclass
from typing import Optional

try:
    from crewai import LLM  # precisa do crewai >= 0.30
except Exception:
    LLM = None

@dataclass
class LLMConfig:
    model: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    api_key: Optional[str] = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    temperature: float = 0.2
    max_tokens: int = 2048

def get_llm(cfg: Optional[LLMConfig] = None):
    if cfg is None:
        cfg = LLMConfig()

    if cfg.api_key is None:
        raise RuntimeError(
            "Faltou a variável de ambiente GEMINI_API_KEY (ou GOOGLE_API_KEY).\n"
            "Crie um .env com GEMINI_API_KEY=sua_chave"
        )

    if LLM is None:
        raise RuntimeError("Biblioteca CrewAI não encontrada. Instale 'crewai'.")

    # CrewAI espera id no formato "gemini/<modelo>"
    model_id = cfg.model
    if not model_id.startswith("gemini/"):
        model_id = f"gemini/{model_id}"

    print(f"[DEBUG] usando Gemini: {model_id} via provider=google")

    return LLM(
        model=model_id,
        provider="google",       # 👈 ESSENCIAL
        api_key=cfg.api_key,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )
