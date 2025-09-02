from __future__ import annotations

import json
import os
import random
import string
from datetime import datetime
from typing import Dict

from core.logging import log_tool_call

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TICKETS_PATH = os.path.join(DATA_DIR, "mock_tickets.json")


def _ensure_store():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(TICKETS_PATH):
        with open(TICKETS_PATH, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)


def _gen_ticket_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"TCK-{stamp}-{suffix}"


@log_tool_call("open_support_ticket")
def open_support_ticket(name: str, email: str, subject: str, message: str) -> str:
    """
    Abre um ticket simples no mock e retorna EXACTAMENTE:
    'Ticket aberto! ID: TCK-…; status: open.'
    """
    _ensure_store()
    ticket_id = _gen_ticket_id()
    record: Dict = {
        "id": ticket_id,
        "status": "open",
        "name": name,
        "email": email,
        "subject": subject,
        "message": message,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    with open(TICKETS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        data = []
    data.append(record)
    with open(TICKETS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # formato exigido pelo repositório:
    return f"Ticket aberto! ID: {ticket_id}; status: open."
