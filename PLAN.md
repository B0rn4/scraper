# Scraper nekretnina – obala Primorsko-goranske županije i otok Krk

Cilj: za svaki novi oglas za prodaju kuće ili građevinskog zemljišta koji odgovara
kriterijima stiže obavijest na mobitel (Telegram). PC ne mora biti upaljen.

## Kriteriji

| | Kuća | Građevinsko zemljište |
|---|---|---|
| Cijena | ≤ 400.000 € | ≤ 300.000 € |
| Površina | ≥ 70 m² stambene površine | ≥ 300 m² |
| Uključeno | samostojeće kuće, kuće za obnovu, starine, kamene kuće, vikendice | građevinsko; „djelomično građevinsko” s oznakom ⚠ |
| Isključeno | stanovi, apartmani, dvojne kuće, kuće u nizu, etaže, dijelovi kuće | poljoprivredno, šumsko |

- **Vrsta kuće:** gdje portal ima polje „vrsta kuće”, koristi se ono. Inače se koriste
  ključne riječi, oprezno: „kuća s dvije etaže” je cijela kuća, a „prodaje se etaža kuće” nije.
  Nesigurni slučajevi idu s oznakom ⚠.
- **Lokacija:** samo ovi gradovi i općine, plus tablica koja svakom naselju pridružuje
  općinu ili grad (prema službenom popisu naselja). Portali često navode samo naselje
  (Ičići, Selce, Njivice, Stara Baška…). Usporedba je točna, a ne po dijelu riječi.
  - Općine: Baška, Dobrinj, Kostrena, Lovran, Malinska-Dubašnica, Omišalj, Punat,
    Vrbnik; iz općine Matulji samo mjesto Matulji (od 5. 10.)
  - Gradovi: Crikvenica, Kraljevica, Krk, Opatija, Rijeka
  - Isključeni: Bakar; od 5. 10. i Mošćenička Draga i Novi Vinodolski.
  - Odluka po naselju (prolaz / upozorenje / odbijen) je u
    `data/naselja_udaljenosti.csv` (korisnik, 5. 10.).
- **Nedostaje cijena ili površina** („cijena na upit”): oglas se šalje s oznakom ⚠.
- **Snižena cijena:** pamte se i oglasi izvan filtera. Kad cijena padne ispod granice,
  ili kad već poslani oglas pojeftini, stiže obavijest „📉 snižena cijena”.
- **Isti oglas na više portala:** jedna obavijest s napomenom „također na: …” (faza 5).

## Izvori

| Izvor | Način | Napomena (rezultat faze 0) |
|---|---|---|
| njuskalo.hr | s Redmija (faza 2); do tada i kao rezerva spremljene pretrage u aplikaciji | iz oblaka blokirano (ShieldSquare captcha); prolaz s hrvatske IP adrese treba provjeriti |
| nekretnine.hr | scraper (strukturirani JSON) | ista grupa kao Crozilla i Indomio, isti oglasi (korisnik provjerio); **zamjenjuje ih** |
| realitica.com | s Redmija radi bez preglednika; **predlaže se izostaviti** | iz oblaka blokirano (403). Proba 5. 10.: 50 najnovijih oglasa u PGŽ (kuće i građevinska zemljišta) sve su agencije, 49 ih je već na index.hr/nekretnine.hr/oglasnik.hr |
| oglasnik.hr | scraper | radi iz oblaka; popis oglasa učitava JavaScript |
| index.hr/oglasi | scraper (njihov interni API) | radi iz oblaka; React aplikacija |
| gohome.hr | izostavljen | tražilica; mjerenje 4. 10.: Njuškalo kasni 0–3 dana, index.hr i oglasnik.hr ne prati, ~95 % oglasa agencija već je na našim portalima |
| vender.hr | scraper (WordPress API) | radi iz oblaka |
| oglasi.hr, nekretnine24.hr | scraper | rade iz oblaka |
| trazimstan.hr | scraper (preglednik) | radi iz oblaka; aplikacija koja oglase učitava JavaScriptom |
| FINA Očevidnik | dnevni CSV izvoz (svi predmeti, ~11.000 redaka) | **samo građevinska zemljišta**; lokacija iz slobodnog opisa (vidi niže) |
| Stranice 15 općina i gradova | RSS, jednom dnevno, ključne riječi | 12 od 15 ima RSS; Dobrinj („Javni pozivi i natječaji”), Punat (Novosti → Natječaj) i Krk („Natječaji”) čitaju se izravno s tih odjeljaka |
| PGŽ, Ministarstvo državne imovine, CERP | jednom dnevno, ključne riječi | rade iz oblaka |
| Novi list (mali oglasi) | (6. 10.) nema na internetu | tiskana Butiga (mali oglasi Novog lista i Glasa Istre) ugašena 1. 6. 2026.; najavljen novi digitalni oglasnik Butiga.hr – mail kad se stranica promijeni (`data/banke.yaml`). Mali oglasi u dnevnom izdanju predaju se preko oglasni.glasistre.hr, na internetu se ne objavljuju |
| burza.com.hr | (6. 10.) scraper (`scraper/sources/burza.py`) | regionalni oglasnik (Kvarner i Istra): ~100 kuća i zemljišta s filtrima naših mjesta, agencije i privatni; površina samo u naslovu ili opisu, filtar „otok Krk” spaja cijeli otok. Od oglasa koji prolaze kriterije 4 već imamo, ~10 nismo mogli usporediti (bez površine). Početno: filtri naših mjesta + prve dvije stranice regije, svaki oglas otvoren, bez poruke (128 oglasa); redovno: prve dvije stranice regije, novi oglasi otvoreni (do 10 po pokretanju). Naselje izvan PGŽ-a (Istra, Lika) → odbijen |
| Lokalne agencije | faza 4 | 10–15 najaktivnijih, izdvojenih iz podataka s portala |
| Banke i leasing kuće | (6. 10.) praćenje stranica (`scraper/watch.py`, `data/banke.yaml`) | na našem području trenutno ništa (Zaba, OTP, HBOR, HPB, Croatia banka, PBZ nekretnine); leasing kuće (Raiffeisen, OTP, PBZ, UniCredit, Erste) nude samo vozila i opremu; Addiko → Njuškalo; EOS Matrix (stranica za BiH), B2 Kapital i APS bez vlastite ponude; prisilne prodaje → FINA e-dražbe. Poruka 🏦 samo za novi tekst koji spominje naše područje |
| Facebook Marketplace i grupe | ručno | ugrađene FB obavijesti („Sve objave” u grupama); bez automatizacije |

### FINA: prepoznavanje lokacije

Analiza CSV-a (`probe/results/fina/analysis.json`): opis je slobodan tekst (medijan 225 znakova),
87 % opisa navodi katastarsku općinu („k.o. …”), a 95 % površinu (m², čhv, ha).

- **Katastarske općine nisu isto što i općine.** Rijeka se u opisima javlja kao k.o. Sušak, Kozala,
  Srdoči, Zamet, Drenova ili Trsat; Opatija kao Ičići, Volosko ili Veprinac; Punat kao Stara Baška;
  Omišalj kao Omišalj-Njivice; Novi Vinodolski kao Ledenice. Zato se koristi službena tablica svih
  katastarskih općina i naselja u 15 jedinica (DGU, DZS).
- **Padeži:** za svaki naziv generiraju se svi oblici, uključujući nepostojano a (Punat → Puntu,
  Omišalj → Omišlju, Bakar → Bakru) i promjenu k → c (Rijeka → Rijeci). Crtice, razmaci i
  dijakritici se normaliziraju („Kostrena-Lucija” = „Kostrena Lucija”).
- **Samo osnova riječi nije dovoljna.** U stvarnim podacima osnova riječi pogrešno hvata: Baška Voda,
  Mošćenica kod Petrinje, Vrbnik kod Knina, rijeku Krku, prezime Bakarić, riječ „Riječ”. Zato se
  koriste točni oblici i pravila isključenja, a nejasni slučajevi idu s ⚠.
- **Sud nije pouzdan filter.** Sudovi u regiji: Općinski sud u Rijeci (i stalne službe u Opatiji,
  Crikvenici, Rabu, Malom Lošinju i Delnicama), Općinski sud u Crikvenici (i stalne službe u Krku i
  Rabu) i Trgovački sud u Rijeci. U stečaju je nadležan sud prema sjedištu tvrtke, pa se Crikvenica
  spominje u 23 predmeta pred sudovima izvan regije. Pretražuju se svi predmeti u Hrvatskoj, a sud
  služi samo kao pomoćni podatak.
- **Obujam:** od oko 1.600 aktivnih predmeta nekretnina u Hrvatskoj, pred sudovima u regiji je 103, a
  od toga samo 6 spominje građevinsko zemljište (cijela regija, uključujući Rab, Lošinj i Gorski
  kotar). Kriterij je zato širok: bolje nekoliko ⚠ previše nego propušten predmet.

## Izvršavanje i obavijesti

- **GitHub Actions** (javni repozitorij, bez ograničenja minuta), **svakih 20 minuta od 7 do 23 h**
  po hrvatskom vremenu; noću ne radi, pa oglasi objavljeni noću stižu prvim pokretanjem u 7 h.
  GitHub raspored radi po UTC-u, pa se workflow pokreće u širem rasponu, a skripta provjerava
  zagrebačko vrijeme (ljetno i zimsko računanje). GitHub pokretanja znaju kasniti 5–15 minuta.
- FINA, općine i natječaji provjeravaju se jednom dnevno, ujutro.
- Stanje (baza viđenih oglasa) čuva se na zasebnoj grani bez povijesti, da repozitorij ne raste.
- **Redmi Note 9S (Termux), hibridno:** na Redmiju radi samo ono što je blokirano iz oblaka
  (Njuškalo, Realitica), a sve ostalo ostaje na GitHubu. Redmi kod preuzima s GitHuba prije svakog
  pokretanja, pa se izmjene ne rade na mobitelu. GitHub nadzire Redmi: ako se ne javi 2 sata,
  stiže mail.
- **Telegram bot** šalje obavijest za svaki oglas: fotografija, vrsta, cijena, m², €/m²,
  lokacija, izvor, oznake (⚠, 📉, „za obnovu”) i gumb za otvaranje oglasa.
- **E-mail** šalje tjedni izvještaj (broj oglasa po izvoru, „za dlaku promašeni”)
  i prijavu grešaka.
- **Nadzor:** ako izvor tri puta zaredom vrati grešku ili 0 oglasa, šalje se poruka
  „⚠ izvor X ne radi”.
