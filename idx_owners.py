# idx_owners.py — Controlling owner / sponsor behind each ticker, as a QUALITATIVE conviction
# layer. IDX monster-runs cluster on stocks backed by powerful tycoons/conglomerates with the
# money + motive to drive price ("bandar"). We tag the backer and a strength tier.
#
# ⚠️ Curated from public knowledge — VERIFY and correct. Entries marked "?" are unconfirmed;
#    do NOT trade conviction on those until you confirm the owner yourself. Never fabricate.
#
# strength tiers:  "mega" = top-tier tycoon (Prajogo/Salim/Aguan/Widjaja/Bakrie/Hapsoro/MNC)
#                  "state"= BUMN / MIND ID (state-owned, strong but slower)
#                  "konglo"= solid conglomerate / strategic owner
#                  "none" = no dominant tycoon backer (retail/VC/float)
#                  "?"    = UNCONFIRMED — verify before relying on it

OWNERS = {
    # 🟣 Prajogo Pangestu — Barito group (the king of IDX monster-runs)
    "BRPT": ("Prajogo Pangestu", "Barito Pacific",      "mega"),
    "TPIA": ("Prajogo Pangestu", "Chandra Asri",        "mega"),
    "BREN": ("Prajogo Pangestu", "Barito Renewables",   "mega"),
    "CUAN": ("Prajogo Pangestu", "Petrindo Jaya",       "mega"),
    "PTRO": ("Prajogo Pangestu", "Petrosea / Barito",   "mega"),
    "CDIA": ("Prajogo Pangestu", "Chandra Daya",        "mega"),
    # 🔴 Bakrie group
    "BUMI": ("Bakrie family",    "Bumi Resources",      "mega"),
    "BNBR": ("Bakrie family",    "Bakrie & Brothers",   "mega"),
    "DEWA": ("Bakrie family",    "Darma Henwa",         "mega"),
    "ENRG": ("Bakrie family",    "Energi Mega Persada", "mega"),
    "BRMS": ("Bakrie family",    "Bumi Resources Min.", "mega"),
    "VKTR": ("Bakrie family",    "VKTR (EV, Bakrie)",   "mega"),
    # 🟢 Salim group (Anthoni Salim) + Aguan
    "INDF": ("Anthoni Salim",    "Indofood / Salim",    "mega"),
    "ICBP": ("Anthoni Salim",    "Indofood CBP",        "mega"),
    "PANI": ("Aguan + Salim",    "Pantai Indah Kapuk 2","mega"),
    # 🟡 Hapsoro (Happy Hapsoro)
    "RATU": ("Happy Hapsoro",    "Raharja Energi",      "mega"),
    "WIFI": ("Happy Hapsoro",    "Surge / digital",     "mega"),
    # ⚫ Sinarmas / Widjaja
    "DSSA": ("Widjaja (Sinarmas)","Dian Swastatika",    "mega"),
    # 🔵 other major conglomerates / tycoons
    "EMTK": ("Sariaatmadja family","Emtek group",       "mega"),
    "MDIA": ("Hary Tanoesoedibjo","MNC media",          "mega"),
    "INDY": ("Agus Lasmono",     "Indika Energy",       "konglo"),
    "AMMN": ("Medco + AP Inv.",  "Amman Mineral",       "konglo"),
    "BYAN": ("Low Tuck Kwong",   "Bayan Resources",     "mega"),
    "ADRO": ("Garibaldi Thohir", "Adaro / Alamtri",     "konglo"),
    "NCKL": ("Lim family",       "Harita nickel",       "konglo"),
    "JPFA": ("Santosa family",   "Japfa",               "konglo"),
    "MEDC": ("Panigoro family",  "Medco Energi",        "konglo"),
    # ⚪ state-owned (BUMN / MIND ID)
    "ANTM": ("State (MIND ID)",  "Aneka Tambang",       "state"),
    "TINS": ("State (MIND ID)",  "Timah",               "state"),
    "INCO": ("Vale + MIND ID",   "Vale Indonesia",      "state"),
    "PGAS": ("State (Pertamina)","Perusahaan Gas Neg.", "state"),
    # ✅ confirmed by owner (Eric)
    "BUVA": ("Happy Hapsoro",        "Bukit Uluwatu Villa", "mega"),
    "RAJA": ("Happy Hapsoro",        "Rukun Raharja",       "mega"),
    "MSIN": ("MNC (Hary Tanoe)",     "MNC-backed",          "mega"),
    "BIPI": ("Halim Jusuf",          "Astrindo Nusantara",  "konglo"),
    "NICL": ("Christopher S. Tjia",  "PAM Mineral",         "konglo"),
    "ARKO": ("no major backer",      "Arkora Hydro",        "none"),
    "FORE": ("no major backer",      "Fore Coffee (VC)",    "none"),
}

STRENGTH_TAG = {
    "mega":  "🏛️⭐⭐⭐ mega-tycoon",
    "state": "🏛️⭐⭐ state/BUMN",
    "konglo":"🏛️⭐⭐ conglomerate",
    "none":  "·   no major backer",
    "?":     "❓ owner unverified",
}
# small conviction nudge for display (NOT independently backtested — qualitative)
STRENGTH_BONUS = {"mega": 10, "state": 4, "konglo": 6, "none": 0, "?": 0}

def backer(ticker):
    """Return (owner, group, strength) or (None, None, None) if unknown."""
    if ticker in OWNERS:
        o, g, s = OWNERS[ticker]
        return o, g, s
    return None, None, None

def backer_line(ticker):
    o, g, s = backer(ticker)
    if o is None:
        return None
    return f"{STRENGTH_TAG.get(s,'')} · {o} ({g})"
