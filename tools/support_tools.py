import json
import os
from datetime import datetime, timezone
from typing import Dict


from core.logging import log_tool_call

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TICKETS_PATH = os.path.join(DATA_PATH, "mock_tickets.json")

def _read_all_tickets():
    if not os.path.exists(TICKETS_PATH):
        return []
    with open(TICKETS_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
        
def _write_all_tickets(tickets):
    os.makedirs(os.path.dirname(TICKETS_PATH), exist_ok=True)
    with open(TICKETS_PATH, "w", encoding="utf-8") as f:
        json.dump(tickets, f, ensure_ascii=False, indent=2)
        
@log_tool_call("open_support_ticket")
def open_support_ticket(name: str, email: str, subject: str, message: str) -> Dict:
    """Abre um ticket de suporte persistindo no arquivo JSON.
        Retorno:
        {
            "id": <int>,
            "status": "open",
            "timestamp": ISO8601,
            "name": str,
            "email": str,
            "subject": str,
            "message": str
        }
    """
    if not name or not email or not subject or not message:
        raise ValueError("Campos obrigatórios: name, email, subject, message.")
    tickets = _read_all_tickets()
    next_id = (max([t.get("id", 0) for t in tickets]) + 1) if tickets else 1
    entry = {
        "id": next_id,
        "status": "open",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": name,
        "email": email,
        "subject": subject,
        "message": message,
    }
    tickets.append(entry)
    _write_all_tickets(tickets)
    return entry
