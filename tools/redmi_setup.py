"""Jednokratno postavljanje Redmija: spremi tajne u ~/.scraper.env i provjeri ih.

    python tools/redmi_setup.py

Pita za token Telegram bota, ID razgovora i GitHub token (ništa se ne prikazuje dok
lijepiš), provjeri ih, pošalje probnu poruku na Telegram i zapiše datoteku koju
čita samo vlasnik (chmod 600). Tajne ne idu nikamo drugamo."""

import getpass
import os
import sys
from pathlib import Path

import requests

ENV = Path.home() / ".scraper.env"
REPO = "B0rn4/scraper"


def ask(prompt: str, secret: bool = True) -> str:
    return (getpass.getpass(prompt) if secret else input(prompt)).strip()


def telegram_chat_id(token: str) -> str:
    """ID razgovora iz zadnjih poruka botu (ako mu je korisnik nešto napisao)."""
    try:
        updates = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json()
    except requests.RequestException:
        return ""
    chats = [u.get("message", {}).get("chat", {}) for u in updates.get("result", [])]
    ids = {str(c["id"]) for c in chats if c.get("type") == "private"}
    return ids.pop() if len(ids) == 1 else ""


def main() -> int:
    print("Postavljanje Redmija. Vrijednosti lijepi dugim pritiskom → Paste, pa Enter.\n")
    tg = ask("1/3 Token Telegram bota (BotFather → /mybots → bot → API Token): ")
    me = requests.get(f"https://api.telegram.org/bot{tg}/getMe", timeout=30).json()
    if not me.get("ok"):
        print("Telegram ne prihvaća token. Provjeri ga i pokreni ponovno.")
        return 1
    print(f"   Bot: @{me['result']['username']}")
    chat = telegram_chat_id(tg)
    if chat:
        print(f"   ID razgovora pronađen iz tvoje poruke botu: {chat}")
    else:
        chat = ask("2/3 ID razgovora (TELEGRAM_CHAT_ID s GitHuba; ili napiši botu bilo što pa pokreni ponovno): ",
                   secret=False)
    sent = requests.post(f"https://api.telegram.org/bot{tg}/sendMessage",
                         data={"chat_id": chat, "text": "✅ Redmi je spojen na scraper (Njuškalo)."}, timeout=30).json()
    if not sent.get("ok"):
        print(f"Probna poruka nije poslana: {sent.get('description')}. Provjeri ID razgovora.")
        return 1
    print("   Probna poruka poslana na Telegram.")

    gh = ask("3/3 GitHub token (redmi-scraper, Contents: Read and write): ")
    r = requests.get(f"https://api.github.com/repos/{REPO}", timeout=30,
                     headers={"Authorization": f"Bearer {gh}", "Accept": "application/vnd.github+json"})
    if r.status_code != 200 or not r.json().get("permissions", {}).get("push"):
        print(f"GitHub token nema dozvolu pisanja u {REPO} ({r.status_code}). Provjeri postavke tokena.")
        return 1
    print("   GitHub token u redu.")

    ENV.write_text(f"TELEGRAM_BOT_TOKEN={tg}\nTELEGRAM_CHAT_ID={chat}\nGITHUB_TOKEN={gh}\n", encoding="utf-8")
    os.chmod(ENV, 0o600)
    print(f"\nSpremljeno u {ENV}. Sljedeći korak u REDMI.md: prvo ručno pokretanje.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
