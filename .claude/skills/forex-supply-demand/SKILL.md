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
index NASDAQ 100 / NQ, nebo zlato XAUUSD), najít supply/demand zóny, navrhnout
vstupy (SL na hraně zóny, TP ≥ 2:1, ideálně zóna-do-zóny) a vygenerovat čisté
vícestránkové PDF s grafem a plánem v češtině (1. strana graf, další strany
obchodní plán – ten „teče" přes tolik stran, kolik si žádá objem textu).

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
   ukládá i PNG náhledy `_page1.png` (graf) a `_page2.png`, `_page3.png`, …
   (obchodní plán – kolik stran, tolik PNG) — všechny si přečti nástrojem Read
   a vizuálně zkontroluj rozvržení i diakritiku, než výsledek předáš. Plán se
   sází „tokem": nikdy se neuřízne, jen případně přeteče na další stranu.
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
```bash
cd <scratchpad>
python3 -m venv venv
./venv/bin/pip install matplotlib      # dangerouslyDisableSandbox: true
export MPLCONFIGDIR="$PWD/.mplcache"
```

### 3. Stažení 1h dat
```bash
./venv/bin/python <skill>/scripts/fetch_1h.py NQ=F --days 60 --out .
# forex:  … fetch_1h.py EURUSD=X …     zlato:  … fetch_1h.py GC=F …
```
Spouštěj s `dangerouslyDisableSandbox: true`. Skript vypíše počet 1h barů,
použité **pásmo pro dělení dnů** (aby dny v grafu seděly na TradingView — viz
slepá ulička 8), poslední close (= aktuální cena), 30/60d rozpětí a **detekované
swing high/low** nad a pod cenou z posledních 30 dní — to jsou kandidáti na zóny.
Na 1h je swingů hodně, proto je okno detekce širší (default 6 barů na stranu, lze
změnit `--swing-window`). Výstupní JSON je dict s polem `anchor_tz` a `bars`
(starší holý seznam `render_pdf.py` pořád načte). Zarovnávání není potřeba řešit.

### 4. Průzkum internetu (kontext + konfluence)
Přes `WebSearch` dohledej aktuální support/resistance a bias (trend, RSI, MACD,
nadcházející události ECB/Fed/NFP). Použij víc zdrojů (RoboForex, DailyForex,
FXStreet, LiteFinance, TradingView …) a hledej **shodu** webových úrovní s reálnými swingy z
dat. V PDF/shrnutí uveď zdroje jako odkazy.

### 5. Výběr zón a úrovní (viz metodika níže)
Vyber jednu **supply** (nad cenou, pro short) a jednu **demand** (pod cenou,
pro long). Definuj zónu, vstup, SL, TP.

### 6. Vygenerování PDF
Napiš `config.json` (šablony podle instrumentu: `assets/config_example.json` pro
forex, `assets/config_example_nq.json` pro NQ, `assets/config_example_xauusd.json`
pro zlato) a spusť:
```bash
./venv/bin/python <skill>/scripts/render_pdf.py config.json
```
Výstup se **pojmenuje automaticky** jako `<YYYYMMDD>_<ticker>.pdf` (datum =
poslední bar dat), např. `20260703_EURUSD.pdf`, `20260703_NQ.pdf`. Vedle vzniknou
PNG náhledy `_page1.png` (graf) a `_page2.png`, `_page3.png`, … (plán, kolik stran
tolik PNG; skript na konci vypíše počet stran) — všechny si přečti a **vizuálně
zkontroluj** rozvržení i diakritiku. Nakonec zkopíruj finální PDF do pracovního
adresáře uživatele.

## Metodika supply/demand (1H)

- **Demand zóna (LONG):** base před silným býčím impulzem (drop-base-rally),
  typicky poslední výrazné swing low / origin aktuálního odrazu, 
  origin posledního výrazného růstu, 
  nebo opakovaně odmítnutý odpor (2+ rejekce ve stejném pásmu).
  Konfluences klíčovou `webovou` podporou zónu posiluje.
- **Supply zóna (SHORT):** base před silným medvědím impulzem (rally-base-drop),
  typicky poslední výrazné swing high / origin aktuálního odrazu, 
  origin posledního výrazného poklesu, 
  nebo opakovaně odmítnutý odpor (2+ rejekce ve stejném pásmu). 
  Konfluences klíčovou `webovou` podporou zónu posiluje.
- **Hrany zóny:** proximální hrana = blíž ceně (tam se vstupuje), distální hrana
  = dál od ceny (za ni jde SL).
- **Vstup:** limitní příkaz na proximální hraně (Sell Limit u supply, Buy Limit
  u demand).
- **SL na hraně zóny:** pár pipů (u NQ ~40–50 bodů, u zlata ~10–15 USD) **za
  distální hranu**, aby ho nevyhodilo běžné proražení knotem. Na 1h jsou zóny
  užší a stopy těsnější než na vyšších timeframech.
- **TP:** minimálně **2:1**, ideálně **proximální hrana protilehlé zóny**
  („zóna do zóny") — vznikne symetrický range trade s vysokým RRR.
- **Jednotka rizika/zisku:** forex = pipy, NQ = body, zlato = USD (za unci).
  Řídí ji `unit_label` v configu; RRR se počítá vždy stejně z `pip_size`.
- Cena bývá uprostřed rozpětí → jde o **čekající (pending) příkazy**, ne okamžitý
  vstup. Řekni to uživateli.
- **1H je nižší timeframe:** setupy se plní a doběhnou rychleji, ale je víc šumu
  a falešných proražení. Bias potvrď na vyšším timeframe (4H/D) a dej pozor na
  intradenní zprávy (CPI, FOMC, NFP), které 1h strukturu snadno rozbijí.

## Config pro render_pdf.py

Šablony: `assets/config_example.json` (forex), `assets/config_example_nq.json`
(NQ), `assets/config_example_xauusd.json` (zlato).

**Povinná pole:** `symbol`, `data_file`, `current_price`, `as_of`, `source`,
`display_start`, `setups` (seznam; každý má `zone_type` SUPPLY/DEMAND, `side`
SHORT/LONG, `zone [low,high]`, `entry`, `sl`, `tp`, `rationale`). 
`rationale` - rozepiš opravdu detailně, ať je jasné, proč zóna vznikla a proč je vhodná 
pro obchod. Uveď i konfluence z webu, swing high/low, a další relevantní faktory. 

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

Velká čísla (NQ, zlato) se automaticky formátují s mezerou po tisících
(`30 480`, `4 187.30`).

`display_start` zvol tak, aby výsek ukázal obě zóny i poslední impulz — na 1h
obvykle posledních ~5–12 dní (delší okno je už příliš husté na svíčky). `ylim`
nastav těsně kolem obou zón, ať jsou svíčky čitelné (jinak se dopočítá
automaticky z výseku).
