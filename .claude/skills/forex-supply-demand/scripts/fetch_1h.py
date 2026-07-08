# -*- coding: utf-8 -*-
# Stáhne 1h OHLC data instrumentu z Yahoo Finance (nativní 1h interval, žádná
# agregace). Poslední 1h close slouží zároveň jako aktuální cena.
#
# Podporované instrumenty (Yahoo symbol):
#   - forex páry:  EURUSD=X, GBPUSD=X, u JPY USDJPY=X (příp. JPY=X)
#   - index NASDAQ 100 (NQ):  NQ=F   (E-mini futures na CME)
#   - zlato (XAUUSD):  GC=F         (zlaté futures COMEX; XAUUSD=X Yahoo NEMÁ)
#
# Yahoo má nativní 1h interval, takže bary bereme přímo (na rozdíl od 4h, které
# by se musela dopočítávat agregací). 1h svíčky se s TradingView kryjí samy –
# hodinové hranice jsou v UTC i v použitých burzovních pásmech (celé hodiny)
# totožné, takže žádné zarovnávání na session není potřeba.
# POZOR: skript potřebuje síť -> spouštěj s vypnutým sandboxem.
#
# Použití:
#   python fetch_1h.py NQ=F [--days 60] [--out DIR] [--swing-window 6]
# Výstup: <DIR>/<symbol>_1h.json  (dict: symbol/interval/anchor_tz/bars) + výpis swingů.

import json, sys, argparse, datetime
import urllib.request
from zoneinfo import ZoneInfo

# Sestaví Yahoo chart API URL a stáhne JSON (nutná hlavička User-Agent).
# Yahoo povoluje 1h interval pro rozsah až 730 dní.
def stahni_1h(symbol, days):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?range={days}d&interval=1h")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

# Časové pásmo pro popisky osy X a datum v názvu souboru tak, aby dělení na dny
# odpovídalo burzovní session na TradingView:
#   - CME/COMEX futures (=F: NQ, ES, GC, …): America/Chicago
#   - forex (=X): America/New_York
#   - ostatní: UTC
# (U 1h svíček neřešíme hodinu otevření session – hodinové bary jsou zarovnané
# samy; pásmo slouží jen k rozřazení barů na dny v grafu.)
def vychozi_pasmo(symbol):
    s = symbol.upper()
    if s.endswith("=F"):
        return "America/Chicago"
    if s.endswith("=X"):
        return "America/New_York"
    return "UTC"

# Převod syrových 1h barů z Yahoo na seznam [ts, o, h, l, c].
# Neúplné bary (Yahoo vrací None u posledního/mezerových) přeskočíme a bary
# seřadíme podle času (Yahoo je vrací chronologicky, řazení je pojistka).
def parsuj_1h(data):
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    o, h, l, c = q["open"], q["high"], q["low"], q["close"]
    bars = []
    for i, t in enumerate(ts):
        if None in (o[i], h[i], l[i], c[i]):
            continue
        bars.append([t, o[i], h[i], l[i], c[i]])
    bars.sort()
    return bars

# Detekce swing high/low – lokální extrém v okně W barů na každou stranu.
# Na 1h je smysluplné okno širší než na 4h (víc a jemnějších svíček) -> default W=6.
def detekuj_swingy(bars, W=6):
    highs, lows = [], []
    for i in range(W, len(bars) - W):
        seg = bars[i - W:i + W + 1]
        if bars[i][2] == max(x[2] for x in seg):
            highs.append((bars[i][0], bars[i][2]))
        if bars[i][3] == min(x[3] for x in seg):
            lows.append((bars[i][0], bars[i][3]))
    return highs, lows

def fmt(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")

# Formát ceny pro výpis: velká čísla (index, zlato) 2 desetinná místa,
# malé forex kurzy 5 desetinných míst.
def pcena(v):
    return f"{v:.2f}" if abs(v) >= 100 else f"{v:.5f}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", help="Yahoo symbol, např. EURUSD=X, USDJPY=X, NQ=F, GC=F")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--out", default=".")
    # Časové pásmo pro dělení barů na dny v grafu; když se nezadá, zvolí se
    # automaticky podle symbolu (viz vychozi_pasmo). Přepiš jen když má tvůj
    # TradingView graf jiné pásmo.
    ap.add_argument("--anchor-tz", default=None,
                    help="časové pásmo pro dny v grafu (jinak auto dle symbolu)")
    # Okno pro detekci swingů; na 1h volíme širší (6) kvůli většímu šumu.
    ap.add_argument("--swing-window", type=int, default=6,
                    help="okno pro detekci swingů (barů na každou stranu)")
    a = ap.parse_args()

    # výchozí pásmo podle typu instrumentu, s možností CLI přepisu
    anchor_tz = a.anchor_tz or vychozi_pasmo(a.symbol)

    data = stahni_1h(a.symbol, a.days)
    bars = parsuj_1h(data)
    if not bars:
        print("CHYBA: žádná data", file=sys.stderr); sys.exit(1)

    safe = a.symbol.replace("=", "").replace("^", "")
    path = f"{a.out}/{safe}_1h.json"
    # Ukládáme jako dict s metadaty – render_pdf.py z něj bere anchor_tz pro
    # popisky osy X a datum v názvu souboru (dny dle burzovního pásma jako TradingView).
    out_obj = {"symbol": a.symbol, "interval": "1h",
               "anchor_tz": anchor_tz, "bars": bars}
    with open(path, "w") as f:
        json.dump(out_obj, f)

    px = bars[-1][4]
    last_ts = bars[-1][0]
    closes = [(t, c) for (t, o, h, l, c) in bars]
    rec30 = [c for t, c in closes if t >= last_ts - 30 * 86400]
    rec60 = [c for t, c in closes if t >= last_ts - 60 * 86400]

    print(f"soubor: {path}")
    print(f"pásmo pro dny v grafu: {anchor_tz} (dělení dnů dle TradingView)")
    print(f"1h barů: {len(bars)}  ({fmt(bars[0][0])} -> {fmt(last_ts)})")
    print(f"AKTUÁLNÍ 1h close: {pcena(px)}   (= aktuální cena)")
    print(f"30d rozpětí: {pcena(min(rec30))} – {pcena(max(rec30))}")
    print(f"60d rozpětí: {pcena(min(rec60))} – {pcena(max(rec60))}")

    # Kandidáti na zóny – swingy z posledních 30 dní (na 1h je jich hodně,
    # užší okno drží seznam přehledný a zaměřený na aktuální strukturu).
    highs, lows = detekuj_swingy(bars, a.swing_window)
    print("\n-- Swing HIGH nad cenou (kandidáti SUPPLY), posledních 30 dní --")
    for t, v in highs:
        if t >= last_ts - 30 * 86400 and v > px:
            print(f"  {fmt(t)}  {pcena(v)}")
    print("\n-- Swing LOW pod cenou (kandidáti DEMAND), posledních 30 dní --")
    for t, v in lows:
        if t >= last_ts - 30 * 86400 and v < px:
            print(f"  {fmt(t)}  {pcena(v)}")

    # navazující krok: algoritmická detekce a ohodnocení supply/demand zón
    print(f"\nDalší krok: python3 <skill>/scripts/find_zones.py {path}")

if __name__ == "__main__":
    main()
