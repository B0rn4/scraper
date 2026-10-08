# Redmi: Njuškalo (faza 2b)

Njuškalo i Realitica blokiraju GitHubove poslužitelje (američke IP adrese). Redmi na
kućnom Wi-Fiju portalima izgleda kao običan posjetitelj iz Hrvatske. Programi se
vrte u Ubuntuu unutar Termuxa jer sam Termux ne može pokrenuti potrebne biblioteke.

Naredbe kopiraj s ove stranice (gumb za kopiranje u kutu bloka) i zalijepi u Termux
dugim pritiskom na zaslon → **Paste**. Cijeli blok možeš zalijepiti odjednom; retci se
izvršavaju jedan za drugim. Prije sljedećeg bloka pričekaj da se opet pojavi
odzivnik: tekst na početku retka u koji upisuješ naredbe (`~ $` u Termuxu,
`root@localhost:~#` u Ubuntuu). Ako naredba usred bloka nešto pita, ostatak
zalijepljenog teksta može se upisati kao odgovor. Zato su takve naredbe izdvojene
ili postavljene da ne pitaju.

## Korak 1: proba (oko 30–40 min, većinom čekanje)

Cilj: vidjeti prolaze li Njuškalo i Realitica s kućne mreže. Ništa se još ne
pokreće automatski. Proba šalje svega nekoliko zahtjeva svakom portalu.

### 1.1 Termux

1. Spoji Redmi na kućni Wi-Fi i na punjač.
2. U pregledniku otvori **f-droid.org**, preuzmi i instaliraj F-Droid (dopusti
   instalaciju iz tog izvora kad Android pita).
3. U F-Droidu potraži **Termux** i instaliraj ga. Termux iz Trgovine Play je
   zastario i ne radi kako treba.
4. Otvori Termux.

**Ako F-Droid javi `INSTALL_FAILED_INTERNAL_ERROR: Permission Denied`** (česta
pojava na Xiaomiju: MIUI ne pušta F-Droidov način instalacije):

