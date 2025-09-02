from __future__ import annotations

import os, re
from typing import Any, Dict, Optional

import flet as ft
from dotenv import load_dotenv

from ui.state import Session
from ui.components import as_text, book_details_to_card, stores_to_card

from agents.orchestrator import classify_intent, OrchestratorResult
from agents.catalog_agent import book_details, where_to_buy
from agents.support_agent import create_ticket


# ---------- env ----------
def ensure_env() -> None:
    load_dotenv(override=False)
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        raise RuntimeError("GEMINI_API_KEY não encontrada no ambiente/.env")


# ---------- helpers (ticket) ----------
_SUBJECT_FROM_TEXT_RE = re.compile(
    r"^\s*abr(?:a|ir)\s+(?:um\s+)?(?:ticket|chamado)\s*['\"“‘]?(?P<subject>.+?)['\"”’]?\s*$",
    re.IGNORECASE | re.DOTALL,
)

def extract_subject_from_text(text: str) -> Optional[str]:
    m = _SUBJECT_FROM_TEXT_RE.match((text or "").strip())
    if not m:
        return None
    s = (m.group("subject") or "").strip()
    if s.lower() in {"ticket", "chamado"} or len(s) < 2:
        return None
    return s


# ---------- helpers (título a partir do texto livre) ----------
# Padrões de linguagem natural que costumam aparecer
_TITLE_PATTERNS = [
    r"(?:onde\s+compro|onde\s+posso\s+comprar)\s+(?P<t>.+?)\s*(?:\?|$)",
    r"(?:quero\s+saber\s+sobre|saber\s+sobre|detalhes\s+de|detalhes\s+do|sobre)\s+(?P<t>.+?)\s*(?:\?|$)",
]

_QUOTED_RE = re.compile(r"[\"“”'‘’](?P<t>.*?)[\"“”'‘’]")

def _soft_title_case(s: str) -> str:
    """Converte para Title Case de forma suave (mantém palavras curtas minúsculas, exceto primeira)."""
    if not s:
        return s
    words = re.split(r"\s+", s.strip())
    if not words:
        return s
    small = {"de","da","do","das","dos","e","em","no","na","nos","nas","a","o","as","os","um","uma"}
    out = []
    for i, w in enumerate(words):
        w_clean = w.strip(" .,:;!?()[]{}")
        if not w_clean:
            continue
        if i == 0 or w_clean.lower() not in small:
            out.append(w_clean[:1].upper() + w_clean[1:])
        else:
            out.append(w_clean.lower())
    return " ".join(out)

