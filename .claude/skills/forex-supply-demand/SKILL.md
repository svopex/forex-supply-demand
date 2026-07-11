---
name: forex-supply-demand
description: >-
  Návrh obchodních vstupů na forex párech (EUR/USD, GBP/USD, USD/JPY, …),
  na indexu NASDAQ 100 (NQ) i na zlatě (XAUUSD) na 1hodinovém timeframe pomocí
  supply/demand zón, s SL na hraně zóny a TP min. 2:1 (ideálně z jedné zóny do
  druhé), a s vygenerováním PDF s 1h grafem a obchodním plánem. Použij tento
  skill VŽDY, když uživatel chce najít vstupy / supply/demand zóny /
  support-resistance na forexu, NQ/Nasdaqu nebo zlatě, navrhnout long/short
  setup, udělat 1h analýzu měnového páru / indexu / komodity, nebo vytvořit
  PDF/graf s tržní situací — i když neřekne přímo „supply/demand" nebo „skill".
  Skript i postup už znají, odkud brát 1h data (Yahoo Finance) a jak vyřešit
  českou diakritiku v PDF.
---

# Supply/demand vstupy na 1H + PDF (forex, NQ, zlato)

Tento skill vede celý postup: získat aktuální 1h data instrumentu (forex pár,
index NASDAQ 100 / NQ, nebo zlato XAUUSD), **algoritmicky najít a ohodnotit
supply/demand zóny** (`find_zones.py` — base→impulz, čerstvost, invalidace,
skóre), navrhnout vstupy (SL na hraně zóny, TP ≥ 2:1, ideálně zóna-do-zóny)
a vygenerovat čisté vícestránkové PDF s grafem a plánem v češtině (1. strana
graf, pak případné **detailní grafy zón** — automaticky, když vznik zóny není
v hlavním výseku vidět —, další strany obchodní plán – ten „teče" přes tolik
stran, kolik si žádá objem textu).

## ⚠️ Slepé uličky, kterým se vyhni (dříve stály čas)

Toto je hlavní důvod existence skillu — nezkoušej znovu věci, co nefungují:

1. **Všechna data (1h řada i aktuální spot) ber z Yahoo přes
   `scripts/fetch_1h.py`.** Yahoo má nativní 1h interval, takže stahujeme přímo
   1h bary — žádná agregace se nedělá (na rozdíl od 4h varianty, kde se 1h musela
   dopočítávat). Aktuální spot cena = poslední 1h close, který skript vypíše;
   žádný další zdroj ceny není potřeba.
2. **Čeština v PDF: použij matplotlib s výchozím fontem DejaVu Sans** — ten má
   plnou českou diakritiku. **NEpoužívej reportlab s výchozí Helvetikou**
   (kóduje WinAnsi/cp1252, komolí ě š č ř ž ů). `render_pdf.py` to už řeší.
3. **Síť je v sandboxu blokovaná.** Stažení dat (`fetch_1h.py`) i
   `pip install` spouštěj s `dangerouslyDisableSandbox: true`.
4. **matplotlib i knihovny typicky chybí** → vytvoř venv a nainstaluj (viz níže).
   Nastav `MPLCONFIGDIR` na zapisovatelnou složku, jinak matplotlib varuje.
5. **PDF nejde vyrenderovat přes Read** (chybí poppler). `render_pdf.py` proto
   ukládá i PNG náhledy `_page1.png` (hlavní graf), pak případné detailní grafy
   zón a stránky obchodního plánu (`_page2.png`, `_page3.png`, … průběžně podle
   pořadí stránek v PDF) — všechny si přečti nástrojem Read a vizuálně
   zkontroluj rozvržení i diakritiku, než výsledek předáš. Plán se sází
   „tokem": nikdy se neuřízne, jen případně přeteče na další stranu.
