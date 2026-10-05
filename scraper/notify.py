"""Obavijesti: Telegram (svaki oglas, izvještaji) i e-mail (tjedni izvještaj, greške)."""

import html
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path

import requests

from .models import HOUSE, LAND, WARN, Decision, Listing
from .text import fmt_eur, fmt_m2

SOURCE_LABELS = {
    "nekretnine_hr": "nekretnine.hr",
    "index_oglasi": "index.hr/oglasi",
    "oglasnik": "oglasnik.hr",
    "fina": "FINA Očevidnik",
    "vender": "vender.hr",
    "njuskalo": "Njuškalo",
    "redmi": "Redmi (Njuškalo)",
}


def format_listing(listing: Listing, decision: Decision, headline: str = "") -> str:
    """Tekst obavijesti (Telegram HTML, najviše ~1000 znakova jer ide kao opis fotografije)."""
    e = html.escape
    kind = "🏠 <b>Kuća</b>" if listing.kind == HOUSE else "🌳 <b>Građevinsko zemljište</b>" if listing.kind == LAND else "<b>Nekretnina</b>"
    parts = [kind, fmt_eur(listing.price) if listing.price and listing.price > 1000 else "cijena nije navedena"]
    if listing.area:
        parts.append(fmt_m2(listing.area))
    if listing.plot_area:
        parts.append(f"okućnica {fmt_m2(listing.plot_area)}")
    lines = []
    if headline:
        lines.append(f"<b>{e(headline)}</b>")
    lines.append(" · ".join(parts))
    place = decision.jls or listing.municipality
    if listing.settlement and listing.settlement != place:
        place = f"{place} – {listing.settlement}" if place else listing.settlement
    if place:
        lines.append(f"📍 {e(place)}")
    ppm = listing.price_per_m2 if listing.price and listing.price > 1000 else None
    meta = [f"{fmt_eur(ppm)}/m²"] if ppm else []
    meta.append(SOURCE_LABELS.get(listing.source, listing.source))
    if listing.subtype:
        meta.append(listing.subtype)
    lines.append("💶 " + e(" · ".join(meta)))
    if listing.extra.get("za_obnovu"):
        lines.append("🔨 za obnovu / starina")
    if listing.previous_price and listing.price and listing.previous_price > listing.price:
        lines.append(f"📉 prije {fmt_eur(listing.previous_price)}")
    if decision.status == WARN:
        for w in decision.warnings[:4]:
            lines.append(f"⚠ {e(w)}")
    if listing.source == "fina":
        sud, spis = listing.extra.get("sud"), listing.extra.get("spis")
        lines.append(f"⚖ {e(sud or '')} {e(spis or '')}".strip())
    lines.append(f"<i>{e(listing.title[:150])}</i>")
    text = "\n".join(lines)
    return text[:1000]


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self._last = 0.0

    @classmethod
    def from_env(cls) -> "Telegram | None":
        token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        return cls(token, chat) if token and chat else None

    def _call(self, method: str, data: dict, files: dict | None = None) -> dict:
        for _ in range(4):
            wait = 1.1 - (time.monotonic() - self._last)  # Telegram: oko 1 poruka u sekundi po razgovoru
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            resp = requests.post(f"{self.base}/{method}", data=data, files=files, timeout=60)
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if resp.status_code == 429:
                time.sleep(int(body.get("parameters", {}).get("retry_after", 5)) + 1)
                continue
            if not body.get("ok"):
                raise RuntimeError(f"Telegram {method}: {resp.status_code} {body.get('description', resp.text[:200])}")
            return body
        raise RuntimeError(f"Telegram {method}: previše zahtjeva")

    def send_text(self, text: str, silent: bool = False, url: str = "") -> None:
        data = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": "true", "disable_notification": str(silent).lower()}
        if url:
            data["reply_markup"] = _button(url)
        self._call("sendMessage", data)

    def send_listing(self, listing: Listing, decision: Decision, headline: str = "") -> None:
        text = format_listing(listing, decision, headline)
        markup = _button(listing.url, "Otvori oglas" if listing.source != "fina" else "Otvori Očevidnik")
        if listing.image_url:
            try:
                self._call("sendPhoto", {"chat_id": self.chat_id, "photo": listing.image_url, "caption": text,
                                         "parse_mode": "HTML", "reply_markup": markup})
                return
            except RuntimeError:
                pass  # slika se nije dala dohvatiti – pošalji bez nje
        self._call("sendMessage", {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true", "reply_markup": markup})

    def send_document(self, path: Path, caption: str) -> None:
        with open(path, "rb") as fh:
            self._call("sendDocument", {"chat_id": self.chat_id, "caption": caption[:1000], "parse_mode": "HTML"},
                       files={"document": (path.name, fh, "text/html")})


def _button(url: str, label: str = "Otvori") -> str:
    import json

    return json.dumps({"inline_keyboard": [[{"text": label, "url": url}]]})


class Email:
    def __init__(self, user: str, password: str, to: str):
        self.user = user
        self.password = password.replace(" ", "")  # Google lozinku za aplikacije prikazuje s razmacima
        self.to = to

    @classmethod
    def from_env(cls) -> "Email | None":
        user = os.environ.get("SMTP_USER", "").strip()
        password = os.environ.get("SMTP_PASSWORD", "").strip()
        to = os.environ.get("EMAIL_TO", "").strip() or user
        return cls(user, password, to) if user and password else None

    def send(self, subject: str, text: str, html_body: str = "", attachments: list[Path] = ()) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.user
        msg["To"] = self.to
        msg.set_content(text)
        if html_body:
            msg.add_alternative(html_body, subtype="html")
        for path in attachments:
            msg.add_attachment(Path(path).read_bytes(), maintype="text", subtype="html", filename=Path(path).name)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=60) as smtp:
            smtp.login(self.user, self.password)
            smtp.send_message(msg)
