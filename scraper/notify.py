"""Obavijesti: Telegram (svaki oglas, izvještaji) i e-mail (tjedni izvještaj, greške)."""

import html
import json
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import requests

from .filters import effective_price
from .models import HOUSE, LAND, WARN, Decision, Listing
from .text import fmt_eur, fmt_m2

SOURCE_LABELS = {
    "nekretnine_hr": "nekretnine.hr",
    "index_oglasi": "index.hr/oglasi",
    "oglasnik": "oglasnik.hr",
    "fina": "FINA Očevidnik",
    "vender": "vender.hr",
    "realestatecroatia": "realestatecroatia.com",
    "burza": "burza.com.hr",
    "njuskalo": "Njuškalo",
    "redmi": "Redmi (Njuškalo)",
}


def _minutes(value: float) -> str:
    value = int(round(value))
    return f"{value} min" if value < 60 else f"{value // 60} h {value % 60:02d} min"


def summary_line(listing: Listing, decision: Decision) -> str:
    """Sažetak na vrhu poruke: more (zračno), Rijeka (vožnja), cijena, broj ⚠.
    Kad oglas navodi samo grad/općinu, mjere su za istoimeno mjesto (~Krk)."""
    warnings = len(decision.warnings) if decision.status == WARN else 0
    return summary_text(listing.extra.get("mjere") or {}, listing.extra.get("cijena_kratko") or [], warnings)


def summary_text(m: dict, price_parts: list[str], warnings: int) -> str:
    """Sažeti redak iz mjera naselja (popis naselja), kratkih usporedbi cijene i broja ⚠."""
    parts = []
    prefix = "" if m.get("tocno", True) else f"~{m.get('naselje')}: "
    if m.get("more_km") is not None:
        parts.append(f"more {m['more_km']:.1f} km".replace(".", ","))
    if m.get("rijeka_min") is not None and m["rijeka_min"] > 0:
        parts.append(f"Rijeka {_minutes(m['rijeka_min'])}")
    if parts:
        parts[0] = prefix + parts[0]
    parts += price_parts
    if warnings:
        parts.append(f"⚠ {warnings}")
    return "📊 " + " · ".join(parts) if parts else ""


