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
  1.1.2026.) za naselje: građevinsko zemljište €/m², a za kuće vrijednost STANOVA
  slične veličine (za kuće PPV ne postoji, pa je to orijentacija).
- **Građevinsko područje (🗺, zemljišta):** prema katastarskoj čestici iz opisa ili
  točnoj oznaci na karti oglasa (ISPU, DGU). Izvan građevinskog područja → ⚠; bez
  točne lokacije piše „nije provjereno”. Uz to PPV na samoj lokaciji.
- **Naselja:** odluka za svako naselje (prolaz / ⚠ s razlogom: daleko od mora, daleko
  od Rijeke, grad Rijeka / ne stiže) je u `data/naselja_udaljenosti.csv`.
- **Cijena prema drugim oglasima:** 💰 ispod / 💸 iznad / 📊 oko medijana traženih
  €/m² u istom naselju (ako ima barem 8 oglasa), inače u gradu/općini.
- **Iz oglasa, kad ga portal navodi:** godina izgradnje i obnove, vlasnički list.
- **Parking (🚗, kuće):** parkirno mjesto ili garaža iz oglasa, ili okućnica od barem
  100 m². „Nema parkinga”, samo javni parking ili parking nije naveden → ⚠.
- **Sažeti redak (📊):** more (zračno), vožnja do Rijeke i Zagreba, cijena prema
  prosjeku i PPV-u, broj upozorenja.
- **Natječaji (📜):** prodaja nekretnina gradova, općina, PGŽ-a i države na našem
  području: sažeti redak, rok, mjesto, a za svaku česticu (do 3) građevinsko područje,
  početna cijena i €/m² prema PPV-u na lokaciji i medijanu traženih. Odluke iz popisa
  naselja vrijede kao za oglase (isključeno naselje napisano u tekstu → bez poruke;
  prema k.o. samo ⚠, jer k.o. može obuhvaćati više naselja).
- **Mail:** tjedni izvještaj ponedjeljkom i poruka ako neki izvor prestane raditi.
- **Pregledni izvještaj:** jedna HTML datoteka sa svim oglasima i razlogom odluke.

## Izvori

| Izvor | Kako | Kada |
|---|---|---|
| nekretnine.hr (isti oglasi kao Crozilla i Indomio) | podaci sa stranice (novi oglasi koji mogu proći otvaraju se radi punog opisa) | svakih 20 min |
| index.hr/oglasi | njihov API (novi oglasi koji mogu proći otvaraju se radi opisa) | svakih 20 min |
| oglasnik.hr | podaci sa stranice | svakih 20 min |
| FINA Očevidnik (samo građevinska zemljišta) | dnevni CSV izvoz | jednom dnevno |
| vender.hr | njihov API | svakih 20 min |
| Njuškalo | s Redmija, pravim preglednikom ([REDMI.md](REDMI.md)) | svakih 20 min |
| realestatecroatia.com (oglasi agencija iz sustava Agentor) | popis cijele PGŽ, najnoviji prvi; novi oglasi koji mogu proći otvaraju se radi površine | svakih 20 min |
| Natječaji gradova i općina, PGŽ-a, CERP-a i Državnih nekretnina ([data/natjecaji.yaml](data/natjecaji.yaml)) | tražilica stranice, RSS ili stranica natječaja; tekst i priloženi PDF | jednom dnevno |
| Banke ([data/banke.yaml](data/banke.yaml)): Zaba, OTP, HBOR, HPB, Croatia banka | stranice s prodajom preuzetih nekretnina; poruka samo za novi tekst koji spominje naše područje | jednom dnevno |

Njuškalo blokira GitHub i zahtjeve bez preglednika, pa ga čita Redmi s kućne mreže.
Javljaju se samo novi oglasi (novi broj oglasa) i sniženja; stari oglasi koje agencije
ponovno objave bilježe se bez poruke. Realitica je izostavljena (njezini oglasi gotovo
su svi već na drugim portalima).

Agencije (faza 5): stranice najaktivnijih agencija su većinom iza Cloudflareove zaštite
i ne otvaraju se iz oblaka, ali većina njih vodi oglase kroz sustav Agentor, koji ih
objavljuje i na realestatecroatia.com. Mjerenje 6. 10.: od oglasa s tog portala koji
prolaze kriterije oko 95 % već imamo s naših portala (i ne stižu ponovno); ostatak su
oglasi koje agencija drži samo ondje. Prvo pokretanje bilježi postojeće oglase bez poruke
(ući će u završni pregled), „cijena na upit” se preskače.

Banke i leasing kuće (6. 10.): na našem području trenutno ništa. Leasing kuće nude samo
vozila i opremu, Addiko objavljuje na Njuškalu, a prisilne prodaje idu kroz FINA
e-dražbe – oboje već pratimo. Stranice banaka se zato samo prate (🏦 poruka kad se pojavi
nešto s našeg područja).

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
