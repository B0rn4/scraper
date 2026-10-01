# Rezultati testa izvedivosti – krug 2

Vrijeme: 2026-10-01 21:26 UTC  
Izlazna IP adresa: {'country': 'US', 'region': 'Wyoming', 'city': 'Cheyenne', 'org': 'AS8075 Microsoft Corporation'}

| grupa | izvor | URL | status | KB | s | zaštita | naslov |
|---|---|---|---|---|---|---|---|
| round2 | fina_csv | https://ponip.fina.hr/ocevidnik-web/preuzmi/csv | 200 | 10121 | 13.3 |  |  |
| round2 | fina_najava | https://ponip.fina.hr/ocevidnik-web/pregled/nadmetanja-u-najavi | 200 / imp 200 | 26 | 0.7 | captcha | FINA - Očevidnik nekretnina i pokretnina |
| round2 | fina_vrste | https://ponip.fina.hr/ocevidnik-web/get/vrsta/objekta/prodaje/nekretnine/list | 200 | 7 | 0.7 |  |  |
| round2 | nekretnine_hr | https://www.nekretnine.hr/prodaja-stambene-nekretnine/primorsko-goranska-zupanija/opcina/ | 103 / imp 200 | 0 | 0.5 |  | Gradovi i općine s oglasima za prodaju kuće u županiji Primorsko-goranska - Nekretnine.hr |
| round2 | nekretnine_hr | https://www.nekretnine.hr/prodaja-samostojeca-kuce/primorsko-goranska-zupanija/ | 103 / imp 200 | 0 | 1.2 |  | Prodaja samostojećih kuća Primorsko-goranska županija - Nekretnine.hr |
| round2 | nekretnine_hr | https://www.nekretnine.hr/prodaja-zemljista/primorsko-goranska-zupanija/ | 103 / imp 200 | 0 | 0.6 |  | Prodaja zemljišta Primorsko-goranska županija - Nekretnine.hr |
| round2 | index_oglasi | https://www.index.hr/oglasi/static/js/main.2c0cd421.js | 200 / imp 200 | 7441 | 0.4 | captcha,access_denied |  |
| round2 | trazimstan | https://trazimstan.hr/sitemap.xml | 200 | 24 | 0.9 |  |  |
| round2 | oglasnik | https://www.oglasnik.hr/kuce-prodaja | 200 / imp 200 | 259 | 0.7 | cloudflare,access_denied | Plavi oglasnik: besplatni mali oglasi |
| round2 | oglasnik | https://www.oglasnik.hr/zemljista-prodajem | 200 / imp 200 | 260 | 0.5 | cloudflare,access_denied | Plavi oglasnik: besplatni mali oglasi |
| round2 | oglasi_hr | https://oglasi.hr/kuce-prodaja | 404 / imp 404 | 25 | 0.7 |  | Oglasi.HR - besplatni mali oglasnik - kuće - prodaja |
| round2 | oglasi_hr | https://oglasi.hr/vikendice-prodaja | 404 / imp 404 | 25 | 0.5 |  | Oglasi.HR - besplatni mali oglasnik - vikendice - prodaja |
| round2 | oglasi_hr | https://oglasi.hr/nekretnine | 200 | 27 | 0.5 |  | Oglasi.HR - besplatni mali oglasnik - nekretnine |
| round2 | nekretnine24 | https://www.nekretnine24.hr/kuce | 200 | 22 | 1.4 |  | Kuće - oglasi za kuće / Nekretnine 24 |
| round2 | nekretnine24 | https://www.nekretnine24.hr/zemljista | 200 | 22 | 1.3 |  | Oglasi za građevinska i poljoprivredna zemljišta / Nekretnine 24 |
| round2 | vender | https://vender.hr/sitemap.rss | 200 | 19 | 1.4 |  | Vender |
| round2 | gohome | https://www.gohome.hr/nekretnine.aspx?q=kuca%20krk%20prodaja | 200 | 160 | 4.4 |  | kuca krk prodaja - GoHome |
| round2 | ekvadrat | https://ekvadrat.hr/ | ConnectionError: HTTPSConnectionPool(host='ekvadrat.hr', port=443): Max retries exceeded with url: / (Caused by NameResolutionError("HTTPSConnection(host='ekvadrat.hr', port=443): Failed to resolve 'ekvadrat.hr' ([Err / imp DNSError: Failed to perform, curl: (6) Could not resolve host: ekvadrat.hr. See https://curl.se/libcurl/c/libcurl-errors.html first for more details. | 0 | 2.3 |  |  |
| round2 | ekvadrat | http://www.ekvadrat.hr/ | ConnectionError: HTTPConnectionPool(host='www.ekvadrat.hr', port=80): Max retries exceeded with url: / (Caused by NameResolutionError("HTTPConnection(host='www.ekvadrat.hr', port=80): Failed to resolve 'www.ekvadrat.h / imp DNSError: Failed to perform, curl: (6) Could not resolve host: www.ekvadrat.hr. See https://curl.se/libcurl/c/libcurl-errors.html first for more details. | 0 | 0.9 |  |  |
