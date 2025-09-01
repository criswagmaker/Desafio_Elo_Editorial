from __future__ import annotations
from typing import Any, Dict, List, Optional
import re
import unicodedata
import flet as ft

# ---------- helpers básicos ----------
def as_text(raw: Any) -> str:
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

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def _norm_label(s: str) -> str:
    return strip_accents(s).lower().strip()

def _bold_weight():
    # compat: algumas versões do Flet têm BOLD, outras só W_700
    return getattr(ft.FontWeight, "BOLD", getattr(ft.FontWeight, "W_700", None))

# ---------- book details ----------
def _parse_details(md: str) -> Dict[str, str]:
    """
    Parser tolerante para os detalhes do livro.
    Aceita variações:
      - **Título:** A Abelha
      - **Título**: A Abelha
      - Título: A Abelha
      - (com/sem **, com/sem espaço antes/dep. dos dois-pontos)
    Também tenta padrões globais como **Sinopse:** <texto>
    """
    result: Dict[str, str] = {}
    if not md:
        return result

    # 1) match direto por regex linha-a-linha (labels comuns)
    lines = [ln.strip() for ln in md.splitlines() if ln.strip()]
    for ln in lines:
        # remove ênfase markdown nas extremidades para facilitar split
        cleaned = ln
        # tira ** do começo/fim e bullets
        cleaned = re.sub(r"^\s*[*•-]+\s*", "", cleaned)
        cleaned = re.sub(r"^\s*\*{1,3}\s*", "", cleaned)
        cleaned = re.sub(r"\s*\*{1,3}\s*$", "", cleaned)

        # tenta split por ":" na primeira ocorrência
        if ":" in cleaned:
            label, value = cleaned.split(":", 1)
            label_n = _norm_label(label)
            value = value.strip()

            if label_n in {"titulo", "título"} and value:
                result["title"] = value
                continue
            if label_n == "autor" and value:
                result["author"] = value
                continue
            if label_n == "imprint" and value:
                result["imprint"] = value
                continue
            if label_n in {"lancamento", "lançamento"} and value:
                result["release"] = value
                continue
            if label_n == "sinopse" and value:
                result["synopsis"] = value
                continue

    # 2) fallback por regex global (caso não tenha splitado bem em linhas)
    if "title" not in result:
        m = re.search(r"\*\*\s*T[íi]tulo\s*:\s*\*\*\s*(.+)", md, flags=re.IGNORECASE)
        if m:
            result["title"] = m.group(1).strip()
    if "author" not in result:
        m = re.search(r"\*\*\s*Autor\s*:\s*\*\*\s*(.+)", md, flags=re.IGNORECASE)
        if m:
            result["author"] = m.group(1).strip()
    if "imprint" not in result:
        m = re.search(r"\*\*\s*Imprint\s*:\s*\*\*\s*(.+)", md, flags=re.IGNORECASE)
        if m:
            result["imprint"] = m.group(1).strip()
    if "release" not in result:
        m = re.search(r"\*\*\s*Lan[çc]amento\s*:\s*\*\*\s*(.+)", md, flags=re.IGNORECASE)
        if m:
            result["release"] = m.group(1).strip()
    if "synopsis" not in result:
        # captura até quebra dupla de linha ou fim
        m = re.search(r"\*\*\s*Sinopse\s*:\s*\*\*\s*([\s\S]+)$", md, flags=re.IGNORECASE)
        if m:
            synopsis = m.group(1).strip()
            # remove excesso de asteriscos residuais
            synopsis = synopsis.strip("* ").strip()
            result["synopsis"] = synopsis

    return result

def book_details_to_card(markdown_text: str) -> ft.Card:
    """
    Constrói o Card de detalhes de forma resiliente.
    Se não conseguir parsear, exibe o markdown bruto.
    """
    fields = _parse_details(markdown_text or "")

    if not fields:
        # fallback total: mostra texto puro (pelo menos o usuário vê algo)
        return ft.Card(
            content=ft.Container(padding=16, content=ft.Text(markdown_text or "", selectable=True))
        )

    title = fields.get("title") or "—"
    author = fields.get("author") or "—"
    imprint = fields.get("imprint") or "—"
    release = fields.get("release") or "—"
    synopsis = fields.get("synopsis") or "—"

    return ft.Card(
        content=ft.Container(
            padding=16,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.BOOK_OUTLINED),
                            ft.Text(title, size=18, weight=_bold_weight()),
                        ]
                    ),
                    ft.Text(f"Autor: {author}", size=14),
                    ft.Text(f"Imprint: {imprint}", size=14),
                    ft.Text(f"Lançamento: {release}", size=14),
                    ft.Divider(),
                    ft.Text("Sinopse", weight=_bold_weight() or ft.FontWeight.W_700),
                    ft.Text(synopsis, selectable=True),
                ],
                spacing=6,
            ),
        )
    )

# ---------- where to buy ----------
def stores_markdown_to_sections(markdown_text: str) -> Dict[str, List[str]]:
    """Parser tolerante do markdown de where_to_buy()."""
    sections: Dict[str, List[str]] = {"Lojas físicas": [], "Online": []}
    if not markdown_text:
        return sections

    lines = [l.rstrip() for l in markdown_text.splitlines()]
    current: Optional[str] = None

    def is_heading(line: str, key: str) -> bool:
        low = line.strip().lower()
        return key.lower() in low  # aceita com/sem ** e com/sem :

    for ln in lines:
        stripped = ln.strip()
        low = stripped.lower()

        if is_heading(stripped, "Lojas físicas"):
            current = "Lojas físicas"; continue
        if is_heading(stripped, "Online"):
            current = "Online"; continue

        if low.startswith("- ") or low.startswith("* ") or low.startswith("• "):
            item = stripped[2:].strip()
            if current in ("Lojas físicas", "Online"):
                sections[current].append(item)
            else:
                sections["Online"].append(item)  # fallback

    return sections

def wrap_or_row(controls: List[ft.Control]) -> ft.Control:
    """Usa Wrap se existir nessa versão do Flet, senão Row."""
    if hasattr(ft, "Wrap"):
        return ft.Wrap(spacing=8, run_spacing=8, controls=controls or [ft.Text("—")])
    return ft.Row(spacing=8, controls=controls or [ft.Text("—")])

def stores_to_card(markdown_text: str) -> ft.Card:
    sections = stores_markdown_to_sections(markdown_text)
    phys = [ft.Chip(label=ft.Text(s)) for s in sections.get("Lojas físicas", [])]
    online = [ft.Chip(label=ft.Text(s)) for s in sections.get("Online", [])]

    body: List[ft.Control] = [
        ft.Row([ft.Icon(ft.Icons.STORE_MALL_DIRECTORY_OUTLINED), ft.Text("Onde comprar", size=18, weight=_bold_weight())]),
        ft.Text("Lojas físicas", weight=_bold_weight()),
        wrap_or_row(phys),
        ft.Divider(),
        ft.Text("Online", weight=_bold_weight()),
        wrap_or_row(online),
    ]

    if not phys and not online:
        body += [ft.Divider(), ft.Text("Não encontramos lojas para este livro no momento.", color=ft.Colors.GREY)]

    return ft.Card(content=ft.Container(padding=16, content=ft.Column(body, spacing=8)))
