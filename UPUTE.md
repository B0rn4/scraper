# Upute za korisnika

Kratke upute za svakodnevno korištenje: što stiže, što znači i što napraviti. Tehnički
detalji su u README.md (kako sustav radi) i REDMI.md (postavljanje Redmija).

## 1. Ukratko

- **GitHub** svakih 20 minuta (7–23 h) čita nekretnine.hr, index.hr oglase, oglasnik.hr,
  vender.hr, realestatecroatia.com, burza.com.hr i FINA-u. Pokreće ga cron-job.org.
- **Redmi** (Termux, kućni Wi-Fi) svakih 20 minuta čita Njuškalo, 10 minuta nakon GitHuba.
- Oba šalju na **Telegram** (Scraperbot): nove oglase, sniženja i natječaje.
- **Mail**: tjedni izvještaj ponedjeljkom ujutro i upozorenja kad nešto ne radi.
- Noću (23–7 h) ništa se ne čita; što se objavi noću stiže u 7 h.
- Isti oglas na više portala stiže jednom. Ponovno stiže samo ako je negdje jeftiniji.

## 2. Poruka oglasa, redak po redak

Primjer (zemljište u Matuljima):

```
🌳 Građevinsko zemljište · 109.000 € · 1.396 m²
📊 skuplji od 24 % područja · PPV +40 % · ⚠ 1
📍 Matulji
💶 78 €/m² · nekretnine.hr · Građevinsko zemljište
🗺 Građevinsko područje: …
📏 PPUO Matulji (2008): min. čest. 600 m² · kig 0,3 (tlocrt ≤ 300 m²) · kis 0,6 (GBP ≤ 600 m²)
🏛 PPV (Matulji – cijela općina, 20 naselja, 12 blokova): građevinsko medijan 56 €/m² …
📐 Područje, zemljišta 1.200–2.499 m² (264): medijan 104 €/m² – ovaj 25 % ispod · skuplji od 24 %
⚠ Matulji: prihvaća se samo mjesto Matulji – provjeri
```

| Oznaka | Značenje |
|---|---|
| 🏠 / 🌳 | kuća / građevinsko zemljište, cijena, površina |
| 📊 | sažetak: more (zračno), vožnja do Rijeke, koliko je skuplji od drugih oglasa, PPV, broj upozorenja |
| 📍 | mjesto (naselje, grad/općina) |
| 💶 | cijena po m², portal, vrsta |
| 🏗 / 🔨 | godina izgradnje i obnove, vlasnički list / kuća za obnovu ili starina |
| 🚗 | parking ili garaža (kuće) |
| 🗺 | građevinsko područje prema ISPU-u (vidi niže) |
| 📏 | uvjeti gradnje iz prostornog plana: najmanja čestica, kig, kis (zemljišta i čestice iz natječaja) |
| 🏛 | PPV: ostvarene cijene građevinskog zemljišta (Ministarstvo), na lokaciji ili za naselje |
| 📐 / 🏘 | usporedba s drugim oglasima iste vrste i veličine: cijelo područje / naselje |
| ✂️ | oglas spominje parcelaciju – stiže neovisno o cijeni i površini |
| ⚠ | nešto treba provjeriti (oglas je ipak stigao) |
| 📉 | snižena cijena (u naslovu poruke: stara → nova) |
| 🔄 | prije odbijen, sad odgovara (izmijenjen oglas) |

**🗺 Građevinsko područje** se provjerava ovako:
- **po broju čestice iz opisa** (k.č. … k.o. …) – najtočnije;
- **po točnoj oznaci na karti oglasa**;
- **po približnoj oznaci** (krug na karti portala: nekretnine.hr 250 m, Njuškalo 500 m) – točno se
  izračuna koliki je dio kruga u građevinskom području (iz obrisa područja Ministarstva):
  „Krug 250 m oko približne oznake na karti (Rukavac): 52 % u građevinskom području
  naselja, ostatak izvan”. Ako je zemljište bilo gdje u krugu jednako vjerojatno, to je i
  vjerojatnost da je u građevinskom području (samo postotak, bez ⚠). U zagradi je naselje u
  kojem je središte oznake, što pomaže kad oglas navodi samo općinu. Za kuće se oko
  približne oznake ne provjerava. index.hr za približnu lokaciju daje samo središte mjesta,
  pa tamo piše „nije provjereno – oglas ima samo mjesto”.