- Pristojan ritam: jedan zahtjev svakih nekoliko sekundi, samo najnoviji oglasi.
- Sve postavke (cijene, m², općine, izvori) su u jednoj konfiguracijskoj datoteci.
- Baza viđenih oglasa (SQLite) čuva se u repozitoriju.

## Provjera točnosti: pregledni izvještaj

Cilj je vidjeti stotine oglasa i provjeriti što je krivo propušteno ili krivo odbijeno,
bez stotina poruka.

- **Način rada „pregled”** ne šalje pojedinačne obavijesti. Izrađuje **jednu HTML
  datoteku** sa svim prikupljenim oglasima i šalje je kao jednu poruku u Telegramu
  (i kao privitak maila).
- Za svaki oglas prikazuje: izvor, vrstu, cijenu, m², lokaciju kako piše na portalu i
  prepoznatu općinu, odluku ✅/⚠/❌ s **razlogom** (npr. „cijena 450.000 € > 400.000 €”,
  „Bakar – nije na popisu”, „dvojna kuća”, „nepoznata lokacija: …”), link i fotografiju.
- U datoteci se može filtrirati po odluci, razlogu i izvoru. Uz svaki oglas je kvačica
  „pogrešno”, a gumb „Kopiraj označene” kopira popis koji se zalijepi u razgovor s Claudeom.
- Na portalima se pretražuje šire od kriterija: grubi filter po području i kategoriji,
  cijena s rezervom. Točne kriterije primjenjuje naš filter, pa svaki odbijeni oglas ima
  vidljiv razlog.
- **Ono što uopće nije prikupljeno:** izvještaj po izvoru prikazuje broj prikupljenih
  oglasa i link na istu pretragu na portalu. Usporedbom brojki vidi se rupa.
- Svaka prijavljena greška postaje automatski test (spremljeni primjer stranice), da se
  ista greška ne vrati.
- Isti izvještaj služi kao **početni zbirni popis** svih trenutno aktivnih oglasa koji
  odgovaraju kriterijima. Nakon njega stižu samo novi oglasi.

## Faze

0. **Test izvedivosti** (gotovo): rezultati su u `probe/results/`. GitHub poslužitelji
   izlaze s američkih IP adresa; blokirani su Njuškalo, Crozilla, Indomio i Realitica.
1. **(gotovo 4. 10.)** Jezgra (konfiguracija, filter, lokacije, baza), Telegram, e-mail,
   pregledni izvještaj, GitHub Actions, FINA, nekretnine.hr, oglasnik.hr, index.hr/oglasi.
   Kod je u `scraper/`, upute u README.md i UPUTE.md. Početni popis poslan 4. 10. 2026.
   (15.894 oglasa). Isti oglas na više portala: riješeno u 3.1. Pokretanje svakih 20
   minuta: cron-job.org (GitHubov raspored je samo rezerva).
2. **2a (gotovo 4. 10. 2026.)** Ostali portali s GitHuba: vender.hr (WordPress API).
   Izostavljeni: nekretnine24.hr (0 oglasa za područje), oglasi.hr (1 oglas),
   trazimstan.hr (većinom najam, robots.txt zabranjuje /api/), gohome.hr (vidi tablicu
   izvora; mjerni alati za otkrivanje maknuti 6. 10., ostaju u povijesti gita).
   **2b (gotovo 5. 10.; novi izgled Njuškala 8. 10.)** Redmi Note 9S, samo za Njuškalo (Realitica izostavljena: 49 od 50
   najnovijih oglasa već je na našim portalima). Ubuntu unutar Termuxa (proot-distro).
   Proba 5. 10.: bez preglednika Njuškalo nakon nekoliko zahtjeva vraća ShieldSquare
   captchu; Chromium (Playwright) s trajnim profilom prolazi. Na vrhu „najnovijih” su
   većinom stari oglasi koje agencije ponovno objave (stari broj oglasa): obavijest
   stiže samo za novi broj oglasa i za sniženje; početnog popisa za Njuškalo nema.
   Upute u REDMI.md.
