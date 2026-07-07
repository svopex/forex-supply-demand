# -*- coding: utf-8 -*-
# Stáhne 1h OHLC data instrumentu z Yahoo Finance a agreguje je na 4h.
# Poslední 4h close slouží zároveň jako aktuální cena.
#
# Podporované instrumenty (Yahoo symbol):
#   - forex páry:  EURUSD=X, GBPUSD=X, u JPY USDJPY=X (příp. JPY=X)
#   - index NASDAQ 100 (NQ):  NQ=F   (E-mini futures na CME)
#   - zlato (XAUUSD):  GC=F         (zlaté futures COMEX; XAUUSD=X Yahoo NEMÁ)
#
# Yahoo nemá nativní 4h interval, proto stahujeme 1h a agregujeme na 4h.
# POZOR: skript potřebuje síť -> spouštěj s vypnutým sandboxem.
#
# Použití:
#   python fetch_4h.py NQ=F [--days 120] [--out DIR]
# Výstup: <DIR>/<symbol>_4h.json  (pole [ts, o, h, l, c]) + výpis swingů.

import json, sys, argparse, datetime
import urllib.request
from zoneinfo import ZoneInfo

# Sestaví Yahoo chart API URL a stáhne JSON (nutná hlavička User-Agent)
def stahni_1h(symbol, days):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?range={days}d&interval=1h")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

# Výchozí zarovnání 4h svíček podle typu instrumentu tak, aby časově sedělo na
# TradingView (bary začínají na otevření burzovní session, ne o půlnoci UTC):
#   - CME/COMEX futures (=F: NQ, ES, GC, …): Globex open 17:00 Chicago
#   - forex (=X): standardní forexový den, open 17:00 New York
#   - ostatní: půlnoc UTC (původní chování)
# Vrací dvojici (název_pásma, hodina_startu_session).
def vychozi_kotva(symbol):
    s = symbol.upper()
    if s.endswith("=F"):
        return ("America/Chicago", 17)
    if s.endswith("=X"):
        return ("America/New_York", 17)
    return ("UTC", 0)

# Agregace 1h barů do 4h košů zarovnaných na burzovní session.
# Hranice košů leží na anchor_hour (a +4h) v pásmu anchor_tz a jsou DST-aware –
# díky tomu svíčky časově odpovídají TradingView (viz vychozi_kotva).
def agreguj_4h(data, anchor_tz, anchor_hour):
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    o, h, l, c = q["open"], q["high"], q["low"], q["close"]
    tz = ZoneInfo(anchor_tz)
    buckets, order = {}, []
    for i, t in enumerate(ts):
        # přeskočíme neúplné bary (Yahoo vrací None u posledního/mezerových)
        if None in (o[i], h[i], l[i], c[i]):
            continue
        # lokální hodina baru v cílovém pásmu -> posun v rámci 4h koše (0..3 h);
        # protože 24 je dělitelné 4, stačí porovnat hodinu vůči anchor_hour mod 4
        loc_hour = datetime.datetime.fromtimestamp(t, tz).hour
        delta = (loc_hour - anchor_hour) % 4
        b = t - delta * 3600  # UTC začátek 4h koše zarovnaný na session
        if b not in buckets:
            buckets[b] = [b, o[i], h[i], l[i], c[i]]
            order.append(b)
        else:
            bb = buckets[b]
            bb[2] = max(bb[2], h[i])  # high
            bb[3] = min(bb[3], l[i])  # low
            bb[4] = c[i]              # close = poslední 1h close v koši
    order.sort()
    return [buckets[b] for b in order]

# Detekce swing high/low – lokální extrém v okně W barů na každou stranu
def detekuj_swingy(bars, W=3):
    highs, lows = [], []
    for i in range(W, len(bars) - W):
        seg = bars[i - W:i + W + 1]
        if bars[i][2] == max(x[2] for x in seg):
            highs.append((bars[i][0], bars[i][2]))
        if bars[i][3] == min(x[3] for x in seg):
            lows.append((bars[i][0], bars[i][3]))
    return highs, lows

def fmt(t):
    return datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d %H:%M")

# Formát ceny pro výpis: velká čísla (index, zlato) 2 desetinná místa,
# malé forex kurzy 5 desetinných míst.
def pcena(v):
    return f"{v:.2f}" if abs(v) >= 100 else f"{v:.5f}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", help="Yahoo symbol, např. EURUSD=X, USDJPY=X, NQ=F, GC=F")
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--out", default=".")
    # Zarovnání 4h svíček; když se nezadá, zvolí se automaticky podle symbolu tak,
    # aby odpovídalo TradingView (viz vychozi_kotva). Přepiš jen když má tvůj
    # TradingView graf jinou session/časové pásmo.
    ap.add_argument("--anchor-tz", default=None,
                    help="časové pásmo pro zarovnání 4h svíček (jinak auto dle symbolu)")
    ap.add_argument("--anchor-hour", type=int, default=None,
                    help="hodina otevření session pro zarovnání (jinak auto dle symbolu)")
    a = ap.parse_args()

    # výchozí kotva podle typu instrumentu, s možností CLI přepisu
    def_tz, def_hour = vychozi_kotva(a.symbol)
    anchor_tz = a.anchor_tz or def_tz
    anchor_hour = a.anchor_hour if a.anchor_hour is not None else def_hour

    data = stahni_1h(a.symbol, a.days)
    bars = agreguj_4h(data, anchor_tz, anchor_hour)
    if not bars:
        print("CHYBA: žádná data", file=sys.stderr); sys.exit(1)

    safe = a.symbol.replace("=", "").replace("^", "")
    path = f"{a.out}/{safe}_4h.json"
    # Ukládáme jako dict s metadaty o zarovnání – render_pdf.py z něj bere
    # anchor_tz pro popisky osy X a datum v názvu souboru (dny dle burzovního pásma).
    out_obj = {"symbol": a.symbol, "interval": "4h",
               "anchor_tz": anchor_tz, "anchor_hour": anchor_hour, "bars": bars}
    with open(path, "w") as f:
        json.dump(out_obj, f)

    px = bars[-1][4]
    last_ts = bars[-1][0]
    closes = [(t, c) for (t, o, h, l, c) in bars]
    rec30 = [c for t, c in closes if t >= last_ts - 30 * 86400]
    rec60 = [c for t, c in closes if t >= last_ts - 60 * 86400]

    print(f"soubor: {path}")
    print(f"zarovnání 4h: {anchor_hour:02d}:00 {anchor_tz} (session dle TradingView)")
    print(f"4h barů: {len(bars)}  ({fmt(bars[0][0])} -> {fmt(last_ts)})")
    print(f"AKTUÁLNÍ 4h close: {pcena(px)}   (= aktuální cena)")
    print(f"30d rozpětí: {pcena(min(rec30))} – {pcena(max(rec30))}")
    print(f"60d rozpětí: {pcena(min(rec60))} – {pcena(max(rec60))}")

    highs, lows = detekuj_swingy(bars)
    print("\n-- Swing HIGH nad cenou (kandidáti SUPPLY), posledních 60 dní --")
    for t, v in highs:
        if t >= last_ts - 60 * 86400 and v > px:
            print(f"  {fmt(t)}  {pcena(v)}")
    print("\n-- Swing LOW pod cenou (kandidáti DEMAND), posledních 60 dní --")
    for t, v in lows:
        if t >= last_ts - 60 * 86400 and v < px:
            print(f"  {fmt(t)}  {pcena(v)}")

if __name__ == "__main__":
    main()
