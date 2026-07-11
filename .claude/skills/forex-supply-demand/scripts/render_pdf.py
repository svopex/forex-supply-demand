# -*- coding: utf-8 -*-
# Vykreslí 1h svíčkový graf instrumentu (forex pár, index NQ, zlato XAUUSD…) se
# supply/demand zónami a vygeneruje vícestránkové PDF (graf + případné detaily
# zón + obchodní plán). Vše řízeno JSON configem.
#
# DETAILNÍ GRAFY ZÓN: když vznik zóny (base + impulz) leží před začátkem
# hlavního výseku (display_start) nebo mimo ylim, není v hlavním grafu vidět
# „situace kolem zóny". Skript pak automaticky přidá stránku s detailním
# výřezem: N svíček před base a N svíček po ní (detail_bars_before/after,
# výchozí 40/40). Vznik zóny se bere z polí base_od/base_do setupu (unix
# timestampy zkopírované ze <symbol>_zones.json); bez nich se dohledá jako
# poslední souvislý úsek svíček protínajících pásmo zóny.
#
# KLÍČOVÉ K ČEŠTINĚ: matplotlib s výchozím fontem DejaVu Sans plně podporuje
# českou diakritiku (ě š č ř ž ý á í é ú ů ď ť ň i uvozovky „ "). Tím se
# vyhneme problému reportlabu, jehož výchozí Helvetica (WinAnsi/cp1252)
# českou diakritiku komolí. NEPOUŽÍVEJ reportlab s výchozím fontem.
#
# PODPORA VÍCE INSTRUMENTŮ: skript nefixuje formát ceny ani jednotku rizika,
# vše bere z configu:
#   - pip_size       velikost 1 pipu/bodu (forex 0.0001, JPY 0.01, NQ 1.0, zlato 0.1/1.0)
#   - unit_label     jednotka rizika/zisku v plánu ("pipů", "bodů", "USD")
#   - price_decimals počet desetinných míst ceny (dopočítá se z pip_size, lze přepsat)
#   - trim_zeros     ořízne koncové nuly (hezké u indexů: 30 480 místo 30 480.00)
# Velká čísla (index, zlato) se formátují s mezerou po tisících (30 480).
#
# NÁZEV VÝSTUPU: pokud config neurčí "output", vygeneruje se automaticky jako
# <YYYYMMDD>_<ticker>.pdf, kde datum = poslední bar dat a ticker = pole "ticker"
# (jinak odvozeno z názvu datového souboru). Např. 20260703_EURUSD.pdf.
#
# Použití:
#   python render_pdf.py config.json
# Config viz assets/config_example*.json v tomto skillu.

import json, sys, os, math, datetime, textwrap
from zoneinfo import ZoneInfo
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_pdf import PdfPages

plt.rcParams["font.family"] = "DejaVu Sans"   # kvůli české diakritice
plt.rcParams["axes.unicode_minus"] = False

cfg = json.load(open(sys.argv[1]))

# Data mohou být buď dict s metadaty (nový formát z fetch_1h.py), nebo holý
# seznam barů (starší formát). anchor_tz použijeme pro popisky osy X a datum
# v názvu souboru, aby dny odpovídaly burzovnímu pásmu (jako TradingView).
raw = json.load(open(cfg["data_file"]))
if isinstance(raw, dict):
    bars = raw["bars"]
    data_anchor_tz = raw.get("anchor_tz", "UTC")
else:
    bars = raw
    data_anchor_tz = "UTC"
# config smí zarovnání přepsat (např. jiné časové pásmo grafu v TradingView)
ANCHOR_TZ = cfg.get("anchor_tz") or data_anchor_tz
TZ = ZoneInfo(ANCHOR_TZ)

# Barvy zón podle strany obchodu
BARVA = {"SUPPLY": "#ef5350", "DEMAND": "#26a69a",
         "SHORT": "#c62828", "LONG": "#1b5e20"}

pip = cfg.get("pip_size", 0.0001)             # velikost 1 pipu/bodu
unit = cfg.get("unit_label", "pipů")          # jednotka rizika/zisku v plánu


