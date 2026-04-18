"""
Vedic Astrology Research Engine
================================
EXTRACT → STRUCTURE → DETECT → VALIDATE → INTERPRET

Operates strictly on:
  - kundli_final_structured.json   (birth chart data)
  - filtered_structured_chunks.json (classical text knowledge base)

No external astrology knowledge is used.
"""

import json
import re
import os
import sys
from collections import defaultdict

# ─────────────────────────────────────────────────────────────
# STEP 1: LOAD DATA
# ─────────────────────────────────────────────────────────────

BASE = os.path.dirname(os.path.abspath(__file__))
KUNDLI_PATH = os.path.join(BASE, "kundli_final_structured.json")
CHUNKS_PATH = os.path.join(BASE, "filtered_structured_chunks.json")

with open(KUNDLI_PATH, encoding="utf-8") as f:
    kundli_raw = json.load(f)

with open(CHUNKS_PATH, encoding="utf-8") as f:
    chunks = json.load(f)


# ─────────────────────────────────────────────────────────────
# STEP 1A: NORMALIZE DEGREE STRINGS
# ─────────────────────────────────────────────────────────────

def dms_to_decimal(dms_str):
    """
    Convert degree strings to decimal.
    Handles: '16-43-29', '136-48-53', '136 48', '136\n48', '136.48' patterns.
    Returns float or None if unreadable.
    """
    if not dms_str or str(dms_str).strip() in ("", "--", "----", "---"):
        return None
    s = str(dms_str).strip().replace("\n", "-").replace(" ", "-")
    # Replace multiple dashes with single
    s = re.sub(r"-+", "-", s)
    parts = s.split("-")
    try:
        if len(parts) == 1:
            return float(parts[0])
        elif len(parts) == 2:
            return float(parts[0]) + float(parts[1]) / 60.0
        elif len(parts) >= 3:
            return float(parts[0]) + float(parts[1]) / 60.0 + float(parts[2]) / 3600.0
    except ValueError:
        return None
    return None


def sign_to_base_degree(sign_name):
    """Return the base absolute degree (0-360) for the start of a zodiac sign."""
    SIGNS = {
        "aries": 0, "taurus": 30, "gemini": 60, "cancer": 90,
        "leo": 120, "virgo": 150, "libra": 180, "scorpio": 210,
        "scorpion": 210, "sagittarius": 240, "capricorn": 270,
        "aquarius": 300, "pisces": 330,
    }
    return SIGNS.get(sign_name.lower().strip())


# ─────────────────────────────────────────────────────────────
# STEP 1B: EXTRACT BIRTH METADATA
# ─────────────────────────────────────────────────────────────

birth_meta = {}
for section in kundli_raw:
    if section.get("page") == 2 and section.get("type") == "unknown":
        for row in section["rows"]:
            if len(row) >= 2:
                birth_meta[row[0]] = row[1]
        if birth_meta:
            break

# Fallback: page 0 section 0 + section 1
if not birth_meta:
    for section in kundli_raw:
        if section.get("page") == 0:
            for row in section.get("rows", []):
                if len(row) >= 2:
                    birth_meta[row[0]] = row[1]

# Extract Lagna/Rasi/Dasha balance from page 0 section 0
lagna_meta = {}
dasha_meta = {}
for section in kundli_raw:
    if section.get("page") == 0 and section.get("type") == "rashi_grid":
        for row in section.get("rows", []):
            if len(row) >= 2:
                lagna_meta[row[0]] = row[1]
        break

# ─────────────────────────────────────────────────────────────
# STEP 1C: EXTRACT PLANETARY POSITIONS (Section type=rashi_grid page=1 section 5)
# ─────────────────────────────────────────────────────────────

PLANET_ALIASES = {
    "asc": "ASC", "sun": "Sun", "moon": "Moon", "mars": "Mars",
    "merc": "Mercury", "mercury": "Mercury", "jupt": "Jupiter", "jupiter": "Jupiter",
    "venu": "Venus", "venus": "Venus", "satn": "Saturn", "saturn": "Saturn",
    "rahu": "Rahu", "rahu [r]": "Rahu", "ketu": "Ketu", "ketu [r]": "Ketu",
    "uran": "Uranus", "uran [r]": "Uranus",
    "nept": "Neptune", "nept [r]": "Neptune", "plut": "Pluto",
}

VEDIC_PLANETS = {"ASC", "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"}

planets = {}   # planet_name -> {sign, degree_in_sign_dms, abs_degree, nakshatra, pada, retrograde}

for section in kundli_raw:
    if section.get("page") == 1 and section.get("type") == "rashi_grid":
        rows = section.get("rows", [])
        # Find the header row
        header_idx = None
        for i, row in enumerate(rows):
            if row and "Planets" in str(row[0]):
                header_idx = i
                break
        if header_idx is None:
            continue
        for row in rows[header_idx + 1:]:
            if not row or len(row) < 3:
                continue
            raw_name = str(row[0]).strip()
            alias = PLANET_ALIASES.get(raw_name.lower())
            if alias is None:
                continue
            sign_raw = str(row[1]).strip() if len(row) > 1 else ""
            deg_raw = str(row[2]).strip() if len(row) > 2 else ""
            nakshatra = str(row[3]).strip() if len(row) > 3 else ""
            pada = str(row[4]).strip() if len(row) > 4 else ""
            retro = "[R]" in raw_name.upper() or "[r]" in raw_name
            base = sign_to_base_degree(sign_raw)
            deg_in_sign = dms_to_decimal(deg_raw)
            abs_deg = None
            if base is not None and deg_in_sign is not None:
                abs_deg = base + deg_in_sign
            planets[alias] = {
                "sign": sign_raw,
                "degree_in_sign_dms": deg_raw,
                "degree_in_sign": deg_in_sign,
                "abs_degree": abs_deg,
                "nakshatra": nakshatra,
                "pada": pada,
                "retrograde": retro,
            }
        if planets:
            break

