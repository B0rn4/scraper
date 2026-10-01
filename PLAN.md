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

| Izvor | Način | Napomena |
|---|---|---|
| njuskalo.hr | spremljene pretrage u Njuškalo aplikaciji | postavlja korisnik; Njuškalo blokira strane IP adrese |
| crozilla.com **ili** indomio.hr | scraper | ista grupa (Indomio); koristi se jedan, drugi je rezerva |
| oglasnik.hr, index.hr/oglasi, nekretnine.hr, gohome.hr, realitica.com, oglasi.hr, nekretnine24.hr, ekvadrat.hr, vender.hr | scraper | izvedivost se provjerava u fazi 0 |
| trazimstan.hr | scraper | samo ako ima kuće i zemljišta |
| FINA Očevidnik | službeni API (data.gov.hr) | **samo građevinska zemljišta** |
| Stranice 15 općina i gradova | jednom dnevno, ključne riječi | natječaji za prodaju; obavijest s linkom |
| PGŽ, Ministarstvo državne imovine, CERP | jednom dnevno, ključne riječi | natječaji za prodaju |
| Novi list (mali oglasi) | provjera | ako postoji online izdanje |
| Lokalne agencije | faza 4 | 10–15 najaktivnijih, izdvojenih iz podataka s portala |
| Banke i leasing kuće | kasnije | prodaja preuzetih nekretnina |
| Facebook Marketplace i grupe | ručno | ugrađene FB obavijesti („Sve objave” u grupama); bez automatizacije |

## Izvršavanje i obavijesti

- **GitHub Actions** (javni repozitorij, bez ograničenja minuta), svakih 30 minuta,
  cijeli dan. GitHub pokretanja po rasporedu znaju kasniti 5–15 minuta.
- Od 23 do 7 h obavijesti stižu bez zvuka (tiha Telegram poruka).
- **Rezerva:** izvori koji blokiraju strane IP adrese pokreću se sa starog Androida
  (Redmi Note 9S, Termux) s hrvatskom IP adresom. Isti kod radi na oba mjesta.
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

0. **Test izvedivosti** (u tijeku): GitHub Actions dohvaća svaki izvor i bilježi
   što radi iz oblaka (`probe/`).
1. Jezgra (konfiguracija, filter, lokacije, baza), Telegram, e-mail, pregledni
   izvještaj, GitHub Actions, FINA i 3–4 najveća portala.
2. Ostali portali.
3. Općine, gradovi, PGŽ, Ministarstvo, CERP.
4. Agencije.
5. Dorade: duplikati među portalima, snižene cijene, tjedni izvještaj.

## Zadaci za korisnika

- Njuškalo: spremljene pretrage s obavijestima u aplikaciji.
- Facebook: u lokalnim grupama uključiti obavijesti „Sve objave”.
- Telegram bot i GitHub Secrets (prije faze 1).
- Gmail lozinka za aplikacije za slanje maila (prije faze 1).
