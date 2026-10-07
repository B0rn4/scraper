#!/bin/bash
# Šalje stanje (state.db, seen.json.gz, cijene.json, github.json) na granu state. Poziva ga
# workflow na kraju posla, a redovno pokretanje i odmah nakon čitanja portala: Redmi u :10
# treba stanje ovog pokretanja, a ono nakon toga još čeka pritiske gumba do :19.
set -e
[ -f state.db ] && [ -f .stanje-ucitano ] || exit 0
# Oštećena baza se ne sprema (ostaje prethodno stanje; kopije su na grani state-kopija).
python -c "import sqlite3, sys; sys.exit(sqlite3.connect('state.db').execute('PRAGMA integrity_check').fetchone()[0] != 'ok')" \
  || { echo "state.db je oštećen – stanje se ne sprema"; exit 1; }
rm -rf /tmp/state && mkdir -p /tmp/state && cp state.db /tmp/state/
# Sažetak već viđenih oglasa – Redmi ga preuzima da ne javi isti oglas s Njuškala.
[ -f seen.json.gz ] && cp seen.json.gz /tmp/state/
[ -f cijene.json ] && cp cijene.json /tmp/state/
# Za Redmi: zadnje pokretanje (nadzor GitHuba) i oglasi označeni "Ne zanima me".
[ -f github.json ] && cp github.json /tmp/state/
cd /tmp/state
git init -q && git checkout -q -b state && git add -A
git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
  commit -qm "Stanje $(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Neuspjelo spremanje znači da sljedeće pokretanje ponovno pošalje iste poruke: 3 pokušaja.
for i in 1 2 3; do
  git push -qf "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" state && exit 0
  echo "Spremanje stanja nije uspjelo (pokušaj $i)"; sleep $((i * 10))
done
exit 1
