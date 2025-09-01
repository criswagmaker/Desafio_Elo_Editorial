from __future__ import annotations

import os
import unicodedata
from typing import Any, Dict, Optional, List

import flet as ft
from dotenv import load_dotenv

from agents.orchestrator import classify_intent, OrchestratorResult
from agents.catalog_agent import book_details, where_to_buy
from agents.support_agent import create_ticket


# ---------------------------
# Sessão leve compatível com o orquestrador
# ---------------------------
class Session:
    def __init__(self) -> None:
        self.data: Dict[str, Any] = {"last_title": None, "last_city": None}

    def update(self, *, title: Optional[str] = None, city: Optional[str] = None) -> None:
        if title:
            self.data["last_title"] = title
        if city is not None:
            self.data["last_city"] = city

    def clear(self) -> None:
        self.data.update(last_title=None, last_city=None)


# ---------------------------
# Helpers
# ---------------------------
def ensure_env() -> None:
    load_dotenv(override=False)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY não encontrado. Crie um .env a partir do .env.example e informe sua chave."
        )


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
    """Remove acentos (apenas para exibição/comparação leve na UI)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def book_details_to_card(markdown_text: str) -> ft.Card:
    """
    Faz um parse muito simples do markdown gerado por book_details()
    e monta um Card bonito. Se não bater, renderiza como texto mesmo.
    """
    # Parse super simples baseado em linhas:
    lines = [l.strip() for l in markdown_text.strip().splitlines() if l.strip()]
    fields: Dict[str, str] = {}
    for ln in lines:
        if ln.startswith("**Título:**"):
            fields["title"] = ln.replace("**Título:**", "").strip()
        elif ln.startswith("**Autor:**"):
            fields["author"] = ln.replace("**Autor:**", "").strip()
        elif ln.startswith("**Imprint:**"):
            fields["imprint"] = ln.replace("**Imprint:**", "").strip()
        elif ln.startswith("**Lançamento:**"):
            fields["release"] = ln.replace("**Lançamento:**", "").strip()
        elif ln.startswith("**Sinopse:**"):
            fields["synopsis"] = ln.replace("**Sinopse:**", "").strip()

    if not fields:
        # fallback: mostra texto puro
        return ft.Card(
            content=ft.Container(
                padding=16, content=ft.Text(markdown_text, selectable=True)
            )
        )

    title = fields.get("title", "—")
    author = fields.get("author", "—")
    imprint = fields.get("imprint", "—")
    release = fields.get("release", "—")
    synopsis = fields.get("synopsis", "—")

    return ft.Card(
        content=ft.Container(
            padding=16,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.BOOK_OUTLINED),
                            ft.Text(title, size=18, weight=ft.FontWeight.BOLD),
                        ]
                    ),
                    ft.Text(f"Autor: {author}", size=14),
                    ft.Text(f"Imprint: {imprint}", size=14),
                    ft.Text(f"Lançamento: {release}", size=14),
                    ft.Divider(),
                    ft.Text("Sinopse", weight=ft.FontWeight.BOLD),
                    ft.Text(synopsis, selectable=True),
                ],
                tight=False,
                spacing=6,
            ),
        )
    )


def stores_markdown_to_sections(markdown_text: str) -> Dict[str, List[str]]:
    """Quebra o markdown de where_to_buy em seções simples (Lojas físicas / Online)."""
    sections: Dict[str, List[str]] = {"Lojas físicas": [], "Online": []}
    lines = [l.strip() for l in markdown_text.strip().splitlines()]
    current = None
    for ln in lines:
        low = ln.lower()
        if low.startswith("**lojas físicas**") or low.startswith("**lojas físicas:**"):
            current = "Lojas físicas"
            continue
        if low.startswith("**online**") or low.startswith("**online:**"):
            current = "Online"
            continue
        if ln.startswith("- ") and current:
            sections[current].append(ln[2:].strip())
    return sections


def stores_to_card(markdown_text: str) -> ft.Card:
    sections = stores_markdown_to_sections(markdown_text)
    chips_physical = [ft.Chip(label=ft.Text(s)) for s in sections.get("Lojas físicas", [])]
    chips_online = [ft.Chip(label=ft.Text(s)) for s in sections.get("Online", [])]

    return ft.Card(
        content=ft.Container(
            padding=16,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.STORE_MALL_DIRECTORY_OUTLINED),
                            ft.Text("Onde comprar", size=18, weight=ft.FontWeight.BOLD),
                        ]
                    ),
                    ft.Text("Lojas físicas", weight=ft.FontWeight.BOLD),
                    ft.Row(spacing=8, controls=chips_physical or [ft.Text("—")]),
                    ft.Divider(),
                    ft.Text("Online", weight=ft.FontWeight.BOLD),
                    ft.Row(spacing=8, controls=chips_physical or [ft.Text("—")]),
                ],
                spacing=8,
            ),
        )
    )


# ---------------------------
# App Flet
# ---------------------------
def main(page: ft.Page):
    ensure_env()

    page.title = "Assistente Editorial • Flet"
    page.theme_mode = "light"
    page.window_width = 1100
    page.window_height = 760
    page.padding = 16
    page.spacing = 16

    session = Session()

    # --------- Lado esquerdo: Controles ---------
    title_field = ft.TextField(
        label="Título",
        hint_text='Ex.: "A Abelha"',
        dense=True,
        expand=True,
    )
    city_field = ft.TextField(
        label="Cidade",
        hint_text='Ex.: "São Paulo"',
        dense=True,
        width=220,
    )

    last_title_btn = ft.TextButton(
        "Usar último título", icon=ft.Icons.HISTORY
    )
    clear_session_btn = ft.TextButton("Limpar sessão", icon=ft.Icons.CLEAR)

    # Ações rápidas
    btn_details = ft.FilledButton("Detalhes", icon=ft.Icons.BOOKMARKS_OUTLINED)
    btn_where = ft.FilledButton("Onde comprar", icon=ft.Icons.STORE_OUTLINED)
    btn_ticket = ft.OutlinedButton("Abrir ticket…", icon=ft.Icons.SUPPORT_AGENT)

    # Debug (colapsável): intenção e slots
    intent_text = ft.Text(value="—", selectable=True)
    slots_text = ft.Text(value="—", selectable=True)
    debug_panel = ft.ExpansionTile(
        title=ft.Text("Contexto detectado (debug)"),
        subtitle=ft.Text("intenção & slots extraídos"),
        initially_expanded=False,
        controls=[
            ft.Text("Intenção:", weight=ft.FontWeight.BOLD),
            intent_text,
            ft.Text("Slots:", weight=ft.FontWeight.BOLD),
            slots_text,
        ],
    )

    # --------- Lado direito: Chat / Resultado ---------
    msg_input = ft.TextField(
        label="Converse comigo",
        hint_text='Ex.: Onde compro "A Abelha" em São Paulo?',
        expand=True,
        on_submit=lambda e: on_send_message(),
    )
    send_btn = ft.FilledButton("Enviar", icon=ft.Icons.SEND)

    chat = ft.ListView(expand=True, spacing=12, auto_scroll=True)

    def push_user(msg: str):
        chat.controls.append(
            ft.Container(
                bgcolor=ft.Colors.BLUE_50,
                padding=10,
                border_radius=10,
                content=ft.Column(
                    [ft.Text("Você", size=12, color=ft.Colors.BLUE_700), ft.Text(msg)],
                    spacing=4,
                ),
            )
        )

    def push_bot(widget: ft.Control | str):
        if isinstance(widget, str):
            content = ft.Text(widget)
        else:
            content = widget
        chat.controls.append(
            ft.Container(
                bgcolor=ft.Colors.GREY_50,
                padding=10,
                border_radius=10,
                content=ft.Column(
                    [ft.Text("Assistente", size=12, color=ft.Colors.BLACK87), content],
                    spacing=4,
                ),
            )
        )

    # --------- Ticket modal ---------
    ticket_name = ft.TextField(label="Nome", dense=True)
    ticket_email = ft.TextField(label="E-mail", dense=True)
    ticket_subject = ft.TextField(label="Assunto", dense=True)
    ticket_message = ft.TextField(label="Mensagem", multiline=True, min_lines=4)

    def open_ticket_dialog(e=None):
        dlg.open = True
        page.update()

    def submit_ticket(e=None):
        name = (ticket_name.value or "").strip()
        email = (ticket_email.value or "").strip()
        subject = (ticket_subject.value or "").strip()
        message = (ticket_message.value or "").strip()
        if not all([name, email, subject, message]):
            page.snack_bar = ft.SnackBar(ft.Text("Preencha todos os campos do ticket."), open=True)
            page.update()
            return
        reply = as_text(create_ticket(name, email, subject, message))
        push_bot(reply)
        # limpa
        for f in (ticket_name, ticket_email, ticket_subject, ticket_message):
            f.value = ""
        dlg.open = False
        page.update()

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text("Abrir ticket de suporte"),
        content=ft.Column([ticket_name, ticket_email, ticket_subject, ticket_message], tight=True),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: setattr(dlg, "open", False)),
            ft.FilledButton("Abrir ticket", icon=ft.Icons.SUPPORT_AGENT, on_click=submit_ticket),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.dialog = dlg

    # --------- Handlers ---------
    def apply_last_title(e=None):
        lt = session.data.get("last_title")
        if lt:
            title_field.value = lt
            page.update()
        else:
            page.snack_bar = ft.SnackBar(ft.Text("Nenhum título anterior encontrado."), open=True)
            page.update()

    def clear_session(e=None):
        session.clear()
        page.snack_bar = ft.SnackBar(ft.Text("Sessão limpa."), open=True)
        page.update()

    last_title_btn.on_click = apply_last_title
    clear_session_btn.on_click = clear_session
    btn_ticket.on_click = open_ticket_dialog

    # --------- Ações rápidas ---------
    def do_details(e=None):
        title = (title_field.value or "").strip()
        if not title:
            page.snack_bar = ft.SnackBar(ft.Text("Informe um título."), open=True)
            page.update()
            return
        session.update(title=title)
        md = as_text(book_details(title))
        push_user(f"Detalhes de “{title}”")
        push_bot(book_details_to_card(md))
        page.update()

    def do_where(e=None):
        title = (title_field.value or "").strip()
        if not title:
            page.snack_bar = ft.SnackBar(ft.Text("Informe um título."), open=True)
            page.update()
            return
        city = (city_field.value or "").strip() or None
        session.update(title=title, city=city)
        md = as_text(where_to_buy(title, city))
        push_user(f"Onde comprar “{title}”" + (f" em {city}" if city else " (Online)"))
        push_bot(stores_to_card(md))
        page.update()

    btn_details.on_click = do_details
    btn_where.on_click = do_where

    # --------- Conversa natural (orquestrador) ---------
    def on_send_message(e=None):
        msg = (msg_input.value or "").strip()
        if not msg:
            page.snack_bar = ft.SnackBar(ft.Text("Digite uma mensagem."), open=True)
            page.update()
            return

        push_user(msg)
        msg_input.value = ""
        page.update()

        try:
            result: OrchestratorResult = classify_intent(msg, session=session.data)
            intent_text.value = f"{result.intent} (conf={result.confidence:.2f})"
            slots_text.value = (
                f"title={result.slots.title!r}, city={result.slots.city!r}, "
                f"name={result.slots.name!r}, email={result.slots.email!r}, "
                f"subject={result.slots.subject!r}, message={result.slots.message!r}"
            )

            # slots + fallback para campos da UI
            title = result.slots.title or (title_field.value.strip() if title_field.value else None) or session.data.get("last_title")
            city = result.slots.city or (city_field.value.strip() if city_field.value else None)

            if result.intent == "DETALHES":
                if not title:
                    push_bot("Preciso do título. Preencha o campo Título à esquerda e envie de novo 😉")
                else:
                    session.update(title=title)
                    md = as_text(book_details(title))
                    push_bot(book_details_to_card(md))

            elif result.intent == "ONDE_COMPRAR":
                if not title:
                    push_bot("Preciso do título. Preencha o campo Título à esquerda e envie de novo 😉")
                else:
                    session.update(title=title, city=city)
                    md = as_text(where_to_buy(title, city))
                    push_bot(stores_to_card(md))

            else:  # SUPORTE
                # se vierem todos os campos via mensagem, abre direto
                if all([result.slots.name, result.slots.email, result.slots.subject, result.slots.message]):
                    reply = as_text(
                        create_ticket(result.slots.name, result.slots.email, result.slots.subject, result.slots.message)
                    )
                    push_bot(reply)
                else:
                    open_ticket_dialog()

        except Exception as ex:
            push_bot(f"Ocorreu um erro: {ex}")

        page.update()

    send_btn.on_click = on_send_message

    # --------- Layout principal ---------
    left = ft.Column(
        [
            ft.Text("Controles", size=18, weight=ft.FontWeight.BOLD),
            ft.Row([title_field, city_field]),
            ft.Row([last_title_btn, clear_session_btn]),
            ft.Row([btn_details, btn_where, btn_ticket]),
            ft.Divider(),
            debug_panel,
        ],
        width=360,
        spacing=10,
    )

    right = ft.Column(
        [
            ft.Row(
                [
                    ft.Text("Converse comigo", size=18, weight=ft.FontWeight.BOLD),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Row([msg_input, send_btn]),
            chat,
        ],
        expand=True,
        spacing=10,
    )

    page.add(
        ft.Row(
            [
                left,
                right,
            ],
            expand=True,
        )
    )


if __name__ == "__main__":
    ft.app(target=main)
