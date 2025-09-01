from __future__ import annotations

from typing import Optional, Dict, List

# Mantemos o get_llm só se você quiser usar o LLM para reformatar textos depois.
# Para este MVP, vamos formatar nós mesmos (sem CrewAI aqui).
# from core.llm import get_llm

from tools.catalog_tools import get_book_details, find_stores_selling_book


def _md_escape(text: str) -> str:
    return text.replace("#", "\\#").replace("*", "\\*").replace("_", "\\_")


def book_details(title: str) -> str:
    """
    Recupera detalhes do livro e devolve uma resposta curta em Markdown.
    Chama diretamente a função de catálogo (sem CrewAI tools).
    """
    try:
        data = get_book_details(title)
    except Exception as e:
        return f"Não encontrei esse título no catálogo. Detalhe técnico: {e}"

    t = _md_escape(data.get("title", ""))
    a = _md_escape(data.get("author", ""))
    im = _md_escape(data.get("imprint", ""))
    rd = _md_escape(data.get("release_date", ""))
    syn = _md_escape(data.get("synopsis", ""))

    return (
        f"**Título:** {t}\n"
        f"**Autor:** {a}\n"
        f"**Imprint:** {im}\n"
        f"**Lançamento:** {rd}\n\n"
        f"**Sinopse:** {syn}\n"
    )


def where_to_buy(title: str, city: Optional[str] = None) -> str:
    """
    Encontra onde comprar o livro, respeitando as regras:
      - Se a cidade não existir no catálogo ou estiver ausente → retornar apenas Online.
      - Se houver lojas na cidade → listar lojas da cidade e também as opções Online.
    Chama diretamente a função de catálogo (sem CrewAI tools).
    """
    try:
        data = find_stores_selling_book(title, city)
    except Exception as e:
        return f"Não foi possível localizar pontos de venda para o livro informado. Detalhe técnico: {e}"

    title_out = _md_escape(data.get("title", ""))
    city_out = data.get("city")
    stores: List[str] = data.get("stores", []) or []
    online: List[str] = data.get("online", []) or []

    lines = [f"**Onde comprar — {title_out}**"]
    if city_out:
        lines.append(f"**Cidade:** {city_out}")

    if stores:
        lines.append("\n**Lojas físicas:**")
        for s in stores:
            lines.append(f"- {s}")

    if online:
        lines.append("\n**Online:**")
        for s in online:
            lines.append(f"- {s}")

    # Caso não haja nada (bem improvável), informamos claramente
    if not stores and not online:
        lines.append("\nNão há lojas cadastradas para este título no momento.")

    return "\n".join(lines) + "\n"
