from __future__ import annotations
from typing import Any, Dict, Optional

class Session:
    """Memória leve de sessão; não persiste entre execuções."""
    def __init__(self) -> None:
        self.data: Dict[str, Any] = {
            "last_title": None,
            "last_city": None,
        }

    def update(self, *, title: Optional[str] = None, city: Optional[str] = None) -> None:
        if title:
            self.data["last_title"] = title
        if city is not None:
            self.data["last_city"] = city

    def clear(self) -> None:
        self.data.update(last_title=None, last_city=None)