3. **Pametnije filtriranje** (dogovoreno 5. 10. 2026., ovim redom):
   1. **(gotovo 5. 10.)** Već viđeni oglasi: isti oglas na drugom portalu ili ponovno
      objavljen ne stiže ponovno, osim ako je cijena niža (`scraper/dedupe.py`). Na
      bazi 5. 10.: od 3.555 oglasa koji odgovaraju kriterijima 1.289 (36 %) bi bili
      „već viđeni”. Pravilo je oprezno: različita naselja u naslovu → nije isti; okrugli
      brojevi (npr. 299.000 €, 100 m²) traže zajedničko naselje ili riječi naslova.
      GitHub objavljuje sažetak viđenih (`seen.json.gz` na grani state) za Redmi, a
      GitHub čita bazu s Redmija.
   2. **(gotovo 5. 10.)** Tablica naselja `data/naselja_udaljenosti.csv` – zračna
      udaljenost od mora (OSM obala), procjena vožnje (OSRM; nepouzdana jer izbjegava
      neasfaltirane/privatne puteve, npr. Brzac 11 min umjesto 4) i **odluka korisnika**
      za svako naselje: Prolaz, Upozorenje (razlog iz stupaca daleko_od_mora /
      daleko_od_rijeke), Upozorenje da je Rijeka, Odbijen. Oglas koji navodi samo
      grad/općinu prolazi; napomenu dobije samo ako je imaju sva prihvaćena naselja
      (Rijeka – „grad Rijeka”; Krk, Punat, Vrbnik – „daleko od Rijeke”). Spominje li
      oglas i prihvaćeno i odbijeno naselje, stiže s ⚠. Drugi nazivi s karte
      (Poljice = Poljica) u `drugi_nazivi_naselja`. Lipovica, Plahuti, Punta Kolova,
      Vrutki, Zora, Kosićevo i Tošina nisu službena naselja nego dijelovi Opatije iz
      popisa lokacija index.hr; prepoznaju se jer ih oglašivači biraju.
      Lokacija oglasa: koordinate (nekretnine.hr, vender.hr, Njuškalo – često
      približne), inače središte naselja; tekst („prvi red”, „200 m od mora”).
      Rijeka ravnopravna s ostalima. Izvan naselja / manje mjesto: samo oznaka.
   3. **(gotovo 5. 10.)** `scraper/risks.py`. Opis imaju nekretnine.hr, oglasnik.hr,
      vender.hr i novi oglasi s Njuškala; za index.hr se novi oglasi koji mogu proći
      otvaraju (api/aditem/single-ad, najviše 10 po pokretanju): opis, vrsta kuće
      (dvojna/u nizu), vrsta zemljišta, okućnica, godine izgradnje i obnove, parking,
      vlasnički list.
      Na 268 stvarnih opisa iz testnih primjera nije bilo lažnih upozorenja.
      Opasni izrazi (suvlasništvo, nasljednici, ostavina, bez papira, legalizacija,
      pravo stanovanja, plodouživanje, poljoprivredno, vanknjižno…): **odbija se samo
      nedvosmisleno** (npr. „prodaje se suvlasnički dio”), inače ⚠ s citiranom
      rečenicom. Niječni izrazi („bez tereta”, „legalizirano”, „1/1”) se izuzimaju.
      Dobre ponude se ne smiju izgubiti.
   4. **(gotovo 5. 10.)** Cijena: ostvarene cijene (ISPU, Plan približnih vrijednosti) važnije su od
      traženih; medijan traženih cijena iz naše baze po naselju samo kad ima dovoljno
      oglasa, inače po općini, s napomenom.
      - **(gotovo 5. 10.)** Medijan traženih €/m² (`scraper/prices.py`): svi viđeni
        oglasi iste vrste u zadnjih godinu dana (i skuplji od granice), isti oglas na
        više portala jednom, zemljišta samo građevinska; naselje ako ima ≥ 8 oglasa,
        inače grad/općina. U poruci: 💰 ≥ 15 % ispod, 💸 ≥ 15 % iznad, 📊 oko medijana;
        ≥ 45 % ispod „neobično jeftino, provjeri zašto”. GitHub sprema `cijene.json`
        na granu state, Redmi ga preuzima.
      - **(gotovo 5. 10.)** ISPU, Plan približnih vrijednosti 1.1.2026.: postoji za
        zemljišta, stanove/apartmane i poslovne prostore – **ne za kuće**. Vrijednost
        za točku daje `api/v1/gis/identify` (bez prijave). Tablica
        `data/ppv_naselja.json` (191 naselje; 5 točaka oko središta naselja jer
        središte zna pasti u šumu ili hotel; izrada: tijek rada „PPV – godišnje
        osvježavanje” na GitHubu, `tools/ppv_preuzmi.py` + `tools/build_ppv.py`). U poruci: zemljište prema rasponu građevinskog
        zemljišta stambene/mješovite namjene (ispod donje granice za 45 %+ „neobično
        jeftino”); (6. 10.) za kuće se ne prikazuje (vrijednost stanova je zavaravala),
        a u tekstu nema godine („🏛 PPV (Njivice): …”). Bez prepoznatog naselja: raspon
        svih naselja grada/općine. Poljoprivredna zemljišta se ne uspoređuju.
        Osvježavanje jednom godišnje: 1. 1. stiže podsjetnik (Telegram i mail), a kad
        ISPU objavi novi PPV (dnevna provjera kataloga) još jedan.
      - **(gotovo 5. 10.)** Građevinsko područje i PPV na samoj lokaciji, za zemljišta
        koja stižu (`scraper/ispu.py`): katastarska čestica iz opisa (k.č. … k.o. …;
        matični broj k.o. iz ISPU-a, čestica iz javnog servisa DGU-a INSPIRE CP WFS)
        ili točna oznaka na karti (nekretnine.hr „marker”, vender.hr, Njuškalo bez
        „približne lokacije”, index.hr s točnom lokacijom). ISPU sloj „Građevinska
        područja (rujan 2024.)”: u GP naselja (izgrađeni/neizgrađeni dio), GP izvan
        naselja (⚠) ili izvan GP-a (⚠). Bez točne lokacije: „nije provjereno”.
        **(8. 10.)** Zemljište s približnom oznakom (krug na karti portala: nekretnine.hr
        250 m iz koda karte, Njuškalo 500 m iz svakog oglasa): točan udio kruga u GP-u
        naselja i izvan naselja, iz obrisa slojeva (GeoServer Ministarstva kroz ISPU, KML),
        i naselje iz bloka PPV-a u središtu; samo postoci, bez ⚠ (odluka korisnika).
        index.hr za „nepreciznu” lokaciju ne daje lokaciju nekretnine – tamo se ne računa
        (uzorak 9. 10., 79 oglasa: 41 točno na referentnoj točki naselja iz API-ja,
        settlementLatitude/Longitude; ostali uglavnom 50–400 m od nje, često ista točka na više
        oglasa iste agencije – Krk 5×, Kostrena 4×, Vrbnik 4×);
        oglasnik.hr, realestatecroatia i burza nemaju lokaciju čestice.
      - Cijena se ne koristi za odbijanje (osim granice iz kriterija) – samo oznake.
      - **Kuće prema stanovima (6. 10.):** fiksnog omjera nema. Tražene cijene na
        index.hr u istom gradu (13 gradova s ≥ 8 oglasa svake vrste): kuća / stan po m²
        medijan 0,66, prosjek 0,73, standardna devijacija 0,19, raspon 0,52 (Opatija)
        – 1,20 (Malinska). Ostvarene cijene (Ministarstvo, HNB) za ovo ne služe: za kuće
        Porezna uprava ima samo ukupnu površinu (zgrada + zemljište), pa je €/m² kuća
        nerealno nizak (medijan RH 156 €/m², „veličina” kuće 513 m²). Korekcija se ne
        stavlja u poruku (raspršenost prevelika); pravilo za glavu: PPV stanova × ⅔,
        ± trećina.
   5. **(gotovo 5. 10.)** Parking (`scraper/parking.py`): kuća mora imati parkirno
      mjesto ili dovoljno okućnice. Izvori: polja portala (index.hr, Njuškalo,
      nekretnine.hr), rečenice iz opisa, okućnica (≥ 100 m², `okucnica_za_parking_m2`).
      „Nema parkinga” / samo javni parking → ⚠ s citatom; nije naveden → ⚠ (osim kad
      je okućnica dovoljna ili je opis skraćen). nekretnine.hr: novi oglasi koji mogu
      proći otvaraju se (puni opis, značajke, godina izgradnje), najviše 10 po pokretanju.
   6. **(gotovo 5. 10.)** Sažeti redak odmah ispod cijene: „📊 more 0,6 km · Rijeka 40
      min · cijena −20 % od prosjeka · PPV u rasponu · ⚠ 2”. More je zračna udaljenost,
      Rijeka vožnja (OSRM, bez prometa) iz `data/naselja_udaljenosti.csv`; bez naselja:
      istoimeno mjesto (~Krk). (6. 10.) Vrijeme do Zagreba maknuto iz poruke – popis
      naselja već sadrži samo prihvatljivo udaljena mjesta.
   - Čitanje opisa jezičnim modelom: zasad ne (korisnik će javiti).
   - **Završni pregled (dogovor 5. 10., dopuna 6. 10.):** kad sve faze budu gotove,
     korisnik još jednom dobiva sve aktivne oglase koji odgovaraju (kao početni popis),
     uključujući Njuškalo, te sve aktivne natječaje, FINA dražbe i ponude banaka s našeg
     područja – sve što se pratilo. Njuškalo za taj pregled čitati s filtrima u adresi
     (područje, cijena, površina) i raspoređeno kroz više pokretanja.
     **Odluka 7. 10.:** s tim pregledom prestaje pravilo „stari oglas” (Njuškalo oglas s
     brojem daleko ispod najnovijih bilježi se tiho). Nakon pregleda nepoznat oglas koji
     odgovara stiže i kad mu je broj star: ponovno aktiviran, ispravljena kategorija ili
     lokacija, pripremljen davno a objavljen sad, ili ga je pregled propustio. Do pregleda
     pravilo ostaje (Redmi zna samo dio Njuškala – inače desetci starih oglasa dnevno).
     Parcelaciju u postojećim oglasima korisnik provjerava sam (pretraga na portalima).
     **Odluka 13. 10.:** uz oglas iz početnog popisa (ili datoteke „N novih oglasa”) pregled
     prikazuje napomene s drugih portala – što je isti oglas drugdje pokazao, i da prema tom
     portalu ne odgovara (npr. dvojna kuća, isključeno naselje): `State.notes()` iz obje baze
     (GitHub i Redmi), `report.entry(x, d, notes)` (redak ➕ s poveznicom na kopiju). Oglas s
     napomenom „ne odgovara” ostaje u pregledu, s ⚠ – ne izostavlja se. Pregled uz to može
     isti oglas povezati i među svježe pročitanima (napomene čuvaju i ono čega više nema).
     **Odluka 19. 10.** (zamjenjuje „ne izostavlja se”; pregled je novi početni popis nakon
     resetiranja oglasa): (1) svaki oglas ocjenjuje se po današnjim pravilima – početni popis
     4. 10. ocijenjen je pravilima prvog dana, a od 3.605 oglasa iz njega 1.655 je kasnije
     preocijenjeno kao „ne odgovara” (popis naselja, gradovi/općine, bazen, opis); stari oglas
     koji se otada nije ponovno pročitao ima staru ocjenu (npr. realestatecroatia „Poljoprivredno
     zemljište, Čižići”, ocijenjen 6. 10.); (2) postojeći podaci se koriste: oglas istog broja i
     cijene ne otvara se ponovno (spremljeni zaključci: vrsta, upozorenja iz opisa, napomene),
     otvaraju se samo novi i promijenjeni (opis se ne čuva – kad se pravila za opis promijene,
     treba ga ponovno otvoriti); (3) kopije istog oglasa sa svih portala (i iz početnih čitanja,
     i stari osvježeni) spajaju se u jedan redak s poveznicama na sve portale; (4) korisnik:
     oglas za koji neki portal pokaže da ne odgovara ne ulazi među one koji prolaze. Kako
     (odluka korisnika 19. 10.): izostavlja se kad je razlog iz polja portala ili naslova (vrsta kuće,
     vrsta zemljišta, naselje) i veza je čvrsta (cijena i površina iste, ne „na upit”); slabija
     veza („na upit”: samo površina i mjesto) ili portali koji se ne slažu (samostojeća /
     dvojna) – ostaje s ⚠ i razlogom; izostavljeni su u sklopljenom odjeljku na dnu (razlog i
     poveznice), da se ništa ne izgubi bez traga. Na podacima 19. 10.: od 4.446 oglasa koji
     odgovaraju (obje baze, bez 👎) 761 ima kopiju koja ne odgovara – 343 dvojna / u nizu, 208
     isključeno naselje, 178 nije građevinsko, 26 bazen, 6 ruševina; u 538 razlog je iz polja
     portala. Pregledani primjeri: ista cijena i površina, često isti naslov iste agencije.
     **Nakon resetiranja** (odluka korisnika 19. 10.): novo s drugog portala za oglas bez vlastite
     poruke (novi početni popis, datoteka „N novih oglasa”) stiže kao poruka s poveznicom na
     stariji oglas (gumb „Stariji oglas”, kao kod „📉 Već viđen”), a ne kao napomena. Do
     resetiranja ostaju napomene: sada bi to bilo 6–16 poruka dnevno, gotovo sve ⚠ „ne odgovara”
     za oglase koje završni pregled ionako izostavlja. Pravilo „stari oglas” prestaje s pregledom
     (odluka 7. 10.), pa tiho zabilježenih starih oglasa nakon resetiranja više nema.
4. **(gotovo 5. 10.)** Natječaji za prodaju nekretnina (`scraper/tenders.py`, popis
   stranica u `data/natjecaji.yaml`), jednom dnevno (prvo pokretanje od 7 h):
   - 13 gradova/općina + Matulji: WordPress tražilica (wp-json) ili RSS tražilica
     (Baška); Dobrinj, Omišalj, Punat i Krk sa stranice natječaja (Krk i RSS).
   - PGŽ, CERP (javni pozivi – nekretnine) i Državne nekretnine d.o.o. (prodaja):
     zadržava se samo objava koja spominje naše područje.
   - Samo prodaja nekretnina (zemljište, kuća, nekretnina, čestica); zakup, vozila,
     stanovi, poslovni prostori, zapošljavanje, savjetovanja, odluke o odabiru i
     neaktivni natječaji se preskaču.
   - Iz teksta ili priloženog PDF-a: rok, početna cijena, površine, čestice. Za
     čestice: građevinsko područje i PPV (ISPU, DGU). Suvlasnički dio → ⚠.
   - (6. 10.) Poruka kao za oglase: cijena i površina vezane uz svaku česticu (kad
     ih tekst navodi uz nju), €/m², PPV na lokaciji, medijan traženih, sažeti redak
     i odluke iz popisa naselja. Nejasno (više cijena uz istu česticu) → samo popis
     cijena i površina, bez €/m².
   - (6. 10., prema stvarnim tekstovima) z.k.č. se ne traži u katastru (na Krku broj
     nije isti kao katastarski); čestice „kao cjelina” imaju jednu cijenu; rok „N dana
     od objave” → ≈ datum. Bez poruke: samo stanovi/poslovni prostori; sve čestice
     ispod kriterija (npr. trake od 10–60 m² za okućnicu) ili preskupe; isključeno
     naselje napisano u tekstu (prema k.o. samo ⚠).
   - Rijeka: zemljišta na stranici „Raspolaganje zemljištem – prodaja, pravo građenja,
     služnosti i zakup”, stanovi i poslovni prostori na zasebnoj stranici; zasebne
     stranice za kuće nema.
   - Prvi dan (5. 10.) poslani natječaji kojima rok nije istekao; poslije svaka nova
     objava. Stranica koja 3 dana zaredom ne radi → upozorenje.
   - Ministarstvo (mpgi.gov.hr) nema zaseban popis prodaje; državnu imovinu prodaju
     CERP i Državne nekretnine d.o.o.
