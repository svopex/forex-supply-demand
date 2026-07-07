# -*- coding: utf-8 -*-
# Vykreslí 1h svíčkový graf instrumentu (forex pár, index NQ, zlato XAUUSD…) se
# supply/demand zónami a vygeneruje dvoustránkové PDF (graf + obchodní plán).
# Vše řízeno JSON configem.
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

# ---------- STRÁNKA 1: 1h svíčkový graf ----------
fig1 = plt.figure(figsize=(11.69, 8.27))     # A4 na šířku
ax = fig1.add_axes([0.075, 0.135, 0.70, 0.775])  # užší osa -> místo na popisky

# Svíčky (x = index baru kvůli vynechání víkendových mezer)
for i, (t, O, H, L, C) in enumerate(disp):
    up = C >= O
    col = "#26a69a" if up else "#ef5350"
    ax.plot([i, i], [L, H], color=col, linewidth=0.8, zorder=2)  # knot
    lo, hi = (O, C) if up else (C, O)
    ax.add_patch(Rectangle((i - 0.3, lo), 0.6, max(hi - lo, 1e-6),
                           facecolor=col, edgecolor=col, linewidth=0.5, zorder=3))

# Popisky cenových úrovní do pravého okraje (mimo osu, aby se nepřekrývaly)
def hline(y, color, style, lw, label):
    ax.axhline(y, color=color, linestyle=style, linewidth=lw, zorder=4)
    ax.text(n + 1.5, y, label, va="center", ha="left", color=color,
            fontsize=7.5, fontweight="bold", zorder=6, clip_on=False)

# Zóny + úrovně pro každý setup
for s in setups:
    zc = BARVA[s["zone_type"]]
    lc = BARVA[s["side"]]
    z0, z1 = s["zone"]
    ax.axhspan(z0, z1, color=zc, alpha=0.16, zorder=1)
    ax.text(0.3, z1 if s["zone_type"] == "SUPPLY" else z0,
            f"  {s['zone_type']} zóna {pf(z0)}–{pf(z1)}",
            va="bottom" if s["zone_type"] == "SUPPLY" else "top",
            ha="left", color=lc, fontsize=9, fontweight="bold", zorder=6)
    hline(s["sl"], lc, (0, (1, 2)), 1.0, f"SL {s['side'].lower()} {pf(s['sl'])}")
    hline(s["entry"], lc, (0, (4, 2)), 1.3,
          f"{s['side']} {pf(s['entry'])}  (TP {pf(s['tp'])})")

# Aktuální cena
ax.axhline(current, color="#1565c0", linestyle="-", linewidth=1.1, zorder=4)
ax.text(n + 1.5, current, f"aktuální {pf(current)}", va="center", ha="left",
        color="#1565c0", fontsize=8, fontweight="bold", zorder=6, clip_on=False)

# Osa X – datum při změně dne
ticks, labels, last_day = [], [], None
for i, (t, *_ ) in enumerate(disp):
    d = datetime.datetime.fromtimestamp(t, TZ).strftime("%d.%m.")
    if d != last_day:
        ticks.append(i); labels.append(d); last_day = d
ax.set_xticks(ticks[::2]); ax.set_xticklabels(labels[::2], fontsize=7)
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

# ---------- STRÁNKA 2: obchodní plán ----------
fig2 = plt.figure(figsize=(11.69, 8.27)); fig2.patch.set_facecolor("white")
ax2 = fig2.add_axes([0, 0, 1, 1]); ax2.axis("off")

def T(x, y, s, size=10, weight="normal", color="#212121"):
    ax2.text(x, y, s, fontsize=size, fontweight=weight, color=color,
             ha="left", va="top", transform=ax2.transAxes)

T(0.06, 0.96, f"Obchodní plán {cfg['symbol']} — 1H supply/demand", 17, "bold", "#0d47a1")
T(0.06, 0.915, f"Aktuální cena: {pf(current)}  ·  datum: {cfg['as_of']}  ·  zdroj dat: {cfg['source']}",
  9.5, color="#555555")
ax2.axhline(0.90, color="#0d47a1", linewidth=1.2)

# Bloky jednotlivých setupů (počítá pipy/body a RRR automaticky)
kruh = ["①", "②", "③", "④"]
y = 0.865
for idx, s in enumerate(setups):
    lc = BARVA[s["side"]]
    risk = abs(s["entry"] - s["sl"]) / pip
    reward = abs(s["tp"] - s["entry"]) / pip
    rrr = reward / risk if risk else 0
    T(0.06, y, f"{kruh[idx]} {s['zone_type']} zóna ({s['side']} / "
      f"{'prodej' if s['side']=='SHORT' else 'nákup'})", 13, "bold", lc)
    y -= 0.04
    rows = [
        ("Zóna:", f"{pf(s['zone'][0])} – {pf(s['zone'][1])}"),
        ("Vstup:", f"{pf(s['entry'])}  ({'Sell' if s['side']=='SHORT' else 'Buy'} Limit, proximální hrana)"),
        ("Stop-loss:", f"{pf(s['sl'])}  (za vzdálenou hranou zóny)  = {risk:.0f} {unit}"),
        ("Take-profit:", f"{pf(s['tp'])}  (protilehlá zóna)  = {reward:.0f} {unit}"),
        ("Poměr RRR:", f"≈ {rrr:.2f} : 1"),
    ]
    # jednořádkové parametry setupu
    for k, v in rows:
        T(0.09, y, k, 10.5, "bold"); T(0.30, y, v, 10.5); y -= 0.034
    # zdůvodnění bývá dlouhé -> zalomíme na více řádků, ať nepřeteče mimo stránku
    rationale = s.get("rationale", "")
    T(0.09, y, "Zdůvodnění:", 10.5, "bold")
    for j, ln in enumerate(textwrap.wrap(rationale, width=100) or [""]):
        T(0.30, y, ln, 10.5); y -= 0.030
    y -= 0.02

# Poznámky z configu + disclaimer
ax2.axhline(y + 0.01, color="#bbbbbb", linewidth=0.8)
y -= 0.03
T(0.06, y, "Poznámky k obchodování", 12, "bold", "#0d47a1"); y -= 0.034
# poznámky rovněž zalamujeme; pokračovací řádky odsadíme pod odrážku
for note in cfg.get("notes", []):
    for j, ln in enumerate(textwrap.wrap("• " + note, width=118) or [""]):
        T(0.07 if j == 0 else 0.085, y, ln, 9.8); y -= 0.030
T(0.06, 0.02, "Upozornění: materiál slouží ke vzdělávacím účelům, nejde o investiční doporučení.",
  8, "normal", "#888888")

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

with PdfPages(out) as pdf:
    pdf.savefig(fig1); pdf.savefig(fig2)
fig1.savefig(out.replace(".pdf", "_page1.png"), dpi=110)   # náhled na vizuální kontrolu
fig2.savefig(out.replace(".pdf", "_page2.png"), dpi=110)
plt.close("all")
print("PDF hotovo:", out)