- „nije provjereno” – oglas nema ni čestice ni oznake.

**Duga poruka** se nastavlja u drugoj poruci odmah ispod (bez zvuka).

## 3. Što možeš napraviti s porukom

- **Otvori oglas** – gumb ispod poruke.
- **Ne zanima me**: dugi pritisak na poruku → reakcija **👎**. Za taj oglas (i isti oglas
  na drugim portalima) više ništa ne stiže, ni sniženje. Obradi se u sljedećem pokretanju
  (do 20 min); ispod poruke se pojavi „🔕 Ne zanima me”.
- **Predomislio si se**: makni 👎 (i nakon više dana) – poruke opet stižu.

## 4. Ostale poruke na Telegramu

- **„N novih oglasa – previše za pojedinačne poruke”**: datoteka s popisom (više od 30
  odjednom, npr. nakon prekida). Otvori je u pregledniku.
- **📜 Natječaji**: prodaja nekretnina gradova, općina, PGŽ-a i države na našem području
  (jednom dnevno, ujutro).
- **Banke**: promjena na stranicama s nekretninama banaka.
- **Novogodišnji podsjetnik** (1. 1.): osvježiti PPV za novu godinu i razmisliti o brisanju
  starih oglasa iz usporedbe cijena. Javi Claudeu.

## 5. Upozorenja (⚠ „Scraper: …”)

Upozorenje stiže **jednom**, a kad prođe, stiže i poruka „ponovno radi”. GitHubova
upozorenja idu mailom (ako mail ne radi, na Telegram); Redmijeva na Telegram (ako ga
Redmi ne može poslati, GitHub ga šalje mailom). Kad piše **„Javi Claudeu ovu poruku”**,
proslijedi je (snimka zaslona je dovoljna).

**Izvori oglasa**

| Upozorenje | Što znači | Što napraviti |
|---|---|---|
| izvor X ne radi | portal 3 puta zaredom vraća grešku (promjena stranice, zaštita) | ako ne prođe za sat-dva, javi Claudeu |
| X – nema novih oglasa | portal se čita, ali danima nema ništa novo (promijenjen redoslijed?) | otvori poveznicu iz poruke; ima li novijih oglasa, javi Claudeu |
| X – stranice oglasa ne rade | popis radi, pojedini oglasi se ne otvaraju | oglasi stižu bez dijela podataka; javi Claudeu |
| Njuškalo traži captchu na stranicama oglasa | zaštita Njuškala | obično prođe samo; ako traje danima, javi |
| Njuškalo – dio oglasa nije pročitan | bilo je više novih oglasa nego što se stigne pročitati (npr. nakon prekida) | pogledaj na poveznici oglase iz navedenog razdoblja |
| X – oglasi se ne daju obraditi | greška u programu za neki oglas | pogledaj oglase s poveznica ručno; javi Claudeu |
| realestatecroatia – dnevno dublje čitanje ne završava | sniženja starijih oglasa se ne vide | javi Claudeu |

**Redmi (Njuškalo)**

| Upozorenje | Što znači | Što napraviti |
|---|---|---|
| Redmi se ne javlja | Redmi 90 min ne šalje stanje | provjeri: uključen, na punjaču, Wi-Fi, obavijest „Termux” u traci |
| Redmi ne završava pokretanja | Redmi radi, ali pokretanje stane prije kraja | u Ubuntuu `tail -40 ~/scraper.log`, pošalji Claudeu |
| Redmi ne može slati na Telegram | promijenjen bot ili razgovor | iste vrijednosti upiši na Redmiju (REDMI.md, „Promijenjen bot”) |
| sat na Redmiju nije točan | sat mobitela odstupa više od 10 min | Postavke → Datum i vrijeme → automatsko vrijeme |
| Redmi radi sa starim kodom | Redmi 6 sati ne preuzima novi kod | u Ubuntuu `cd ~/scraper && git status && git fetch --prune origin`, ispis Claudeu |
| stanje s Redmija je oštećeno | datoteka koju Redmi šalje nije ispravna | javi Claudeu |
| Redmi javlja – … | Redmijevo upozorenje koje nije stiglo na Telegram | kao gore, prema sadržaju |