def format_listing(listing: Listing, decision: Decision, headline: str = "") -> str:
    """Tekst obavijesti (Telegram HTML, najviše ~1000 znakova jer ide kao opis fotografije).
    Kad je predugo, izostavljaju se cijeli manje važni retci (nikad usred HTML oznake)."""
    e = html.escape
    kind = "🏠 <b>Kuća</b>" if listing.kind == HOUSE else "🌳 <b>Građevinsko zemljište</b>" if listing.kind == LAND else "<b>Nekretnina</b>"
    total = effective_price(listing.price, listing.area, bool(listing.extra.get("ukupna_cijena")), listing.kind)
    if total is None:
        shown = "cijena nije navedena"
    elif total == listing.price:
        shown = fmt_eur(total)
    else:                                            # vjerojatno cijena po m² (vidi filters.py)
        shown = f"≈ {fmt_eur(total)} ({fmt_eur(listing.price)}/m²?)"
    parts = [kind, shown]
    if listing.area:
        parts.append(fmt_m2(listing.area))
    if listing.plot_area:
        parts.append(f"okućnica {fmt_m2(listing.plot_area)}")
    lines: list[tuple[str, str]] = []          # (vrsta retka, tekst)
    if headline:
        lines.append(("naslov", f"<b>{e(headline)}</b>"))
    lines.append(("glavni", " · ".join(parts)))
    summary = summary_line(listing, decision)
    if summary:
        lines.append(("sazetak", e(summary)))
    place = decision.jls or listing.municipality
    settlement = listing.settlement or ((listing.extra.get("mjere") or {}).get("naselje")
                                        if (listing.extra.get("mjere") or {}).get("tocno") else "")
    if settlement and settlement != place:
        place = f"{place} – {settlement}" if place else settlement
    if place:
        lines.append(("mjesto", f"📍 {e(place)}"))
    ppm = listing.price_per_m2 if listing.price and listing.price > 1000 else None
    meta = [f"{fmt_eur(ppm)}/m²"] if ppm else []
    meta.append(SOURCE_LABELS.get(listing.source, listing.source))
    if listing.subtype:
        meta.append(listing.subtype)
    lines.append(("cijena", "💶 " + e(" · ".join(meta))))
    facts = ["🔨 za obnovu / starina"] if listing.extra.get("za_obnovu") else []
    if listing.extra.get("godina_izgradnje"):
        facts.append(f"izgrađena {listing.extra['godina_izgradnje']}")
    if listing.extra.get("godina_obnove"):
        facts.append(f"obnovljena {listing.extra['godina_obnove']}")
    if listing.extra.get("vlasnicki_list"):
        facts.append("vlasnički list ✔")
    if facts:
        lines.append(("cinjenice", ("" if facts[0].startswith("🔨") else "🏗 ") + e(" · ".join(facts))))
    for key in ("parking_redak", "gp", "ppv", "usporedba"):
        if listing.extra.get(key):
            # Kuća bez točne lokacije: "nije provjereno" je najmanje važan redak.
            kind = "gp_neprovjereno" if key == "gp" and listing.extra.get("gp_neprovjereno") else key
            lines.append((kind, e(listing.extra[key])))
    if listing.previous_price and listing.price and listing.previous_price > listing.price:
        lines.append(("prije", f"📉 prije {fmt_eur(listing.previous_price)}"))
    if decision.status == WARN:
        for w in decision.warnings[:5]:
            lines.append(("upozorenje", f"⚠ {e(w if len(w) <= 200 else w[:197] + '…')}"))
    if listing.source == "fina":
        sud, spis = listing.extra.get("sud"), listing.extra.get("spis")
        lines.append(("fina", f"⚖ {e(sud or '')} {e(spis or '')}".strip()))
    lines.append(("naslov_oglasa", f"<i>{e(listing.title[:150])}</i>"))
    # Predugo: redom izostavi manje važne retke.
    for drop in ("gp_neprovjereno", "naslov_oglasa", "usporedba", "cinjenice", "ppv", "parking_redak", "mjesto"):
        if len("\n".join(t for _, t in lines)) <= 1000:
            break
        lines = [(k, t) for k, t in lines if k != drop]
    while len("\n".join(t for _, t in lines)) > 1000 and any(k == "upozorenje" for k, _ in lines):
        last = max(i for i, (k, _) in enumerate(lines) if k == "upozorenje")
        lines.pop(last)
    return "\n".join(t for _, t in lines)

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
        markup = listing_markup(listing)
        if listing.image_url:
            try:
                self._call("sendPhoto", {"chat_id": self.chat_id, "photo": listing.image_url, "caption": text,
                                         "parse_mode": "HTML", "reply_markup": markup})
                return
            except (RuntimeError, requests.RequestException):
                pass  # slika se nije dala dohvatiti (ili Telegram nije odgovorio na vrijeme) – pošalji bez nje
        self._call("sendMessage", {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true", "reply_markup": markup})

    # --- gumb "Ne zanima me": pritisci se čitaju pri pokretanju (nema stalnog poslužitelja) ---

    def get_updates(self, offset: int | None) -> list[dict]:
        data = {"timeout": "0", "allowed_updates": json.dumps(["callback_query"])}
        if offset:
            data["offset"] = str(offset)
        return self._call("getUpdates", data).get("result") or []

    def answer_callback(self, query_id: str, text: str) -> None:
        self._call("answerCallbackQuery", {"callback_query_id": query_id, "text": text})

    def edit_markup(self, chat_id, message_id, markup: str) -> None:
        self._call("editMessageReplyMarkup", {"chat_id": str(chat_id), "message_id": str(message_id), "reply_markup": markup})

    def send_document(self, path: Path, caption: str) -> None:
        with open(path, "rb") as fh:
            self._call("sendDocument", {"chat_id": self.chat_id, "caption": caption[:1000], "parse_mode": "HTML"},
                       files={"document": (path.name, fh, "text/html")})


def safe_url(url: str) -> str:
    """Adresa za gumb: Telegram odbija razmake i znakove izvan ASCII-ja ("…/Natječaj za
    prodaju.pdf"), a postojeće %XX ostaju kakve jesu."""
    return quote(url or "", safe=":/?#[]@!$&'()*+,;=%~")


def _button(url: str, label: str = "Otvori") -> str:
    return json.dumps({"inline_keyboard": [[{"text": label, "url": safe_url(url)}]]})


MUTE_PREFIX = "nz:"          # callback_data gumba "Ne zanima me" (Telegram: najviše 64 bajta)
UNMUTE_PREFIX = "pz:"        # callback_data gumba za poništenje
MUTE_LABEL = "🔕 Ne zanima me"
MUTED_LABEL = "🔕 Zabilježeno · ↩ dodirni za poništenje"


def listing_markup(listing: Listing) -> str:
    """Gumbi ispod oglasa: otvori oglas i "Ne zanima me" (više nikakvih poruka o njemu)."""
    row = [{"text": "Otvori oglas" if listing.source != "fina" else "Otvori Očevidnik", "url": safe_url(listing.url)}]
    data = MUTE_PREFIX + listing.key
    if len(data.encode("utf-8")) <= 64:
        row.append({"text": MUTE_LABEL, "callback_data": data})
    return json.dumps({"inline_keyboard": [row]})


def _link_buttons(message: dict) -> list[dict]:
    rows = (message.get("reply_markup") or {}).get("inline_keyboard") or []
    return [b for row in rows for b in row if b.get("url")][:1]


def muted_markup(message: dict, key: str) -> str:
    """Nakon "Ne zanima me": poveznica ostaje, a gumb pokazuje da je zabilježeno i da se
    može poništiti (slučajan dodir)."""
    undo = {"text": MUTED_LABEL, "callback_data": UNMUTE_PREFIX + key}
    links = _link_buttons(message)
    return json.dumps({"inline_keyboard": [links, [undo]] if links else [[undo]]})


def unmuted_markup(message: dict, key: str) -> str:
    """Nakon poništenja: opet poveznica i "Ne zanima me", kao u izvornoj poruci."""
    return json.dumps({"inline_keyboard": [_link_buttons(message) + [{"text": MUTE_LABEL, "callback_data": MUTE_PREFIX + key}]]})


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
