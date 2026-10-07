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
- **Parcelacija (✂️):** oglas koji u naslovu ili opisu spominje mogućnost parcelacije
  (i „parcelizacija”, „parcelirati”, „podijeliti na dvije čestice”, engleski…) stiže
  neovisno o cijeni i površini – one se navode kao ⚠. Mjesto (popis naselja) i ostala
  pravila i dalje vrijede; „parcelacija nije moguća” i sama riječ „parcela” ne broje se.
  Stranica oglasa zemljišta na našem području otvara se i kad cijena ili površina ne
  odgovaraju, jer je spomen obično tek u opisu.
- **Opasni izrazi u opisu** (suvlasništvo, ostavina, legalizacija, teret…): ⚠ s
  citiranom rečenicom; odbija se samo nedvosmisleno (prodaje se suvlasnički dio).
- **Ostvarene cijene (🏛 PPV, samo zemljišta):** Plan približnih vrijednosti
  Ministarstva (ISPU) za naselje: građevinsko zemljište €/m². Za kuće PPV ne postoji
  (vrijednost stanova slične veličine je zavaravala pa je maknuta 6. 10.).
- **Građevinsko područje (🗺, zemljišta i kuće):** prema katastarskoj čestici iz opisa
  ili točnoj oznaci na karti oglasa (ISPU, DGU). Izvan građevinskog područja → ⚠ (kod
  kuće: dogradnja i zamjenska gradnja ograničene, provjeriti legalnost); bez točne
  lokacije piše „nije provjereno” (kod kuća se taj redak prvi izostavlja kad je poruka
  preduga). Za zemljišta uz to PPV na samoj lokaciji.
- **Kulturna baština (⚠, kuće i zemljišta):** u istom upitu ISPU-u i zaštićena kulturna
  dobra Ministarstva kulture (Z- i P-lista): pojedinačno dobro, kulturno-povijesna
  cjelina (npr. Krk, Vrbnik, Opatija, Bakar, Omišalj, Baška, šire središte Rijeke),
  arheološka zona → ⚠ „radovi uz uvjete konzervatora”. Za zemljište ⚠ „nova gradnja uz
  uvjete konzervatora (oblik, visina, materijali)”: gradnja nije zabranjena, ali traži
  posebne uvjete i potvrdu projekta konzervatorskog odjela, a koliko su strogi ovisi o
  zoni zaštite (A, B, C); u arheološkoj zoni moguća su istraživanja prije gradnje. Kad je oznaka na karti
  približna, provjerava se samo cjelina i samo ako opis spominje staru jezgru
  („vjerojatno u …”). Uz to ⚠ kad opis spominje kulturno dobro, konzervatora ili
  zaštićenu jezgru.
- **Naselja:** odluka za svako naselje (prolaz / ⚠ s razlogom: daleko od mora, daleko
  od Rijeke, grad Rijeka / ne stiže) je u `data/naselja_udaljenosti.csv`.
- **Cijena prema drugim oglasima (📐 područje, 🏘 naselje):** usporedba s oglasima koji
  odgovaraju kriterijima (nisu odbijeni, cijena i površina u granicama; viđeni u zadnjih
  godinu dana; isti oglas na više portala jednom, a sam oglas i njegova kopija se ne
  broje; očito pogrešni unosi – €/m² izvan razumnog raspona – izbačeni). Uspoređuju se
  oglasi iste vrste i razreda površine, jer €/m² jako pada s površinom: kuće 70–99,
  100–129, 130–169, 170–249 i od 250 m²; zemljišta 300–799, 800–1.199, 1.200–2.499 i od
  2.500 m². Kuće za obnovu, starine, ruševine i nedovršene (Rohbau) su zasebna
  kategorija, sve veličine zajedno (prepoznaju se u naslovu i opisu; kategorija se pamti
  u bazi). Redak kaže prosjek područja (bez 10 % najjeftinijih i najskupljih) ili medijan
  naselja, koliko je oglas iznad ili ispod, i **od koliko posto tih oglasa je skuplji**
  (točno prebrojano, jednaki se broje upola). Područje treba barem 10 oglasa, naselje 8;
  kad naselje nema dovoljno, gleda se cijeli grad/općina. Bez dovoljno oglasa po
  kriterijima ostaje stara usporedba s medijanom svih oglasa u naselju (💰/💸/📊), osim
  za kuće za obnovu. Stanje 7. 10. (prosjek €/m²): kuće 3.230 / 2.530 / 2.120 / 1.580 /
  1.060, zemljišta 268 / 193 / 103 / 49.