5. **(gotovo 6. 10.) Agencije.**
   - Najaktivnije na našem području (nekretnine.hr, oglasi koji prolaze kriterije):
     Dogma 195, RE/MAX Centar 135, DUX 114, Euro Immobilien 88, Miro 60, Pontera 52,
     Manor 52, Premium SM 46, Vero Krk 44, Smart Invest 42.
   - Njihove stranice: 9 od 11 iza Cloudflareove zaštite (iz oblaka „Just a moment…”).
     Većina koristi sustav Agentor, koji oglase objavljuje i na realestatecroatia.com
     (Labin d.o.o.; radi iz oblaka) – zato je izvor taj portal
     (`scraper/sources/realestatecroatia.py`): popis cijele PGŽ (regija=8), najnoviji
     prvi (broj oglasa), do granice cijene; površina sa stranice oglasa.
   - Mjerenje: od oglasa s cijenom koji prolaze kriterije 217 već imamo, 13 nekretnina
     ne (~5 %, od toga nekoliko poljoprivrednih ili krivo smještenih). Najnoviji oglasi
     se na našim portalima pojavljuju u isto vrijeme – portal nije brži.
   - Prvo pokretanje se bilježi bez poruke (ulazi u završni pregled); „cijena na upit”
     (luksuzne vile) se preskače. Prvo čitanje nije otvaralo oglase (4.500 stranica ≈
     2,5 h), pa ti oglasi nemaju površinu – za završni pregled otvaraju se oni koji mogu
     proći. (6. 10.) Novi oglasi iznad ograničenja otvaranja (10 po pokretanju) više se ne
     šalju bez površine nego čekaju sljedeće pokretanje; isto za Njuškalo (8). Novi oglasi koji su već poslani s drugog portala ne
     stižu ponovno (već viđeni).
6. **(gotovo 6. 10.) Dodaci za kuće.**
   - Građevinsko područje (ISPU) kao kod zemljišta: po k.č. iz opisa ili točnoj oznaci
     na karti. Izvan građevinskog područja → samo ⚠ (oglas stiže). Kuće rijetko imaju
     točnu lokaciju, pa je redak „nije provjereno” prvi koji otpada kad je poruka preduga.
   - Zaštićeno kulturno dobro / kulturno-povijesna cjelina → ⚠. Izvor: slojevi
     Ministarstva kulture i medija u ISPU-u (Z- i P-lista), u istom upitu kao
     građevinsko područje (mjerenje 6. 10.: 34 upita bez greške, +0,03 s). Pronađene
     cjeline: Krk, Vrbnik, Opatija, Bakar, Omišalj, Baška, Rijeka (Korzo, Trsat).
     Geoportal kulturnih dobara ima i pretragu po čestici/adresi
     (`api/wfs/get-kulturna-dobra-katastarska-cestica/`) – zasad nije potrebna.
     Približna oznaka: samo cjeline i samo kad opis spominje staru jezgru. Uz to
     pravilo za tekst (kulturno dobro, konzervator, zaštićena jezgra). Isto za čestice
     iz natječaja.