# Výchozí počet desetinných míst odvozený z velikosti pipu
# (0.0001 -> 4, 0.01 -> 2, 0.1 -> 1, >=1 -> 2 kvůli desetinám u indexů/zlata).
def _vychozi_desetinna(p):
    if p >= 1:
        return 2
    return max(0, -int(round(math.log10(p))))


DEC = cfg.get("price_decimals", _vychozi_desetinna(pip))
TRIM = cfg.get("trim_zeros", False)           # ořezat koncové nuly (hezké u indexů)
current = cfg["current_price"]
setups = cfg["setups"]                         # seznam obchodních setupů


# Formátování ceny: pevný počet desetinných míst, mezera jako oddělovač tisíců.
# Funguje pro malá forex čísla (1.1440) i velká (30 480, 4 187.30).
# S trim_zeros=True se ořežou koncové nuly (30 480 místo 30 480.00).
def pf(v):
    neg = v < 0
    v = abs(v)
    s = f"{v:.{DEC}f}"
    intp, _, frac = s.partition(".")
    # seskupení celé části po trojicích zprava -> mezera jako oddělovač tisíců
    groups = []
    while len(intp) > 3:
        groups.insert(0, intp[-3:]); intp = intp[:-3]
    groups.insert(0, intp)
    out = " ".join(groups)
    # desetinnou část přidáme podle režimu (pevně / oříznuté nuly)
    if frac:
        if TRIM:
            frac = frac.rstrip("0")
        if frac:
            out += "." + frac
    return ("-" if neg else "") + out


# Výběr zobrazeného výseku podle data (půlnoc v burzovním pásmu, aby řez
# byl konzistentní se zarovnáním svíček)
start_ts = datetime.datetime.strptime(cfg["display_start"], "%Y-%m-%d") \
    .replace(tzinfo=TZ).timestamp()
disp = [b for b in bars if b[0] >= start_ts]
n = len(disp)
# bary jsou seřazené podle času, disp je tedy sufix celé řady -> index prvního
# zobrazeného baru (pro test, zda je vznik zóny v hlavním výseku vidět)
first_disp_idx = len(bars) - n

# ---------- sdílené kreslicí funkce (hlavní graf i detaily zón) ----------

# Vykreslí svíčky do dané osy (x = pořadí baru kvůli vynechání mezer v datech).
def vykresli_svicky(ax, data):
    for i, (t, O, H, L, C) in enumerate(data):
        up = C >= O
        col = "#26a69a" if up else "#ef5350"
        ax.plot([i, i], [L, H], color=col, linewidth=0.8, zorder=2)  # knot
        lo, hi = (O, C) if up else (C, O)
        ax.add_patch(Rectangle((i - 0.3, lo), 0.6, max(hi - lo, 1e-6),
                               facecolor=col, edgecolor=col, linewidth=0.5, zorder=3))

# Vodorovná cenová úroveň s popiskem v pravém okraji (mimo osu, aby se
# popisky nepřekrývaly se svíčkami); nbars = počet barů v ose.
def hline(ax, nbars, y, color, style, lw, label):
    ax.axhline(y, color=color, linestyle=style, linewidth=lw, zorder=4)
    ax.text(nbars + 1.5, y, label, va="center", ha="left", color=color,
            fontsize=7.5, fontweight="bold", zorder=6, clip_on=False)

# Popisky osy X: datum při změně dne (v burzovním pásmu); krok=2 = každý
# druhý den (hustý hlavní graf), krok=1 = každý den (kratší detailní výřez).
def osa_dnu(ax, data, krok=2):
    ticks, labels, last_day = [], [], None
    for i, (t, *_ ) in enumerate(data):
        d = datetime.datetime.fromtimestamp(t, TZ).strftime("%d.%m.")
        if d != last_day:
            ticks.append(i); labels.append(d); last_day = d
    ax.set_xticks(ticks[::krok]); ax.set_xticklabels(labels[::krok], fontsize=7)

# Barevné pásmo zóny s popiskem u levého okraje.
def pasmo_zony(ax, s):
    z0, z1 = s["zone"]
    ax.axhspan(z0, z1, color=BARVA[s["zone_type"]], alpha=0.16, zorder=1)
    ax.text(0.3, z1 if s["zone_type"] == "SUPPLY" else z0,
            f"  {s['zone_type']} zóna {pf(z0)}–{pf(z1)}",
            va="bottom" if s["zone_type"] == "SUPPLY" else "top",
            ha="left", color=BARVA[s["side"]], fontsize=9, fontweight="bold", zorder=6)