- **Iz oglasa, kad ga portal navodi:** godina izgradnje i obnove, vlasnički list.
- **Parking (🚗, kuće):** parkirno mjesto ili garaža iz oglasa, ili okućnica od barem
  100 m². „Nema parkinga”, samo javni parking ili parking nije naveden → ⚠.
- **Duga poruka:** opis uz fotografiju smije imati oko 1.000 znakova. Što ne stane
  (redom: usporedba s medijanom mjesta, činjenice, PPV, prosjek područja, parking, mjesto,
  zadnja upozorenja) stiže odmah u drugoj poruci, kao odgovor na prvu i bez zvuka; 👎 na
  bilo kojoj od njih vrijedi za oglas. Ne stane li samo naslov oglasa ili „nije
  provjereno”, druge poruke nema.
- **Sažeti redak (📊):** more (zračno), vožnja do Rijeke, „skuplji od 31 % područja,
  18 % mjesta” (ili „mjesto −25 %” prema medijanu svih oglasa), PPV, broj upozorenja.
- **Natječaji (📜):** prodaja nekretnina gradova, općina, PGŽ-a i države na našem
  području: sažeti redak, rok, mjesto, a za svaku česticu (do 3) građevinsko područje,
  početna cijena i €/m² prema PPV-u na lokaciji i medijanu traženih. Odluke iz popisa
  naselja vrijede kao za oglase (isključeno naselje napisano u tekstu → bez poruke;
  prema k.o. samo ⚠, jer k.o. može obuhvaćati više naselja).
- **Cijena na upit:** procjena = površina × medijan traženih €/m² u naselju. Odbija se
  luksuzna (u naslovu vila, bazen, luksuzna, ekskluzivna, prvi red… i procjena × 0,4
  iznad granice) i golema kuća (procjena × 0,2 iznad granice); ostale stižu s ⚠ i
  procjenom. Starina, ruševina i nedovršena gradnja (Rohbau, započeta gradnja) se ne
  odbijaju – cijena po m² im je daleko ispod medijana. Mjereno na 12.378 oglasa s
  cijenom: od kuća u granici pravilo bi izgubilo 3 goleme (660–810 m²). S
  realestatecroatia.com i burze „na upit” se i dalje preskače.
- **„Ne zanima me” = reakcija 👎 na poruku oglasa** (dugi pritisak → 👎): za taj oglas (i
  isti oglas na drugim portalima) više ne stiže ništa, ni sniženje. Obradi se pri sljedećem
  pokretanju (do 20 min; noću u 7:00) i ispod poruke se pojavi „🔕 Ne zanima me · makni 👎
  za poništenje”. Maknuta 👎 (i nakon nekoliko dana) vraća poruke. Reakciju Telegram čuva
  do sljedećeg pokretanja; pritisak gumba ne bi (izgubi se ako ga bot ne preuzme odmah).
