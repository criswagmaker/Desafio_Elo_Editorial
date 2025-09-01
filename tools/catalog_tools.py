from __future__ import annotations

import json
import os
import unicodedata
from functools import lru_cache
from typing import Dict, List, Optional

from core.logging import log_tool_call

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CATALOG_PATH = os.path.join(DATA_PATH, "mock_catalog.json")


# ---------------------------
# util: normalização
# ---------------------------
def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    """normaliza para comparação: sem acento + lowercase + trim"""
    return _strip_accents(str(s)).lower().strip()


def _canonical_city_input(city: str) -> str:
    """aplica sinônimos/abreviações comuns antes de comparar com o catálogo"""
    c = _norm(city)
    # mapeamento básico; ajuste conforme seu catálogo
    synonyms = {
        "sp": "sao paulo",
        "sampa": "sao paulo",
        "sao-paulo": "sao paulo",
        "rj": "rio de janeiro",
        "rio": "rio de janeiro",
        "rio-de-janeiro": "rio de janeiro",
        "bh": "belo horizonte",
        "floripa": "florianopolis",
    }
    return synonyms.get(c, c)


# ---------------------------
# carregamento do catálogo
# ---------------------------
@lru_cache(maxsize=1)
def _load_catalog() -> List[Dict]:
    """
    Carrega o catálogo e retorna SEMPRE uma lista de livros (normalizada).
    Formatos aceitos:
      A) [ {...}, {...} ]
      B) { "books": [ {...}, {...} ] }
    """
    if not os.path.exists(CATALOG_PATH):
        raise FileNotFoundError(f"Catálogo não encontrado em '{CATALOG_PATH}'.")

    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "books" in data:
        books = data.get("books")
        if not isinstance(books, list):
            raise ValueError("Formato inválido: 'books' deve ser uma lista.")
        return books

    if isinstance(data, list):
        return data

    raise ValueError(
        "Formato do catálogo inválido. Esperado lista na raiz ou objeto com chave 'books'."
    )


def _find_book_by_title(title: str) -> Optional[Dict]:
    tnorm = _norm(title)
    for item in _load_catalog():
        if _norm(item.get("title", "")) == tnorm:
            return item
    return None


# ---------------------------
# API de catálogo (funções puras)
# ---------------------------
@log_tool_call("get_book_details")
def get_book_details(title: str) -> Dict:
    """
    Retorna detalhes do livro pelo título (match exato, case/acentos-insensitive).
    Campos: title, author, imprint, release_date, synopsis, availability (dict)
    """
    if not title or not str(title).strip():
        raise ValueError("Título do livro não informado.")

    book = _find_book_by_title(title)
    if book is None:
        raise ValueError("Livro não encontrado no catálogo.")

    return {
        "title": book.get("title", ""),
        "author": book.get("author", ""),
        "imprint": book.get("imprint", ""),
        "release_date": book.get("release_date", ""),  # DD/MM/AAAA
        "synopsis": book.get("synopsis", ""),
        "availability": book.get("availability", {}) or {},
    }


@log_tool_call("find_stores_selling_book")
def find_stores_selling_book(title: str, city: Optional[str] = None) -> Dict:
    """
    Retorna pontos de venda para um livro, com normalização de cidades:
      - compara cidades sem acentos e sem diferenciar maiúsc./minúsc.
      - aceita sinônimos/abreviações (ex.: 'sp' → 'São Paulo').
    Regras:
      - Se city (normalizada) existir no availability → retorna lojas da cidade + Online.
      - Caso contrário → retorna apenas Online (se existir).
    """
    details = get_book_details(title)  # valida e carrega availability
    availability = details.get("availability", {}) or {}

    # sempre tente pegar Online (se existir)
    online_raw = availability.get("Online", [])
    online = list(online_raw) if isinstance(online_raw, list) else []

    # se cidade foi informada, tentar casar de forma robusta
    if city:
        # índice normalizado: "sao paulo" -> "São Paulo"
        index: Dict[str, str] = {
            _norm(k): k for k in availability.keys() if isinstance(k, str) and k != "Online"
        }

        # 1) usa sinônimo/abreviação
        c_in = _canonical_city_input(city)

        # 2) match direto (normalizado)
        if c_in in index:
            canonical_key = index[c_in]
            stores = availability.get(canonical_key)
            if isinstance(stores, list) and stores:
                return {
                    "title": details["title"],
                    "city": canonical_key,  # mantém forma do catálogo (com acento)
                    "stores": stores,
                    "online": online,
                }

        # 3) tentativa “startswith”/“contains” leve (ajuda “sao” → “sao paulo”)
        for norm_key, original_key in index.items():
            if c_in.startswith(norm_key) or norm_key.startswith(c_in) or c_in in norm_key:
                stores = availability.get(original_key)
                if isinstance(stores, list) and stores:
                    return {
                        "title": details["title"],
                        "city": original_key,
                        "stores": stores,
                        "online": online,
                    }

    # sem cidade ou não encontrada → apenas Online (se houver)
    return {
        "title": details["title"],
        "city": None if not city else city.strip(),
        "stores": [],
        "online": online,
    }
