#!/usr/bin/env python3
"""
Auto-discover new BatYam sections on coing.co
Runs periodically (weekly) to find newly added sections
"""

import requests
import re
import batyam_db as db

BASE_URL = "https://www.coing.co"
CITY_SLUG = "batya"

# Patterns to test for new sections — coing.co slugs are PascalCase or lowercase,
# usually one of: language-agnostic English, Hebrew transliteration, or a holiday/topic.
# This list grows whenever we hit a missing section in the wild — see
# communities_data.json for the canonical confirmed list.
PATTERNS = [
    # Confirmed in production (kept for reachability checks)
    "BatYam_Main",
    "BatYam_culture",
    "BatYam_shelters",
    "BatYam_south",
    "BatYam_Kehilot",          # קהילות — confirmed 2026-05-07
    "plusi_all",
    "BatYam_PLUSI_Hagim",
    # Likely English-named sections
    "BatYam_North", "BatYam_East", "BatYam_West", "BatYam_Central",
    "BatYam_Sports", "BatYam_Kids", "BatYam_Teen", "BatYam_Elderly",
    "BatYam_Education", "BatYam_Health", "BatYam_Environment",
    "BatYam_Community", "BatYam_Volunteering", "BatYam_Business",
    "BatYam_Events", "BatYam_Workshops", "BatYam_Art", "BatYam_Music",
    "BatYam_Theater", "BatYam_Family", "BatYam_Senior", "BatYam_Youth",
    "BatYam_Women", "BatYam_Men", "BatYam_Disability", "BatYam_Russian",
    # Hebrew-transliterated (coing.co frequently uses these)
    "BatYam_Toranut", "BatYam_Mishpacha", "BatYam_Gilaim",
    "BatYam_Tinokot", "BatYam_Peutot", "BatYam_Yeladim",
    "BatYam_Mitnasim", "BatYam_Sport", "BatYam_Tarbut",
    "BatYam_Hagim", "BatYam_Shabbat", "BatYam_Klitah",
    "BatYam_Olim", "BatYam_Vatikim", "BatYam_GilHaZahav",
    # Sub-locations
    "BatYam_RamatYosef", "BatYam_RamatHanasi", "BatYam_Amidar",
    "BatYam_LevHair", "BatYam_ParkHayam",
]

def discover_sections():
    """Discover all BatYam sections with CIDs"""
    conn = db.get_db()
    existing = {r[0]: r[1] for r in conn.execute("SELECT slug, cid FROM sections").fetchall()}
    conn.close()

    found = {}
    print(f"Discovering BatYam sections... ({len(PATTERNS)} patterns to test)")

    for slug in PATTERNS:
        url = f"{BASE_URL}/{CITY_SLUG}/{slug}"
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)

            if resp.status_code == 200 and 'var community' in resp.text:
                # Try multiple cid patterns; reject single-digit hits as noise.
                cid = None
                for pat in (r'"cid"\s*:\s*(\d+)', r'cid=(\d+)', r'"id"\s*:\s*(\d+)'):
                    m2 = re.search(pat, resp.text)
                    if m2 and int(m2.group(1)) > 100:
                        cid = int(m2.group(1))
                        break
                if cid is not None:
                    name_match = re.search(r'"name":"([^"]+)"', resp.text)
                    name = name_match.group(1) if name_match else slug

                    is_new = slug not in existing
                    status = "NEW" if is_new else "OK"
                    print(f"  [{status}] {slug:<35} cid={cid}")

                    found[slug] = {"cid": cid, "name": name, "is_new": is_new}
        except:
            pass

    # Add new sections to database
    new_sections = {s: f for s, f in found.items() if f["is_new"]}
    if new_sections:
        print(f"\n✅ Found {len(new_sections)} NEW sections! Adding to database...")
        conn = db.get_db()
        for slug, info in new_sections.items():
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO sections (slug, name, cid, city, active) VALUES (?, ?, ?, ?, ?)",
                    (slug, info["name"], info["cid"], CITY_SLUG, 1)
                )
                print(f"    Added: {slug} (cid={info['cid']})")
            except Exception as e:
                print(f"    Error: {e}")
        conn.commit()
        conn.close()
        return True
    else:
        print("\n✓ No new sections found.")
        return False

if __name__ == "__main__":
    print("BatYam Sections Discovery")
    print("=" * 50)
    discover_sections()