# ─────────────────────────────────────────────────────────────
# STEP 1D: REFINE ABSOLUTE DEGREES FROM KP TABLE (Section 92)
# ─────────────────────────────────────────────────────────────
# Section 92 rows 20+ give KP absolute degrees; use these for precision

KP_PLANET_MAP = {
    "sun": "Sun", "moon": "Moon", "mars": "Mars", "mercury": "Mercury",
    "jupiter": "Jupiter", "venus": "Venus", "saturn": "Saturn",
    "rahu": "Rahu", "ketu": "Ketu",
}

for section in kundli_raw:
    if section.get("page") == 17 and section.get("type") == "aspects":
        rows = section.get("rows", [])
        header_found = False
        for row in rows:
            if not row:
                continue
            first = str(row[0]).strip().lower()
            if first == "planet" and len(row) > 1 and "degree" in str(row[1]).lower():
                header_found = True
                continue
            if header_found:
                pname = KP_PLANET_MAP.get(first)
                if pname and pname in planets and len(row) > 1:
                    deg_raw = str(row[1]).strip()
                    kp_abs = dms_to_decimal(deg_raw)
                    if kp_abs is not None:
                        planets[pname]["abs_degree"] = kp_abs
                        planets[pname]["kp_degree_raw"] = deg_raw
        break

# ─────────────────────────────────────────────────────────────
# STEP 1E: LAGNA DEGREE
# ─────────────────────────────────────────────────────────────
lagna_sign = lagna_meta.get("Lagna", "Gemini")
lagna_lord = lagna_meta.get("Lagna Lord", "Mer")
lagna_degree_abs = None
if "ASC" in planets:
    lagna_degree_abs = planets["ASC"].get("abs_degree")

# ─────────────────────────────────────────────────────────────
# STEP 1F: COMPUTE HOUSE POSITIONS (Equal-house from Lagna)
# ─────────────────────────────────────────────────────────────

SIGN_ORDER = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpion", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]
SIGN_NORM = {
    "aries": "Aries", "taurus": "Taurus", "gemini": "Gemini", "cancer": "Cancer",
    "leo": "Leo", "virgo": "Virgo", "libra": "Libra",
    "scorpio": "Scorpion", "scorpion": "Scorpion",
    "sagittarius": "Sagittarius", "capricorn": "Capricorn",
    "aquarius": "Aquarius", "pisces": "Pisces",
}

def sign_index(sign_name):
    norm = SIGN_NORM.get(sign_name.lower().strip())
    if norm is None:
        return None
    return SIGN_ORDER.index(norm)

def house_of_planet(planet_sign, lagna_sign_name):
    p_idx = sign_index(planet_sign)
    l_idx = sign_index(lagna_sign_name)
    if p_idx is None or l_idx is None:
        return None
    return (p_idx - l_idx) % 12 + 1

# Build house → [planets] mapping
house_occupants = defaultdict(list)
planet_houses = {}

for pname, pdata in planets.items():
    if pname not in VEDIC_PLANETS:
        continue
    if pname == "ASC":
        planet_houses[pname] = 1
        house_occupants[1].append(pname)
        continue
    house = house_of_planet(pdata["sign"], lagna_sign)
    if house is not None:
        planet_houses[pname] = house
        house_occupants[house].append(pname)

# ─────────────────────────────────────────────────────────────
# STEP 1G: EXTRACT SHADBALA (Section 116)
# ─────────────────────────────────────────────────────────────

shadbala = {}   # planet -> {total_shad_bala, shad_bala_rupas, min_req, ratio, rank, dig_bala}
SHADBALA_PLANETS = ["SUN", "MOON", "MARS", "MER", "JUP", "VEN", "SAT"]
SHAD_PLANET_MAP = {
    "SUN": "Sun", "MOON": "Moon", "MARS": "Mars", "MER": "Mercury",
    "JUP": "Jupiter", "VEN": "Venus", "SAT": "Saturn",
}

for section in kundli_raw:
    if section.get("page") == 23 and section.get("type") == "planetary_table":
        rows = section.get("rows", [])
        headers = None
        for row in rows:
            if row and str(row[0]).strip() == "" and any("SUN" in str(c) for c in row):
                headers = [str(c).strip() for c in row[1:]]
                break
        if headers is None:
            continue
        # Map header index to planet name
        hdr_map = {}
        for i, h in enumerate(headers):
            p = SHAD_PLANET_MAP.get(h)
            if p:
                hdr_map[i] = p

        for row in rows:
            label = str(row[0]).strip() if row else ""
            vals = [str(c).strip() for c in row[1:]] if len(row) > 1 else []
            if label == "Total Shad Bala":
                for i, p in hdr_map.items():
                    if i < len(vals):
                        shadbala.setdefault(p, {})["total_shad_bala"] = vals[i]
            elif label == "Shadbala In Rupas":
                for i, p in hdr_map.items():
                    if i < len(vals):
                        shadbala.setdefault(p, {})["shad_bala_rupas"] = vals[i]
            elif label == "Minimum Requirements":
                for i, p in hdr_map.items():
                    if i < len(vals):
                        shadbala.setdefault(p, {})["min_req"] = vals[i]
            elif label == "Ratio":
                for i, p in hdr_map.items():
                    if i < len(vals):
                        shadbala.setdefault(p, {})["ratio"] = vals[i]
            elif label == "Relative Rank":
                for i, p in hdr_map.items():
                    if i < len(vals):
                        shadbala.setdefault(p, {})["rank"] = vals[i]
            elif label == "Total Dig Bala":
                for i, p in hdr_map.items():
                    if i < len(vals):
                        shadbala.setdefault(p, {})["dig_bala"] = vals[i]
        break

# ─────────────────────────────────────────────────────────────
# STEP 1H: EXTRACT ASPECT TABLE (Section 118)
# ─────────────────────────────────────────────────────────────

# Aspect score = weight * (1 - actual_orb / max_orb)
# The number in the table IS this score (verified mathematically).

