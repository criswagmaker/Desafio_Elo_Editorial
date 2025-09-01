from __future__ import annotations

from tools.support_tools import open_support_ticket


def create_ticket(name: str, email: str, subject: str, message: str) -> str:
    """
    Abre um ticket de suporte diretamente via função Python (sem CrewAI tools).
    Retorna exatamente: 'Ticket aberto com sucesso (ID: <id>). Status: <status>.'
    """
    try:
        ticket = open_support_ticket(name=name, email=email, subject=subject, message=message)
        tid = ticket.get("id", "?")
        status = ticket.get("status", "open")
        return f"Ticket aberto com sucesso (ID: {tid}). Status: {status}."
    except Exception as e:
        return f"Não foi possível abrir o ticket agora. Detalhe técnico: {e}"