# ---------- STRÁNKA 1: 1h svíčkový graf ----------
fig1 = plt.figure(figsize=(11.69, 8.27))     # A4 na šířku
ax = fig1.add_axes([0.075, 0.135, 0.70, 0.775])  # užší osa -> místo na popisky

vykresli_svicky(ax, disp)

# Zóny + úrovně pro každý setup
for s in setups:
    lc = BARVA[s["side"]]
    pasmo_zony(ax, s)
    hline(ax, n, s["sl"], lc, (0, (1, 2)), 1.0, f"SL {s['side'].lower()} {pf(s['sl'])}")
    hline(ax, n, s["entry"], lc, (0, (4, 2)), 1.3,
          f"{s['side']} {pf(s['entry'])}  (TP {pf(s['tp'])})")

# Aktuální cena
ax.axhline(current, color="#1565c0", linestyle="-", linewidth=1.1, zorder=4)
ax.text(n + 1.5, current, f"aktuální {pf(current)}", va="center", ha="left",
        color="#1565c0", fontsize=8, fontweight="bold", zorder=6, clip_on=False)

osa_dnu(ax, disp, krok=2)
ax.set_xlim(-1, n + 0.5)

# Osa Y – z configu nebo automaticky z výseku s rezervou
if "ylim" in cfg:
    ax.set_ylim(*cfg["ylim"])
else:
    lows = [b[3] for b in disp]; highs = [b[2] for b in disp]
    pad = (max(highs) - min(lows)) * 0.05
    ax.set_ylim(min(lows) - pad, max(highs) + pad)

ax.set_ylabel(cfg["symbol"], fontsize=10)
ax.grid(True, axis="y", linestyle=":", alpha=0.35)
ax.set_title(f"{cfg['symbol']} — 1H timeframe — supply/demand zóny a doporučené vstupy\n"
             f"aktuální data k {cfg['as_of']} (cena {pf(current)}, zdroj {cfg['source']})",
             fontsize=12, fontweight="bold", pad=12)

# Legenda jako patička (bez rizika překryvu s popisky vpravo)
z2z = "   ·   ".join(f"{s['side']} {pf(s['entry'])} → TP {pf(s['tp'])}" for s in setups)
leg = ("červené pásmo = SUPPLY (prodej)      zelené pásmo = DEMAND (nákup)      "
       "modrá čára = aktuální cena      – –  vstup      ····  stop-loss\n"
       f"Zóna do zóny:  {z2z}   (TP každého obchodu = protilehlá zóna)")
fig1.text(0.5, 0.045, leg, fontsize=8, va="center", ha="center",
          bbox=dict(boxstyle="round,pad=0.6", fc="#f5f5f5", ec="#bbbbbb"))

# ---------- DETAILNÍ GRAFY ZÓN (jen když vznik zóny není v hlavním výseku vidět) ----------
# Zóna vzniklá hluboko v historii je v hlavním grafu jen prázdné pásmo bez
# svíček — není vidět base ani impulzní odchod, tedy „situace kolem zóny".
# Pro každou takovou zónu se přidá stránka s výřezem kolem jejího vzniku.

DETAIL_PRED = cfg.get("detail_bars_before", 40)   # svíček před začátkem base
DETAIL_PO = cfg.get("detail_bars_after", 40)      # svíček po konci base

# Najde index prvního baru s časem >= ts (bary jsou seřazené podle času).
def idx_podle_casu(ts):
    for i, b in enumerate(bars):
        if b[0] >= ts:
            return i
    return len(bars) - 1