ASPECT_WEIGHT = {
    "CONJ": 10, "OPPN": 10, "TRIN": 3, "SQUR": 3,
    "SEXT": 3, "SSQU": 1, "NONL": 1, "QUIN": 1, "SQQD": 1, "QCUN": 1,
}
ASPECT_MAX_ORB = {
    "CONJ": 15, "OPPN": 15, "TRIN": 6, "SQUR": 6,
    "SEXT": 6, "SSQU": 1, "NONL": 1, "QUIN": 1, "SQQD": 1, "QCUN": 1,
}

# Table planet header map
TABLE_HEADER_PLANET = {}
TABLE_PLANET_MAP = {
    "SUN": "Sun", "MOON": "Moon", "MARS": "Mars", "MERC": "Mercury",
    "JUPT": "Jupiter", "VENU": "Venus", "SATN": "Saturn",
    "RAHU": "Rahu", "KETU": "Ketu",
}

aspects_table = []   # list of {p1, p2, aspect_type, score}

for section in kundli_raw:
    if section.get("page") == 24 and section.get("type") == "planetary_table":
        rows = section.get("rows", [])
        if not rows:
            continue
        # First row is header
        header_row = rows[0]
        col_planets = []
        for cell in header_row[1:]:
            raw = str(cell).strip()
            # Extract planet abbreviation (first token)
            tok = raw.split()[0] if raw.split() else ""
            p = TABLE_PLANET_MAP.get(tok)
            col_planets.append(p)

        for row in rows[1:]:
            if not row:
                continue
            row_label = str(row[0]).strip()
            # Extract row planet
            tok = row_label.split()[0] if row_label.split() else ""
            p1 = TABLE_PLANET_MAP.get(tok)
            if p1 is None:
                continue
            for col_idx, p2 in enumerate(col_planets):
                if p2 is None or p2 == p1:
                    continue
                if col_idx + 1 >= len(row):
                    continue
                cell = str(row[col_idx + 1]).strip()
                if cell == "--":
                    continue
                parts = cell.split()
                if len(parts) != 2:
                    continue
                asp_type = parts[0]
                try:
                    score = float(parts[1])
                except ValueError:
                    continue
                # Only store once (upper triangle)
                exists = any(
                    (a["p1"] == p1 and a["p2"] == p2) or
                    (a["p1"] == p2 and a["p2"] == p1)
                    for a in aspects_table
                )
                if not exists:
                    aspects_table.append({
                        "p1": p1, "p2": p2,
                        "aspect_type": asp_type, "score": score
                    })
        break

def get_aspect(p1, p2):
    for a in aspects_table:
        if (a["p1"] == p1 and a["p2"] == p2) or (a["p1"] == p2 and a["p2"] == p1):
            return a
    return None

# ─────────────────────────────────────────────────────────────
# STEP 1I: DASHA TIMELINE (from section 6 = page 1 type dasha)
# ─────────────────────────────────────────────────────────────

dasha_balance_raw = lagna_meta.get("Dasha Balance", "Rah 9 Y 4 M 23 D")

mahadasha_sequence = []
for section in kundli_raw:
    if section.get("page") == 1 and section.get("type") == "dasha":
        rows = section.get("rows", [])
        if rows and rows[0]:
            header = str(rows[0][0]).strip()
            # Mahadasha header like 'RAH -18 Years 3/ 9/00 - 26/ 1/10'
            if "-" in header and "Years" in header:
                mahadasha_sequence.append(header)
        if len(mahadasha_sequence) >= 9:
            break

# ─────────────────────────────────────────────────────────────
# STEP 2: DETECT YOGAS
# ─────────────────────────────────────────────────────────────

yogas_detected = []

def get_planet_abs_deg(pname):
    p = planets.get(pname, {})
    return p.get("abs_degree")

def get_planet_sign(pname):
    p = planets.get(pname, {})
    return p.get("sign", "")

def get_planet_house(pname):
    return planet_houses.get(pname)

def is_kendra(house):
    return house in (1, 4, 7, 10)

def is_trikona(house):
    return house in (1, 5, 9)

def is_dusthana(house):
    return house in (6, 8, 12)

# House lordships for Gemini lagna
# Gemini=1, Cancer=2, Leo=3, Virgo=4, Libra=5, Scorpio=6,
# Sagittarius=7, Capricorn=8, Aquarius=9, Pisces=10, Aries=11, Taurus=12
HOUSE_LORD_GEMINI = {
    1: "Mercury", 2: "Moon", 3: "Sun", 4: "Mercury",  # Gemini/Virgo lords = Mercury
    5: "Venus", 6: "Mars", 7: "Jupiter", 8: "Saturn",  # Scorpio lord = Mars, Capricorn = Saturn
    9: "Saturn", 10: "Jupiter",  # Aquarius = Saturn, Pisces = Jupiter
    11: "Mars", 12: "Venus",  # Aries = Mars, Taurus = Venus
}
# Note: Mercury rules both 1st (Gemini) and 4th (Virgo)
# Saturn rules both 8th (Capricorn) and 9th (Aquarius)
# Jupiter rules both 7th (Sagittarius) and 10th (Pisces)
# Mars rules both 6th (Scorpio) and 11th (Aries)
# Venus rules both 5th (Libra) and 12th (Taurus)

def house_lord(house_num):
    return HOUSE_LORD_GEMINI.get(house_num)

# ── YOGA 1: Budha-Aditya Yoga ──────────────────────────────
# Sun and Mercury in the same sign

sun_sign = get_planet_sign("Sun")
merc_sign = get_planet_sign("Mercury")

if sun_sign and merc_sign and sun_sign.lower() == merc_sign.lower():
    asp = get_aspect("Sun", "Mercury")
    sun_house = get_planet_house("Sun")
    merc_house = get_planet_house("Mercury")
    yogas_detected.append({
        "yoga_name": "Budha-Aditya Yoga",
        "condition": (
            f"Sun and Mercury both occupy {sun_sign} "
            f"(House {sun_house} from Gemini Lagna). "
            f"They share the same sign, fulfilling the core condition."
        ),
        "planets": ["Sun", "Mercury"],
        "house": sun_house,
        "aspect_data": asp,
    })

# ── YOGA 2: Jupiter-Saturn Conjunction ────────────────────
# Both in Taurus (House 12)

