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

# Patterns to test for new sections
PATTERNS = [
    "BatYam_Main",
    "BatYam_culture",
    "BatYam_shelters",
    "BatYam_south",
    "BatYam_North",
    "BatYam_PLUSI_Hagim",
    "plusi_all",
    # Try other variations
    "BatYam_East",
    "BatYam_West",
    "BatYam_Central",
    "BatYam_Sports",
    "BatYam_Kids",
    "BatYam_Teen",
    "BatYam_Elderly",
    "BatYam_Education",
    "BatYam_Health",
    "BatYam_Culture",
    "BatYam_Environment",
    "BatYam_Community",
    "BatYam_Volunteering",
    "BatYam_Business",
    "BatYam_Events",
    "BatYam_Workshops",
    "BatYam_Art",
    "BatYam_Music",
    "BatYam_Theater",
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
                match = re.search(r'"id":(\d+)', resp.text)
                if match:
                    cid = int(match.group(1))
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
