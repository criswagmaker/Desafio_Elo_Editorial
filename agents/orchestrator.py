from __future__ import annotations

import re
from typing import Any, Dict, Optional

from crewai import Agent, Task, Crew
from pydantic import BaseModel

from core.llm import get_llm  # garante provider=google (Gemini)


# ---------------------------
# Data models
# ---------------------------
class Slots(BaseModel):
    title: Optional[str] = None
    city: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    subject: Optional[str] = None
    message: Optional[str] = None


class OrchestratorResult(BaseModel):
    intent: str
    slots: Slots
    confidence: float


# ---------------------------
# Helpers de heurística
# ---------------------------
_CITY_ONLY_RE = re.compile(
    r"(?:^|[\s,.;!?])(e\s+em|em|no|na)\s+([A-Za-zÀ-ÿ\s]+)\??$",
    re.IGNORECASE,
)

def _extract_city_from_text(text: str) -> Optional[str]:
    m = _CITY_ONLY_RE.search((text or "").strip())
    if not m:
        return None
    city = m.group(2).strip()
    return city if len(city) >= 2 else None


# ---------------------------
# Função principal
# ---------------------------
def classify_intent(
    user_input: str, session: Optional[Dict[str, Any]] = None, llm: Any = None
) -> OrchestratorResult:
    """
    Classifica intenção e extrai slots.
    Heurísticas:
      - Se usuário disser só 'Em <cidade>?' e já houver título na sessão → ONDE_COMPRAR.
      - Se vier um título entre aspas → DETALHES direto.
      - Se a frase tiver 'onde compro'/'onde comprar' → ONDE_COMPRAR.
    """
    text = (user_input or "").strip()

    # Heurística 1: "Em <cidade>?" com título prévio
    last_title = (session or {}).get("last_title") if isinstance(session, dict) else None
    city_candidate = _extract_city_from_text(text)
    if last_title and city_candidate:
        return OrchestratorResult(
            intent="ONDE_COMPRAR",
            slots=Slots(title=str(last_title), city=city_candidate),
            confidence=0.99,
        )

    # Heurística 2: título entre aspas → DETALHES imediato
    m_title = re.search(r'"([^"]+)"', text)
    if m_title and not re.search(r"\bonde\s+compr(ar|o)\b", text, flags=re.IGNORECASE):
        return OrchestratorResult(
            intent="DETALHES",
            slots=Slots(title=m_title.group(1).strip()),
            confidence=0.98,
        )

    # Heurística 3: "onde compro|onde comprar" → ONDE_COMPRAR
    if re.search(r"\bonde\s+compr(ar|o)\b", text, flags=re.IGNORECASE):
        title = m_title.group(1).strip() if m_title else None
        city_inline = _extract_city_from_text(text)
        return OrchestratorResult(
            intent="ONDE_COMPRAR",
            slots=Slots(title=title, city=city_inline),
            confidence=0.95 if title else 0.80,
        )

    # LLM (Gemini) para demais casos
    if llm is None:
        llm = get_llm()
        print("[DEBUG] Orchestrator usando LLM do Gemini")

    orchestrator = Agent(
        role="Orchestrator",
        goal="Classificar a intenção do usuário (DETALHES, ONDE_COMPRAR, SUPORTE) e extrair slots relevantes.",
        backstory="Especialista em compreender pedidos do usuário e rotear para os agentes corretos.",
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )

    task = Task(
        description=(
            "Analise a mensagem do usuário e retorne **apenas** JSON válido com o formato:\n"
            '{ "intent": "DETALHES|ONDE_COMPRAR|SUPORTE", '
            '"slots": {"title": str|null, "city": str|null, "name": str|null, '
            '"email": str|null, "subject": str|null, "message": str|null}, '
            '"confidence": float }.\n'
            f"Mensagem: {text}"
        ),
        agent=orchestrator,
        expected_output="JSON válido contendo intent, slots e confidence.",
    )

    crew = Crew(agents=[orchestrator], tasks=[task], verbose=False)
    raw = crew.kickoff()

    # Normalização de retorno
    try:
        data = raw.json if hasattr(raw, "json") else raw  # alguns providers retornam dict
        intent = str(data.get("intent", "DETALHES")).upper()
        slots = Slots(**(data.get("slots", {}) or {}))
        conf = float(data.get("confidence", 0.5))
        return OrchestratorResult(intent=intent, slots=slots, confidence=conf)
    except Exception:
        # fallback conservador
        return OrchestratorResult(intent="DETALHES", slots=Slots(), confidence=0.5)