7. **Finiširanje (dogovoreno 6. 10.).** Redom:
   1. **(gotovo 6. 10.) Čišćenje i privatnost:** maknuti alati za otkrivanje
      (`tools/discover*.py`, 42 skripte), probni tijekovi rada, opcija „debug” i sirove
      snimke stranica (`probe/results/**/samples`; sažeci ostaju); grana `debug`
      obrisana. Telefonski brojevi u testnim primjerima zamijenjeni nulama. GitHub akcije
      na v6 (Node.js 24). Izrada PPV-a sačuvana kao `tools/ppv_preuzmi.py` i tijek rada
      „PPV – godišnje osvježavanje” (godinu sloja nalazi sam). Napomena: maknute
      datoteke ostaju u povijesti gita (javne stranice portala, bez tajni).
   2. **(gotovo 6. 10.) Moje mišljenje** – odluke korisnika:
      - nadzor cijelog sustava: Redmi provjerava GitHub (`github.json` na grani
        `state`: zadnje pokretanje); poruka ako kasni 2 h (od 9 h) i kad proradi;
      - gumb samo „🔕 Ne zanima me” (bez 👍): oglas i isti oglas na drugim portalima
        više ne javljaju ništa; pritisci se čitaju pri pokretanju na GitHubu
        (getUpdates; isti bot i za Redmijeve poruke), popis ide Redmiju u `github.json`;
      - dnevna kopija stanja (7 dana, grana `state-kopija`); oštećena baza se ne sprema;
      - PPV za kuće maknut; godina se ne piše u poruci; podsjetnik za PPV 1. 1. i kad
        ISPU objavi novi;
      - ne: spremljene pretrage u aplikaciji Njuškalo, starost oglasa, FINA kuće
        (previše mogućih komplikacija).
   3. **(gotovo 6. 10.) Moja provjera grešaka** (kod, baze GitHuba i Redmija, 98
      pokretanja – 4 neuspjela su prekid GitHuba 5. 10.). Popravljeno:
      - isti oglas „cijena na upit” na više portala stizao je više puta (vila Matulji,
        kuća Krk, zemljište Jadranovo);
      - Susak (Mali Lošinj) / Sušak (Rijeka) i Sveti Anton: odlučuje tekst (22 oglasa
        s otoka Suska bila su ⚠);
      - lažno „sniženje” nakon poskupljenja – uspoređuje se s cijenom iz poruke;
      - ujutro i nakon prekida čitalo se premalo stranica (index.hr 2 × 24 uz 44 nova
        oglasa u satu) – sad dok ima novih;
      - novi oglasi iznad ograničenja otvaranja stizali su bez površine (RC, Njuškalo);
      - cijena po m² u prvom retku poruke; PPV podsjetnik bilježi se tek kad je poslan;
      - popis stranica tvrdio je da „cijena na upit” ne stiže;
      - (korisnik uočio) „isti oglas” je spajao različite nekretnine: jedinice istog
        projekta na istom portalu (Barušići 350.000 / 352.000 €) i kuće koje dijele samo
        ime mjesta u naslovu. Sad na istom portalu samo iste brojke (ponovna objava),
        nazivi mjesta nisu zajedničke riječi, naselja u osnovnom obliku.
      „Cijena na upit” (6 od 26 poruka): korisnik želi maknuti samo luksuzne – procjena
      površina × medijan traženih €/m²; odbija se luksuzna (riječi u naslovu + procjena
      × 0,4 iznad granice) i golema kuća (× 0,2); ostale ⚠ s procjenom. Na podacima: od
      628 oglasa na upit u bazi odbačeno 112 (88 luksuznih, 24 goleme kuće), na
      oglasima s cijenom izgubljeno 11 od 1.389 kuća u granici.
   4. **(gotovo 6. 10.) Svježi pregled koda:** nova instanca (podagent) bez znanja o
      razgovoru, samo s kodom i README/PLAN kao opisom; traži greške. Svaki nalaz
      provjeren prije popravka. Našla je 15 grešaka, sve stvarne i sve popravljene (uz
      test za svaku):
      - Redmi i GitHub su kretali u istoj minuti, pa je isti oglas s Njuškala i drugog
        portala stizao dvaput (u bazi 6. 10. u 7 h: 3 od 4 Redmijeve poruke). Redmi
        sad radi 10 minuta kasnije (:10, :30, :50) i stanje s GitHuba preuzima preko
        API-ja (raw adresa vraća do 5 minuta staro stanje);
      - neuspjelo slanje: isti oglas na drugom portalu bio je zabilježen kao „isti kao”
        neposlani, pa nije stigao nijedan;
      - index.hr i Njuškalo: oglas odbijen prema stranici oglasa (dvojna kuća,
        poljoprivredno, suvlasnički dio) sljedeći put je s podacima samo s popisa
        stizao kao „🔄 Sad odgovara”;
      - odgođeni oglasi (Njuškalo, realestatecroatia, burza) gubili su se kad ih novi
        pomaknu s pročitanih stranica – sad se pamte u bazi i otvaraju prvi; stranica
        oglasa koja 3 puta ne odgovori → oglas stiže s podacima s popisa;
      - prelazak na „cijenu na upit” (1 €) javljao se kao sniženje, a zatim skrivao
        prava sniženja;
      - „1 200 m2” čitano kao 200 m², „0,345 ha” kao 345 ha; burza za zemljište sad
        uzima najveću površinu iz opisa;
      - „kuća u idealnom dijelu Malinske” odbijana kao „prodaje se suvlasnički dio”
        (u bazi se nije dogodilo);
      - kratki prekid mreže pri učitavanju stanja na GitHubu: pokretanje bi krenulo od
        praznog stanja i prepisalo pravo (i sedmodnevne kopije) – sad posao staje;
      - vender.hr površina „0.00” → odbijeno umjesto ⚠ „površina nije navedena”;
      - regionalni natječaji (CERP, Državne nekretnine) prolazili su jer tekst spominje
        Rijeku (sjedište) – sad samo s česticom na našem području;
      - neuspjelo slanje zbirne datoteke, početnog popisa ili upozorenja o kvaru
        bilježilo se kao poslano – sad se ponavlja;
      - poništenje „Ne zanima me” nije vrijedilo za iste oglase utišane na Redmiju;
      - natječaji iznad dnevnog ograničenja (15) bili su izgubljeni – sad stižu sutra.

      **Druga runda (6. 10., nova instanca):** 16 nalaza, svi provjereni i popravljeni (uz test):
      - sniženje nakon razdoblja „cijena na upit” (390.000 → na upit → 350.000) nije stizalo;
      - FINA: prodaje preko javnog bilježnika i stečajnog upravitelja (oko 200 u cijeloj
        Hrvatskoj) odbacivane bez gledanja mjesta – sad stižu s ⚠ kad opis navodi naše mjesto;
      - k.o. Sveta Jelena (Crikvenica) prepoznavana kao naselje Sveta Jelena u Mošćeničkoj
        Dragi (odbijeno); iza „k.o.” sad vrijedi tablica katastarskih općina, i za „Sv. Jelena”;
      - natječaj za zemljište s rečenicom „u poslovnim prostorijama Općine” preskakan kao
        „samo stanovi/poslovni prostori”;
      - adresa s razmacima ili slovima č/ć (npr. PDF natječaja) – Telegram odbija gumb, pa
        poruka nikad ne bi stigla; adrese se sad kodiraju;
      - index.hr i oglasnik.hr su poredani po zadnjoj aktivnosti: stranica puna noćnih
        obnova poznatih oglasa zaustavljala je čitanje, a nov oglas je bio na sljedećoj –
        sad se čita dalje dok je stranica novija od prošlog čitanja;
      - Njuškalo: captcha na stranici oglasa prihvaćena kao otvoren oglas – sad čeka;
      - GitHubov raspored (rezerva, radi povremeno u slučajno vrijeme) mogao se poklopiti s
        Redmijem – sad radi samo kad cron-job.org kasni više od 30 minuta;
      - rok natječaja: „najkasnije do” iz rečenice o jamčevini/plaćanju uzimao se kao rok
        ponuda, a približan rok („15 dana od objave”) računao od krivog datuma → natječaj
        preskočen kao istekao; približan rok se više ne smatra isteklim;
      - oštećen redmi.db zaustavljao je cijelo pokretanje na GitHubu – sad upozorenje mailom;
      - banke i regionalni natječaji: „Sveti Ivan Zelina”, „Poljane, Zagreb”, „Bregi,
        Karlovac”, „Martinšćica na Cresu” brojani kao naše područje;
      - natječaj „u 1/1 dijela” (cijelo vlasništvo) dobivao ⚠ „prodaje se dio”;
      - pokretanja bez novog sažetka (tjedni izvještaj, noć) brisala su seen.json.gz,
        cijene.json i github.json s grane state – Redmi bi radio sa starim;
      - neuspjelo upozorenje o promjeni na stranici (Butiga) gubilo je promjenu;
      - slanje fotografije koje istekne (timeout) nije pokušalo poslati poruku bez slike;
      - godišnje osvježavanje PPV-a moglo je spremiti nepotpunu tablicu kad istekne vrijeme.

      **Treća runda (6. 10., nova instanca bez popisa prijašnjih nalaza, po scenarijima):**
      9 nalaza, svi provjereni i popravljeni (uz test):
      - rok natječaja riječima („osam (8) dana”, „petnaest (15) dana”, „15. dana”, „8 radnih
        dana”) nije se čitao, pa je datum objave postajao rok → natječaj preskočen kao istekao;
      - „zaključno s danom 20. listopada” / „do uključivo” nije prepoznato kao točan datum;
      - „negrađevinsko zemljište” prolazilo kao građevinsko (u bazi 4 takva ✅);
      - zemljište po 22–60 €/m² smatrano „cijenom na upit” (i odbijano kao luksuzno) – sad
        10–99 € je cijena po m² (100 € ostaje zamjena za „na upit”: ~100 takvih oglasa u bazi);
      - „cijena na upit” bez upisane cijene (nekretnine.hr, vender) nije se prepoznavala kao
        isti oglas na drugom portalu → dvije poruke;
      - lanac kopija nakon dva neuspjela slanja (C „isti kao” B „isti kao” neposlani A);
      - burza / Njuškalo zemljište: površina iz kratkog isječka prepisivala onu sa stranice
        oglasa (1.200 → 80 m², pa odbijeno i bez sniženja);
      - FINA: nečitljiv CSV (preimenovan stupac, stranica održavanja) bio je „0 oglasa, radi”;
      - „Prodajem kuću, polovica kuće je renovirana” odbijano kao prodaja dijela.
      Uz to: „Ne zanima me” se više ne prenosi na jeftiniju kuću iste površine u istom mjestu
      (može biti druga nekretnina) – takva stiže kao „već viđen … sad jeftiniji”.

      **Četvrta runda (6. 10., nova instanca, od stvarnih podataka u bazi):** 9 nalaza, svi
      provjereni i popravljeni (uz test):
      - odbijeni oglasi zabilježeni „tiho” (tiho početno čitanje, stari Njuškalo oglasi) smatrali
        su se viđenima: kad počnu odgovarati, nije stizalo „🔄 Sad odgovara”, a njihove kopije na
        drugim portalima bile su „već viđene”. Stvaran slučaj: Matulji – strogi centar, kuća
        80 m², 300.000 € (Njuškalo, index.hr, oglasnik) i Matulji, zemljište 717 m², 145.000 €.
        Odbijeni se više ne bilježe tiho; postojeći (oko 4.800) jednokratno oslobođeni;
      - neuspjela obavijest ponavljala se samo ako je portal ponovno prikaže – sad se pamti
        (najviše 2 dana, od pete runde 7) i šalje sljedeći put;
      - moj popravak iz treće runde: „Soline, građevinsko”, „Atraktivan građevinski teren”,
        „Fužine, građevinsko” nisu se prepoznavali kao građevinsko (riječ završava na „ne”/„van”);
      - natječaj: čestica sa „zgradom”, „ruševinom” ili „starinom” mjerena kao zemljište (180 m²
        → premalo); naslovi „… po načelu najpovoljnije ponude” odbacivani kao odluka o odabiru;
      - burza: „Barić Draga” (Karlobag) i „Sveti Ivan, Općina Oprtalj” prolazili kao naše
        mjesto – sad svaki dio naziva mora biti cijeli naš naziv;
      - kuća za 1.200–3.000 € uz 180–400 m² je cijena po m² (prije ukupna – prolazila je);
      - „suvlasnički dio zajedničkog puta/dvorišta/parkirališta” uz kuću više se ne odbija;
      - „500m2” u naslovu (bez razmaka) spajao je dva različita zemljišta kao isti oglas.

      **Peta runda (7. 10., nova instanca, namjerno izazvani kvarovi):** 15 nalaza, svi
      provjereni skriptom i popravljeni (uz test koji na starom kodu pada):
      - jedan neispravan oglas (portal promijeni polje) rušio je cijelo pokretanje, a izvor se
        vodio kao ispravan – sad se taj oglas preskače; kad ne prođe većina, greška izvora;
      - pokretanje prekinuto prije slanja (istek vremena, Android ugasi Termux) gubilo je nove
        oglase – red obavijesti se sprema odmah nakon svakog izvora;
      - dnevna kopija stanja: neuspjelo preuzimanje starih kopija brisalo je svih 7 dana; slanje
        stanja na granu state sad ima 3 pokušaja;
      - mail ne radi → upozorenja idu na Telegram; Telegram ne prima ništa 3 pokretanja
        zaredom → jedan mail (i jedan kad proradi);
      - poruku koju Telegram odbije (400: HTML, adresa gumba) šalje se kao običan tekst;
        „čekaj 900 s” (429) više ne zaustavlja pokretanje;
      - prazna kategorija (zemljišta) na portalu i vender.hr bez ijedne kuće/zemljišta su
        greška izvora, a ne tiha nula;
      - natječaji i banke: stranica zaštite od robota („Just a moment…”) ili održavanja s
        HTTP 200, RSS koji nije RSS i stranica bez poveznica su greška, a ne „ništa novo”;
        greške se broje najviše jednom dnevno; neuspjelo slanje za banke se ponavlja;
      - zaglavljene stranice oglasa: najviše 4 minute otvaranja po izvoru, ostali se odgađaju;
      - Njuškalo: jedan neobično velik broj oglasa činio je sve nove oglase „starima” (tiho);
      - Redmi: skraćen seen.json.gz i vrijeme bez zone u github.json rušili su pokretanje;
        sažetak i github.json pišu se preko privremene datoteke;
      - tjedni izvještaj: neuspio mail bilježio se kao „poslan” – sad se ponavlja (do 2 dana).
      Uz to (stvaran kvar 7. 10.): pritisci „Ne zanima me” nisu stizali. Proba (naredba
      `gumbi`): dok bot bez prekida čeka, pritisak stiže odmah, a nitko drugi bota ne čita
      (nema greške 409); poruka botu čeka 20 minuta, a pritisak koji bot ne preuzme odmah
      izgubi se. Prvo je pokretanje čekalo pritiske do sljedećeg (:00, :20, :40); zatim je
      gumb zamijenjen reakcijom 👎 na poruku: Telegram je čuva (proba: stigla je), pa nema
      čekanja. Reakcija nosi samo broj poruke – pri slanju se pamti koja je poruka koji oglas
      (i na Redmiju). Maknuta 👎 poništava. Pritisci se čitaju bez pomaka (offset).
      **Šesta runda (7. 10., nova instanca, simulacija tri tjedna rada GitHuba i Redmija s
      lažnim satom, tržištem, ispadima i pritiscima gumba):** 7 nalaza, svi popravljeni (uz test):
      - čekanje gumba (dodano isti dan) odgađalo je slanje stanja do :19, pa je Redmi u :10
        radio sa stanjem starim 30 minuta – isti oglas s Njuškala stizao je drugi put (48 parova
        u 21 dan). Popravljeno, a zatim je čekanje i ukinuto (reakcija 👎 umjesto gumba);
      - sniženje već javljenog oglasa koje se ne uspije poslati više se nije ponavljalo;
      - luksuzna vila „na upit” (luksuz samo u opisu) nakon obnove oglasa stizala je kao „sad
        odgovara” (popis nema opis);
      - tjedni izvještaj u 7:15 čekao bi u redu iza pokretanja koje čeka gumbe (GitHub takav
        može otkazati) – sad ga šalje prvo redovno pokretanje u ponedjeljak;
      - druga kuća iste površine utišana kao „već viđena” kad je prva u međuvremenu poskupjela;
      - poništenje „Ne zanima me” nije stizalo do kopije kopije;
      - kopija s već postojećim redom (nakon poništenja) nije se bilježila kao viđena.
      **Parcelacija (7. 10., odluka korisnika):** oglas koji spominje mogućnost parcelacije
      stiže neovisno o cijeni i površini (zemljišta i kuće); mjesto i ostala pravila vrijede.
      Prepoznaje se i „parcelizacija”, glagoli, pogreške, engleski i opisni izrazi; nijekanja
      i sama „parcela” ne. Na stvarnim naslovima: od 141 s „parcel” 4 spominju parcelaciju
      (sva izvan našeg popisa mjesta). Ograničenje: oglasi već zabilježeni prije ove izmjene
      (i početno čitanje nakon reseta) nemaju opis, pa se parcelacija iz opisa vidi samo
      kod novih oglasa.
      **Dodaci 7. 10. (navečer, zahtjevi korisnika):**
      - (gotovo) Usporedba cijene s oglasima po kriterijima: od koliko posto tih oglasa je
        oglas skuplji po m² (točno prebrojano), na cijelom području (razred površine) i u
        naselju (premalo: grad/općina), uz prosjek područja i medijan naselja. Kuće za
        obnovu, starine i nedovršene zasebno (stupac `category` u bazi). Ideje za druge
        kategorije: novogradnja (unutar granice cijene gotovo je nema), kuća u nizu /
        dvojna, velika okućnica – odluka korisnika.
      - (gotovo) Duga poruka: ostatak u drugoj poruci (odgovor na prvu, bez zvuka).
      - (gotovo) Zemljište u kulturno-povijesnoj cjelini: „nova gradnja uz uvjete
        konzervatora (oblik, visina, materijali)”.
      - (gotovo) Uvjeti gradnje (📏) iz UPU-a naselja, inače PPU-a: najmanja građevna
        čestica, kig, kis za samostojeću kuću, prema površini čestice i zoni, s najvećim
        tlocrtom i GBP-om; `data/uvjeti_gradnje.yaml` (14 gradova/općina, oko 60 planova:
        UPU-i naselja Omišlja, Krka, Malinske, Punta, Baške, Vrbnika, Opatije, Lovrana,
        Matulja, Kostrene, Kraljevice, Crikvenice, Rijeke uz GUP po urbanim pravilima). Planovi
        preuzeti na GitHubu (`tools/planovi.py`, tijek rada „Planovi – preuzimanje”, grana
        debug). Zone UPU-a (S1, M12…) ISPU ne daje, pa se za njih piše raspon; izgrađeni /
        neizgrađeni dio dolazi s ISPU-a. Gdje UPU pokriva samo dio naselja (Crikvenica,
        Dramalj, Jadranovo, Selce, Mihotići), „zona” kaže koji dio. Kratka napomena na kraju
        retka gdje je važna (Baška: u staroj jezgri nove kuće nisu dopuštene; Krk: kuća s
        2 stana GBP do 400 m²). Ograničenja: Matulji i Dobrinj PPU 2008., Omišalj PPU 2011.
        (tablica izmjena 2017. u PDF-u); tablice UPU-a Poljane, Pehlin i UPU 3 Punat nisu u
        tekstu odluka. Za natječaje redak još ne postoji.
      - (gotovo) Tjedni izvještaj: nove odluke o prostornim planovima (Službene novine PGŽ-a,
        tekuća i prošla godina; Zavodov registar prostornih planova) – umjesto obnove
        uvjeta gradnje jednom godišnje (`scraper/planwatch.py`). Najviše 3 minute, bez
        ponovnih pokušaja (registar prvi); što ne stigne, piše se u izvještaju i čita se
        sljedeći tjedan. Izvor koji nije pročitan cijeli ne bilježi se kao pročitan.
      - (gotovo) PPV naselja iz svih cjenovnih blokova građevinskog zemljišta stambene i
        mješovite namjene (medijan uz raspon i broj blokova), umjesto pet točaka oko
        središta. ISPU-ov WMS posrednik propušta zahtjeve na GeoServer (LAYERS = sloj iz
        kataloga s layerHash); GetMap u obliku KML (kmattr) vrati sve blokove kvadrata od
        4 km s atributima i obrisima (GetFeatureInfo vraća samo dio). Naselje bez bloka sa
        svojim imenom dobiva blokove oko središta. 176 naselja. Dio godišnjeg osvježavanja.
      - (na redu) Zona zaštite kulturno-povijesne cjeline (A, B, C) u upozorenju, ako je
        negdje dostupna u digitalnom obliku. Provjereno 7. 10. (`tools/ispu_istrazi.py`):
        slojevi kulturnih dobara u ISPU-u imaju samo naziv, vrstu i broj, bez zone; ni
        zone prostornih planova nisu javni slojevi. Zone su u konzervatorskim podlogama i
        kartama UPU-a (PDF). ISPU ima sloj „Cjenovni blokovi”, a blokovi nose ime naselja
        („KRK - GRAĐEVINSKO 1”) – za PPV naselja iz svih blokova dovoljno je gušće
        uzorkovanje točaka oko naselja.
      **Sedma do dvanaesta runda (7.–8. 10., nove instance):** ukupno oko 60 nalaza, svi
      provjereni skriptom i popravljeni uz test. Teme: vrijeme i kalendar (noć, ponoć,
      ljetno vrijeme), Redmi i razmjena stanja s GitHubom, „nijedan oglas koji odgovara ne
      smije se tiho izgubiti” (11A, 12), „ništa ne smije tiho stati, nadzor ne smije lagati”
      (11B: cron-job.org, sat na Redmiju, pokretanja koja ne završavaju, stari kod na
      Redmiju, izvor bez novih oglasa, stranice oglasa, praznine u čitanju Njuškala,
      dnevno dublje čitanje realestatecroatije, prosljeđivanje Redmijevih upozorenja).
      **8. 10.:** Njuškalo je oko 13:30 promijenio izgled popisa (greška izvora javljena
      nakon 3 pokretanja; popravljeno isti dan, stari i novi izgled se čitaju, „Super Vau”
      sa strane); greška „popis bez oglasa” sad nosi naslov stranice, a stranica se sprema
      za slanje (`redmi_probe.py --posalji`). Alat `tools/provjeri_lokaciju.py` (tijek
      rada „Planovi”, naredba `lokacija`) provjerava lokaciju bilo kojeg oglasa.
   5. **(djelomično) Testovi:** automatski 292 (8. 10.); vježbe kvarova (izvor ne radi,
      Telegram ne radi, ISPU ne radi, Redmi ne javlja, prekid usred pokretanja) napravljene
      su u rundama pregleda i simulacijama. Ostaje popis provjera koje može samo
      korisnik: izgled poruka na mobitelu, mail tjednog izvještaja (nije u neželjenoj
      pošti), Redmi nakon nestanka struje / ponovnog pokretanja, obavijesti
      cron-job.org kod neuspjeha, ručna usporedba s portalima (popis praćenih stranica).
   6. **(gotovo 8. 10.) Upute za korisnika** (`UPUTE.md`): značenje svakog retka i oznake u poruci,
      kako promijeniti kriterije i naselja, dodati stranicu natječaja, pauzirati, što
      napraviti kad stigne upozorenje o kvaru.
   7. **Završni pregled** (dogovor 5. 10., dopuna 6. 10.): svi aktivni oglasi koji
      odgovaraju, uključujući cijelo Njuškalo preko Redmija, te natječaji, FINA dražbe,
      banke – sve što se prati; nakon toga redovni rad. Uz pregled ukinuti pravilo „stari
      oglas” (odluka 7. 10., vidi gore).
   8. **Nakon 1–2 tjedna rada:** s korisnikom proći što je stiglo, a bilo je
      nepotrebno, i što je propušteno; podesiti pravila.

