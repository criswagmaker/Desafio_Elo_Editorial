from __future__ import annotations

import os
from typing import Any, Dict, Optional

import flet as ft
from dotenv import load_dotenv

from ui.state import Session
from ui.components import (
    as_text, book_details_to_card, stores_to_card,
)

from agents.orchestrator import classify_intent, OrchestratorResult
from agents.catalog_agent import book_details, where_to_buy
from agents.support_agent import create_ticket


# ---------- env ----------
def ensure_env() -> None:
    load_dotenv(override=False)
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        raise RuntimeError("GEMINI_API_KEY não encontrada no ambiente/.env")


# ---------- App ----------
def main(page: ft.Page):
    ensure_env()

    page.title = "Assistente Editorial • Flet"
    page.theme_mode = "light"
    page.window_width = 1100
    page.window_height = 760
    page.padding = 16
    page.spacing = 16

    session = Session()

    # --- esquerda: controles
    title_field = ft.TextField(label="Título", hint_text='Ex.: "A Abelha"', dense=True, expand=True)
    city_field = ft.TextField(label="Cidade", hint_text='Ex.: "São Paulo"', dense=True, width=220)
    last_title_btn = ft.TextButton("Usar último título", icon=ft.Icons.HISTORY)
    clear_session_btn = ft.TextButton("Limpar sessão", icon=ft.Icons.CLEAR)
    btn_details = ft.FilledButton("Detalhes", icon=ft.Icons.BOOKMARKS_OUTLINED)
    btn_where = ft.FilledButton("Onde comprar", icon=ft.Icons.STORE_OUTLINED)
    btn_ticket = ft.OutlinedButton("Abrir ticket…", icon=ft.Icons.SUPPORT_AGENT)

    intent_text = ft.Text(value="—", selectable=True)
    slots_text = ft.Text(value="—", selectable=True)
    debug_panel = ft.ExpansionTile(
        title=ft.Text("Contexto detectado (debug)"),
        subtitle=ft.Text("intenção & slots extraídos"),
        initially_expanded=False,
        controls=[ft.Text("Intenção:", weight=ft.FontWeight.BOLD), intent_text, ft.Text("Slots:", weight=ft.FontWeight.BOLD), slots_text],
    )

    # Raw output (debug)
    raw_output = ft.Text("", selectable=True, max_lines=16, overflow=ft.TextOverflow.ELLIPSIS)
    raw_panel = ft.ExpansionTile(title=ft.Text("Raw output (debug)"), initially_expanded=False, controls=[raw_output])

    # --- direita: chat
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
                bgcolor=ft.Colors.BLUE_50, padding=10, border_radius=10,
                content=ft.Column([ft.Text("Você", size=12, color=ft.Colors.BLUE_700), ft.Text(msg)], spacing=4),
            )
        )

    def push_bot(widget: ft.Control | str):
        content = widget if isinstance(widget, ft.Control) else ft.Text(widget)
        chat.controls.append(
            ft.Container(
                bgcolor=ft.Colors.GREY_50, padding=10, border_radius=10,
                content=ft.Column([ft.Text("Assistente", size=12, color=ft.Colors.BLACK87), content], spacing=4),
            )
        )

    # --- modal de ticket
    ticket_name = ft.TextField(label="Nome", dense=True)
    ticket_email = ft.TextField(label="E-mail", dense=True)
    ticket_subject = ft.TextField(label="Assunto", dense=True)
    ticket_message = ft.TextField(label="Mensagem", multiline=True, min_lines=4)

    def open_ticket_dialog(e=None):
        dlg.open = True; page.update()

    def submit_ticket(e=None):
        name = (ticket_name.value or "").strip()
        email = (ticket_email.value or "").strip()
        subject = (ticket_subject.value or "").strip()
        message = (ticket_message.value or "").strip()
        if not all([name, email, subject, message]):
            page.snack_bar = ft.SnackBar(ft.Text("Preencha todos os campos do ticket."), open=True); page.update(); return
        reply = as_text(create_ticket(name, email, subject, message))
        push_bot(reply)
        for f in (ticket_name, ticket_email, ticket_subject, ticket_message): f.value = ""
        dlg.open = False; page.update()

    dlg = ft.AlertDialog(
        modal=True, title=ft.Text("Abrir ticket de suporte"),
        content=ft.Column([ticket_name, ticket_email, ticket_subject, ticket_message], tight=True),
        actions=[ft.TextButton("Cancelar", on_click=lambda e: setattr(dlg, "open", False)),
                 ft.FilledButton("Abrir ticket", icon=ft.Icons.SUPPORT_AGENT, on_click=submit_ticket)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.dialog = dlg

    # --- actions
    def apply_last_title(e=None):
        lt = session.data.get("last_title")
        if lt:
            title_field.value = lt; page.update()
        else:
            page.snack_bar = ft.SnackBar(ft.Text("Nenhum título anterior."), open=True); page.update()

    def clear_session(e=None):
        session.clear()
        page.snack_bar = ft.SnackBar(ft.Text("Sessão limpa."), open=True); page.update()

    last_title_btn.on_click = apply_last_title
    clear_session_btn.on_click = clear_session
    btn_ticket.on_click = open_ticket_dialog

    def do_details(e=None):
        title = (title_field.value or "").strip()
        if not title:
            page.snack_bar = ft.SnackBar(ft.Text("Informe um título."), open=True); page.update(); return
        session.update(title=title)
        md = as_text(book_details(title))
        raw_output.value = md
        push_user(f"Detalhes de “{title}”")
        push_bot(book_details_to_card(md))
        page.update()

    def do_where(e=None):
        title = (title_field.value or "").strip()
        if not title:
            page.snack_bar = ft.SnackBar(ft.Text("Informe um título."), open=True); page.update(); return
        city = (city_field.value or "").strip() or None
        session.update(title=title, city=city)
        md = as_text(where_to_buy(title, city))
        raw_output.value = md
        push_user(f"Onde comprar “{title}”" + (f" em {city}" if city else " (Online)"))
        push_bot(stores_to_card(md))
        page.update()

    btn_details.on_click = do_details
    btn_where.on_click = do_where

    # --- conversa natural
    def on_send_message(e=None):
        msg = (msg_input.value or "").strip()
        if not msg:
            page.snack_bar = ft.SnackBar(ft.Text("Digite uma mensagem."), open=True); page.update(); return

        push_user(msg); msg_input.value = ""; page.update()

        try:
            result: OrchestratorResult = classify_intent(msg, session=session.data)
            intent_text.value = f"{result.intent} (conf={result.confidence:.2f})"
            slots_text.value = (
                f"title={result.slots.title!r}, city={result.slots.city!r}, "
                f"name={result.slots.name!r}, email={result.slots.email!r}, "
                f"subject={result.slots.subject!r}, message={result.slots.message!r}"
            )

            title = result.slots.title or (title_field.value.strip() if title_field.value else None) or session.data.get("last_title")
            city = result.slots.city or (city_field.value.strip() if city_field.value else None)

            if result.intent == "DETALHES":
                if not title:
                    push_bot("Preciso do título. Preencha o campo Título à esquerda e envie de novo 😉")
                else:
                    session.update(title=title)
                    md = as_text(book_details(title))
                    raw_output.value = md
                    push_bot(book_details_to_card(md))

            elif result.intent == "ONDE_COMPRAR":
                if not title:
                    push_bot("Preciso do título. Preencha o campo Título à esquerda e envie de novo 😉")
                else:
                    session.update(title=title, city=city)
                    md = as_text(where_to_buy(title, city))
                    raw_output.value = md
                    push_bot(stores_to_card(md))

            else:  # SUPORTE
                if all([result.slots.name, result.slots.email, result.slots.subject, result.slots.message]):
                    reply = as_text(create_ticket(result.slots.name, result.slots.email, result.slots.subject, result.slots.message))
                    push_bot(reply)
                else:
                    open_ticket_dialog()

        except Exception as ex:
            push_bot(f"Ocorreu um erro: {ex}")

        page.update()

    send_btn.on_click = on_send_message

    # --- layout
    left = ft.Column(
        [
            ft.Text("Controles", size=18, weight=ft.FontWeight.BOLD),
            ft.Row([title_field, city_field]),
            ft.Row([last_title_btn, clear_session_btn]),
            ft.Row([btn_details, btn_where, btn_ticket]),
            ft.Divider(),
            debug_panel,
            raw_panel,
        ],
        width=360,
        spacing=10,
    )
    right = ft.Column(
        [
            ft.Row([ft.Text("Converse comigo", size=18, weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row([msg_input, send_btn]),
            chat,
        ],
        expand=True,
        spacing=10,
    )
    page.add(ft.Row([left, right], expand=True))


if __name__ == "__main__":
    ft.app(target=main)
