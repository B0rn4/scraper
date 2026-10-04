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
- **Lokacija:** samo ovih 15 jedinica lokalne samouprave, plus tablica koja svakom
  naselju pridružuje općinu ili grad (prema službenom popisu naselja). Portali često
  navode samo naselje (Ičići, Selce, Njivice, Stara Baška…). Usporedba je točna, a ne
  po dijelu riječi.
  - Općine: Baška, Dobrinj, Kostrena, Lovran, Malinska-Dubašnica, Mošćenička Draga,
    Omišalj, Punat, Vrbnik
  - Gradovi: Crikvenica, Kraljevica, Krk, Novi Vinodolski, Opatija, Rijeka
  - Bakar je namjerno isključen.
- **Nedostaje cijena ili površina** („cijena na upit”): oglas se šalje s oznakom ⚠.
- **Snižena cijena:** pamte se i oglasi izvan filtera. Kad cijena padne ispod granice,
  ili kad već poslani oglas pojeftini, stiže obavijest „📉 snižena cijena”.
- **Isti oglas na više portala:** jedna obavijest s napomenom „također na: …” (faza 5).

## Izvori

| Izvor | Način | Napomena (rezultat faze 0) |
|---|---|---|
| njuskalo.hr | s Redmija (faza 2); do tada i kao rezerva spremljene pretrage u aplikaciji | iz oblaka blokirano (ShieldSquare captcha); prolaz s hrvatske IP adrese treba provjeriti |
| nekretnine.hr | scraper (strukturirani JSON) | ista grupa kao Crozilla i Indomio, isti oglasi (korisnik provjerio); **zamjenjuje ih** |
| realitica.com | s Redmija (faza 2), probno | iz oblaka blokirano (403); ostaje samo ako donosi oglase kojih nema drugdje |
| oglasnik.hr | scraper | radi iz oblaka; popis oglasa učitava JavaScript |
| index.hr/oglasi | scraper (njihov interni API) | radi iz oblaka; React aplikacija |
| gohome.hr | scraper | radi iz oblaka; tražilica koja skuplja oglase s drugih stranica |
| vender.hr | RSS | radi iz oblaka |
| oglasi.hr, nekretnine24.hr | scraper | rade iz oblaka |
| trazimstan.hr | scraper (preglednik) | radi iz oblaka; aplikacija koja oglase učitava JavaScriptom |
| FINA Očevidnik | dnevni CSV izvoz (svi predmeti, ~11.000 redaka) | **samo građevinska zemljišta**; lokacija iz slobodnog opisa (vidi niže) |
| Stranice 15 općina i gradova | RSS, jednom dnevno, ključne riječi | 12 od 15 ima RSS; Dobrinj („Javni pozivi i natječaji”), Punat (Novosti → Natječaj) i Krk („Natječaji”) čitaju se izravno s tih odjeljaka |
| PGŽ, Ministarstvo državne imovine, CERP | jednom dnevno, ključne riječi | rade iz oblaka |
| Novi list (mali oglasi) | provjera | stranica radi; treba naći oglasnik |
| Lokalne agencije | faza 4 | 10–15 najaktivnijih, izdvojenih iz podataka s portala |
| Banke i leasing kuće | kasnije | prodaja preuzetih nekretnina |
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
2. **2a (gotovo 4. 10. 2026.)** Ostali portali s GitHuba: vender.hr (WordPress API) i
   gohome.hr (tražilica, samo oglasi s portala koje ne pratimo izravno – većinom Njuškalo
   i agencije; privremeno isključen dok se ne izmjere kašnjenje i pokrivenost). Izostavljeni: nekretnine24.hr (0 oglasa za područje),
   oglasi.hr (1 oglas), trazimstan.hr (većinom najam, robots.txt zabranjuje /api/).
   **2b** Redmi Note 9S (Termux) za Njuškalo i Realiticu. Napomena iz starog
   scrapera (stan-alert): Njuškalo je s kućne IP adrese prolazio uz pravi preglednik
   (Playwright, selektori `li.EntityList-item--Regular`, URL parametri `sort=new`,
   `price[max]`, `livingArea[min]`). Termux ne pokreće Playwright, pa treba provjeriti
   prolazi li običan zahtjev s hrvatske IP adrese ili tražiti drugi način.
3. Općine, gradovi, PGŽ, Ministarstvo, CERP.
4. Agencije.
5. Dorade: duplikati među portalima, snižene cijene, tjedni izvještaj.

## Zadaci za korisnika

- Njuškalo: spremljene pretrage s obavijestima u aplikaciji.
- Facebook: u lokalnim grupama uključiti obavijesti „Sve objave”.
- Telegram bot i GitHub Secrets (prije faze 1).
- Gmail lozinka za aplikacije za slanje maila (prije faze 1).
