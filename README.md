# Scraper nekretnina – obala PGŽ i otok Krk

Prati oglase za prodaju kuća i građevinskih zemljišta i za svaki novi oglas koji
odgovara kriterijima šalje obavijest na Telegram. Radi na GitHub Actions, pa PC
ne mora biti upaljen. Plan i odluke: [PLAN.md](PLAN.md).

## Što dobivaš

- **Telegram:** obavijest za svaki novi oglas (fotografija, cijena, m², €/m², mjesto,
  izvor, gumb za otvaranje oglasa). Oznaka ⚠ znači da nešto treba provjeriti
  (npr. nema cijene). 📉 znači sniženu cijenu.
- **Već viđeni oglasi ne stižu ponovno:** isti oglas na drugom portalu ili ponovno
  objavljen pod novim brojem (ista općina i vrsta, ista površina, ista cijena, a kod
  okruglih brojeva i isto naselje ili slične riječi u naslovu). Ako je negdje jeftiniji,
  stiže s napomenom „📉 Već viđen na … – sad jeftiniji”. Preskočeni su popisani u
  tjednom izvještaju. Kad pravilo nije sigurno, oglas stiže.
- **Opasni izrazi u opisu** (suvlasništvo, ostavina, legalizacija, teret…): ⚠ s
  citiranom rečenicom; odbija se samo nedvosmisleno (prodaje se suvlasnički dio).
- **Ostvarene cijene (🏛 PPV):** Plan približnih vrijednosti Ministarstva (ISPU,
  1.1.2026.) za naselje: građevinsko zemljište €/m², a za kuće vrijednost stanova
  slične veličine (za kuće PPV ne postoji, pa je to orijentacija).
- **Cijena prema drugim oglasima:** 💰 ispod / 💸 iznad / 📊 oko medijana traženih
  €/m² u istom naselju (ako ima barem 8 oglasa), inače u gradu/općini.
- **Iz oglasa, kad ga portal navodi:** godina izgradnje i obnove, parking, vlasnički list.
- **Mail:** tjedni izvještaj ponedjeljkom i poruka ako neki izvor prestane raditi.
- **Pregledni izvještaj:** jedna HTML datoteka sa svim oglasima i razlogom odluke.

## Izvori

| Izvor | Kako | Kada |
|---|---|---|
| nekretnine.hr (isti oglasi kao Crozilla i Indomio) | podaci sa stranice | svakih 20 min |
| index.hr/oglasi | njihov API (novi oglasi koji mogu proći otvaraju se radi opisa) | svakih 20 min |
| oglasnik.hr | podaci sa stranice | svakih 20 min |
| FINA Očevidnik (samo građevinska zemljišta) | dnevni CSV izvoz | jednom dnevno |
| vender.hr | njihov API | svakih 20 min |
| Njuškalo | s Redmija, pravim preglednikom ([REDMI.md](REDMI.md)) | svakih 20 min |

Njuškalo blokira GitHub i zahtjeve bez preglednika, pa ga čita Redmi s kućne mreže.
Javljaju se samo novi oglasi (novi broj oglasa) i sniženja; stari oglasi koje agencije
ponovno objave bilježe se bez poruke. Realitica je izostavljena (njezini oglasi gotovo
su svi već na drugim portalima).

Provjereni i izostavljeni: nekretnine24.hr (nema oglasa za područje), oglasi.hr
(gotovo prazan), trazimstan.hr (većinom najam, zabranjuje automatsko čitanje),
gohome.hr (tražilica: Njuškalo osvježava svakih nekoliko dana, index.hr i oglasnik.hr
ne prati, a oglasi agencija gotovo su svi već na našim portalima).

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

## Automatsko pokretanje (cron-job.org)

GitHub raspored za ovaj repozitorij ne pokreće workflow, pa ga pokreće besplatni
servis cron-job.org, svakih 20 minuta od 7 do 23 h, preko GitHub API-ja.

- Adresa: `https://api.github.com/repos/B0rn4/scraper/actions/workflows/scraper.yml/dispatches`
- Metoda: `POST`
- Zaglavlja: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
  `X-GitHub-Api-Version: 2022-11-28`
- Tijelo: `{"ref":"claude/real-estate-scraper-primorska-jrlscq","inputs":{"naredba":"raspored"}}`
- Tjedni izvještaj: isti poziv ponedjeljkom u 7:15 s `"naredba":"tjedni"`.
- Token: GitHub fine-grained token samo za ovaj repozitorij, dozvola **Actions: Read and write**.

`raspored` poštuje radno vrijeme 7–23 h, a ručni `run` radi odmah.
