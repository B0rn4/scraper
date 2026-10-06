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
1. **(u tijeku)** Jezgra (konfiguracija, filter, lokacije, baza), Telegram, e-mail,
   pregledni izvještaj, GitHub Actions, FINA, nekretnine.hr, oglasnik.hr, index.hr/oglasi.
   Kod je u `scraper/`, upute u README.md. Početni popis poslan 4. 10. 2026.
   (15.894 oglasa). Poznato: isti oglas na više portala stiže više puta (rješava faza 5);
   GitHub raspored se nije sam pokrenuo – rješenje u README.md („Raspored ne radi”).
2. **2a (gotovo 4. 10. 2026.)** Ostali portali s GitHuba: vender.hr (WordPress API).
   Izostavljeni: nekretnine24.hr (0 oglasa za područje), oglasi.hr (1 oglas),
   trazimstan.hr (većinom najam, robots.txt zabranjuje /api/), gohome.hr (vidi tablicu
   izvora; mjerni alati za otkrivanje maknuti 6. 10., ostaju u povijesti gita).
   **2b (u tijeku)** Redmi Note 9S, samo za Njuškalo (Realitica izostavljena: 49 od 50
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
   4. Cijena: ostvarene cijene (ISPU, Plan približnih vrijednosti) važnije su od
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
     područja – sve što se pratilo. Nakon toga s Njuškala stižu samo stvarno novi oglasi; stari oglasi koje
     agencije osvježe i dalje se samo bilježe. Njuškalo za taj pregled čitati s
     filtrima u adresi (područje, cijena, površina) i raspoređeno kroz više pokretanja.
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
5. **(6. 10.) Agencije.**
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
6. **(6. 10.) Dodaci za kuće.**
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
   3. **Moja provjera grešaka:** pregled koda po modulima i podataka u bazi (sumnjive
      vrijednosti: površina < 20 m², cijena < 1.000 €, nepoznata lokacija, najčešća
      upozorenja), zapisnici zadnjih pokretanja (greške, ograničenja vremena, zdravlje
      izvora).
   4. **Svježi pregled koda:** nova instanca (podagent) bez znanja o razgovoru, samo s
      kodom i README/PLAN kao opisom; traži greške. Svaki nalaz provjeravam prije
      popravka (ne zna za odluke poput isključenih naselja).
   5. **Testovi:** automatski (sad 106) dopuniti cijelim pokretanjem na spremljenim
      stvarnim stranicama i vježbama kvarova (izvor ne radi, Telegram ne radi, ISPU ne
      radi, Redmi ne javlja) – stiže li upozorenje. Popis provjera koje može samo
      korisnik: izgled poruka na mobitelu, mail tjednog izvještaja (nije u neželjenoj
      pošti), Redmi nakon nestanka struje / ponovnog pokretanja, obavijesti
      cron-job.org kod neuspjeha, ručna usporedba s portalima (popis praćenih stranica).
   6. **Upute za korisnika** (`UPUTE.md`): značenje svakog retka i oznake u poruci,
      kako promijeniti kriterije i naselja, dodati stranicu natječaja, pauzirati, što
      napraviti kad stigne upozorenje o kvaru.
   7. **Završni pregled** (dogovor 5. 10., dopuna 6. 10.): svi aktivni oglasi koji
      odgovaraju, uključujući cijelo Njuškalo preko Redmija, te natječaji, FINA dražbe,
      banke – sve što se prati; nakon toga redovni rad.
   8. **Nakon 1–2 tjedna rada:** s korisnikom proći što je stiglo, a bilo je
      nepotrebno, i što je propušteno; podesiti pravila.

## Zadaci za korisnika

- Njuškalo: spremljene pretrage s obavijestima u aplikaciji.
- Facebook: u lokalnim grupama uključiti obavijesti „Sve objave”.
- Telegram bot i GitHub Secrets (prije faze 1).
- Gmail lozinka za aplikacije za slanje maila (prije faze 1).