## Otvorena pitanja i sitnice (8. 10.)

- **(gotovo 9. 10.) Ruševina se odbija** (oglas index.hr „u ruševnom stanju, s idejnim
  rješenjem za poslovnu zgradu” stigao je kao obična kuća): ruševno stanje, za rušenje, bez
  krova, urušena → odbijen; kad oglas kaže da je za obnovu / adaptaciju / rekonstrukciju →
  kategorija za obnovu (🔨). Odbijeni ne ulaze u medijan.
- **Za pregled nakon 1–2 tjedna:** kuća u Lovranu (325.000 €, 90 m²) stigla je 9. 10. s
  index.hr, a bila je 4. 10. u početnom popisu s nekretnine.hr – okrugli brojevi i samo
  „Lovran” u naslovima, pa je pravilo istog oglasa (namjerno oprezno) nije povezalo.
- **(gotovo 8. 10.) Dopuna s drugog portala (➕):** kad isti oglas stigne s portala koji zna
  više, kratka poruka kao odgovor na prvu – samo gumb za taj oglas i popis novog (odluka
  korisnika 8. 10.: lokacija i građevinsko, podaci koji su nedostajali, nova upozorenja iz
  opisa; kad prema novom portalu ne odgovara – dopuna s ⚠; kuće i zemljišta).
  - Što je poruka rekla pamti se pri slanju (tablica `podaci`, i u sažetku za Redmi); dopune
    se pribrajaju, pa ista novost ne stiže dvaput. Bolja lokacija: broj čestice > točna
    oznaka > krug oko približne > ništa.
  - Samo za oglase koji su stigli kao vlastita poruka (u stvarnim podacima 407 od 424
    odbijenih kopija bile su kopije oglasa iz početnog popisa – bez dopune).
  - **(13. 10., odluka korisnika)** Za oglas iz datoteke s popisom isti retci se ne šalju, nego
    pamte uz njega kao napomena za završni pregled (tablica `napomene`, `State.notes`; na
    Redmiju za kopije s Njuškala). Procjena: 20–25 kopija dnevno, uglavnom ⚠ „ne odgovara”
    (isključeno naselje, dvojna kuća ili kuća u nizu, nije građevinsko). Jednokratno popunjeno
    iz ranijih odbijenih kopija (od početnog popisa; u bazi su samo razlozi, pa samo ⚠): prema
    kopijama stanja 13. 10. oko 58 napomena na GitHubu i 171 na Redmiju. Odbijena kopija s ⚠
    dopunom ili napomenom više nije na popisu „preskočeni kao već viđeni” u tjednom izvještaju.
  - ⚠ „ne odgovara” ne dolazi od granica cijene i površine ni od grada/općine izvan popisa
    (to je promjena pravila, isti grad/općina), ni kad je prvi oglas danas i sam odbijen.
    Procjena iz stvarnih podataka: nekoliko ⚠ dopuna tjedno (npr. „Bregi” umjesto „Matulji”).
  - Poruke poslane prije ove promjene nemaju snimku: za njih se zna samo lokacija portala
    (oglasnik, burza, realestatecroatia: nikad; vender: uvijek točna).
- **Provjera stanja 9. 10. popodne** (zakazana): lažni ili propušteni alarmi novog nadzora,
  dublje čitanje realestatecroatije do kraja popisa, Njuškalo u novom izgledu, približne
  lokacije u porukama; prve dopune (➕) – ponavljaju li nešto iz prve poruke.
- **Podjela `scraper/runner.py`** (2.230 redaka: glavni tok, nadzor, tjedni izvještaj) na
  dvije-tri datoteke – bez promjene ponašanja, na pregledu nakon 1–2 tjedna.
- **(gotovo 8. 10.) 📏 uvjeti gradnje za natječaje:** uz svaku česticu zemljišta iz natječaja
  isti redak kao za oglase (naselje iz teksta oko čestice, površina, izgrađeni / neizgrađeni
  dio s ISPU-a); čestica manja od najmanje → ⚠.
- **(odluka 8. 10.: ne radi se) Kuće s približnom oznakom:** postotak kruga u GP-u računa se
  samo za zemljišta.
- **(odluka 8. 10.: ne radi se) Zona zaštite kulturno-povijesne cjeline (A, B, C):** nije
  dostupna u digitalnom obliku (provjereno 7. 10.); ne traži se dalje.
- **Brisanje starih oglasa iz usporedbe cijena:** novogodišnja poruka podsjeća; korisnik
  će o tome razmisliti kad stigne podsjetnik (oko 2028.).
