# -*- coding: utf-8 -*-
# Algoritmická detekce supply/demand zón z 1h dat (výstup fetch_1h.py).
#
# Na rozdíl od prosté detekce swingů hledá skutečné S/D struktury:
#   base (1–6 svíček s malými těly) -> impulzivní odchod (měřeno v ATR).
# Každou zónu pak ohodnotí (0–100 bodů) podle:
#   - síly odchodu z báze (kolik ATR urazil impulz)         max 30 b
#   - čerstvosti (počet návratů ceny do zóny po vzniku)      max 25 b
#   - kompaktnosti base (méně svíček = větší nerovnováha)    max 15 b
#   - typu vzoru (reverzní DBR/RBD > pokračovací RBR/DBD)    max 10 b
#   - konfluence se swing high/low                           max 10 b
#   - stáří (novější struktura = relevantnější)              max 10 b
#   - penalizace: široká zóna (>1.5 ATR) -10 b
# Zóny proražené závěrem svíčky za distální hranou VYŘAZUJE (invalidace).
#
# Hrany zóny: proximální = krajní TĚLO base (blíž ceně, tam se vstupuje),
# distální = krajní KNOT base (dál od ceny, za ni jde SL). Konvence
# „tělo-proximálně, knot-distálně" dává na 1h užší zóny a lepší RRR.
#
# Dále vypíše ATR (pro volbu SL bufferu), HTF bias (EMA50/EMA200 + struktura
# swingů) a párování zóna-do-zóny s vypočteným RRR pro long i short.
#
# Skript je čistý stdlib: běží BEZ venv i BEZ vypínání sandboxu (žádná síť).
#
# Použití:
#   python3 find_zones.py EURUSDX_1h.json [--top 5] [--pip-size 0.0001]
#                         [--min-depart 1.8] [--days 45] [--swing-window 6]
# Výstup: přehled na stdout + <symbol>_zones.json (strojově čitelné totéž).

import json, sys, argparse, datetime, os

# ---------- pomocné výpočty ----------

# True Range + Wilderovo vyhlazení -> ATR série (index i = ATR platné pro bar i).
def atr_serie(bars, period=14):
    trs = []
    for i, (t, o, h, l, c) in enumerate(bars):
        if i == 0:
            trs.append(h - l)
        else:
            pc = bars[i - 1][4]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = [None] * len(bars)
    if len(bars) < period:
        return atr
    atr[period - 1] = sum(trs[:period]) / period
    for i in range(period, len(bars)):
        atr[i] = (atr[i - 1] * (period - 1) + trs[i]) / period
    return atr

# Exponenciální klouzavý průměr přes zavírací ceny.
def ema(vals, n):
    k = 2 / (n + 1)
    e = vals[0]
    out = [e]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out

# Swing high/low – lokální extrém v okně W barů na každou stranu
# (stejná logika jako ve fetch_1h.py, tady slouží ke konfluenci a biasu).
def detekuj_swingy(bars, W):
    highs, lows = [], []
    for i in range(W, len(bars) - W):
        seg = bars[i - W:i + W + 1]
        if bars[i][2] == max(x[2] for x in seg):
            highs.append((bars[i][0], bars[i][2]))
        if bars[i][3] == min(x[3] for x in seg):
            lows.append((bars[i][0], bars[i][3]))
    return highs, lows