# Určí rozsah barů vzniku zóny (indexy první a poslední svíčky base):
# primárně z polí base_od/base_do setupu (unix timestampy ze zones.json),
# jinak fallback = poslední souvislý úsek svíček protínajících pásmo zóny
# (u čerstvé zóny bez retestů je to právě base + odchod).
def rozsah_vzniku(s):
    if "base_od" in s and "base_do" in s:
        return idx_podle_casu(s["base_od"]), idx_podle_casu(s["base_do"])
    z0, z1 = s["zone"]
    posledni = None
    for i, (t, o, h, l, c) in enumerate(bars):
        if h >= z0 and l <= z1:
            posledni = i
    if posledni is None:
        return None, None
    prvni = posledni
    while prvni > 0 and bars[prvni - 1][2] >= z0 and bars[prvni - 1][3] <= z1:
        prvni -= 1
    return prvni, posledni

# Vznik zóny je v hlavním grafu vidět, když celá base leží v zobrazeném okně
# a pásmo zóny se vejde do ylim (je-li v configu zadané ručně).
def vznik_viditelny(s, i0):
    if i0 is None:
        return True          # vznik nešel dohledat -> detail nemá co ukázat
    if i0 < first_disp_idx:
        return False         # base začíná před display_start (moc do historie)
    if "ylim" in cfg:
        z0, z1 = s["zone"]
        if z0 < cfg["ylim"][0] or z1 > cfg["ylim"][1]:
            return False     # zóna je oříznutá ruční osou Y
    return True

detail_figs = []
for s in setups:
    i0, i1 = rozsah_vzniku(s)
    if vznik_viditelny(s, i0):
        continue
    # výřez: DETAIL_PRED svíček před base a DETAIL_PO svíček po ní
    lo = max(0, i0 - DETAIL_PRED)
    hi = min(len(bars), i1 + DETAIL_PO + 1)
    sub = bars[lo:hi]
    m = len(sub)
    lc = BARVA[s["side"]]
    z0, z1 = s["zone"]

    figd = plt.figure(figsize=(11.69, 8.27))          # A4 na šířku jako graf
    axd = figd.add_axes([0.075, 0.135, 0.70, 0.775])
    # šedý svislý pás = svíčky base (vznik zóny), ať je situace ihned vidět
    axd.axvspan(i0 - lo - 0.45, i1 - lo + 0.45, color="#90a4ae", alpha=0.18, zorder=0)
    vykresli_svicky(axd, sub)
    pasmo_zony(axd, s)
    hline(axd, m, s["entry"], lc, (0, (4, 2)), 1.3, f"{s['side']} {pf(s['entry'])}  (vstup)")
    hline(axd, m, s["sl"], lc, (0, (1, 2)), 1.0, f"SL {pf(s['sl'])}")

    # osa Y těsně kolem výřezu, ale vždy zahrnout celou zónu, vstup i SL
    lows = [b[3] for b in sub] + [z0, s["sl"], s["entry"]]
    highs = [b[2] for b in sub] + [z1, s["sl"], s["entry"]]
    pad = (max(highs) - min(lows)) * 0.06
    axd.set_ylim(min(lows) - pad, max(highs) + pad)
    # TP a aktuální cena bývají daleko -> jen pokud padnou do rozsahu výřezu
    y0ax, y1ax = axd.get_ylim()
    if y0ax <= s["tp"] <= y1ax:
        hline(axd, m, s["tp"], lc, (0, (6, 2)), 1.0, f"TP {pf(s['tp'])}")
    if y0ax <= current <= y1ax:
        axd.axhline(current, color="#1565c0", linestyle="-", linewidth=1.1, zorder=4)
        axd.text(m + 1.5, current, f"aktuální {pf(current)}", va="center", ha="left",
                 color="#1565c0", fontsize=8, fontweight="bold", zorder=6, clip_on=False)

    osa_dnu(axd, sub, krok=1)   # kratší výřez -> popisek na každý den
    axd.set_xlim(-1, m + 0.5)
    axd.set_ylabel(cfg["symbol"], fontsize=10)
    axd.grid(True, axis="y", linestyle=":", alpha=0.35)
    vznik = datetime.datetime.fromtimestamp(bars[i1][0], TZ).strftime("%d. %m. %Y %H:%M")
    axd.set_title(f"{cfg['symbol']} — DETAIL {s['zone_type']} zóny {pf(z0)}–{pf(z1)} "
                  f"({s['side']}) — vznik {vznik}\n"
                  f"výřez {i0 - lo} svíček před base a {hi - 1 - i1} po ní "
                  f"(vznik zóny leží mimo výsek hlavního grafu)",
                  fontsize=12, fontweight="bold", pad=12)
    figd.text(0.5, 0.045,
              "šedý svislý pás = base (svíčky vzniku zóny)      barevné pásmo = zóna      "
              "– –  vstup      ····  stop-loss\n"
              "Detailní stránka se přidává automaticky, když situace kolem zóny "
              "(base + impulzní odchod) není vidět v hlavním grafu.",
              fontsize=8, va="center", ha="center",
              bbox=dict(boxstyle="round,pad=0.6", fc="#f5f5f5", ec="#bbbbbb"))
    detail_figs.append(figd)