- **Završni pregled i kraj pravila „stari oglas”** (7.7) i **pregled nakon 1–2 tjedna**
  (7.8) – nakon povratka korisnika. Uvjet korisnika (9. 10.): ono na što je stavio 👎 ne smije
  stići ni nakon resetiranja oglasa – tablica `muted` i retci utišanih oglasa (za prepoznavanje
  kopija na drugim portalima) ostaju, završni pregled ih izostavlja (i njihove kopije). Dva 👎
  od 7. 10. (poruke 81 i 87, prije pamćenja brojeva poruka) nisu primijenjena – pitati korisnika
  za te oglase prije resetiranja.
- **(gotovo 9. 10.) Raspon za malo oglasa:** s 3–7 usporedivih oglasa (naselje, inače
  grad/općina) redak 🏘 kaže raspon i broj umjesto medijana.
- **(gotovo 12. 10.) index.hr: dvojna kuća i poljoprivredno zemljište prolazili su** (korisnik:
  7608900 „Tip kuće: dvojna”, 3802115 „Tip zemljišta: poljoprivredno”). Vrsta se čita dobro, ali
  samo sa stranice oglasa, a popis je nema: oglas iznad ograničenja otvaranja (10 po pokretanju)
  ili sa stranicom koja nije odgovorila stizao je s podacima s popisa, a početni popis (4. 10.)
  nije otvorio nijedan. Sad: index.hr otvara do 25 novih po pokretanju, ostali čekaju sljedeće
  pokretanje (kao Njuškalo, realestatecroatia, burza); isto čekanje i za nekretnine.hr (ondje vrsta
  dolazi s popisa, pun opis sa stranice oglasa). Zapamćeni oglasi s index.hr koji nisu odbijeni
  (~830) jednom se ponovno otvaraju, 30 po pokretanju, i tiho ocjenjuju ispočetka – dvojne i
  poljoprivredna ispadaju iz usporedbe cijena, bez poruka (`reopen_once`; ponavlja se i nakon
  novog početnog popisa, npr. kad se oglasi resetiraju).
- **(gotovo 13. 10.) realestatecroatia: sniženje bez površine** (korisnik: REC 1251625, „površina
  nije navedena”, a stranica kaže 197 m², okućnica 342 m², 4 parkirna mjesta). Isti uzrok: početni
  popis (6. 10.) nije otvarao oglase, a poznat oglas se ne otvara – 1311 neodbijenih bez površine,
  6 poruka o sniženju bez nje. Sad: poznat oglas sa sniženom cijenom otvara se prije poruke (svi
  izvori sa zajedničkim otvaranjem: index.hr, nekretnine.hr, realestatecroatia); realestatecroatia
  čita i broj parkirnih mjesta; zapamćeni oglasi bez površine jednom se ponovno otvaraju, 30 po
  pokretanju (vrsta i mjesto iz zaglavlja stranice), tiho – kuće ispod 70 m² i zemljišta ispod
  300 m² postaju odbijene, ostali ulaze u usporedbu cijena.
- **(gotovo 13. 10.) Revizija: koje podatke portali daju, a ne čitamo** (korisnik: „Ima li još
  stranica na kojima ne prikupljamo sve informacije?”). Izmjereno na stvarnim oglasima
  (`tools/provjeri_lokaciju.py polja:IZVOR:N`, grana debug) i snimkama stranica:
  - vender: „Tip kuće: dvojna / u nizu” u dodatnim značajkama (vrsta je inače samo „Kuća” –
    dvojna bi prošla), godina izgradnje i adaptacije, parkirna mjesta, površina parcele,
    oznake garaža / parkirno mjesto / bazen, „Stara cijena”;
  - oglasnik: godina izgradnje, parking (broj, garaža), dozvole i vlasnički list, bazen (polje
    „Okućnica”: 29 od 100 kuća u snimci), stanje – sve je već na popisu;
  - nekretnine.hr: stanje („Za renoviranje” → za obnovu), parking („3 na zajedničkom parkingu”
    umjesto dosadašnjeg nagađanja „garaža”), bazen (9 od 25 kuća), okućnica iz razdiobe površina;
    stanje, parking i bazen i s popisa (polja ga4…, na talijanskom);
  - index.hr: bazen, građevinska i uporabna dozvola (namjena zemljišta: šifre 1–3 bez naziva –
    nije uključeno);
  - realestatecroatia: garaža i parkiralište; koordinate na karti su središte mjesta (svi oglasi
    istog mjesta imaju istu točku) – ne vrijede za građevinsko područje;
  - Njuškalo: bazen, vlasnički list i dozvole iz grupa svojstava, godina zadnje renovacije;
    namjena zemljišta (već čitana) sad daje ⚠ kad nije stambena ni mješovita; poznat oglas sa
    sniženjem ili bez površine (103 zemljišta) otvara se kad se pojavi na popisu;
  - burza: oglasnik slobodnog teksta – čita se sve što ima. (23. 10.: krivo – stranica oglasa ima
    tablicu podataka; vidi niže.)
  Filtri: bazen iz polja odbija kao i naslov; stanje za renoviranje → 🔨 i kategorija za obnovu;
  🏗 i dopuna navode dozvole. Zapamćeni oglasi s vendera, oglasnika i nekretnine.hr jednom se
  ponovno otvaraju (index ispočetka, s bazenom i dozvolama), tiho, najviše 3 minute po pokretanju.
  Dostupno, a ne korišteno: komunalni priključci zemljišta (voda, struja, kanalizacija),
  udaljenost od mora, energetski razred.
- **(gotovo 13. 10.) Priključci u poruci za zemljišta** (odluka korisnika): redak 🔌 – iz polja
  oglasa (index.hr: voda, kanalizacija, plin, asfalt – polja za struju nema; vender: oznake;
  nekretnine.hr: popis na talijanskom i stranica oglasa, vrijednost 0 = nema, i pristup;
  Njuškalo: grupe svojstava), inače citat rečenice iz opisa (oglasnik i realestatecroatia za
  zemljišta nemaju polja; na 100 zemljišta s oglasnika 75 ih spominje u opisu), inače „nisu
  navedeni”. Vender: i vlasnički list i dozvole iz oznaka, vrsta zemljišta iz dodatnih značajki.
  Popravljeno usput: "Bazen: Ne" na Njuškalu čitao se kao bazen (fold() briše dvotočku).
- **(gotovo 13. 10.) index.hr: obnovljeni stari oglasi stizali su kao novi.** Jutros 383
  nepoznatih oglasa u jednom čitanju (srednji broj oglasa 6,6 mil., poznatih 7,1 mil.): agencije su
  noću obnovile stare oglase, a početni popis (4. 10.) čitao je najviše 80 stranica po vrsti
  (poredano po zadnjoj aktivnosti), pa ih nije zabilježio. Stiglo je 23 poruke za stare oglase.
  Sad se nepoznat oglas objavljen prije početka praćenja (postedTime) bilježi bez poruke, kao na
  Njuškalu, a pri otvaranju stranica novi oglasi idu prije starih. Ponovno otvaranje zapamćenih
  oglasa: vrijeme (3 min po pokretanju) dijeli se na izvore i broji se samo ono, ne čitanje popisa.
- **(gotovo 15. 10.) Dvojna kuća samo u punom opisu, poruka bez ⚠** (korisnik: realestatecroatia
  989420 – „Prodaje se vrlo interesantna dvojna kuća”; isti oglas na index.hr ima polje „Dvojna
  kuća” i 15. 10. je stigla dopuna s ⚠). Poruka 9. 10. bila je sniženje poznatog oglasa, a tada
  se stranica poznatog oglasa nije otvarala: samo isječak s popisa, bez te rečenice (i bez
  površine). Za realestatecroatia, nekretnine.hr i index.hr to je popravljeno 13. 10.; burza je
  ostala – sad i ona otvara poznat oglas sa sniženjem. Drugi nalaz: upozorenja iz punog opisa
  (dvojna, bazen, suvlasništvo, namjena…) brisalo je prvo sljedeće čitanje popisa (isječak), pa je
  u bazi taj oglas „prolazi” – sad ostaju (`runner._keep_text_warnings`, kao `_keep_text_reject`
  za odbijanja), a novi pun opis bez rečenice ih briše. Zapamćeni neodbijeni oglasi s
  realestatecroatia, nekretnine.hr i index.hr jednom se ponovno otvaraju (`opis-2026-10`), tiho,
  da se upozorenja vrate u bazu (završni pregled).
- **(gotovo 18. 10.) oglasnik.hr: karta nije točna lokacija** (korisnik: oglas 6731618 „otvara
  Google Maps s preciznom lokacijom”). U podacima oglasa jedine koordinate su „točke” razina
  lokacije (Hrvatska → županija → grad/općina → naselje); karta pokazuje točku najdublje razine –
  ovdje grad „Rijeka” (45,344937, 14,431943, sjever Rijeke), a kuća je prema opisu u Kastvu,
  Spinčići. U 200 oglasa iz snimki svako mjesto ima uvijek istu točku. Kao na realestatecroatia:
  ne vrijedi za građevinsko područje, oglasnik ostaje „bez lokacije na karti” (`dopuna.NO_COORDS`).
  Usput: oglas je 16. 10. stigao kao Rijeka, a naslov kaže „Kuća u Kastvu” (Kastav nije na popisu).
  Sad, kad naslov kaže „u <grad/općina>” za drugi grad ili općinu s drugom odlukom, lokacija je
  nesigurna (⚠, oglas stiže; i obrnuto – polje izvan područja, naslov „u Rijeci” – ne gubi se tiho).
  Samo imena gradova i općina, ne naselja („u centru” je i rječki Centar). Na 28.475 oglasa u bazi
  to mijenja samo ovaj oglas.