6. **Zlato: Yahoo NEMÁ `XAUUSD=X`** (vrací HTTP 404). Použij `GC=F` (zlaté
   futures COMEX) — cena i struktura odpovídají spotovému zlatu. Do názvu
   souboru a nadpisů ale dej `XAUUSD` (přes pole `ticker` v configu).
7. **NQ ani zlato NEJSOU pipy.** Cena je v tisících (NQ ~30 000, zlato ~4 200) a
   riziko/zisk se počítá v **bodech** (NQ) nebo **USD** (zlato). Řeší to config
   (`pip_size`, `unit_label`, `price_decimals`, `trim_zeros`) — viz níže. Výchozí
   forexové `.4f` formátování by u velkých čísel vypadalo hnusně.
8. **1h svíčky se s TradingView kryjí samy — žádné zarovnávání na session není
   potřeba.** Hodinové bary začínají na celou hodinu a hodinové hranice jsou v UTC
   i v použitých burzovních pásmech (celé hodiny) totožné. `fetch_1h.py` proto
   žádnou hodinu otevření session neřeší; časové pásmo (`anchor_tz`) slouží už jen
   k rozdělení barů na **dny** v grafu (popisky osy X, datum v názvu souboru) —
   futures `=F` na `America/Chicago`, forex `=X` na `America/New_York`, zvolí se
   automaticky podle symbolu. **Pozor:** shoda s TV stejně nebude 100% — Yahoo 1h
   data mají díry (chybějící noční knoty) a `NQ=F`/`GC=F` je jiný continuous
   kontrakt než `NQ1!`/`GC1!` v TV. Tvar i časování svíček ale sedí.
9. **Root adresář projektu drž čistý.** Všechny pracovní soubory (venv,
   `.mplcache`, stažená data `*_1h.json`, `*_zones.json`, configy, PNG náhledy
   stran) patří do podadresáře `work/` v rootu projektu (je v `.gitignore`).
   Skripty zapisují do aktuálního adresáře, proto **všechny kroky spouštěj
   z `work/`**. Do rootu se na konci kopíruje **jen finální `*.pdf`** — po
   skončení běhu nesmí v rootu zbýt žádný jiný nově vytvořený soubor.

## Postup

### 1. Symbol instrumentu
Zvol symbol ve formátu Yahoo podle instrumentu:

| Instrument | Yahoo symbol | `ticker` do názvu | `pip_size` | `unit_label` | `price_decimals` | `trim_zeros` |
|---|---|---|---|---|---|---|
| Forex major (EUR/USD…) | `EURUSD=X` | `EURUSD` | `0.0001` | `pipů` | 4 | — |
| Forex JPY pár | `USDJPY=X` | `USDJPY` | `0.01` | `pipů` | 3 | — |
| NASDAQ 100 (NQ) | `NQ=F` | `NQ` | `1.0` | `bodů` | 2 | `true` |
| Zlato (XAUUSD) | `GC=F` | `XAUUSD` | `1.0` | `USD` | 2 | — |

Aktuální cenu i 30/60d rozpětí získáš rovnou z výstupu `fetch_1h.py` v kroku 3 —
samostatné volání ceny není potřeba. (Pozor: `XAUUSD=X` Yahoo nemá, ber `GC=F`.)

### 2. Příprava prostředí (jednorázově)
Všechno pracovní žije v podadresáři `work/` v rootu projektu — venv, cache,
stažená data, configy i PNG náhledy. Venv i data tam přežívají mezi běhy,
takže tento krok stačí udělat jen napoprvé (nebo když venv chybí).
```bash
mkdir -p <root>/work && cd <root>/work
python3 -m venv venv
./venv/bin/pip install matplotlib      # dangerouslyDisableSandbox: true
export MPLCONFIGDIR="$PWD/.mplcache"
```

