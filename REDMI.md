# Redmi: Njuškalo i Realitica (faza 2b)

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
apt update && DEBIAN_FRONTEND=noninteractive apt install -y python3 python3-venv git
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

## Korak 1b: pravi preglednik (samo ako ti javim; oko 15 min)

Ako Njuškalo ne prolazi bez preglednika, probat ćemo s Chromiumom:

```
pip install playwright
python -m playwright install --with-deps chromium
python tools/redmi_probe.py --playwright
```

## Korak 2: automatsko pokretanje (nakon probe; oko 15 min)

Kad napišem čitanje Njuškala i Realitice prema rezultatima probe, ovdje će biti
upute za automatsko pokretanje svakih 20 minuta od 7 do 23 h. Uključuje Termux:Boot
za pokretanje nakon ponovnog paljenja te postavke baterije u MIUI-ju (Termux bez
ograničenja baterije, automatsko pokretanje uključeno). Plan je da GitHub primijeti
ako Redmi prestane javljati i pošalje mail.
