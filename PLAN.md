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
     područja – sve što se pratilo. Njuškalo za taj pregled čitati s filtrima u adresi
     (područje, cijena, površina) i raspoređeno kroz više pokretanja.
     **Odluka 7. 10.:** s tim pregledom prestaje pravilo „stari oglas” (Njuškalo oglas s
     brojem daleko ispod najnovijih bilježi se tiho). Nakon pregleda nepoznat oglas koji
     odgovara stiže i kad mu je broj star: ponovno aktiviran, ispravljena kategorija ili
     lokacija, pripremljen davno a objavljen sad, ili ga je pregled propustio. Do pregleda
     pravilo ostaje (Redmi zna samo dio Njuškala – inače desetci starih oglasa dnevno).
     Parcelaciju u postojećim oglasima korisnik provjerava sam (pretraga na portalima).
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
   5. **Testovi:** automatski (sad 207) dopuniti cijelim pokretanjem na spremljenim
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
      banke – sve što se prati; nakon toga redovni rad. Uz pregled ukinuti pravilo „stari
      oglas” (odluka 7. 10., vidi gore).
   8. **Nakon 1–2 tjedna rada:** s korisnikom proći što je stiglo, a bilo je
      nepotrebno, i što je propušteno; podesiti pravila.

## Zadaci za korisnika

- Njuškalo: spremljene pretrage s obavijestima u aplikaciji.
- Facebook: u lokalnim grupama uključiti obavijesti „Sve objave”.
- Telegram bot i GitHub Secrets (prije faze 1).
- Gmail lozinka za aplikacije za slanje maila (prije faze 1).