**GitHub, Telegram, mail**

| Upozorenje | Što znači | Što napraviti |
|---|---|---|
| cron-job.org ne pokreće GitHub | GitHub radi samo povremeno (rezerva) | cron-job.org: povijest pokretanja, je li posao uključen; 401/403 = token |
| GitHub ne radi | GitHub 2 sata nije pokrenuo scraper | cron-job.org i githubstatus.com |
| GitHub ne završava pokretanja | pokreće se, ali stane prije kraja | GitHub → Actions: zadnja pokretanja (crvena?); javi Claudeu |
| Redmi ne preuzima stanje s GitHuba | Redmi nema interneta ili mu je istekao GitHub token | internet na Redmiju; GITHUB_TOKEN u `~/.scraper.env` |
| Telegram ne prima poruke | bot blokiran ili obrisan | neposlane obavijesti čekaju 7 dana; javi Claudeu |
| Telegram nije postavljen | nedostaju TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID | GitHub → Settings → Secrets and variables → Actions |
| mail nije postavljen | nedostaju SMTP_USER / SMTP_PASSWORD | isto mjesto; bez maila nema tjednog izvještaja |
| tjedni izvještaj nije poslan | mail 2 dana ne prolazi | provjeri lozinku za mail (SMTP_PASSWORD) |

## 6. Tjedni izvještaj (mail, ponedjeljak)

- novi oglasi po izvoru (✅ prolazi, ⚠ upozorenje, ❌ odbijen);
- poslane obavijesti;
- **za dlaku promašeni** (cijena ili površina do 15 % izvan granice) – vrijedi pogledati;
- preskočeni kao već viđeni (isti oglas na drugom portalu);
- **stanje izvora**: ✅ radi / ⚠ greške / ❔ nepoznato (Redmi se dugo ne javlja), uz
  zadnji nov oglas po izvoru;
- nove odluke o prostornim planovima naših gradova i općina.

## 7. Redmi – održavanje

- Neka stoji **na punjaču i kućnom Wi-Fiju**, s Termuxom zaključanim u nedavnim
  aplikacijama (lokot). Šifra koju mobitel traži svakih 72 sata ne smeta – scraper radi i
  dok je zaključan.
- Nakon ponovnog paljenja Termux se pokreće sam (Termux:Boot). Ako nisi siguran: otvori
  Termux jednom.
- **Dnevnik**: u Termuxu `proot-distro login ubuntu`, zatim `tail -30 ~/scraper.log`.
  Iz Ubuntua se izlazi s `exit` – automatska pokretanja to ne prekida.
- **Poslati Claudeu spremljene stranice** (kad on to zatraži):
  `cd ~/scraper && . ~/venv/bin/activate && python tools/redmi_probe.py --posalji`
- Kod se na Redmiju osvježava sam pri svakom pokretanju; ništa ne treba instalirati ručno.
- Zaglavljeno, ponovna instalacija, promijenjen bot: REDMI.md, „Kad nešto zapne”.

## 8. Promjena postavki

Na GitHubu otvori datoteku → olovka (Edit) → promijeni → **Commit changes**. Promjena
vrijedi od sljedećeg pokretanja (do 20 min), i na Redmiju.

- **Cijene i površine**: `config.yaml` → `kriteriji` (`max_cijena`, `min_povrsina`,
  `za_dlaku_posto`).