- **(19. 10.) Tjedna tablica i stari oglasi** (korisnik: „Njuškalo 1 novi oglas po kriterijima
  čini mi se premalo”). Tablica broji nove oglase bez istih kao već viđeni i bez tiho zabilježenih.
  Na Njuškalu je ovaj tjedan 264 oglasa koji odgovaraju zabilježeno tiho kao „stari” (agencije
  osvježavaju stare oglase; broj oglasa ostaje) – čekaju završni pregled. Nalazi:
  - Njuškalo: pravilo „stari” gledalo je samo zadnja ~3 dana brojeva (stvarno ~40.000 dnevno), pa je
    oglas koji na popis stigne danima nakon dobivanja broja bio „star”. Od 5. 10. takvih 16 koji
    odgovaraju; 15 je stiglo s drugog portala, propušten je jedan (Crikvenica, građevinsko zemljište
    1.050 m², 189.000 €, Njuškalo 51718204). Sad oglas s brojem većim od najvećeg na početku
    praćenja nikad nije star (`State.start_max_id`, pamti se u meta `pocetni_broj:IZVOR`).
  - index.hr: od 196 poruka od 12. 10. samo 7 je za oglase objavljene nakon početka praćenja; 189 su
    osvježeni stari oglasi (brojevi do 1,4 mil., medijan 6,8 mil.; početni najveći 7,59 mil.):
    osvježavanje mijenja postedTime, pa ih pravilo od 13. 10. ne prepoznaje. Stvarno novih koji
    odgovaraju tjedno je na oba portala podjednako (~12). **Odluka korisnika 19. 10.:** kao na
    Njuškalu – oglas s brojem do najvećeg na početku praćenja je „stari” i bilježi se bez poruke
    (završni pregled); s index.hr tada stiže ~1 poruka dnevno umjesto ~28.
  - Tablica sad odvaja: ✅ ⚠ ❌ samo novi (broj veći od najvećeg na početku), „stari ✅⚠” osvježeni
    stari koji odgovaraju (bez istih kao već viđeni). Za tjedan do 19. 10.: index.hr 3/3/179 i 189
    starih, Njuškalo 1/0/178 i 255 starih.
- **(19. 10.) Kopija starog oglasa nije nova** (korisnik: „Za mene je to i dalje stari oglas, ne
  treba doći. Jedino što treba doći je obavijest o novim informacijama … poruka s novim
  informacijama sadrži i link na stariji oglas … vrijedi za sve oglase”). Tiho zabilježen stari
  oglas (početak praćenja bez popisa – realestatecroatia, burza; osvježen stari – Njuškalo, index.hr)
  sad je „viđen” (`Seen.known`): kopija s drugog portala je „isti kao” i ne stiže, a novo s nje
  postaje napomena za završni pregled, kao kod oglasa iz početnog popisa (`Seen.quiet_root`).
  Od 5. 10. bilo je 78 takvih poruka: 72 stara index oglasa (utišana već istog jutra), 6 s drugih
  portala. Jeftinija kopija i dalje stiže („📉 Već viđen … sad jeftiniji”), sad s gumbom „Stariji
  oglas” (url u sažetku viđenih oglasa). Kad isti oglas ima i vlastitu poruku, dopuna je odgovor na
  nju (prednost pred tiho zabilježenim). Sniženje već javljenog oglasa stiže i kad tiho zabilježen
  blizanac ima istu cijenu (tu cijenu korisnik nije vidio). Uklonjen popravak od 8. 10.
  (`_repair_silent_twins`: kopije tiho zabilježenih stižu). Jednokratno: napomene iz ranijih odbijenih kopija tiho zabilježenih
  oglasa (`popravak:napomene_tiho`; proba na kopiji baza: GitHub 99, Redmi 77 – „nije građevinsko”,
  kuća u nizu, dvojna kuća). Ostale novosti za oglase bez vlastite poruke (⚠ „ne odgovara”,
  bolja lokacija) do resetiranja ostaju napomene (odluka 13. 10.; bilo bi ~6–16 poruka dnevno,
  103 od 106 redaka ⚠ „ne odgovara”); **odluka korisnika 19. 10.:** nakon resetiranja (završni
  pregled) stižu kao poruka s poveznicom na stariji oglas (vidi Završni pregled).
- **(23. 10.) burza.com.hr: tablica podataka sa stranice oglasa** (korisnik: oglas 351078 navodi
  priključke i pristupni put, a poruka ih nema). Stranica oglasa ima tablicu (`parse_features`):
  redci naziv – vrijednost („Vrsta kuće”, „Godina izgradnje”, „Kvadratura”) i popisi („Vrsta
  zemljišta”, „Pristupni put”, „Priključci”, „Prateći objekti”, „Opremljenost i sadržaji”, „U
  blizini”). Dosad se čitali samo mjesto i opis, pa je poruka imala ⚠ „vrsta zemljišta nije
  navedena”, a 🔌 samo iz opisa. Sad: vrsta kuće (dvojna / u nizu odbija se kao na drugim
  portalima) i zemljišta, kvadratura (prije teksta), godina izgradnje, priključci (i internet),
  pristupni put („pristup: asfaltni put”), garaža (parking), bazen. Neodbijeni burzini oglasi (24)
  jednom se ponovno otvaraju i tiho ocjenjuju (`reopen_once = "polja-2026-10"`, `Burza.reopen`).
  Usput: „gradilište” u naslovu / vrsti je građevinsko zemljište (bez ⚠ „vrsta nije navedena”);
  poljoprivredno koje u opisu spominje gradilište ostaje odbijeno.
- **(23. 10.) Naslov s drugom županijom → ⚠ „lokacija nesigurna”** (odluka korisnika; burza 63926:
  mjesto s portala „Matulji”, naslov „Jovići (Zadarska županija)” – prolazio je). Samo s riječju
  „županija” (`locations.other_county`; „pogled na Istru” nije to), i samo kad je mjesto s
  portala naše; oglas stiže s ⚠.
- **(23. 10.) Revizija 2: tablice svih portala** (korisnik: „pogledaj sve tablice svih relevantnih
  portala da vidimo propuštamo li još nešto”). Alat `polja:` sad i za burzu; Njuškalo: Redmi pri
  čitanju bilježi nazive polja i svojstava (do 8 primjera, bez opisa i kontakata) u meta
  `popis_polja:njuskalo:VRSTA` (`scraper/popis_polja.py`, najviše 80 stranica po vrsti).
  Nalazi (GitHub, 23. 10., 15–40 oglasa po portalu i vrsti):
  - nekretnine.hr, oglasnik, vender, realestatecroatia: sve bitno se čita (vrsta, površine,
    priključci, parking, bazen, dozvole i vlasnički list, stanje, godine). nekretnine.hr nema
    vrstu dvojna / u nizu („Obiteljska / Seoska kuća, Vikendica…”); „Optičko vlakno” = internet.
  - burza: uz tablicu od istog dana i kvadratura kuće i okućnice, broj parkirnih mjesta, zadnja
    adaptacija, stanje („Starina” → za obnovu), pravni status pristupa („pravo služnosti”),
    čisto vlasništvo (→ vlasnički list); ponovno otvaranje `polja2-2026-10`.
  - index.hr: i polje `internet` (priključak) i namjena zemljišta (`landUse`; nazivi iz
    ui-config/hr/detail.json?v=…: 1 komercijalno, 2 stambeno, 3 ostalo) – nije stambena → ⚠ kao
    na Njuškalu. Zapamćeni se ne otvaraju ponovno (završni pregled ionako ponovno ocjenjuje).
  - FINA: CSV nema stupaca za mjesto (lokacija i dalje iz opisa); novo: koja je dražba
    („Oznaka EJD” → „⚖ … · druga dražba”), skupni predmet prodaje → ⚠ (cijena za više nekretnina),
    napomena da nekretnina nije slobodna („stanuje ovršenik”) → ⚠ s citatom.
  - Njuškalo: u tijeku – Redmi bilježi polja pri čitanju (ujutro, kad stigne puno novih oglasa).

## Trinaesta runda pregleda (9. 10., izmjene od 8. 10.)

Svježa instanca, 11 potvrđenih nalaza (svaki reproduciran na pravom kodu), svi popravljeni:
- F-A ruševina: odbijale se i useljive / obnovljene kuće („obnovljena iz ruševine”, „u blizini
  ruševine utvrde”, „parkirno mjesto bez krova”, „suhozid urušen”) – sad samo kad je ruševina
  sama kuća. Ruševina na građevinskoj čestici / s građevinskom dozvolom: (gotovo, odluka
  korisnika) stiže kao zemljište s ⚠ – površina je okućnica, granice i usporedba zemljišta.
- F-B poslan oglas postajao je „ruševina” zbog skraćenog opisa s popisa (dnevno dublje
  čitanje) – sniženje se gubilo.
- F-C (regresija 12. runde) prekid pokretanja brisao je zapis o već poslanim dopunama,
  natječajima, bankama – sljedeće pokretanje slalo bi ih ponovno. Sad se poništava samo
  nedovršena obrada oglasa, a poslano se odmah sprema.
- F-D ista ⚠ dopuna drugim riječima („nije građevinsko (naslov)”) stizala je ponovno.
- F-E 📏 za česticu natječaja iz plana susjedne čestice (tekst oko čestice zahvaćao je sljedeću).
- F-F krug uz obalu: more se brojalo kao „izvan građevinskog područja” (100 % kopna u GP-u
  pokazivalo 63 %) – sad udio od kopna (maska: područja gradova i općina, izmjereno na
  Malinskoj, Opatiji, Matuljima).
- F-G ruševna štala uz useljivu kuću davala je 🔨 i kategoriju „za obnovu”.
- F-H opis oglasa s kontaktom prodavatelja u redovima čekanja javne baze stanja – sad bez
  bloka s kontaktom, telefona i e-adresa (dopune, neposlane, odgođene).
- F-I brisanje kontakata nije hvatalo „091.503.2253”, „(051) 341-080”, „ime(at)…”.
- F-J bez Telegrama dopuna se brisala (sad čeka kao obavijest).
- F-K 👎 na dopunu mijenjao je njen gumb na prvi portal (sad se pamti gumb svake poruke).
Nepotvrđeno, zapisano: dublje čitanje RC-a kad obje vrste traže više od 240 s; slika umjesto
obrisa s GeoServera (dodana zaštita); utrka GitHub/Redmi za istu dopunu; dopuna na krivi
original kad kopija odgovara dvama poslanim oglasima; dva 👎 od 7. 10. na poruke prije pamćenja.

## Zadaci za korisnika

- Njuškalo: spremljene pretrage s obavijestima u aplikaciji.
- Facebook: u lokalnim grupama uključiti obavijesti „Sve objave”.
- (gotovo) Telegram bot i GitHub Secrets (prije faze 1).
- (gotovo) Gmail lozinka za aplikacije za slanje maila (prije faze 1).
- (gotovo 8. 10.) Token za cron-job.org s rokom „No expiration”.
- Provjere koje može samo korisnik (7.5): izgled poruka na mobitelu, tjedni izvještaj nije
  u neželjenoj pošti, Redmi nakon nestanka struje / ponovnog paljenja, obavijesti
  cron-job.org kod neuspjeha, ručna usporedba s portalima (popis praćenih stranica).