jup_sign = get_planet_sign("Jupiter")
sat_sign = get_planet_sign("Saturn")

if jup_sign and sat_sign and jup_sign.lower() == sat_sign.lower():
    asp = get_aspect("Jupiter", "Saturn")
    jup_house = get_planet_house("Jupiter")
    yogas_detected.append({
        "yoga_name": "Jupiter-Saturn Conjunction (Taurus, House 12)",
        "condition": (
            f"Jupiter and Saturn are both in {jup_sign} (House {jup_house}). "
            f"This is a Graha-Maitri (planetary conjunction) in the 12th house."
        ),
        "planets": ["Jupiter", "Saturn"],
        "house": jup_house,
        "aspect_data": asp,
    })

# ── YOGA 3: Viparita Raja Yoga (Partial) ───────────────────
# Lord of 8th (Saturn) in 12th house + Lord of 12th (Venus) in 4th house (kendra)
# Classical rule: lord of 6/8/12 in another dusthana → Viparita Raja Yoga

sat_house = get_planet_house("Saturn")   # Saturn = lord of 8th (Capricorn)
ven_house = get_planet_house("Venus")    # Venus = lord of 12th (Taurus)
mars_house = get_planet_house("Mars")    # Mars = lord of 6th (Scorpio)

viparita_conditions = []
if sat_house == 12:
    viparita_conditions.append(
        f"Saturn (lord of House 8) is placed in House 12 (a dusthana)."
    )
if ven_house is not None and is_dusthana(ven_house):
    viparita_conditions.append(
        f"Venus (lord of House 12) is placed in House {ven_house} (a dusthana)."
    )
if mars_house is not None and is_dusthana(mars_house):
    viparita_conditions.append(
        f"Mars (lord of House 6) is placed in House {mars_house} (a dusthana)."
    )

if len(viparita_conditions) >= 1:
    note = ""
    if ven_house == 4:
        note = (
            " NOTE: Venus (12th lord) is in House 4 (a kendra, not a dusthana); "
            "full classical Viparita requires 12th lord in 6th/8th only — "
            "this condition is therefore only partially met for Venus."
        )
    yogas_detected.append({
        "yoga_name": "Viparita Raja Yoga (Partial)",
        "condition": " ".join(viparita_conditions) + note,
        "planets": ["Saturn", "Venus", "Mars"],
        "conditions_met": len(viparita_conditions),
        "conditions_needed": 2,
    })

# ── YOGA 4: Chandra-Mangal Yoga (Mars 4th aspect on Moon) ──
# Mars has special 4th, 7th, 8th house aspects in Vedic astrology.
# Mars in House 2 → 4th aspect falls on House 5 (where Moon is).

moon_house = get_planet_house("Moon")
mars_house_val = get_planet_house("Mars")

# 4th special aspect from house X = house (X-1+3) mod 12 + 1
mars_4th_asp = ((mars_house_val - 1 + 3) % 12) + 1 if mars_house_val else None

if mars_house_val and moon_house and mars_4th_asp == moon_house:
    yogas_detected.append({
        "yoga_name": "Chandra-Mangal Yoga (via Mars 4th Special Aspect)",
        "condition": (
            f"Mars (House {mars_house_val}) casts its special 4th aspect on House {mars_4th_asp}, "
            f"where Moon is placed. Moon and Mars are thus in a functional aspect relation. "
            f"Moon is in Libra (House 5), Mars is in Cancer (House 2)."
        ),
        "planets": ["Mars", "Moon"],
    })

# ── YOGA 5: Mars Neecha (Debilitation in Cancer) ───────────
DEBILITATION = {
    "Sun": "Libra", "Moon": "Scorpion", "Mars": "Cancer",
    "Mercury": "Pisces", "Jupiter": "Capricorn",
    "Venus": "Virgo", "Saturn": "Aries",
}
DEBIL_DEEPEST_DEG = {
    "Sun": 10, "Moon": 3, "Mars": 28, "Mercury": 15,
    "Jupiter": 5, "Venus": 27, "Saturn": 20,
}

for pname, debil_sign in DEBILITATION.items():
    actual_sign = get_planet_sign(pname)
    if not actual_sign:
        continue
    if actual_sign.lower() == debil_sign.lower():
        house_pos = get_planet_house(pname)
        deg = planets.get(pname, {}).get("degree_in_sign")
        deepest = DEBIL_DEEPEST_DEG.get(pname)
        note = ""
        if deg is not None and deepest is not None:
            orb_from_deepest = abs(deg - deepest)
            note = f" Degree within {debil_sign}: {deg:.2f}° (deepest debilitation at {deepest}°, orb {orb_from_deepest:.2f}°)."
        yogas_detected.append({
            "yoga_name": f"{pname} Neecha (Debilitation) in {debil_sign}, House {house_pos}",
            "condition": (
                f"{pname} is placed in {actual_sign} (House {house_pos}), "
                f"its sign of debilitation.{note}"
            ),
            "planets": [pname],
            "house": house_pos,
            "is_affliction": True,
        })

# ── YOGA 6: Kemadruma Yoga check ───────────────────────────
# If no planets in 2nd and 12th from Moon AND no planets in kendras from lagna
# (Moon is house 5, so 2nd from Moon = house 6, 12th from Moon = house 4)
moon_h = get_planet_house("Moon")
if moon_h:
    second_from_moon = (moon_h % 12) + 1
    twelfth_from_moon = ((moon_h - 2) % 12) + 1
    planets_in_2nd_from_moon = [p for p in VEDIC_PLANETS - {"ASC", "Moon"}
                                 if get_planet_house(p) == second_from_moon]
    planets_in_12th_from_moon = [p for p in VEDIC_PLANETS - {"ASC", "Moon"}
                                  if get_planet_house(p) == twelfth_from_moon]
    if not planets_in_2nd_from_moon and not planets_in_12th_from_moon:
        yogas_detected.append({
            "yoga_name": "Kemadruma Yoga (Inauspicious)",
            "condition": (
                f"Moon is in House {moon_h}. No planets in 2nd from Moon "
                f"(House {second_from_moon}) or 12th from Moon (House {twelfth_from_moon}). "
                f"Kemadruma yoga conditions met."
            ),
            "planets": ["Moon"],
            "is_affliction": True,
        })
    else:
        # Kemadruma is cancelled
        pass  # Not recording cancelled yogas as detected