- U pregledniku otvori **f-droid.org/packages/com.termux/**, kod najnovije verzije
  preuzmi APK označen s **arm64-v8a** i otvori preuzetu datoteku. Instalira ga
  Androidov instalacijski program, a ne F-Droid. Kad pita, dopusti pregledniku
  instaliranje aplikacija.
- Ako ni to ne prođe: Postavke → O telefonu → 7 puta dodirni **MIUI verzija**
  (uključuje opcije za razvojne programere), zatim Postavke → Dodatne postavke →
  Opcije za razvojne programere → isključi **Uključi MIUI optimizaciju**. Instaliraj
  Termux pa optimizaciju možeš opet uključiti.

Termux i njegove kasnije dodatke (Termux:Boot) treba instalirati iz istog izvora.
Zato APK uzmi s F-Droidove stranice, a ne s GitHuba.

### 1.2 GitHub token

Token služi da Redmi pošalje rezultate probe na GitHub, gdje ih ja čitam. Najlakše ga
je napraviti na samom Redmiju, u pregledniku:
**github.com/settings/personal-access-tokens/new**

- Token name: `redmi-scraper`
- Expiration: **No expiration**
- Repository access: **Only select repositories** → `B0rn4/scraper`
- Permissions → Repository permissions → **Contents: Read and write**
- **Generate token**, zatim ga kopiraj.

Token zalijepi samo u Termux kad ga skripta zatraži (korak 1.4). Ne šalji ga meni.
Isti token trebat će i za automatska pokretanja u koraku 2. Ako ga ne spremiš
(npr. u upravitelj lozinki), tada se jednostavno napravi novi.

### 1.3 Ubuntu unutar Termuxa

U Termuxu:

```
termux-wake-lock
pkg update -y && pkg upgrade -y
```

`termux-wake-lock` sprječava da Android uspava Termux; u obavijestima se pojavi
oznaka. Ako `pkg upgrade` pita što učiniti s konfiguracijskom datotekom (npr.
`openssl.cnf ... [default=N] ?`), upiši **Y** i Enter: Termux je nov, pa nema tvojih
izmjena koje bi trebalo čuvati. Isto odgovori ako pita više puta.

```
pkg install -y proot-distro
proot-distro install ubuntu
```

```
proot-distro login ubuntu
```

Ovo sam ne mijenjaš; promijeni se samo. Početak retka u koji pišeš više nije `~ $`
nego `root@localhost:~#`, a to znači da si sada u Ubuntuu. Sve daljnje naredbe idu
ondje.

### 1.4 Scraper i proba

```
apt update && DEBIAN_FRONTEND=noninteractive apt install -y python3 python3-venv git procps
```

```
git clone -b claude/real-estate-scraper-primorska-jrlscq https://github.com/B0rn4/scraper.git
cd scraper
python3 -m venv ~/venv && . ~/venv/bin/activate
pip install -r requirements.txt
```

```
python tools/redmi_probe.py
```

Skripta za svaku stranicu ispiše **PROLAZI** ili **NE PROLAZI** i na kraju zatraži
token. Zalijepi ga (ne prikazuje se dok ga lijepiš) i pritisni Enter. Kad ispiše
„Gotovo”, javi mi; rezultate čitam s GitHuba. Ako nešto zapne, pošalji snimku zaslona.

**Povratak kasnije:** otvori Termux pa upiši

```
proot-distro login ubuntu
cd scraper && . ~/venv/bin/activate
```

## Korak 1b: Realitica i pravi preglednik (oko 15–20 min)

Rezultat prve probe (5. 10. u 1 h):
- **Realitica** prolazi bez preglednika.
- **Njuškalo** je prvi put vratio prave stranice (31 oglas), a tri minute kasnije
  zaštita (ShieldSquare) je na sve zahtjeve vratila stranicu s captchom. Zato
  Njuškalo ne diramo nekoliko sati i probamo s pravim preglednikom, koji zaštiti
  izgleda kao običan posjetitelj.

Prvo osvježi scraper (svaki put kad nastavljaš):

```
cd ~/scraper && . ~/venv/bin/activate && git pull
```

**1. Realitica (odmah):** pretraga kuća i građevinskih zemljišta u PGŽ te jedan oglas.

```
python tools/redmi_probe.py --samo-realitica
```

**2. Instalacija Chromiuma (odmah; ništa ne šalje Njuškalu).** Preuzima nekoliko
stotina MB.

```
pip install playwright
python -m playwright install --with-deps chromium
```

```
python tools/redmi_probe.py --provjeri-preglednik
```

Zadnja naredba otvori Realiticu u Chromiumu i provjeri radi li preglednik unutar
Ubuntua. Ako javi grešku, pošalji snimku zaslona.

**3. Njuškalo preglednikom (najranije nekoliko sati nakon captche, npr. sutra
popodne):**

```
python tools/redmi_probe.py --playwright
```

Svaka naredba na kraju sama traži token i šalje rezultate. Ako slanje ne uspije,
ponovi ga s `python tools/redmi_probe.py --posalji`.

## Korak 2: redovno pokretanje (oko 20 min)

Redmi svakih 20 minuta (7–23 h) pravim preglednikom otvori Njuškalo (kuće i zemljišta
u PGŽ, najnovije), za nove oglase koji bi mogli proći otvori i sam oglas, pošalje
obavijesti na Telegram i stanje na GitHub. Ako se Redmi 90 minuta ne javi, GitHub
šalje mail. Stari oglasi koje agencije samo ponovno objave ne stižu (osim sniženja).

### 2.1 Tajne (u Ubuntuu)

Botu u Telegramu napiši bilo što (npr. „bok”) i **odmah** (u roku od minute) pokreni
naredbe ispod – tako skripta sama pronađe ID razgovora. GitHub svakih 20 minuta pročita
poruke botu, pa ih skripta poslije toga više ne vidi; ako ID ne pronađe, ponovi.

```
cd ~/scraper && . ~/venv/bin/activate && git pull
python tools/redmi_setup.py
```

Skripta pita za:
- **token bota**: u Telegramu @BotFather → /mybots → tvoj bot → API Token (isti kao
  TELEGRAM_BOT_TOKEN na GitHubu);
- **ID razgovora**: samo ako ga ne pronađe sama (isti kao TELEGRAM_CHAT_ID; GitHub ga
  više ne prikazuje, pa je lakše ponoviti „bok” i skriptu);
- **GitHub token**: `redmi-scraper` iz koraka 1.2. Ako ga nisi spremio, napravi novi
  na isti način.

Na kraju stiže probna poruka na Telegram. Tajne ostaju samo na Redmiju.

### 2.2 Prvo pokretanje (u Ubuntuu)

```
bash tools/redmi_run.sh; tail -15 ~/scraper.log
```

Prvo pokretanje samo zabilježi oglase s prve stranice, bez poruka (nakon ponovne
instalacije stanje se vrati s GitHuba, pa mogu stići i poruke). U ispisu treba
pisati „Njuškalo: … oglasa” i „redmi_sync: stanje poslano”. Javi mi kad prođe.

### 2.3 Automatsko pokretanje (u Termuxu)

Izađi iz Ubuntua (`exit`, odzivnik je opet `~ $`) pa:

```
pkg install -y cronie termux-services
```

Zatvori Termux potpuno: u svakom prozoru upiši `exit` (ili ga makni iz nedavnih
aplikacija) i ponovno ga otvori, da se pokrenu servisi. Zatim:

```
sv-enable crond
echo 'PATH=/data/data/com.termux/files/usr/bin' > ~/scraper.cron
echo '*/20 7-22 * * * proot-distro login ubuntu -- bash /root/scraper/tools/redmi_run.sh' >> ~/scraper.cron
crontab ~/scraper.cron
crontab -l
```

Zadnja naredba ispiše ta dva retka – tada je raspored postavljen.

Cron pokreće skriptu u :00, :20 i :40, a skripta sama pričeka 10 minuta (radi u :10,
:30 i :50): tako Redmi i GitHub ne rade istodobno i svaki prije čitanja ima najnovije
stanje drugoga, pa isti oglas ne stigne dvaput. Ručno pokretanje iz terminala kreće odmah.

### 2.4 Nakon ponovnog paljenja i baterija

1. U pregledniku otvori **f-droid.org/packages/com.termux.boot/**, preuzmi APK i
   instaliraj ga (isti izvor kao Termux). Otvori **Termux:Boot** jednom pa ga zatvori.
2. U Termuxu:

```
mkdir -p ~/.termux/boot
echo '#!/data/data/com.termux/files/usr/bin/sh' > ~/.termux/boot/start-scraper
echo 'termux-wake-lock' >> ~/.termux/boot/start-scraper
echo '. /data/data/com.termux/files/usr/etc/profile' >> ~/.termux/boot/start-scraper
chmod +x ~/.termux/boot/start-scraper
```

3. MIUI postavke (da Android ne gasi Termux):
   - Postavke → Aplikacije → Upravljanje aplikacijama → **Termux** → Ušteda baterije →
     **Bez ograničenja**; Automatsko pokretanje → **uključeno**.
   - Isto za **Termux:Boot** (automatsko pokretanje uključeno).
   - U nedavnim aplikacijama dugo pritisni Termux → **lokot** (zaključaj).
4. Redmi neka stoji na punjaču i kućnom Wi-Fiju.

### Provjera

U Ubuntuu `tail -30 ~/scraper.log` pokazuje zadnja pokretanja. Ako Redmi ne radi,
GitHub nakon 90 minuta šalje mail „Redmi se ne javlja”; ako Redmi radi, ali ne može
slati na Telegram, mail „Redmi ne može slati na Telegram”.

Kod se osvježava sam pri svakom pokretanju (uvijek točno kao na GitHubu; izmjene u
`~/scraper` na Redmiju se odbacuju), a novi paketi se instaliraju kad se promijeni
`requirements.txt`.

## Kad nešto zapne

**Promijenjen bot ili razgovor** (novi token ili TELEGRAM_CHAT_ID na GitHubu): iste
vrijednosti treba i Redmi. U Ubuntuu ponovi korak 2.1 (`python tools/redmi_setup.py`).

**U dnevniku stalno „prethodno pokretanje još traje”:** svaki korak ima najdulje
trajanje (ukupno oko 25 minuta), pa bi to trebalo proći samo. Ako ne prođe, u Ubuntuu
(ako javi da `pkill` ne postoji, prvo `apt install -y procps`):

```
pkill -f redmi_run.sh; pkill -f "scraper run"; pkill -f chrom
```

**Ponovna instalacija:**
- **novi Termux** (npr. nakon brisanja aplikacije): koraci 1.1 i 1.3 (cijeli), zatim 1.4
  do `pip install -r requirements.txt` (bez probe);
- **samo novi Ubuntu** (Termux je ostao): iz koraka 1.3 od `proot-distro install ubuntu`,
  zatim 1.4 do `pip install -r requirements.txt`.

Zatim iz koraka 1b točka 2 (`pip install playwright` i `python -m playwright install
--with-deps chromium`) i koraci 2.1–2.4. Stanje Redmija (redmi.db) prvo pokretanje samo
vrati s GitHuba; ako GitHub tada ne odgovara, pokretanje se preskoči (da prazna baza ne
prepiše staru) i pokuša ponovno za 20 minuta.