- **Radno vrijeme**: `config.yaml` → `vrijeme` (`od_sata`, `do_sata`).
- **Naselja** (prolaz / upozorenje / odbijen): `data/naselja_udaljenosti.csv`, stupac
  `odluka` (`Prolaz`, `Upozorenje`, `Odbijen`). Ako nisi siguran, pošalji Claudeu
  izmjene – on provjeri i ostalo što o naselju ovisi.
- **Najviše poruka odjednom**: `config.yaml` → `obavijesti` → `max_poruka_po_pokretanju`.
- **Uključiti / isključiti portal**: `config.yaml` → `izvori` (`true` / `false`).
- **Nova stranica natječaja** (grad, općina): pošalji Claudeu adresu stranice s
  natječajima; on je doda u `data/natjecaji.yaml` (način čitanja ovisi o stranici).

**Pauza** (godišnji, kupljeno…):
- **kratko**: Telegram razgovor utišaj u aplikaciji; sve i dalje radi i bilježi se;
- **dulje**: na cron-job.org isključi posao, a na Redmiju u Termuxu (izvan Ubuntua)
  upiši `crontab -r`. Upozorenja „cron-job.org ne pokreće GitHub” i „Redmi se ne javlja”
  tada su očekivana. Za nastavak uključi posao na cron-job.org i u Termuxu upiši
  `crontab ~/scraper.cron`. Prvo pokretanje nakon pauze pročita ono što stigne s vrha
  popisa; starije oglase iz pauze pogledaj ručno.

## 9. Ručno pokretanje

GitHub → **Actions** → **Scraper nekretnina** → **Run workflow**:
- `test` – probna poruka na Telegram i probni mail;
- `pregled` – pregledni izvještaj cijelog područja (HTML, svi oglasi s razlogom
  odluke). Pogrešno procijenjene označi kvačicom, dodaj napomenu, klikni **Kopiraj
  označene** i zalijepi Claudeu;
- `run` – jedno pokretanje odmah;
- `tjedni` – tjedni izvještaj odmah.

**Provjera lokacije oglasa** (građevinsko područje, PPV, kulturna dobra):
Actions → **Planovi – preuzimanje** → naredba `lokacija`, u „adrese” zalijepi adresu oglasa
(nekretnine.hr, index.hr) ili koordinate `45.36,14.29`. Rezultat je na grani `debug`
(`planovi/lokacije/`); najlakše je zamoliti Claudea da ga pročita.

## 10. Tajne i tokeni

- Tokene i lozinke **nikad ne šalji Claudeu ni u razgovor**. Upisuju se samo u
  GitHub Secrets (Settings → Secrets and variables → Actions) i na Redmiju u
  `~/.scraper.env`.
- GitHub Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SMTP_USER`,
  `SMTP_PASSWORD`, `EMAIL_TO`.
- Token za cron-job.org ima rok **No expiration**. Ako ga ikad mijenjaš, ostavi isto.
- Redmijev GITHUB_TOKEN (u `~/.scraper.env`) služi za slanje stanja i preuzimanje koda.
  Ako istekne, stiže „Redmi ne preuzima stanje s GitHuba”.

## 11. Česta pitanja

**Zašto nije stigao oglas koji vidim na portalu?** Najčešće:
- odbijen je (cijena, površina, naselje, vrsta kuće, opis) – vidi se u preglednom izvještaju;
- isti oglas već je stigao s drugog portala;
- „stari oglas”: agencija je ponovno objavila oglas koji već dugo postoji;
- označio si ga s 👎.

Ako misliš da je trebao stići, pošalji Claudeu poveznicu.

**Stiže li i kad je cijena „na upit”?** Da, s procjenom prema medijanu u naselju (⚠), osim
luksuznih (vila, bazen…) i golemih kuća.

**Što s istekom oglasa na Njuškalu?** Oglas koji je u međuvremenu istekao stiže s
upozorenjem „oglas je istekao” – prodavatelj je obično i dalje dostupan.

**Koliko je sve ovo pouzdano?** Ništa se ne bi smjelo tiho izgubiti: kad nešto ne radi
ili se nije stiglo pročitati, stiže upozorenje. Tišina znači „nema novih oglasa”.