# ── YOGA 7: Gajakesari check ────────────────────────────────
# Jupiter in kendra from Moon
jup_h = get_planet_house("Jupiter")
moon_h = get_planet_house("Moon")
if jup_h and moon_h:
    jup_from_moon = ((jup_h - moon_h) % 12) + 1
    if is_kendra(jup_from_moon):
        yogas_detected.append({
            "yoga_name": "Gajakesari Yoga",
            "condition": (
                f"Jupiter (House {jup_h}) is in House {jup_from_moon} from Moon (House {moon_h}) — "
                f"a kendra position from Moon."
            ),
            "planets": ["Jupiter", "Moon"],
        })
    else:
        yogas_detected.append({
            "yoga_name": "Gajakesari Yoga — NOT FORMED",
            "condition": (
                f"Jupiter is in House {jup_h}. Moon is in House {moon_h}. "
                f"Jupiter is in the {jup_from_moon}th house from Moon — "
                f"NOT a kendra (1/4/7/10). Condition NOT met."
            ),
            "planets": ["Jupiter", "Moon"],
            "not_formed": True,
        })

# ── YOGA 8: Saraswati Yoga check ────────────────────────────
# Jupiter, Mercury, Venus all in kendras (1,4,7,10) or some in kendras/2nd/5th
jup_h2 = get_planet_house("Jupiter")
merc_h = get_planet_house("Mercury")
ven_h = get_planet_house("Venus")
saraswati_check = []
for p, h in [("Jupiter", jup_h2), ("Mercury", merc_h), ("Venus", ven_h)]:
    in_kendra = is_kendra(h) if h else False
    in_2_5 = h in (2, 5) if h else False
    saraswati_check.append((p, h, in_kendra or in_2_5))
all_met = all(c[2] for c in saraswati_check)
if not all_met:
    missing = [c[0] for c in saraswati_check if not c[2]]
    yogas_detected.append({
        "yoga_name": "Saraswati Yoga — NOT FORMED",
        "condition": (
            f"Requires Jupiter, Mercury, and Venus all in kendras or 2nd/5th houses. "
            f"Jupiter is in House {jup_h2}, Mercury in House {merc_h}, Venus in House {ven_h}. "
            f"Condition NOT met for: {', '.join(missing)}."
        ),
        "not_formed": True,
    })

# ─────────────────────────────────────────────────────────────
# STEP 3: RETRIEVE CLASSICAL TEXTS
# ─────────────────────────────────────────────────────────────

def search_structural(keywords, require_all=False, max_results=3, min_score=None):
    """
    Search chunks for keywords. Returns list of best matching chunks.
    require_all: all keywords must be present (AND); otherwise OR.
    """
    results = []
    for c in filtered_chunks:
        t = c["text"].lower()
        hits = sum(1 for kw in keywords if kw.lower() in t)
        if require_all and hits < len(keywords):
            continue
        if not require_all and hits == 0:
            continue
        score = hits * c.get("score", 1)
        results.append((score, c))
    results.sort(key=lambda x: -x[0])
    seen_texts = set()
    out = []
    for score, c in results:
        snippet = c["text"][:80]
        if snippet in seen_texts:
            continue
        seen_texts.add(snippet)
        out.append(c)
        if len(out) >= max_results:
            break
    return out


