"""Jednokratno postavljanje Redmija: spremi tajne u ~/.scraper.env i provjeri ih.

    python tools/redmi_setup.py

Pita za token Telegram bota, ID razgovora i GitHub token (ništa se ne prikazuje dok
lijepiš), provjeri ih, pošalje probnu poruku na Telegram i zapiše datoteku koju
čita samo vlasnik (chmod 600). Tajne ne idu nikamo drugamo. Kad je Redmi već postavljen,
Enter ostavlja postojeću vrijednost (npr. samo nov token bota nakon opoziva u BotFatheru)."""

import getpass
import os
import sys
from pathlib import Path

import requests

ENV = Path.home() / ".scraper.env"
REPO = "B0rn4/scraper"


def ask(prompt: str, secret: bool = True) -> str:
    return (getpass.getpass(prompt) if secret else input(prompt)).strip()


def existing() -> dict[str, str]:
    """Vrijednosti iz postojeće ~/.scraper.env (ponovno postavljanje: Enter ih ostavlja)."""
    values = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip():
                values[name.strip()] = value.strip()
    return values


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
    old = existing()
    keep = " (Enter = ostaje postojeći)"
    tg = ask("1/3 Token Telegram bota (BotFather → /mybots → bot → API Token)"
             f"{keep if old.get('TELEGRAM_BOT_TOKEN') else ''}: ") or old.get("TELEGRAM_BOT_TOKEN", "")
    me = requests.get(f"https://api.telegram.org/bot{tg}/getMe", timeout=30).json()
    if not me.get("ok"):
        print("Telegram ne prihvaća token. Provjeri ga i pokreni ponovno.")
        return 1
    print(f"   Bot: @{me['result']['username']}")
    chat = telegram_chat_id(tg)
    if chat:
        print(f"   ID razgovora pronađen iz tvoje poruke botu: {chat}")
    elif old.get("TELEGRAM_CHAT_ID"):
        chat = old["TELEGRAM_CHAT_ID"]
        print("   ID razgovora: postojeći iz ~/.scraper.env")
    else:
        # GitHub svakih 20 minuta pročita (i potvrdi) poruke botu, pa ih skripta poslije ne vidi.
        print("   ID razgovora nije pronađen: napiši botu bilo što (npr. „bok”) i ODMAH pokreni skriptu\n"
              "   ponovno (GitHub svakih 20 minuta pročita poruke botu). Ili ga upiši ako ga znaš.")
        chat = ask("2/3 ID razgovora (Enter za prekid): ", secret=False)
        if not chat:
            return 1
    sent = requests.post(f"https://api.telegram.org/bot{tg}/sendMessage",
                         data={"chat_id": chat, "text": "✅ Redmi je spojen na scraper (Njuškalo)."}, timeout=30).json()
    if not sent.get("ok"):
        print(f"Probna poruka nije poslana: {sent.get('description')}. Provjeri ID razgovora.")
        return 1
    print("   Probna poruka poslana na Telegram.")

    gh = ask("3/3 GitHub token (redmi-scraper, Contents: Read and write)"
             f"{keep if old.get('GITHUB_TOKEN') else ''}: ") or old.get("GITHUB_TOKEN", "")
    r = requests.get(f"https://api.github.com/repos/{REPO}", timeout=30,
                     headers={"Authorization": f"Bearer {gh}", "Accept": "application/vnd.github+json"})
    if r.status_code != 200 or not r.json().get("permissions", {}).get("push"):
        print(f"GitHub token nema dozvolu pisanja u {REPO} ({r.status_code}). Provjeri postavke tokena.")
        return 1
    print("   GitHub token u redu.")

    other = "".join(f"{k}={v}\n" for k, v in old.items() if k not in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GITHUB_TOKEN"))
    ENV.write_text(f"TELEGRAM_BOT_TOKEN={tg}\nTELEGRAM_CHAT_ID={chat}\nGITHUB_TOKEN={gh}\n{other}", encoding="utf-8")
    os.chmod(ENV, 0o600)
    print(f"\nSpremljeno u {ENV}. Sljedeći korak u REDMI.md: prvo ručno pokretanje.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
