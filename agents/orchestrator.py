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

# 0-A) "Abrir/Abr(a) um ticket/chamado: name=..., email=..., subject=..., message=..."
_TICKET_CMD_RE = re.compile(
    r"^\s*abr(?:a|ir)\s+(?:um\s+)?(?:ticket|chamado)\s*:?\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)

# 0-B) "Abra um ticket 'Assunto...'" (aceita aspas simples, duplas e aspas tipográficas)
_TICKET_SUBJECT_CMD_RE = re.compile(
    r"^\s*abr(?:a|ir)\s+(?:um\s+)?(?:ticket|chamado)\s*['\"“‘](?P<subject>.+?)['\"”’]\s*$",
    re.IGNORECASE | re.DOTALL,
)


# pares chave=valor separados por vírgula; aceita chaves PT/EN
# Ex.: name=EU, email=eu@ex.com, subject=Dúvida, message=Como envio?
_KV_RE = re.compile(
    r"(?P<key>name|nome|email|subject|assunto|message|mensagem)\s*=\s*(?P<val>[^,]+)",
    re.IGNORECASE,
)


def _extract_city_from_text(text: str) -> Optional[str]:
    m = _CITY_ONLY_RE.search((text or "").strip())
    if not m:
        return None
    city = m.group(2).strip()
    return city if len(city) >= 2 else None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")) or (
        s.startswith("“") and s.endswith("”")
    ) or (s.startswith("‘") and s.endswith("’")):
        return s[1:-1].strip()
    return s


def _parse_ticket_kv(payload: str) -> Dict[str, str]:
    """Extrai pares chave=valor do payload do comando de ticket."""
    out: Dict[str, str] = {}
    for m in _KV_RE.finditer(payload or ""):
        key = m.group("key").lower().strip()
        val = _strip_quotes(m.group("val").strip())
        if key in {"name", "nome"}:
            out["name"] = val
        elif key == "email":
            out["email"] = val
        elif key in {"subject", "assunto"}:
            out["subject"] = val
        elif key in {"message", "mensagem"}:
            out["message"] = val
    return out


# ---------------------------
# Função principal
# ---------------------------
def classify_intent(
    user_input: str, session: Optional[Dict[str, Any]] = None, llm: Any = None
) -> OrchestratorResult:
    """
    Classifica intenção e extrai slots.
    Heurísticas:
      - "Abra/Abrir um ticket 'Assunto...'" → SUPORTE (subject preenchido).
      - "Abrir ticket: name=..., email=..., subject=..., message=..." → SUPORTE.
      - Se usuário disser só 'Em <cidade>?' e já houver título na sessão → ONDE_COMPRAR.
      - Se a frase tiver 'onde compro'/'onde comprar' → ONDE_COMPRAR.
      - Se vier um título entre aspas → DETALHES direto.
    """
    text = (user_input or "").strip()

    # 0-B) Comando de ticket com assunto entre aspas (modo "igual ao repo")
    m_subj = _TICKET_SUBJECT_CMD_RE.match(text)
    if m_subj:
        subject = (m_subj.group("subject") or "").strip()
        if subject:
            return OrchestratorResult(
                intent="SUPORTE",
                slots=Slots(subject=subject),
                confidence=0.99,
            )
        else:
            return OrchestratorResult(intent="SUPORTE", slots=Slots(), confidence=0.85)

    # 0-A) Comando de ticket com pares chave=valor
    m_ticket = _TICKET_CMD_RE.match(text)
    if m_ticket:
        kv = _parse_ticket_kv(m_ticket.group(1))
        if kv:
            return OrchestratorResult(
                intent="SUPORTE",
                slots=Slots(
                    name=kv.get("name"),
                    email=kv.get("email"),
                    subject=kv.get("subject"),
                    message=kv.get("message"),
                ),
                confidence=0.99,
            )
        else:
            return OrchestratorResult(intent="SUPORTE", slots=Slots(), confidence=0.85)

    # 1) "Em <cidade>?" com título prévio → ONDE_COMPRAR
    last_title = (session or {}).get("last_title") if isinstance(session, dict) else None
    city_candidate = _extract_city_from_text(text)
    if last_title and city_candidate:
        return OrchestratorResult(
            intent="ONDE_COMPRAR",
            slots=Slots(title=str(last_title), city=city_candidate),
            confidence=0.99,
        )

    # 2) "onde compro|onde comprar" → ONDE_COMPRAR
    has_onde_compr = re.search(r"\bonde\s+compr(ar|o)\b", text, flags=re.IGNORECASE)
    m_title = re.search(r'"([^"]+)"', text)
    if has_onde_compr:
        title = m_title.group(1).strip() if m_title else None
        city_inline = _extract_city_from_text(text)
        return OrchestratorResult(
            intent="ONDE_COMPRAR",
            slots=Slots(title=title, city=city_inline),
            confidence=0.95 if title else 0.80,
        )

    # 3) título entre aspas → DETALHES
    if m_title:
        return OrchestratorResult(
            intent="DETALHES",
            slots=Slots(title=m_title.group(1).strip()),
            confidence=0.98,
        )

    # 4) LLM (Gemini) para demais casos
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

    try:
        data = raw.json if hasattr(raw, "json") else raw
        intent = str(data.get("intent", "DETALHES")).upper()
        slots = Slots(**(data.get("slots", {}) or {}))
        conf = float(data.get("confidence", 0.5))
        return OrchestratorResult(intent=intent, slots=slots, confidence=conf)
    except Exception:
        return OrchestratorResult(intent="DETALHES", slots=Slots(), confidence=0.5)