def search_technical(keywords, require_all=False, max_results=3):
    results = []
    for c in enriched_chunks:
        t = c["text"].lower()
        hits = sum(1 for kw in keywords if kw.lower() in t)

        if require_all and hits < len(keywords):
            continue
        if not require_all and hits == 0:
            continue

        score = hits * c.get("score", 1)
        results.append((score, c))

    results.sort(key=lambda x: -x[0])

    seen = set()
    out = []
    for score, c in results:
        key = c["text"][:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(c)

        if len(out) >= max_results:
            break

    return out

# Classical text database per yoga topic
classical_support = {}

# Budha-Aditya: search specifically for "Budha-Aaditya" and Sun+Mercury yoga descriptions
_ba_direct = [c for c in filtered_chunks if "Budha-Aaditya" in c["text"] or "Budha-Aditya" in c["text"]]
_ba_indirect = search_structural(["sun", "mercury", "same", "sign", "yoga"], max_results=3)
classical_support["Budha-Aditya Yoga"] = (_ba_direct + _ba_indirect)[:2]

# Viparita Raja Yoga — look for the exact definition text
_vip_direct = [c for c in filtered_chunks if "Viparita Raja" in c["text"] or "Vipareeta Raja" in c["text"]]
_vip_indirect = search_structural(["viparita", "eighth", "twelfth", "sixth", "lord", "dusthana"], max_results=2)
classical_support["Viparita Raja Yoga"] = (_vip_direct + _vip_indirect)[:2]

# Chandra-Mangal — Moon and Mars combination
_cm_direct = [c for c in filtered_chunks if "Chandra-Mangal" in c["text"] or "Chandra Mangal" in c["text"]]
_cm_indirect = search_structural(["moon", "mars", "conjunction", "aspect", "wealth", "yoga"], max_results=2)
classical_support["Chandra-Mangal Yoga"] = (_cm_direct + _cm_indirect)[:2]

# Jupiter-Saturn conjunction
_js_direct = [c for c in filtered_chunks
              if ("Jupiter" in c["text"] or "Guru" in c["text"])
              and ("Saturn" in c["text"] or "Shani" in c["text"])
              and "conjoin" in c["text"].lower()]
_js_indirect = search_structural(["jupiter", "saturn", "conjunction", "twelfth", "house"], max_results=2)
classical_support["Jupiter-Saturn Conjunction"] = (_js_direct + _js_indirect)[:2]

# Neecha/Debilitation — Mars in Cancer
_mn_direct = [c for c in filtered_chunks
              if "Cancer" in c["text"] and "Mars" in c["text"]
              and ("debil" in c["text"].lower() or "fall" in c["text"].lower())]
_mn_table = [c for c in filtered_chunks if "Capricorn" in c["text"] and "Cancer" in c["text"]
             and "exaltation" in c["text"].lower() and "Mars" in c["text"]]
classical_support["Mars Neecha"] = (_mn_table + _mn_direct)[:2]

# Neecha/Debilitation — Venus in Virgo
_vn_table = [c for c in filtered_chunks if "Virgo" in c["text"] and "Venus" in c["text"]
             and "exaltation" in c["text"].lower()]
_vn_direct = [c for c in filtered_chunks if "Virgo" in c["text"] and "Venus" in c["text"]
              and ("debil" in c["text"].lower() or "fall" in c["text"].lower())]
classical_support["Venus Neecha"] = (_vn_table + _vn_direct)[:2]

# Neecha Bhanga — cancellation of debility (5 conditions)
_nb_direct = [c for c in filtered_chunks
              if "Neechabhanga" in c["text"] or "Neecha Bhanga" in c["text"]
              or "neechabhanga" in c["text"].lower()]
_nb_indirect = search_structural(["debilitation", "cancelled", "kendra", "lord", "exaltation"], max_results=2)
classical_support["Neecha Bhanga"] = (_nb_direct + _nb_indirect)[:3]

# Gajakesari
_gj_direct = [c for c in filtered_chunks if "Gajakesari" in c["text"] or "gajakesari" in c["text"].lower()]
classical_support["Gajakesari Yoga"] = _gj_direct[:2]

# Saraswati Yoga
_sw_direct = [c for c in filtered_chunks if "Saraswati Yoga" in c["text"] or "Saraswati yoga" in c["text"]]
classical_support["Saraswati Yoga"] = _sw_direct[:2]

# ─────────────────────────────────────────────────────────────
# STEP 4: TECHNICAL VALIDATION
# ─────────────────────────────────────────────────────────────


def extract_combustion_threshold(planet_name):
    results = search_technical([planet_name, "combustion", "degree"], max_results=2)
    for c in results:
        text = c["text"].lower()
        match = re.search(r'(\\d+)\\s*degree', text)
        if match:
            return float(match.group(1))
    return None


def validate_combustion(planet_name):
    sun_deg = get_planet_abs_deg("Sun")
    p_deg = get_planet_abs_deg(planet_name)

    if sun_deg is None or p_deg is None:
        return "Not found in dataset"

    orb = min(abs(p_deg - sun_deg), 360 - abs(p_deg - sun_deg))

    extracted_orb = extract_combustion_threshold(planet_name)

    DEFAULT_ORB = {
        "Moon": 12, "Mars": 17, "Mercury": 14,
        "Jupiter": 11, "Venus": 10, "Saturn": 15,
    }

    max_orb = extracted_orb if extracted_orb else DEFAULT_ORB.get(planet_name)

    if max_orb is None:
        return f"Not applicable for {planet_name}"

    source = "enriched data" if extracted_orb else "default rule"

    if orb <= max_orb:
        return f"COMBUST (orb {orb:.2f}° ≤ {max_orb}° threshold, source: {source})"

    return f"Not combust (orb {orb:.2f}° > {max_orb}° threshold, source: {source})"

def validate_shadbala(planet_name):
    data = shadbala.get(planet_name)
    if not data:
        return "Not found in dataset"
    ratio = data.get("ratio", "?")
    rupas = data.get("shad_bala_rupas", "?")
    min_req = data.get("min_req", "?")
    rank = data.get("rank", "?")
    try:
        ratio_f = float(ratio)
        status = "STRONG (ratio ≥ 1.0)" if ratio_f >= 1.0 else "WEAK (ratio < 1.0)"
    except ValueError:
        status = "uncertain"
    return (
        f"Shadbala = {rupas} Rupas (min required: {min_req}, ratio: {ratio}, rank: {rank}/7). "
        f"Status: {status}."
    )

def validate_digbala(planet_name):
    data = shadbala.get(planet_name)
    if not data:
        return "Not found in dataset"
    db = data.get("dig_bala", "?")
    try:
        db_f = float(db)
        note = "HIGH Digbala" if db_f >= 40 else ("MODERATE" if db_f >= 20 else "LOW Digbala")
    except ValueError:
        note = "uncertain"
    return f"Digbala = {db} ({note})"

def validate_aspect_tightness(p1, p2):
    asp = get_aspect(p1, p2)
    if asp is None:
        return f"No aspect recorded between {p1} and {p2} in provided dataset."
    deg1 = get_planet_abs_deg(p1)
    deg2 = get_planet_abs_deg(p2)
    if deg1 is None or deg2 is None:
        return f"{asp['aspect_type']} aspect (score {asp['score']}, degrees not available)"
    raw_diff = abs(deg1 - deg2)
    orb_diff = min(raw_diff, 360 - raw_diff)
    return (
        f"{asp['aspect_type']} aspect. Actual degree separation: {orb_diff:.2f}°. "
        f"Aspect strength score: {asp['score']} (out of max {ASPECT_WEIGHT.get(asp['aspect_type'], '?')})."
    )


# ─────────────────────────────────────────────────────────────
# STEP 5: ASSEMBLE OUTPUT
# ─────────────────────────────────────────────────────────────

SEPARATOR = "=" * 80

def fmt_chunk(c):
    return (
        f'  Book: {c["book"]}, Page: {c["page"]}\n'
        f'  Excerpt: "{c["text"][:400].strip()}..."'
    )

def render_yoga(yoga):
    name = yoga["yoga_name"]
    not_formed = yoga.get("not_formed", False)
    is_affliction = yoga.get("is_affliction", False)
    output = []
    output.append(f"\nYoga Name: {name}")
    output.append(f"\nDetected Because:\n  {yoga['condition']}")

    # Classical Support — determine the best key match
    sup_key = None
    clean_name = (name.replace(" — NOT FORMED", "")
                      .replace(" (Partial)", "")
                      .replace(" (Inauspicious)", ""))
    for k in classical_support:
        if k.lower() in clean_name.lower():
            sup_key = k
            break
    if sup_key is None:
        for k in classical_support:
            kw_tokens = set(k.lower().split())
            name_tokens = set(clean_name.lower().split())
            if kw_tokens & name_tokens:
                sup_key = k
                break
    is_neecha = "Neecha" in name and "Bhanga" not in name
    nb_texts = classical_support.get("Neecha Bhanga", [])

    output.append("\nSupporting Texts:")
    if sup_key and classical_support.get(sup_key):
        for c in classical_support[sup_key]:
            output.append(fmt_chunk(c))
    else:
        output.append("  Not found in provided data (no matching chunks retrieved).")
    if is_neecha and nb_texts:
        output.append("\n  [Neecha Bhanga / Cancellation of Debility — from classical texts]:")
        for c in nb_texts[:2]:
            output.append(fmt_chunk(c))

    # Technical Evaluation
    output.append("\nTechnical Evaluation:")
    planets_in_yoga = yoga.get("planets", [])

    # Degree analysis
    deg_lines = []
    for p in planets_in_yoga:
        abs_d = get_planet_abs_deg(p)
        deg_in_sign = planets.get(p, {}).get("degree_in_sign_dms", "?")
        sign = get_planet_sign(p)
        h = get_planet_house(p)
        if abs_d is not None:
            deg_lines.append(
                f"    {p}: {sign} {deg_in_sign} (abs {abs_d:.3f}°, House {h})"
            )
        else:
            deg_lines.append(f"    {p}: Sign={sign}, House={h}, degree not found in dataset")
    output.append("  Degree analysis:")
    output.extend(deg_lines)

    # Combustion status for relevant planets
    output.append("  Combustion status:")
    for p in planets_in_yoga:
        if p in ("Sun", "ASC", "Rahu", "Ketu"):
            continue
        comb = validate_combustion(p)
        output.append(f"    {p}: {comb}")

    # Strength assessment
    output.append("  Strength assessment (Shadbala):")
    for p in planets_in_yoga:
        if p in ("ASC", "Rahu", "Ketu"):
            output.append(f"    {p}: Not found in dataset (not in Shadbala table)")
            continue
        s = validate_shadbala(p)
        output.append(f"    {p}: {s}")
        d = validate_digbala(p)
        output.append(f"           Digbala — {d}")

    # Aspect tightness if 2 planets
    if len(planets_in_yoga) == 2 and not yoga.get("not_formed"):
        output.append("  Conjunction/Aspect tightness:")
        tightness = validate_aspect_tightness(planets_in_yoga[0], planets_in_yoga[1])
        output.append(f"    {tightness}")

    # Neecha Bhanga analysis for debilitated planets
    if is_neecha and len(planets_in_yoga) == 1:
        pname = planets_in_yoga[0]
        output.append("  Neecha Bhanga (Cancellation of Debility) Check:")
        # 5 classical conditions (per book7, page 89-90 as retrieved):
        # (1) Lord of debil-sign OR planet exalted in debil-sign in kendra from lagna or Moon
        # (2) Lord of debil-sign AND lord of exaltation-sign mutually in kendra
        # (3) Debilitated planet aspected by lord of its sign
        # (4) Same as (1) — repeated in some texts as separate condition
        # (5) Debilitated planet in kendra (with reference to Moon or Lagna)
        DEBIL_SIGN_LORD = {
            "Mars": "Moon",      # Cancer lord = Moon
            "Venus": "Mercury",  # Virgo lord = Mercury
        }
        EXALT_SIGN_PLANET = {
            "Mars": "Jupiter",   # Jupiter exalts in Cancer
            "Venus": "Mercury",  # Mercury exalts in Virgo
        }
        debil_lord = DEBIL_SIGN_LORD.get(pname)
        exalt_planet = EXALT_SIGN_PLANET.get(pname)

        # Condition (1): debil-sign lord in kendra from Lagna
        c1a = False
        c1b = False
        if debil_lord:
            dl_house = get_planet_house(debil_lord)
            c1a = is_kendra(dl_house) if dl_house else False
            output.append(
                f"    Condition (1a): {debil_lord} (lord of debil-sign) in kendra from Lagna? "
                f"{debil_lord} is in House {dl_house}. "
                f"{'MET' if c1a else 'NOT MET'}."
            )
        if exalt_planet and exalt_planet != debil_lord:
            ep_house = get_planet_house(exalt_planet)
            c1b = is_kendra(ep_house) if ep_house else False
            output.append(
                f"    Condition (1b): {exalt_planet} (planet exalted in debil-sign) in kendra from Lagna? "
                f"{exalt_planet} is in House {ep_house}. "
                f"{'MET' if c1b else 'NOT MET'}."
            )

        # Condition (1) from Moon — only if debil_lord is not Moon itself
        if debil_lord and debil_lord != "Moon":
            dl_house = get_planet_house(debil_lord)
            moon_h_nb = get_planet_house("Moon")
            if dl_house and moon_h_nb:
                pos_from_moon = ((dl_house - moon_h_nb) % 12) + 1
                c1c = is_kendra(pos_from_moon)
                output.append(
                    f"    Condition (1c): {debil_lord} in kendra from Moon? "
                    f"{debil_lord} is in House {dl_house}, Moon in House {moon_h_nb}, "
                    f"so {debil_lord} is {pos_from_moon}th from Moon. "
                    f"{'MET' if c1c else 'NOT MET'}."
                )
        elif debil_lord == "Moon":
            output.append(
                f"    Condition (1c): Debil-sign lord is Moon itself — "
                "condition (1c) from Moon is not independently testable."
            )

        # Condition (5): Debilitated planet itself in kendra (from Lagna)
        p_house = get_planet_house(pname)
        c5 = is_kendra(p_house) if p_house else False
        output.append(
            f"    Condition (5): {pname} itself in kendra from Lagna? "
            f"{pname} is in House {p_house}. "
            f"{'MET' if c5 else 'NOT MET'}."
        )

        any_nb = c1a or c1b or c5
        if not any_nb:
            output.append(
                f"    SUMMARY: No Neecha Bhanga conditions are met for {pname}. "
                "Debilitation is unmitigated per extracted data."
            )
        else:
            output.append(
                f"    SUMMARY: One or more Neecha Bhanga conditions are partially indicated. "
                "See individual condition results above."
            )

    # Limitations
    lims = []
    for p in planets_in_yoga:
        if planets.get(p, {}).get("abs_degree") is None:
            lims.append(f"Absolute degree of {p} not available.")
    if yoga.get("conditions_met") is not None:
        met = yoga["conditions_met"]
        needed = yoga.get("conditions_needed", 2)
        if met < needed:
            lims.append(
                f"Only {met} of {needed} classical conditions fully met — "
                "yoga is partial."
            )
    output.append("  Data limitations:")
    if lims:
        for l in lims:
            output.append(f"    - {l}")
    else:
        output.append("    None identified.")

    # Final interpretation
    output.append("\nFinal Interpretation:")
    if not_formed:
        output.append(
            f"  Based strictly on extracted data, {name} is NOT formed. "
            f"The conditions extracted from kundli_final_structured.json do not satisfy "
            "the classical requirement as retrieved from filtered_structured_chunks.json."
        )
    elif is_affliction:
        output.append(
            f"  {name} is confirmed from extracted data. "
            "This is an affliction/challenging configuration. "
            "Classical texts describe reduced signification of the afflicted planet. "
            "Interpretation is strictly per extracted positions and retrieved text."
        )
    elif "Partial" in name:
        output.append(
            f"  {name} is partially indicated. "
            "Not all classical conditions are simultaneously met. "
            "Partial yoga effects may manifest, dependent on dasha activation."
        )
    else:
        output.append(
            f"  {name} is confirmed from extracted data. "
            "Effects as described in retrieved classical texts apply, "
            "subject to planetary strength and dasha activation noted above."
        )

    return "\n".join(output)


# ─────────────────────────────────────────────────────────────
# MAIN OUTPUT
# ─────────────────────────────────────────────────────────────

def main():
    lines = []
    lines.append(SEPARATOR)
    lines.append("VEDIC ASTROLOGY RESEARCH ENGINE — DATA-GROUNDED REPORT")
    lines.append(SEPARATOR)

    # Birth data header
    lines.append("\n[BIRTH DATA — from kundli_final_structured.json, page 2]")
    for k, v in birth_meta.items():
        lines.append(f"  {k}: {v}")

    lines.append(f"\n[LAGNA DATA]")
    lagna_fields = ["Lagna", "Lagna Lord", "Rasi", "Rasi Lord",
                    "Nakshatra-Pada", "Nakshatra Lord", "Dasa Balance", "Ayanamsa Name"]
    for k in lagna_fields:
        v = lagna_meta.get(k, "Not found in dataset")
        lines.append(f"  {k}: {v}")

    lines.append("\n" + SEPARATOR)
    lines.append("STEP 1: EXTRACTED AND NORMALIZED PLANETARY DATA")
    lines.append(SEPARATOR)
    lines.append(
        f"\n{'Planet':<12} {'Sign':<14} {'Deg in Sign':<14} {'Abs Deg':>10} "
        f"{'House':>6} {'Retro':>6} {'Nakshatra':<16} {'Pada'}"
    )
    lines.append("-" * 90)
    for pname in ["ASC", "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]:
        pd = planets.get(pname, {})
        abs_d = pd.get("abs_degree")
        abs_str = f"{abs_d:.3f}" if abs_d is not None else "UNCERTAIN"
        h = planet_houses.get(pname, "?")
        retro = "R" if pd.get("retrograde") else ""
        lines.append(
            f"{pname:<12} {pd.get('sign', '?'):<14} {pd.get('degree_in_sign_dms', '?'):<14} "
            f"{abs_str:>10} {str(h):>6} {retro:>6} {pd.get('nakshatra','?'):<16} {pd.get('pada','?')}"
        )

    lines.append("\n[HOUSE OCCUPANTS]")
    for h in range(1, 13):
        occ = house_occupants.get(h, [])
        lines.append(f"  House {h:>2} ({SIGN_ORDER[(sign_index(lagna_sign) + h - 1) % 12]}): {', '.join(occ) if occ else 'empty'}")

    lines.append("\n[SHADBALA SUMMARY]")
    for p in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]:
        s = shadbala.get(p, {})
        lines.append(
            f"  {p:<10}: {s.get('shad_bala_rupas','?')} Rupas "
            f"(min {s.get('min_req','?')}, ratio {s.get('ratio','?')}, "
            f"rank {s.get('rank','?')}/7, digbala {s.get('dig_bala','?')})"
        )

    lines.append("\n[ASPECT TABLE — Key Vedic Pairs from Section 118]")
    for a in aspects_table:
        if a["p1"] in VEDIC_PLANETS and a["p2"] in VEDIC_PLANETS:
            lines.append(
                f"  {a['p1']}-{a['p2']}: {a['aspect_type']} (score {a['score']})"
            )

    lines.append("\n[DASHA TIMELINE — from kundli_final_structured.json page 1]")
    lines.append(f"  Dasha Balance at birth: {dasha_balance_raw}")
    for md in mahadasha_sequence[:9]:
        lines.append(f"  {md}")

    lines.append("\n" + SEPARATOR)
    lines.append("STEPS 2–5: YOGA DETECTION → CLASSICAL SUPPORT → VALIDATION → INTERPRETATION")
    lines.append(SEPARATOR)

    for yoga in yogas_detected:
        lines.append("\n" + ("─" * 80))
        lines.append(render_yoga(yoga))

    lines.append("\n" + SEPARATOR)
    lines.append("END OF REPORT")
    lines.append(SEPARATOR)

    report = "\n".join(lines)
    return report


if __name__ == "__main__":
    output = main()
    print(output)
    # Also write to file
    out_path = os.path.join(BASE, "vedic_analysis_report.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\n[Report also saved to {out_path}]", file=sys.stderr)