### 3. Stažení 1h dat
Spouštěj z `work/` — datový JSON tak skončí ve `work/`, ne v rootu:
```bash
./venv/bin/python <skill>/scripts/fetch_1h.py NQ=F --days 60 --out .
# forex:  … fetch_1h.py EURUSD=X …     zlato:  … fetch_1h.py GC=F …
```
Spouštěj s `dangerouslyDisableSandbox: true`. Skript vypíše počet 1h barů,
použité **pásmo pro dělení dnů** (aby dny v grafu seděly na TradingView — viz
slepá ulička 8), poslední close (= aktuální cena), 30/60d rozpětí a orientační
swing high/low. Výstupní JSON je dict s polem `anchor_tz` a `bars`
(starší holý seznam `render_pdf.py` pořád načte). Zarovnávání není potřeba řešit.

### 4. Algoritmická detekce zón (hlavní zdroj kandidátů)
Opět z `work/` — `<symbol>_zones.json` vznikne vedle datového souboru:
```bash
python3 <skill>/scripts/find_zones.py EURUSDX_1h.json
```
Čistý stdlib — běží **bez venv i bez vypínání sandboxu**. Najde skutečné S/D
struktury (base 1–6 svíček s malými těly → impulzivní odchod měřený v ATR),
zóny proražené závěrem svíčky za distální hranou rovnou vyřadí (invalidace)
a zbylé ohodnotí **skóre 0–100** (síla odchodu, čerstvost = počet retestů,
kompaktnost base, reverzní vzor DBR/RBD, konfluence se swingy, stáří).
Vypíše:

- top SUPPLY nad cenou a top DEMAND pod cenou s hranami **prox/distal**
  (prox = krajní tělo base, tam se vstupuje; distal = krajní knot, za něj SL),
- **ATR(14) a doporučený SL buffer** (~0.30×ATR) — použij ho místo odhadu,
- **bias** (EMA50/EMA200 + struktura swingů) — rychlá náhrada HTF kontroly,
- zóny, ve kterých cena právě je (ty pro pending vstup nepoužívej),
- **párování zóna-do-zóny s hotovým RRR** pro long i short,
- vedle uloží strojově čitelný `<symbol>_zones.json` (stejná data, pro
  přesné hodnoty do configu). Ze zvolené zóny **zkopíruj do setupu v configu
  i `base_od` a `base_do`** (unix timestampy vzniku base) — `render_pdf.py`
  podle nich pozná, zda je vznik zóny v hlavním grafu vidět, a když ne,
  přidá detailní stránku s výřezem kolem vzniku zóny.

Když je kandidátů málo (typicky u instrumentu na kraji range), zkus
`--min-depart 1.4` (default 1.8) nebo `--days 60` (default 45). `--top N`
zvětší výpis, `--swing-window` ladí konfluenci.

### 5. Průzkum internetu (kontext + konfluence)
Přes `WebSearch` dohledej aktuální support/resistance a bias (trend, RSI, MACD,
nadcházející události ECB/Fed/NFP). Použij víc zdrojů (RoboForex, DailyForex,
FXStreet, LiteFinance, TradingView …) a hledej **shodu** webových úrovní se
zónami z `find_zones.py`. V PDF/shrnutí uveď zdroje jako odkazy.

### 6. Výběr zón a úrovní (viz metodika níže)
Vyber jednu **supply** (nad cenou, pro short) a jednu **demand** (pod cenou,
pro long) — primárně z kandidátů `find_zones.py`. Definuj zónu, vstup, SL, TP.