# ---------- STRÁNKA 2+: obchodní plán (teče přes více stránek dle objemu textu) ----------
# Plán se sází "tokem": kurzor plyne shora dolů a jakmile by blok textu spadl pod
# dolní okraj, založí se automaticky nová stránka. Tím se detailní zdůvodnění ani
# poznámky nikdy neuříznou (dřív se sázelo na pevné y a dlouhý plán přetékal mimo A4).
Y_TOP = 0.94        # horní okraj textového toku
Y_BOTTOM = 0.055    # dolní okraj toku (nad patičkou s disclaimerem)
plan_state = {"ax": None, "y": Y_TOP}   # aktuální osa a svislý kurzor
plan_figs = []                           # všechny vysázené stránky plánu

# Založí novou stránku plánu (bílé A4 na šířku), vloží patičku s disclaimerem a
# nastaví kurzor na horní okraj.
def nova_stranka():
    fig = plt.figure(figsize=(11.69, 8.27)); fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)   # ať axhline i souřadnice sedí 0–1
    # disclaimer jako patička každé stránky plánu
    ax.text(0.06, 0.025, "Upozornění: materiál slouží ke vzdělávacím účelům, nejde o investiční doporučení.",
            fontsize=8, color="#888888", ha="left", va="bottom", transform=ax.transAxes)
    plan_figs.append(fig)
    plan_state["ax"] = ax
    plan_state["y"] = Y_TOP

# Vypíše text na aktuální kurzor; dy případně posune kurzor dolů o daný krok.
def T(x, s, size=10, weight="normal", color="#212121", dy=0.0):
    plan_state["ax"].text(x, plan_state["y"], s, fontsize=size, fontweight=weight,
                          color=color, ha="left", va="top", transform=plan_state["ax"].transAxes)
    plan_state["y"] -= dy

# Pojistí, že se blok o výšce `space` ještě vejde; jinak přeteče na novou stránku.
def zajisti(space):
    if plan_state["y"] - space < Y_BOTTOM:
        nova_stranka()

nova_stranka()
# Hlavička plánu (jen na první stránce)
T(0.06, f"Obchodní plán {cfg['symbol']} — 1H supply/demand", 17, "bold", "#0d47a1", dy=0.040)
T(0.06, f"Aktuální cena: {pf(current)}  ·  datum: {cfg['as_of']}  ·  zdroj dat: {cfg['source']}",
  9.5, color="#555555", dy=0.022)
plan_state["ax"].axhline(plan_state["y"] + 0.004, color="#0d47a1", linewidth=1.2)
plan_state["y"] -= 0.020