def fmt_ts(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")

# ---------- detekce zón ----------

# Parametry detekce (násobky ATR); --min-depart lze měnit z CLI.
BASE_BODY_MAX = 0.65   # max tělo base svíčky (× ATR)
BASE_MAX = 6           # max počet svíček v base
LEG_OUT_CHECK = 5      # do kolika barů po base musí cena rozhodně opustit zónu
IMPULSE_BODY = 1.0     # min tělo impulzní svíčky v prvních 3 barech odchodu (× ATR)
DEPART_WIN = 24        # okno pro měření celkové síly odchodu (barů)
LEGIN_WIN = 6          # okno pro klasifikaci příchozího pohybu (drop/rally)
WIDTH_MAX = 3.0        # zóny širší než tolik ATR rovnou zahodit
WIDTH_PENALTY = 1.5    # širší než tolik ATR = -10 bodů skóre

# Zkusí z base bars[i:j] vytvořit zónu daného směru; vrátí dict nebo None.
# smer = +1 demand (odchod nahoru), -1 supply (odchod dolů).
def zkus_zonu(bars, atr, i, j, smer, min_depart):
    # ATR bereme z impulzní svíčky (index j) — base může začínat ještě ve
    # warmup období ATR, kde je hodnota None
    a = atr[j]
    base = bars[i:j]
    base_lo = min(b[3] for b in base)
    base_hi = max(b[2] for b in base)
    body_hi = max(max(b[1], b[4]) for b in base)
    body_lo = min(min(b[1], b[4]) for b in base)
    # hrany: proximální = tělo, distální = knot (podle směru zóny)
    prox = body_hi if smer > 0 else body_lo
    distal = base_lo if smer > 0 else base_hi
    out = bars[j:j + DEPART_WIN]
    if len(out) < 2:
        return None
    # 1) rozhodný únik: close za knotovou hranou base do LEG_OUT_CHECK barů
    unik = None
    for k, b in enumerate(out[:LEG_OUT_CHECK]):
        if smer > 0 and b[4] > base_hi + 0.25 * a:
            unik = k; break
        if smer < 0 and b[4] < base_lo - 0.25 * a:
            unik = k; break
    if unik is None:
        return None
    # 2) impulzní svíčka správným směrem hned na začátku odchodu
    if not any((b[4] - b[1]) * smer >= IMPULSE_BODY * a for b in out[:3]):
        return None
    # 3) celková síla odchodu od proximální hrany (v ATR)
    if smer > 0:
        extrem = max(b[2] for b in out)
        depart = (extrem - prox) / a
    else:
        extrem = min(b[3] for b in out)
        depart = (prox - extrem) / a
    if depart < min_depart:
        return None
    # šířka zóny v ATR – moc široká base není obchodovatelná
    sirka = abs(prox - distal)
    if sirka > WIDTH_MAX * a or sirka < 0.10 * a:
        return None
    # klasifikace příchozího pohybu -> reverzní vs pokračovací vzor
    pred = bars[max(0, i - LEGIN_WIN):i]
    vzor = "?"
    if len(pred) >= 2:
        zmena = pred[-1][4] - pred[0][4]
        if smer > 0:
            vzor = "DBR" if zmena < -0.8 * a else ("RBR" if zmena > 0.8 * a else "base")
        else:
            vzor = "RBD" if zmena > 0.8 * a else ("DBD" if zmena < -0.8 * a else "base")
    return {
        "type": "DEMAND" if smer > 0 else "SUPPLY",
        "smer": smer,
        "prox": prox, "distal": distal,
        "zone_low": min(prox, distal), "zone_high": max(prox, distal),
        "base_od": base[0][0], "base_do": base[-1][0],
        "base_svicek": len(base),
        "i": i, "j": j,
        "atr_vzniku": a,
        "depart_atr": depart,
        "vzor": vzor,
        "sirka": sirka,
    }

# Projde bary za zónou: spočítá retesty (návraty ceny do zóny) a zjistí
# invalidaci (close za distální hranou = zóna proražena, vyřadit).
def retesty_a_invalidace(bars, z):
    smer, prox, distal, a = z["smer"], z["prox"], z["distal"], z["atr_vzniku"]
    odesla = False    # cena už zónu po vzniku rozhodně opustila
    uvnitr = False    # stavový automat: právě je cena v zóně
    retesty = 0
    for b in bars[z["j"]:]:
        t, o, h, l, c = b
        if not odesla:
            # počkej, až se cena vzdálí od proximální hrany, teprve pak počítej návraty
            if (c - prox) * smer > 0.3 * a:
                odesla = True
            continue
        # invalidace: závěr svíčky za distální hranou
        if (distal - c) * smer > 0:
            return retesty, True
        # návrat do zóny: extrém svíčky dosáhl proximální hrany
        dotyk = (l <= prox) if smer > 0 else (h >= prox)
        if dotyk and not uvnitr:
            retesty += 1
            uvnitr = True
        elif not dotyk and uvnitr:
            # cena zónu zase opustila správným směrem
            if (c - prox) * smer > 0:
                uvnitr = False
    return retesty, False

# Složené skóre zóny 0–100 (viz hlavička souboru).
def skore(z, swingy, last_ts):
    s = min(z["depart_atr"] / 3.0, 1.0) * 30
    s += {0: 25, 1: 15, 2: 5}.get(z["retesty"], 0)
    s += {1: 15, 2: 15, 3: 10, 4: 10}.get(z["base_svicek"], 5)
    s += 10 if z["vzor"] in ("DBR", "RBD") else 5
    # konfluence: swing extrém uvnitř zóny (s tolerancí 0.25 ATA)
    tol = 0.25 * z["atr_vzniku"]
    lo, hi = z["zone_low"] - tol, z["zone_high"] + tol
    z["swing_konfluence"] = any(lo <= v <= hi for _, v in swingy)
    s += 10 if z["swing_konfluence"] else 0
    stari = (last_ts - z["base_do"]) / 86400
    z["stari_dni"] = stari
    s += 10 if stari <= 7 else (5 if stari <= 21 else 0)
    if z["sirka"] > WIDTH_PENALTY * z["atr_vzniku"]:
        s -= 10
    return round(s, 1)

# Hlavní detekční smyčka „impulz -> base zpětně": najde impulzní svíčku
# (velké tělo v násobku ATR) a base sbírá dozadu od ní — base je tak vždy
# přilehlá k impulzu (dopředný sken dřív bral i konsolidaci daleko před ním).
# Další svíčky téhož impulzního legu base nemají (za nimi je velké tělo),
# takže se jeden leg nepočítá vícekrát; zbylé překryvy řeší merge.
def najdi_zony(bars, atr, min_depart, period=14):
    zony = []
    for k in range(period + 1, len(bars) - 1):
        a = atr[k]
        if a is None or a <= 0:
            continue
        body = bars[k][4] - bars[k][1]
        for smer in (+1, -1):
            # impulzní svíčka správným směrem
            if body * smer < IMPULSE_BODY * a:
                continue
            # base: malé svíčky těsně před impulzem, zpětně max BASE_MAX
            i = k - 1
            while (i >= 0 and k - i <= BASE_MAX
                   and abs(bars[i][4] - bars[i][1]) <= BASE_BODY_MAX * a):
                i -= 1
            if i == k - 1:
                continue          # před impulzem není žádná base svíčka
            z = zkus_zonu(bars, atr, i + 1, k, smer, min_depart)
            if z:
                z["retesty"], z["invalid"] = retesty_a_invalidace(bars, z)
                if not z["invalid"]:
                    zony.append(z)
    return zony

# Odstranění překryvů stejného typu: řadí dle skóre, slabší zónu s překryvem
# > 50 % užší z obou zahodí (jen zvedne počítadlo překryvů u silnější).
def merge_prekryvy(zony):
    zony = sorted(zony, key=lambda z: -z["skore"])
    kept = []
    for z in zony:
        dup = False
        for k in kept:
            if k["type"] != z["type"]:
                continue
            inter = min(k["zone_high"], z["zone_high"]) - max(k["zone_low"], z["zone_low"])
            if inter > 0 and inter / min(k["sirka"], z["sirka"]) > 0.5:
                k["prekryvu"] = k.get("prekryvu", 0) + 1
                dup = True
                break
        if not dup:
            z.setdefault("prekryvu", 0)
            kept.append(z)
    return kept

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_file", help="JSON z fetch_1h.py (<symbol>_1h.json)")
    ap.add_argument("--top", type=int, default=5, help="kolik zón na každou stranu vypsat")
    ap.add_argument("--pip-size", type=float, default=None,
                    help="velikost pipu/bodu pro výpis vzdáleností (jinak auto dle symbolu)")
    ap.add_argument("--min-depart", type=float, default=1.8,
                    help="min. síla odchodu z base v ATR (default 1.8)")
    ap.add_argument("--days", type=int, default=45,
                    help="brát jen zóny vzniklé v posledních N dnech")
    ap.add_argument("--swing-window", type=int, default=6)
    a = ap.parse_args()

    raw = json.load(open(a.data_file))
    if isinstance(raw, dict):
        bars, symbol = raw["bars"], raw.get("symbol", "?")
    else:
        bars, symbol = raw, "?"

    # auto pip_size: futures/velká čísla = 1.0 (body/USD), JPY = 0.01, forex = 0.0001
    px = bars[-1][4]
    pip = a.pip_size or (1.0 if (symbol.upper().endswith("=F") or px >= 100)
                         else (0.01 if "JPY" in symbol.upper() else 0.0001))
    dec = 2 if px >= 100 else (3 if pip == 0.01 else 5)
    def p(v):     # formát ceny pro výpis
        return f"{v:,.{dec}f}".replace(",", " ")

    atr = atr_serie(bars)
    cur_atr = atr[-1]
    last_ts = bars[-1][0]
    sw_hi, sw_lo = detekuj_swingy(bars, a.swing_window)

    zony = najdi_zony(bars, atr, a.min_depart)
    # jen zóny z posledních --days dní
    zony = [z for z in zony if z["base_do"] >= last_ts - a.days * 86400]
    for z in zony:
        z["skore"] = skore(z, sw_hi if z["type"] == "SUPPLY" else sw_lo, last_ts)
    zony = merge_prekryvy(zony)

    # rozdělení podle polohy vůči aktuální ceně
    supply = sorted([z for z in zony if z["type"] == "SUPPLY" and z["prox"] > px],
                    key=lambda z: -z["skore"])[:a.top]
    demand = sorted([z for z in zony if z["type"] == "DEMAND" and z["prox"] < px],
                    key=lambda z: -z["skore"])[:a.top]
    uvnitr = [z for z in zony if z["zone_low"] <= px <= z["zone_high"]]

    buf = 0.30 * cur_atr    # doporučený SL buffer za distální hranu

    print(f"symbol: {symbol}   aktuální cena: {p(px)}   ATR(14): {p(cur_atr)}"
          f"  (~{cur_atr / pip:.0f} jedn.)")
    print(f"doporučený SL buffer za distální hranou: ~{p(buf)} (~{buf / pip:.0f} jedn., 0.30×ATR)")

    # HTF bias: EMA50/200 + struktura posledních swingů (širší okno ~ 4h pohled)
    closes = [b[4] for b in bars]
    e50, e200 = ema(closes, 50)[-1], ema(closes, 200)[-1]
    if px > e50 > e200:
        bias = "býčí"
    elif px < e50 < e200:
        bias = "medvědí"
    else:
        bias = "smíšený/range"
    hh, ll = detekuj_swingy(bars, 12)
    strukt = ""
    if len(hh) >= 2 and len(ll) >= 2:
        strukt = (f"  poslední swingy: high {'roste' if hh[-1][1] > hh[-2][1] else 'klesá'},"
                  f" low {'roste' if ll[-1][1] > ll[-2][1] else 'klesá'}")
    print(f"bias (1h EMA50 {p(e50)} / EMA200 {p(e200)}): {bias}{strukt}")

    # výpis kandidátů; hvězdičky = orientační síla dle skóre
    def vypis(zs, nadpis):
        print(f"\n-- {nadpis} --")
        if not zs:
            print("  (žádná nenalezena — zvaž --min-depart nižší nebo --days delší)")
        for z in zs:
            hvezd = "★" * min(5, int(z["skore"] // 20) + 1)
            dist = abs(z["prox"] - px)
            print(f"  [{z['skore']:5.1f} b] {hvezd:<5} zóna {p(z['zone_low'])}–{p(z['zone_high'])}"
                  f"  prox {p(z['prox'])} / distal {p(z['distal'])}")
            print(f"      vznik {fmt_ts(z['base_do'])} UTC · vzor {z['vzor']}"
                  f" · base {z['base_svicek']} sv. · odchod {z['depart_atr']:.1f}×ATR"
                  f" · retestů {z['retesty']}"
                  f" · {'swing✓' if z['swing_konfluence'] else 'swing–'}"
                  f" · stáří {z['stari_dni']:.1f} d"
                  f" · od ceny {dist / pip:.0f} jedn."
                  + (f" · překryvů {z['prekryvu']}" if z.get("prekryvu") else ""))

    vypis(supply, f"SUPPLY zóny nad cenou (top {a.top} dle skóre)")
    vypis(demand, f"DEMAND zóny pod cenou (top {a.top} dle skóre)")
    if uvnitr:
        print("\n-- POZOR: cena je právě UVNITŘ těchto zón (nevhodné pro pending vstup) --")
        for z in uvnitr:
            print(f"  {z['type']} {p(z['zone_low'])}–{p(z['zone_high'])} (skóre {z['skore']})")

    # párování zóna-do-zóny: RRR long/short pro kombinace top 3 × top 3
    pary = []
    for d in demand[:3]:
        for s in supply[:3]:
            risk_l = d["prox"] - (d["distal"] - buf)
            risk_s = (s["distal"] + buf) - s["prox"]
            range_ = s["prox"] - d["prox"]
            if risk_l > 0 and risk_s > 0 and range_ > 0:
                pary.append({
                    "demand": [d["zone_low"], d["zone_high"]],
                    "supply": [s["zone_low"], s["zone_high"]],
                    "long":  {"entry": d["prox"], "sl": d["distal"] - buf, "tp": s["prox"],
                              "rrr": range_ / risk_l},
                    "short": {"entry": s["prox"], "sl": s["distal"] + buf, "tp": d["prox"],
                              "rrr": range_ / risk_s},
                    "skore": d["skore"] + s["skore"],
                })
    pary.sort(key=lambda x: -x["skore"])
    if pary:
        print("\n-- Párování zóna-do-zóny (entry = prox, SL = distal ± buffer, TP = protilehlá prox) --")
        for pr in pary[:4]:
            L, S = pr["long"], pr["short"]
            okL = "✓" if L["rrr"] >= 2 else "✗"
            okS = "✓" if S["rrr"] >= 2 else "✗"
            print(f"  D {p(pr['demand'][0])}–{p(pr['demand'][1])}  ×  S {p(pr['supply'][0])}–{p(pr['supply'][1])}"
                  f"   LONG RRR {L['rrr']:.1f}:1 {okL}   SHORT RRR {S['rrr']:.1f}:1 {okS}")

    # strojově čitelný výstup vedle datového souboru
    out_path = a.data_file.replace("_1h.json", "_zones.json")
    if out_path == a.data_file:
        out_path = a.data_file + ".zones.json"
    with open(out_path, "w") as f:
        json.dump({"symbol": symbol, "current_price": px, "atr": cur_atr,
                   "sl_buffer": buf, "pip_size": pip, "bias": bias,
                   "supply": supply, "demand": demand, "inside": uvnitr,
                   "pairs": pary[:4]}, f, ensure_ascii=False, indent=1)
    print(f"\nJSON se zónami: {out_path}")

if __name__ == "__main__":
    main()