- **Mail:** tjedni izvještaj ponedjeljkom i poruka ako neki izvor prestane raditi.
- **Nadzor:** GitHub provjerava javlja li se Redmi (mail), a Redmi provjerava radi li
  GitHub (Telegram, ako nije pokrenuo scraper 2 h, od 9 h) – tišina inače izgleda kao
  „nema novih oglasa”.
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
| burza.com.hr (regionalni oglasnik, agencije i privatni) | prve dvije stranice Kvarnera i Istre; novi oglasi se otvaraju radi mjesta i površine (do 10 po pokretanju) | svakih 20 min |
| Natječaji gradova i općina, PGŽ-a, CERP-a i Državnih nekretnina ([data/natjecaji.yaml](data/natjecaji.yaml)) | tražilica stranice, RSS ili stranica natječaja; tekst i priloženi PDF | jednom dnevno |
| Banke ([data/banke.yaml](data/banke.yaml)): Zaba, OTP, HBOR, HPB, Croatia banka | stranice s prodajom preuzetih nekretnina; poruka samo za novi tekst koji spominje naše područje | jednom dnevno |

Popis svih praćenih stranica s poveznicama na iste pretrage (filtri cijene i površine
iz kriterija), za ručnu provjeru propuštenih oglasa: `python tools/stranice.py stranice.html`.

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

burza.com.hr (6. 10.): regionalni oglasnik Kvarnera i Istre, oko 100 kuća i zemljišta s
našeg područja. Mjesto i datum zadnje izmjene su na stranici oglasa, površina samo u
naslovu ili opisu (kod kuća se površina uz koju piše okućnica/zemljište/terasa ne
računa kao stambena). Regija obuhvaća i Istru i Liku, a na stranici oglasa piše samo
naselje: oglas iz naselja koje nije u PGŽ-u se odbija (i kad naslov spominje neko naše
mjesto, npr. „Barić Draga” kod Karlobaga). Prvo pokretanje (6. 10.) zabilježilo je 128
oglasa bez poruke; dva koja prolaze već imamo s nekretnine.hr i index.hr.

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
- Stanje (viđeni oglasi) je u `state.db` na grani `state`; oštećena baza se ne sprema.
  Dnevna kopija (zadnjih 7 dana, i Redmijeva baza) je na grani `state-kopija`.
- Testovi: `python -m pytest`.
- Tajne (GitHub Secrets): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SMTP_USER`,
  `SMTP_PASSWORD`, `EMAIL_TO`.

## PPV jednom godišnje

Plan približnih vrijednosti (ISPU) objavljuje se za stanje 1.1. Prvog dana nove godine
stiže podsjetnik (Telegram i mail), a kad ISPU objavi novi PPV još jedan. Tada na
GitHubu pokreni tijek rada **PPV – godišnje osvježavanje** (Actions → Run workflow):
preuzme vrijednosti po naseljima, sažme ih u `data/ppv_naselja.json` i spremi. Poruke
same preuzmu novu godinu; PPV na točnoj lokaciji (ISPU) uvijek je najnoviji.

## Automatsko pokretanje (cron-job.org)

GitHub raspored za ovaj repozitorij pokreće workflow tek povremeno (nekoliko puta
dnevno, u slučajno vrijeme), pa ga pokreće besplatni servis cron-job.org, svakih 20
minuta od 7 do 23 h, preko GitHub API-ja. GitHubov raspored ostaje kao rezerva: radi
samo kad zadnje pokretanje kasni više od 30 minuta (inače bi se mogao poklopiti s
Redmijem).

- Adresa: `https://api.github.com/repos/B0rn4/scraper/actions/workflows/scraper.yml/dispatches`
- Metoda: `POST`
- Zaglavlja: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
  `X-GitHub-Api-Version: 2022-11-28`
- Tijelo: `{"ref":"claude/real-estate-scraper-primorska-jrlscq","inputs":{"naredba":"raspored"}}`
- Tjedni izvještaj šalje prvo redovno pokretanje u ponedjeljak (od 7. 10.); poseban poziv
  s `"naredba":"tjedni"` više nije potreban (ako postoji, ne šalje izvještaj drugi put).
- Token: GitHub fine-grained token samo za ovaj repozitorij, dozvola **Actions: Read and write**.

`raspored` poštuje radno vrijeme 7–23 h, a ručni `run` radi odmah.
