#!/bin/bash
# Redovno pokretanje na Redmiju (Njuškalo). Poziva ga cron u Termuxu, kroz
# "proot-distro login ubuntu"; ručno: bash ~/scraper/tools/redmi_run.sh
set -u
cd "$HOME/scraper" || exit 1
# Iz crona (*/20) 10 minuta kasnije, između pokretanja na GitHubu (:00, :20, :40): tako
# svaki uređaj prije čitanja ima stanje drugoga i isti oglas ne stigne dvaput.
# Ručno pokretanje (iz terminala) kreće odmah.
[ -t 0 ] || sleep "${REDMI_ODGODA:-600}"
exec 9>/tmp/scraper-redmi.lock
flock -n 9 || exit 0   # prethodno pokretanje još traje

LOG="$HOME/scraper.log"
{
  echo "=== $(date '+%F %T')"
  . "$HOME/venv/bin/activate"
  set -a; . "$HOME/.scraper.env"; set +a
  git pull -q --ff-only || echo "git pull nije uspio – radim sa starim kodom"
  # S GitHuba: već viđeni oglasi (da isti oglas s Njuškala ne stigne ponovno), medijani
  # cijena, zadnje pokretanje (nadzor GitHuba) i oglasi označeni "Ne zanima me".
  python tools/redmi_preuzmi.py "$HOME" || echo "dio stanja s GitHuba nije preuzet – radim sa starim"
  python -m scraper run --uredjaj redmi --db "$HOME/redmi.db" --out "$HOME/redmi-out" --vidjeni "$HOME/seen.json.gz" \
    --cijene "$HOME/cijene.json"
  python tools/redmi_sync.py "$HOME/redmi.db"
} >> "$LOG" 2>&1

# Dnevnik drži samo zadnjih 3000 redaka.
tail -n 3000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