# Bloky jednotlivých setupů (počítá pipy/body a RRR automaticky)
kruh = ["①", "②", "③", "④"]
for idx, s in enumerate(setups):
    lc = BARVA[s["side"]]
    risk = abs(s["entry"] - s["sl"]) / pip
    reward = abs(s["tp"] - s["entry"]) / pip
    rrr = reward / risk if risk else 0
    # Zdůvodnění bývá delší než celá stránka, takže blok setupu nelze držet vcelku —
    # pohromadě udržíme jen "hlavu" (nadpis + parametry + první tři řádky textu),
    # aby na konci stránky neosiřel nadpis; zbytek zdůvodnění pak teče po řádcích.
    rationale = s.get("rationale", "")
    radky = textwrap.wrap(rationale, width=100) or [""]
    hlava_h = 0.036 + 5 * 0.028 + 3 * 0.025
    zajisti(hlava_h)
    T(0.06, f"{kruh[idx]} {s['zone_type']} zóna ({s['side']} / "
      f"{'prodej' if s['side']=='SHORT' else 'nákup'})", 13, "bold", lc, dy=0.036)
    rows = [
        ("Zóna:", f"{pf(s['zone'][0])} – {pf(s['zone'][1])}"),
        ("Vstup:", f"{pf(s['entry'])}  ({'Sell' if s['side']=='SHORT' else 'Buy'} Limit, proximální hrana)"),
        ("Stop-loss:", f"{pf(s['sl'])}  (za vzdálenou hranou zóny)  = {risk:.0f} {unit}"),
        # popis cíle lze přebít polem tp_popis (když TP není protilehlá zóna,
        # ale třeba hrana konsolidace u protitrendového obchodu)
        ("Take-profit:", f"{pf(s['tp'])}  ({s.get('tp_popis', 'protilehlá zóna')})  = {reward:.0f} {unit}"),
        ("Poměr RRR:", f"≈ {rrr:.2f} : 1"),
    ]
    # jednořádkové parametry setupu (klíč vlevo, hodnota od 0.30 na stejném řádku)
    for k, v in rows:
        T(0.09, k, 10.5, "bold"); T(0.30, v, 10.5, dy=0.028)
    # zdůvodnění: popisek na prvním řádku, zalomený text pod ním; dlouhý text
    # přeteče na další stránku po jednotlivých řádcích (nikdy se neuřízne)
    T(0.09, "Zdůvodnění:", 10.5, "bold")
    for ln in radky:
        zajisti(0.025)
        T(0.30, ln, 10.5, dy=0.025)
    plan_state["y"] -= 0.015

# Poznámky z configu
notes = cfg.get("notes", [])
# Rezerva = oddělovač + nadpis + CELÁ první poznámka (po zalomení může mít víc
# řádků) — jinak by nadpis zůstal osiřelý na konci stránky a poznámky by
# přetekly samy na další stranu.
prvni_h = (len(textwrap.wrap("• " + notes[0], width=118)) if notes else 1) * 0.030
zajisti(0.03 + 0.034 + prvni_h)
# oddělovací linku kresli jen uvnitř rozepsané stránky (na čerstvé nemá smysl)
if plan_state["y"] < Y_TOP:
    plan_state["ax"].axhline(plan_state["y"] + 0.01, color="#bbbbbb", linewidth=0.8)
    plan_state["y"] -= 0.03
T(0.06, "Poznámky k obchodování", 12, "bold", "#0d47a1", dy=0.034)
# poznámky rovněž zalamujeme; pokračovací řádky odsadíme pod odrážku
for note in notes:
    wr = textwrap.wrap("• " + note, width=118) or [""]
    zajisti(len(wr) * 0.030)   # celou poznámku drž pohromadě
    for j, ln in enumerate(wr):
        T(0.07 if j == 0 else 0.085, ln, 9.8, dy=0.030)

# ---------- Uložení ----------
# Automatický název <YYYYMMDD>_<ticker>.pdf z data posledního baru a tickeru.
# Datum bereme z dat (poslední bar), ne z hodin stroje -> deterministické.
last_ts = bars[-1][0]
date_str = datetime.datetime.fromtimestamp(last_ts, TZ).strftime("%Y%m%d")
# ticker pro název: z configu, jinak odvozený z názvu datového souboru
ticker = cfg.get("ticker")
if not ticker:
    base = os.path.basename(cfg["data_file"])
    ticker = base.replace("_1h.json", "").replace(".json", "")
out = cfg.get("output", f"{date_str}_{ticker}.pdf")

# Do PDF: hlavní graf, pak detailní grafy zón (jsou-li), pak stránky plánu.
vsechny = [fig1] + detail_figs + plan_figs
with PdfPages(out) as pdf:
    for f in vsechny:
        pdf.savefig(f)
# Náhledy na vizuální kontrolu: _page1 = hlavní graf, dál detaily zón a plán
# (číslované průběžně podle pořadí stránek v PDF).
for i, f in enumerate(vsechny, start=1):
    f.savefig(out.replace(".pdf", f"_page{i}.png"), dpi=110)
plt.close("all")
print("PDF hotovo:", out,
      f"({len(vsechny)} stránek, z toho {len(detail_figs)} detail zóny)")
