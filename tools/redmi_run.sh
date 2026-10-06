#!/bin/bash
# Redovno pokretanje na Redmiju (Njuškalo). Poziva ga cron u Termuxu, kroz
# "proot-distro login ubuntu"; ručno: bash ~/scraper/tools/redmi_run.sh
set -u
cd "$HOME/scraper" || exit 1
exec 9>/tmp/scraper-redmi.lock
flock -n 9 || exit 0   # prethodno pokretanje još traje

LOG="$HOME/scraper.log"
{
  echo "=== $(date '+%F %T')"
  . "$HOME/venv/bin/activate"
  set -a; . "$HOME/.scraper.env"; set +a
  git pull -q --ff-only || echo "git pull nije uspio – radim sa starim kodom"
  # Oglasi koje je GitHub već vidio (da isti oglas s Njuškala ne stigne ponovno).
  python -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/B0rn4/scraper/state/seen.json.gz', '$HOME/seen.json.gz.tmp')" \
    && mv "$HOME/seen.json.gz.tmp" "$HOME/seen.json.gz" || echo "sažetak viđenih oglasa nije preuzet"
  python -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/B0rn4/scraper/state/cijene.json', '$HOME/cijene.json.tmp')" \
    && mv "$HOME/cijene.json.tmp" "$HOME/cijene.json" || echo "medijani cijena nisu preuzeti"
  # Zadnje pokretanje na GitHubu (nadzor) i oglasi označeni "Ne zanima me".
  python -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/B0rn4/scraper/state/github.json', '$HOME/github.json.tmp')" \
    && mv "$HOME/github.json.tmp" "$HOME/github.json" || echo "github.json nije preuzet"
  python -m scraper run --uredjaj redmi --db "$HOME/redmi.db" --out "$HOME/redmi-out" --vidjeni "$HOME/seen.json.gz" \
    --cijene "$HOME/cijene.json"
  python tools/redmi_sync.py "$HOME/redmi.db"
} >> "$LOG" 2>&1

# Dnevnik drži samo zadnjih 3000 redaka.
tail -n 3000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