### 7. Vygenerování PDF
Napiš `work/config.json` (pole popisuje sekce „Config pro render_pdf.py" níže)
a spusť z `work/` — PDF i PNG náhledy tak vzniknou ve `work/`:
```bash
./venv/bin/python <skill>/scripts/render_pdf.py config.json
```
Výstup se **pojmenuje automaticky** jako `<YYYYMMDD>_<ticker>.pdf` (datum =
poslední bar dat), např. `20260703_EURUSD.pdf`, `20260703_NQ.pdf`.

**Detailní grafy zón:** když vznik některé zóny (base + impulzní odchod) není
v hlavním výseku vidět — base začíná před `display_start`, nebo zónu ořízne
ruční `ylim` —, skript za hlavní graf automaticky přidá stránku s detailem:
výřez `detail_bars_before` svíček před base a `detail_bars_after` po ní
(výchozí 40/40), base zvýrazněná šedým svislým pásem, zóna, vstup i SL. Vznik
zóny bere z `base_od`/`base_do` setupu (zkopírované ze `<symbol>_zones.json`);
bez nich si ho dohledá sám podle poslední souvislé skupiny svíček protínajících
zónu. Zóny viditelné v hlavním grafu žádnou stránku navíc nedostanou.

Vedle PDF vzniknou PNG náhledy `_page1.png` (hlavní graf) a `_page2.png`,
`_page3.png`, … (případné detaily zón a stránky plánu, číslované průběžně;
skript na konci vypíše počet stran i detailů) — všechny si přečti a **vizuálně
zkontroluj** rozvržení i diakritiku (klidně přímo z `work/`, do rootu je
nekopíruj). Nakonec zkopíruj **jen finální PDF** do root adresáře projektu:
```bash
cp <YYYYMMDD>_<ticker>.pdf ..
```
a ověř, že v rootu nezůstal žádný jiný nově vytvořený soubor — data, configy,
PNG náhledy i venv zůstávají ve `work/`.

## Metodika supply/demand (1H)

### Jak vybrat z kandidátů find_zones.py

- **Řaď se skóre, ale rozhoduj úsudkem:** skóre je ranking, ne verdikt. Při
  podobném skóre dej přednost zóně **blíž ceně** (rychlejší naplnění) a s
  **konfluencí webových úrovní** z kroku 5.
- **Čerstvost je klíčová:** ber zóny s **0–1 retestem**. Každý návrat ceny
  spotřebovává čekající příkazy v zóně; 2+ retesty = slabá zóna (jen s velmi
  silnou další konfluencí).
- **Reverzní vzory (DBR/RBD) > pokračovací (RBR/DBD) > `base`** (impulz z
  ploché konsolidace).
- **Preferuj zóny po směru biasu**, který skript vypíše (medvědí bias →
  primární setup short ze supply; protisměrný setup uveď jako sekundární).
- **Zóny označené „cena uvnitř" nepoužívej** pro pending vstup — cena už v
  zóně je, vstup by neměl žádnou reakci k odpracování.
- **Vizuálně ověř** vybrané zóny na vykresleném grafu (PNG náhled): hrany smí
  být jemně doladěné na shluk knotů nebo kulaté číslo, ale drž se hodnot z
  `<symbol>_zones.json` jako základu.
- Detekce je deterministická z dat — **webový průzkum ji doplňuje** (události,
  sentiment, HTF úrovně), nikdy nenahrazuje.

### Konstrukce obchodu

- **Demand zóna (LONG):** base před silným býčím impulzem (drop-base-rally).
- **Supply zóna (SHORT):** base před silným medvědím impulzem (rally-base-drop).
- **Hrany zóny:** proximální hrana = blíž ceně, krajní **tělo** base (tam se
  vstupuje); distální hrana = dál od ceny, krajní **knot** base (za ni jde SL).
- **Vstup:** limitní příkaz na proximální hraně (Sell Limit u supply, Buy Limit
  u demand).
- **SL za distální hranou:** buffer **~0.30×ATR(14)** — konkrétní hodnotu
  vypisuje `find_zones.py` (orientačně: forex pár pipů, NQ ~40 bodů, zlato
  ~5–10 USD). Chrání před běžným proražením knotem; na 1h jsou zóny užší a
  stopy těsnější než na vyšších timeframech.
- **TP:** minimálně **2:1**, ideálně **proximální hrana protilehlé zóny**
  („zóna do zóny") — RRR pro páry zón počítá `find_zones.py` rovnou.
- **Jednotka rizika/zisku:** forex = pipy, NQ = body, zlato = USD (za unci).
  Řídí ji `unit_label` v configu; RRR se počítá vždy stejně z `pip_size`.
- Cena bývá uprostřed rozpětí → jde o **čekající (pending) příkazy**, ne okamžitý
  vstup. Řekni to uživateli.
- **1H je nižší timeframe:** setupy se plní a doběhnou rychleji, ale je víc šumu
  a falešných proražení. Bias potvrď na vyšším timeframe (4H/D) a dej pozor na
  intradenní zprávy (CPI, FOMC, NFP), které 1h strukturu snadno rozbijí.

## Config pro render_pdf.py

Config piš rovnou podle polí níže (žádné šablony nejsou) a ulož ho do
`work/config.json`.

**Povinná pole:** `symbol`, `data_file`, `current_price`, `as_of`, `source`,
`display_start`, `setups` (seznam; každý má `zone_type` SUPPLY/DEMAND, `side`
SHORT/LONG, `zone [low,high]`, `entry`, `sl`, `tp`, `rationale`). 
`rationale` - rozepiš opravdu detailně, ať je jasné, proč zóna vznikla a proč je vhodná 
pro obchod. Uveď i konfluence z webu, swing high/low, a další relevantní faktory. 

Do každého setupu navíc **vždy přidej `base_od` a `base_do`** (unix timestampy
vzniku base, zkopírované ze `<symbol>_zones.json`) — podle nich skript pozná,
zda je vznik zóny v hlavním výseku vidět, a případně vykreslí detailní stránku
(bez těchto polí použije méně přesnou autodetekci podle dotyku svíček se zónou).

**Volitelná pole:**
- `ticker` — kód do názvu souboru a nadpisů (`EURUSD`, `NQ`, `XAUUSD`). Když
  chybí, odvodí se z názvu datového souboru.
- `pip_size` — velikost 1 pipu/bodu (forex 0.0001, JPY 0.01, NQ i zlato 1.0).
  Podle něj se počítá riziko/zisk a RRR.
- `unit_label` — jednotka v plánu (`pipů` / `bodů` / `USD`). Výchozí `pipů`.
- `price_decimals` — počet desetinných míst ceny. Když chybí, dopočítá se z
  `pip_size` (0.0001→4, 0.01→2, ≥1→2).
- `trim_zeros` — `true` ořeže koncové nuly (hezké u NQ: `30 480` místo
  `30 480.00`). U forexu nech vypnuté, ať zůstane `1.1440`.
- `ylim` — rozsah osy Y (jinak auto z výseku).
- `anchor_tz` — **jen když chceš přebít** pásmo pro dělení dnů z dat (pásmo pro
   popisky osy X a datum v názvu). Normálně se bere z datového JSONu (`anchor_tz`
   uložený při stažení), takže sem nic psát netřeba.
- `output` — **jen když chceš přebít** automatický název `<YYYYMMDD>_<ticker>.pdf`.
- `notes` — seznam poznámek do plánu.
- `detail_bars_before` / `detail_bars_after` — kolik svíček před base a po ní
  ukáže detailní graf zóny (výchozí 40/40). Měň jen, když je výřez moc hustý
  nebo naopak neukazuje celý impulz.

Velká čísla (NQ, zlato) se automaticky formátují s mezerou po tisících
(`30 480`, `4 187.30`).

`display_start` zvol tak, aby výsek ukázal obě zóny i poslední impulz — na 1h
obvykle posledních ~5–12 dní (delší okno je už příliš husté na svíčky).
**Nenatahuj výsek jen kvůli zóně vzniklé hluboko v historii** — její vznik
pokryje automatická detailní stránka. `ylim` nastav těsně kolem obou zón, ať
jsou svíčky čitelné (jinak se dopočítá automaticky z výseku).
