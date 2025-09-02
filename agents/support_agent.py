from __future__ import annotations
from typing import Optional

from tools.support_tools import open_support_ticket

def create_ticket(name: str, email: str, subject: str, message: str) -> str:
    """Camada fina de agente para abertura de ticket."""
    name = (name or "").strip()
    email = (email or "").strip()
    subject = (subject or "").strip()
    message = (message or "").strip()

    if not all([name, email, subject, message]):
        raise ValueError("Campos obrigatórios ausentes para abrir ticket.")

    # delega para a tool (que já loga e retorna no formato exigido)
    return open_support_ticket(name, email, subject, message)
