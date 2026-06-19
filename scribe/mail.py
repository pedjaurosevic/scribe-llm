"""
Email bridge for Scribe — send notifications and accept commands by email.

Standard library only (smtplib + imaplib). Tuned for Gmail with an App Password,
but works with any IMAP/SMTP provider.

Security model
--------------
Commands are accepted ONLY when BOTH hold:
  1. the message is from the single approved sender address, AND
  2. the subject carries the shared secret token `[scribe:SECRET]`.

The `From:` header can be spoofed, so the secret is the real gate; the sender
check is just a coarse filter. Accepted commands run through the sandboxed
workspace file tools (no shell).
"""

from __future__ import annotations

import email
import imaplib
import smtplib
import ssl
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any

# How much of a command result we put in the reply body (keep emails sane).
MAX_REPLY_CHARS = 8_000


@dataclass
class IncomingCommand:
    """A vetted command pulled from the inbox."""

    sender: str
    subject: str
    body: str
    message_id: str

    def instruction(self, secret: str) -> str:
        """The natural-language instruction: subject + body, token stripped from
        both (the secret is a credential, never part of the command)."""
        token = f"[scribe:{secret}]"
        subj = self.subject.replace(token, "").strip()
        body = self.body.replace(token, "").strip()
        parts = [p for p in (subj, body) if p]
        return "\n".join(parts).strip()


def _decode(raw: str | None) -> str:
    """Decode a possibly RFC2047-encoded header into plain text."""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def _plain_body(msg: email.message.Message) -> str:
    """Extract the text/plain body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition", "")
            ):
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return str(msg.get_payload())


class EmailBridge:
    """Send mail and poll the inbox for approved commands."""

    def __init__(
        self,
        address: str,
        password: str,
        *,
        approved_sender: str = "",
        secret: str = "",
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        imap_host: str = "imap.gmail.com",
        imap_port: int = 993,
    ) -> None:
        if not address or not password:
            raise ValueError("Email address and app password are required")
        self.address = address
        self.password = password
        self.approved_sender = (approved_sender or address).strip().lower()
        self.secret = secret
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.imap_host = imap_host
        self.imap_port = imap_port

    # --- sending ---------------------------------------------------------

    def send(
        self,
        subject: str,
        body: str,
        to: str | None = None,
        in_reply_to: str | None = None,
    ) -> None:
        """Send a plain-text email (defaults to the approved sender)."""
        msg = EmailMessage()
        msg["From"] = self.address
        msg["To"] = to or self.approved_sender or self.address
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)

        context = ssl.create_default_context()
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
            server.starttls(context=context)
            server.login(self.address, self.password)
            server.send_message(msg)

    # --- receiving -------------------------------------------------------

    def poll_commands(self) -> list[IncomingCommand]:
        """
        Return new approved commands from the inbox.

        Only unseen messages from the approved sender that carry the shared
        secret token are returned. The token is accepted in the message **body**
        (recommended — the body can be encrypted, the Subject travels in
        cleartext metadata across relays) and, for compatibility, in the
        Subject. Fetching marks them seen, so each command is handed back once.
        """
        if not self.secret:
            # No secret configured → never accept commands. Fail closed.
            return []

        token = f"[scribe:{self.secret}]"
        commands: list[IncomingCommand] = []

        imap = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        try:
            imap.login(self.address, self.password)
            imap.select("INBOX")
            typ, data = imap.search(None, "UNSEEN")
            if typ != "OK":
                return []

            for num in data[0].split():
                typ, msg_data = imap.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])

                sender = parseaddr(msg.get("From", ""))[1].strip().lower()
                subject = _decode(msg.get("Subject", ""))
                body = _plain_body(msg)

                if sender != self.approved_sender:
                    continue
                # Body is the secure location; Subject stays a compat fallback.
                if token not in body and token not in subject:
                    continue

                commands.append(
                    IncomingCommand(
                        sender=sender,
                        subject=subject,
                        body=body,
                        message_id=msg.get("Message-ID", "").strip(),
                    )
                )
        finally:
            try:
                imap.logout()
            except Exception:
                pass

        return commands


def build_bridge(config: Any) -> EmailBridge:
    """Construct an EmailBridge from a ScribeConfig (raises if misconfigured)."""
    cfg = config.email_config()
    return EmailBridge(
        address=cfg["address"],
        password=cfg["password"],
        approved_sender=cfg["approved_sender"],
        secret=cfg["secret"],
        smtp_host=cfg["smtp_host"],
        smtp_port=cfg["smtp_port"],
        imap_host=cfg["imap_host"],
        imap_port=cfg["imap_port"],
    )


def execute_instruction(config: Any, instruction: str, max_iters: int = 6) -> str:
    """
    Run one headless Scribe turn with sandboxed workspace tools and return the
    final answer text. Mirrors the web/TUI tool loop, no streaming UI.
    """
    from scribe.llm_adapter import LLMAdapter
    from scribe.prompts import get_system_prompt
    from scribe.tools import fs

    workspace = Path(config.workspace_dir)
    workspace.mkdir(parents=True, exist_ok=True)

    adapter = LLMAdapter.from_config(config)

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": get_system_prompt(
                config.reasoning,
                workspace=str(workspace),
                max_thinking_words=config.max_thinking_words,
                mode=config.reasoning_mode,
            ),
        },
        {"role": "user", "content": instruction},
    ]

    tools = fs.TOOL_SCHEMAS if config.tools_enabled else None
    final_answer = ""

    for _ in range(max_iters):
        answer_text = ""
        thinking_text = ""
        tool_calls = None

        for kind, payload in adapter.streaming_turn(messages, tools=tools):
            if kind == "thinking":
                thinking_text += payload
            elif kind == "answer":
                answer_text += payload
            elif kind == "tool_calls":
                tool_calls = payload

        if not tool_calls:
            if not answer_text.strip() and thinking_text.strip():
                answer_text = thinking_text
            final_answer = answer_text
            break

        messages.append(
            {
                "role": "assistant",
                "content": answer_text,
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"]},
                    }
                    for c in tool_calls
                ],
            }
        )
        for c in tool_calls:
            result = fs.dispatch(workspace, c["name"], c["arguments"])
            messages.append(
                {"role": "tool", "tool_call_id": c["id"], "content": result}
            )

    answer = final_answer.strip() or "(no answer)"
    if len(answer) > MAX_REPLY_CHARS:
        answer = answer[:MAX_REPLY_CHARS] + "\n... [truncated]"
    return answer
