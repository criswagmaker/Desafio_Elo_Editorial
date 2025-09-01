from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, Optional

from dotenv import load_dotenv

# imports dos agentes
from agents.orchestrator import classify_intent, OrchestratorResult
from agents.catalog_agent import book_details, where_to_buy
from agents.support_agent import create_ticket


# ---------------------------
# .env / bootstrap
# ---------------------------
def ensure_env() -> None:
    load_dotenv(override=False)
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        raise RuntimeError(
            "GEMINI_API_KEY não encontrada no ambiente/.env. "
            "Crie um .env com GEMINI_API_KEY=sua_chave"
        )


# ---------------------------
# utilitário de console
# ---------------------------
class Console:
    @staticmethod
    def banner() -> None:
        print("\n=== Assistente Editorial (CrewAI + Gemini) ===")
        print("Digite 'sair' para encerrar.\n")

    @staticmethod
    def ask(prompt: str) -> str:
        try:
            return input(prompt).strip()
        except EOFError:
            return "sair"

    @staticmethod
    def info(msg: str) -> None:
        print(msg)

    @staticmethod
    def error(msg: str) -> None:
        print(f"[erro] {msg}", file=sys.stderr)


# ---------------------------
# memória de sessão mínima
# ---------------------------
class Session:
    """Memória leve; não persiste entre execuções."""
    def __init__(self) -> None:
        self.data: Dict[str, Any] = {
            "last_title": None,
            "last_city": None,
            "awaiting_where_city": False,  # passo 2 do fluxo (cidade)
        }

    def update(self, *, title: Optional[str] = None, city: Optional[str] = None) -> None:
        if title:
            self.data["last_title"] = title
        if city is not None:
            self.data["last_city"] = city


# ---------------------------
# helpers de parsing
# ---------------------------
_CITY_ONLY_RE = re.compile(
    r"(?:^|[\s,.;!?])(e\s+em|em|no|na)\s+([A-Za-zÀ-ÿ\s]+)\??$",
    re.IGNORECASE,
)

def _extract_city_from_text(text: str) -> Optional[str]:
    """Extrai 'São Paulo' de 'Em São Paulo?' | 'no Rio de Janeiro' etc."""
    m = _CITY_ONLY_RE.search((text or "").strip())
    if not m:
        return None
    city = m.group(2).strip()
    return city if len(city) >= 2 else None


def _as_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for attr in ("raw", "output", "content"):
        if hasattr(raw, attr):
            val = getattr(raw, attr)
            if isinstance(val, str):
                return val
    return str(raw)


def _title_from_text(text: str) -> Optional[str]:
    """Extrai um possível título do texto do usuário.
    1) Entre aspas: "A Abelha"
    2) Após 'sobre' ou 'detalhes de': Quero saber sobre A Abelha
    """
    if not text:
        return None
    m = re.search(r'"([^"]+)"', text)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"(?:sobre|detalhes de)\s+(.+)$", text, flags=re.IGNORECASE)
    if m2:
        cand = m2.group(1).strip()
        cand = re.sub(r'[?.!]+$', '', cand).strip()
        if 2 <= len(cand) <= 120:
            return cand
    return None


# ---------------------------
# handlers por intenção
# ---------------------------
def handle_details(slots: Dict[str, Optional[str]], session: Session) -> str:
    title = slots.get("title") or session.data.get("last_title")
    if not title:
        title = Console.ask("Título do livro: ")
    if not title:
        return "Não foi possível identificar o título. Tente novamente."

    session.update(title=title)
    reply = _as_text(book_details(title))

    # sugere o próximo passo e arma o flag
    session.data["awaiting_where_city"] = True
    Console.info(
        "\nQuer ver onde comprar? Diga, por exemplo: 'Em São Paulo?' "
        "ou pressione Enter para ver apenas Online.\n"
    )
    return reply


def handle_where_to_buy(slots: Dict[str, Optional[str]], session: Session) -> str:
    title = slots.get("title") or session.data.get("last_title")
    if not title:
        title = Console.ask("Título do livro: ")
    if not title:
        return "Não foi possível identificar o título. Tente novamente."

    city = slots.get("city")
    session.update(title=title, city=city)
    return _as_text(where_to_buy(title, city))


def handle_support(slots: Dict[str, Optional[str]], session: Session) -> str:
    name = slots.get("name") or Console.ask("Seu nome: ")
    email = slots.get("email") or Console.ask("Seu e-mail: ")
    subject = slots.get("subject") or Console.ask("Assunto: ")
    message = slots.get("message") or Console.ask("Descreva o problema: ")
    return _as_text(create_ticket(name or "", email or "", subject or "", message or ""))


# ---------------------------
# entrypoint
# ---------------------------
def main() -> None:
    ensure_env()
    Console.banner()
    session = Session()

    while True:
        user_input = Console.ask("> ")
        if not user_input:
            continue
        if user_input.lower() in {"sair", "exit", "quit", ":q", "fechar"}:
            Console.info("Até mais! 👋")
            break

        # Passo 2 do fluxo guiado: logo após DETALHES, esperar cidade
        if session.data.get("awaiting_where_city"):
            session.data["awaiting_where_city"] = False

            # 🔧 extrai a cidade corretamente de frases tipo "Em São Paulo?"
            city_candidate = _extract_city_from_text(user_input)
            city = city_candidate if city_candidate else None

            last_title = session.data.get("last_title")
            if not last_title:
                Console.error("Não encontrei um título recente. Peça os detalhes novamente.")
                continue
            reply = handle_where_to_buy({"title": last_title, "city": city}, session)
            Console.info("\n" + reply + "\n")
            continue

        try:
            # classifica intenção + slots
            result: OrchestratorResult = classify_intent(user_input, session=session.data)
            print(f"[intent] {result.intent} (conf={result.confidence:.2f})")

            # usa model_dump() (Pydantic v2) e aplica fallback de título extraído do texto
            slots: Dict[str, Optional[str]] = result.slots.model_dump()
            if not slots.get("title"):
                maybe_title = _title_from_text(user_input)
                if maybe_title:
                    slots["title"] = maybe_title

            if result.intent == "DETALHES":
                reply = handle_details(slots, session)
            elif result.intent == "ONDE_COMPRAR":
                # se a cidade veio no texto ("em <cidade>"), aproveita
                if not slots.get("city"):
                    slots["city"] = _extract_city_from_text(user_input)
                reply = handle_where_to_buy(slots, session)
            else:  # SUPORTE
                reply = handle_support(slots, session)

            Console.info("\n" + reply + "\n")

        except KeyboardInterrupt:
            Console.info("\nEncerrando...")
            break
        except Exception as e:
            Console.error(f"Ocorreu um erro inesperado: {e}")


if __name__ == "__main__":
    main()
