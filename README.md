# Scraper nekretnina – obala PGŽ i otok Krk

Prati oglase za prodaju kuća i građevinskih zemljišta i za svaki novi oglas koji
odgovara kriterijima šalje obavijest na Telegram. Radi na GitHub Actions, pa PC
ne mora biti upaljen. Plan i odluke: [PLAN.md](PLAN.md).

## Što dobivaš

- **Telegram:** obavijest za svaki novi oglas (fotografija, cijena, m², €/m², mjesto,
  izvor, gumb za otvaranje oglasa). Oznaka ⚠ znači da nešto treba provjeriti
  (npr. nema cijene). 📉 znači sniženu cijenu.
- **Mail:** tjedni izvještaj ponedjeljkom i poruka ako neki izvor prestane raditi.
- **Pregledni izvještaj:** jedna HTML datoteka sa svim oglasima i razlogom odluke.

## Izvori

| Izvor | Kako | Kada |
|---|---|---|
| nekretnine.hr (isti oglasi kao Crozilla i Indomio) | podaci sa stranice | svakih 20 min |
| index.hr/oglasi | njihov API | svakih 20 min |
| oglasnik.hr | podaci sa stranice | svakih 20 min |
| FINA Očevidnik (samo građevinska zemljišta) | dnevni CSV izvoz | jednom dnevno |

Njuškalo i Realitica dolaze u fazi 2 (preko Redmija).

## Ručno pokretanje

GitHub → repozitorij → **Actions** → **Scraper nekretnina** → **Run workflow**, pa odaberi:

- `test` – probna poruka na Telegram i probni mail,
- `pregled` – pregledni izvještaj cijelog područja (stiže na Telegram i mail),
- `run` – jedno redovno pokretanje odmah,
- `tjedni` – tjedni izvještaj odmah.

## Pregledni izvještaj

Otvori HTML datoteku u pregledniku (na mobitelu iz Telegrama: otvori datoteku → preglednik).
Filtriraj po odluci (✅ / ⚠ / ❌), razlogu, izvoru i vrsti. Kod pogrešno procijenjenog
oglasa označi kvačicu **pogrešno**, upiši napomenu (npr. „trebao je proći”) i na kraju
klikni **Kopiraj označene**. Zalijepi popis Claudeu u razgovor.

## Postavke

- `config.yaml` – cijene, površine, radno vrijeme, uključeni izvori.
- `data/locations_extra.yaml` – popis gradova i općina koji se prate (`ukljuceno`),
  dodatni nazivi, katastarske općine, lažni pogoci.
- `data/locations.yaml` – naselja po gradovima i općinama (generirano, ne mijenjati ručno).

## Tehnički

- `python -m scraper run|pregled|test|tjedni` (opcije: `--izvori`, `--bez-slanja`, `--force`).
- Stanje (viđeni oglasi) je u `state.db` na grani `state`.
- Testovi: `python -m pytest`.
- Tajne (GitHub Secrets): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SMTP_USER`,
  `SMTP_PASSWORD`, `EMAIL_TO`.