def extract_title_from_free_text(text: str) -> Optional[str]:
    """Heurística para extrair o título do livro de uma frase sem aspas."""
    if not text:
        return None
    raw = text.strip()

    # 1) se vier com aspas, é o caminho mais confiável
    m = _QUOTED_RE.search(raw)
    if m:
        title = m.group("t").strip()
        return _soft_title_case(title)

    # 2) tenta padrões comuns (onde compro X, detalhes de X, sobre X)
    lowered = raw.lower()
    for pat in _TITLE_PATTERNS:
        m = re.search(pat, lowered, flags=re.IGNORECASE)
        if m:
            frag = m.group("t").strip()
            # corta artigos de cauda (ex: "a abelha?" -> "a abelha")
            frag = re.sub(r"[.?!]+$", "", frag).strip()
            # remove conectores finais comuns
            frag = re.sub(r"\s+(?:em|no|na|de|do|da)\s*$", "", frag, flags=re.IGNORECASE).strip()
            return _soft_title_case(frag)

    # 3) fallback: tenta capturar duas+ palavras seguidas que não são conectores
    tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9]+", raw)
    if len(tokens) >= 2:
        guess = " ".join(tokens[-2:])
        return _soft_title_case(guess)

    return None


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
    session.data.setdefault("ticket_form_open", False)
    session.data.setdefault("last_title", None)

    # --- esquerda: controles
    title_field = ft.TextField(label="Título", hint_text='Ex.: "A Abelha"', dense=True, expand=True)
    city_field = ft.TextField(label="Cidade", hint_text='Ex.: "São Paulo"', dense=True, width=220)
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
        controls=[
            ft.Text("Intenção:", weight=ft.FontWeight.BOLD),
            intent_text,
            ft.Text("Slots:", weight=ft.FontWeight.BOLD),
            slots_text,
        ],
    )

    # Raw output (debug)
    raw_output = ft.Text("", selectable=True, max_lines=16, overflow=ft.TextOverflow.ELLIPSIS)
    raw_panel = ft.ExpansionTile(title=ft.Text("Raw output (debug)"), initially_expanded=False, controls=[raw_output])

    # --- direita: chat
    msg_input = ft.TextField(
        label="Converse comigo",
        hint_text='Ex.: Onde compro "A Abelha" em São Paulo?  |  Abra um ticket "Dúvida sobre submissão"',
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
                content=ft.Column([ft.Text("Você", size=12, color=ft.Colors.BLUE_700), ft.Text(msg)], spacing=4),
            )
        )

    def push_bot(widget: ft.Control | str):
        content = widget if isinstance(widget, ft.Control) else ft.Text(widget)
        chat.controls.append(
            ft.Container(
                bgcolor=ft.Colors.GREY_50,
                padding=10,
                border_radius=10,
                content=ft.Column([ft.Text("Assistente", size=12, color=ft.Colors.BLACK87), content], spacing=4),
            )
        )

    # ---------- TICKET: Formulário inline ----------
    def render_inline_ticket_form(prefill: Optional[Dict[str, Optional[str]]] = None):
        pre = prefill or {}
        form_name = ft.TextField(label="Nome", dense=True, value=pre.get("name") or "")
        form_email = ft.TextField(label="E-mail", dense=True, value=pre.get("email") or "")
        form_subject = ft.TextField(label="Assunto", dense=True, value=pre.get("subject") or "")
        form_message = ft.TextField(label="Mensagem", multiline=True, min_lines=3, value=pre.get("message") or "")

        status_text = ft.Text("", color=ft.Colors.GREY)

        def on_submit_inline(e=None):
            name = (form_name.value or "").strip()
            email = (form_email.value or "").strip()
            subject = (form_subject.value or "").strip()
            message = (form_message.value or "").strip()
            if not all([name, email, subject, message]):
                status_text.value = "Preencha todos os campos do ticket."
                status_text.color = ft.Colors.RED
                card.update()
                return
            reply = as_text(create_ticket(name, email, subject, message))
            push_bot(reply)
            page.update()
            form_name.disabled = form_email.disabled = form_subject.disabled = form_message.disabled = True
            btn_inline.disabled = True
            status_text.value = "Ticket enviado."
            status_text.color = ft.Colors.GREEN
            session.data["ticket_form_open"] = False
            card.update()

        btn_inline = ft.FilledButton("Enviar ticket", icon=ft.Icons.SUPPORT_AGENT, on_click=on_submit_inline)

        card = ft.Card(
            content=ft.Container(
                padding=12,
                content=ft.Column(
                    [
                        ft.Row([ft.Icon(ft.Icons.SUPPORT_AGENT), ft.Text("Abrir ticket de suporte", weight=ft.FontWeight.BOLD)]),
                        form_name,
                        form_email,
                        form_subject,
                        form_message,
                        ft.Row([status_text], alignment=ft.MainAxisAlignment.START),
                        ft.Row([btn_inline], alignment=ft.MainAxisAlignment.END),
                    ],
                    spacing=8,
                ),
            )
        )
        push_bot(card)
        session.data["ticket_form_open"] = True
        page.update()

    # --- actions (botões da esquerda)
    def clear_session(e=None):
        session.clear()
        session.data["ticket_form_open"] = False
        session.data["last_title"] = None
        title_field.value = ""
        city_field.value = ""
        intent_text.value = "—"
        slots_text.value = "—"
        raw_output.value = ""
        page.snack_bar = ft.SnackBar(ft.Text("Sessão limpa."), open=True)
        page.update()

    clear_session_btn.on_click = clear_session

    def click_open_ticket(e=None):
        if session.data.get("ticket_form_open"):
            page.snack_bar = ft.SnackBar(ft.Text("Já existe um formulário de ticket aberto acima."), open=True)
            page.update()
            return

        prefill: Dict[str, Optional[str]] = {}
        text = (msg_input.value or "").strip()
        if text:
            subj = extract_subject_from_text(text)
            if not subj:
                try:
                    res: OrchestratorResult = classify_intent(text, session=session.data)
                    if res.intent == "SUPORTE" and res.slots.subject:
                        subj = res.slots.subject
                except Exception:
                    pass
            if subj:
                prefill["subject"] = subj

        msg_input.value = ""
        page.update()

        render_inline_ticket_form(prefill=prefill)
        page.update()

    btn_ticket.on_click = click_open_ticket

    def do_details(e=None):
        title = (title_field.value or "").strip()
        if not title:
            page.snack_bar = ft.SnackBar(ft.Text("Informe um título."), open=True)
            page.update()
            return
        session.update(title=title)
        session.data["last_title"] = title
        md = as_text(book_details(title))
        raw_output.value = md
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
        session.data["last_title"] = title
        md = as_text(where_to_buy(title, city))
        raw_output.value = md
        push_user(f"Onde comprar “{title}”" + (f" em {city}" if city else " (Online)"))
        push_bot(stores_to_card(md))
        page.update()

    btn_details.on_click = do_details
    btn_where.on_click = do_where

    # --- conversa natural
    def on_send_message(e=None):
        text_msg = (msg_input.value or "").strip()
        if not text_msg:
            page.snack_bar = ft.SnackBar(ft.Text("Digite uma mensagem."), open=True)
            page.update()
            return

        push_user(text_msg)
        msg_input.value = ""
        page.update()

        try:
            result: OrchestratorResult = classify_intent(text_msg, session=session.data)
            intent_text.value = f"{result.intent} (conf={result.confidence:.2f})"
            slots_text.value = (
                f"title={result.slots.title!r}, city={result.slots.city!r}, "
                f"name={result.slots.name!r}, email={result.slots.email!r}, "
                f"subject={result.slots.subject!r}, message={result.slots.message!r}"
            )

            # guard para formulário aberto (SUPORTE)
            if session.data.get("ticket_form_open") and result.intent == "SUPORTE":
                page.snack_bar = ft.SnackBar(ft.Text("Já existe um formulário de ticket aberto acima. Complete e envie."), open=True)
                push_bot("Já existe um formulário de ticket aberto acima. Complete e clique em **Enviar ticket**.")
                page.update()
                return

            # Fallback: tentar extrair título do texto livre se slots.title vier vazio
            inferred_title = None
            if not result.slots.title:
                inferred_title = extract_title_from_free_text(text_msg)

            title = result.slots.title or inferred_title or (title_field.value.strip() if title_field.value else None) or session.data.get("last_title")
            city = result.slots.city or (city_field.value.strip() if city_field.value else None)

            # se inferiu, já preenche o campo e salva como last_title
            if inferred_title:
                title_field.value = inferred_title
                session.data["last_title"] = inferred_title

            if result.intent == "DETALHES":
                if not title:
                    push_bot("Não consegui identificar o título. Tente algo como: **Quero saber sobre A Abelha**.")
                else:
                    session.update(title=title)
                    session.data["last_title"] = title
                    md = as_text(book_details(title))
                    raw_output.value = md
                    push_bot(book_details_to_card(md))

            elif result.intent == "ONDE_COMPRAR":
                if not title:
                    push_bot("Não consegui identificar o título. Tente: **Onde compro A Abelha?**")
                else:
                    session.update(title=title, city=city)
                    session.data["last_title"] = title
                    md = as_text(where_to_buy(title, city))
                    raw_output.value = md
                    push_bot(stores_to_card(md))

            else:  # SUPORTE
                if all([result.slots.name, result.slots.email, result.slots.subject, result.slots.message]):
                    reply = as_text(create_ticket(result.slots.name, result.slots.email, result.slots.subject, result.slots.message))
                    push_bot(reply)
                    page.update()
                else:
                    prefill = {
                        "name": result.slots.name,
                        "email": result.slots.email,
                        "subject": result.slots.subject,
                        "message": result.slots.message,
                    }
                    render_inline_ticket_form(prefill=prefill)

        except Exception as ex:
            push_bot(f"Ocorreu um erro: {ex}")

        page.update()

    send_btn.on_click = on_send_message

    # --- layout
    left = ft.Column(
        [
            ft.Text("Controles", size=18, weight=ft.FontWeight.BOLD),
            ft.Row([title_field, city_field]),
            ft.Row([clear_session_btn]),
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
