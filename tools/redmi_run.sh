#!/bin/bash
# Redovno pokretanje na Redmiju (Njuškalo). Poziva ga cron u Termuxu, kroz
# "proot-distro login ubuntu"; ručno: bash ~/scraper/tools/redmi_run.sh
set -u
cd "$HOME/scraper" || exit 1
# Iz crona (*/20) 10 minuta kasnije, između pokretanja na GitHubu (:00, :20, :40): tako
# svaki uređaj prije čitanja ima stanje drugoga i isti oglas ne stigne dvaput.
# Ručno pokretanje (iz terminala) kreće odmah. Čeka se po satu, ne jednim "sleep 600":
# dok Android spava, "sleep" ne broji vrijeme, pa se čekanje produljivalo do 19 minuta.
if [ ! -t 0 ]; then
  wake_at=$(( $(date +%s) + ${REDMI_ODGODA:-600} ))
  while [ "$(date +%s)" -lt "$wake_at" ]; do sleep 10; done
fi
LOG="$HOME/scraper.log"
exec 9>/tmp/scraper-redmi.lock
if ! flock -n 9; then
  echo "=== $(date '+%F %T') prethodno pokretanje još traje – ovo se preskače" >> "$LOG"
  exit 0
fi

# Svaki korak ima najdulje trajanje: jedan zaglavljeni korak (preglednik, mreža) inače bi
# zauvijek držao zaključavanje i Njuškalo se više ne bi pratio.
{
  echo "=== $(date '+%F %T')"
  . "$HOME/venv/bin/activate"
  set -a; . "$HOME/.scraper.env"; set +a
  # Kod uvijek točno kao na GitHubu (Redmi nema svojih izmjena; "git pull --ff-only" bi nakon
  # prepisane povijesti zauvijek ostao na starom kodu).
  timeout 5m git fetch -q origin && git reset -q --hard '@{u}' || echo "kod s GitHuba nije osvježen – radim sa starim kodom"
  # Paketi: dok popis (requirements.txt) nije uspješno instaliran – i nakon neuspjeha ili
  # ručnog "git pull" – pokušava se pri svakom pokretanju.
  req=$(git rev-parse HEAD:requirements.txt 2>/dev/null)
  if [ -n "$req" ] && [ "$req" != "$(cat "$HOME/.paketi-instalirani" 2>/dev/null)" ]; then
    if timeout 20m pip install -q -r requirements.txt; then
      echo "$req" > "$HOME/.paketi-instalirani"
    else
      echo "pip install nije uspio – pokušava se ponovno sljedeći put"
    fi
  fi
  # S GitHuba: već viđeni oglasi (da isti oglas s Njuškala ne stigne ponovno), medijani
  # cijena, zadnje pokretanje (nadzor GitHuba) i oglasi označeni "Ne zanima me"; nakon
  # ponovne instalacije i redmi.db. Nema li baze, a preuzimanje nije uspjelo (2 ili prekid),
  # pokretanje se preskače: prazna baza ne smije prepisati staru na GitHubu.
  rc=0; timeout 5m python tools/redmi_preuzmi.py "$HOME" || rc=$?
  if [ $rc -eq 2 ] || { [ $rc -ne 0 ] && [ ! -f "$HOME/redmi.db" ]; }; then
    echo "redmi.db nije vraćen s GitHuba ($rc) – pokretanje se preskače (prazna baza ne smije prepisati staru)"
  else
    [ $rc -eq 0 ] || echo "dio stanja s GitHuba nije preuzet – radim sa starim"
    timeout -k 60 15m python -m scraper run --uredjaj redmi --db "$HOME/redmi.db" --out "$HOME/redmi-out" \
      --vidjeni "$HOME/seen.json.gz" --cijene "$HOME/cijene.json" || echo "scraper je završio s greškom ili je prekinut ($?)"
    timeout 5m python tools/redmi_sync.py "$HOME/redmi.db" || echo "stanje nije poslano na GitHub"
  fi
} >> "$LOG" 2>&1

# Dnevnik drži samo zadnjih 3000 redaka.
tail -n 3000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
