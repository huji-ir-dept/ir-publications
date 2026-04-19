#!/usr/bin/env python3
"""
enrich_countries.py
===================
מוסיף מדינת שיוך לכל מחבר שותף בפרסומים.
מקור: OpenAlex לפי DOI.

שימוש:
    python3 enrich_countries.py
"""

import json, time, requests
from pathlib import Path

OUTPUT_FILE = "publications.json"
EMAIL       = "ir-dept@mail.huji.ac.il"
OPENALEX    = "https://api.openalex.org"
RATE        = 0.12   # שניות בין קריאות

# מיפוי קוד מדינה → שם מלא
COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "DE": "Germany",
    "FR": "France", "CA": "Canada", "AU": "Australia", "NL": "Netherlands",
    "IL": "Israel", "SE": "Sweden", "NO": "Norway", "DK": "Denmark",
    "FI": "Finland", "CH": "Switzerland", "AT": "Austria", "BE": "Belgium",
    "IT": "Italy", "ES": "Spain", "PT": "Portugal", "PL": "Poland",
    "CZ": "Czech Republic", "HU": "Hungary", "RO": "Romania",
    "TR": "Turkey", "RU": "Russia", "CN": "China", "JP": "Japan",
    "KR": "South Korea", "IN": "India", "BR": "Brazil", "MX": "Mexico",
    "AR": "Argentina", "ZA": "South Africa", "NG": "Nigeria",
    "EG": "Egypt", "JO": "Jordan", "LB": "Lebanon", "PS": "Palestine",
    "HK": "Hong Kong", "SG": "Singapore", "NZ": "New Zealand",
    "IE": "Ireland", "GR": "Greece", "UA": "Ukraine", "CL": "Chile",
}


def get_country(code):
    return COUNTRY_NAMES.get(code, code) if code else None


# תיקון ידני: מוסדות שOpenAlex מזהה בטעות
# "Hebrew College" (ניוטון MA) ← נקרא לפעמים בטעות במקום "Hebrew University of Jerusalem"
INSTITUTION_CORRECTIONS = {
    "hebrew college": ("Hebrew University of Jerusalem", "Israel"),
}

def correct_institution(institution, country):
    """מתקן שיוכים מוסדיים שגויים של OpenAlex."""
    if not institution:
        return institution, country
    inst_lower = institution.lower().strip()
    # בדוק תיקון מדויק
    if inst_lower in INSTITUTION_CORRECTIONS:
        return INSTITUTION_CORRECTIONS[inst_lower]
    # Hebrew College עם וריאציות
    if inst_lower in ("hebrew college", "the hebrew college"):
        return "Hebrew University of Jerusalem", "Israel"
    return institution, country


def fetch_openalex_doi(doi_url):
    """שולף authorships מ-OpenAlex לפי DOI."""
    doi_clean = doi_url.replace("https://doi.org/", "")
    try:
        r = requests.get(
            f"{OPENALEX}/works/doi:{doi_clean}",
            params={"select": "authorships", "mailto": EMAIL},
            timeout=20
        )
        if r.status_code == 200:
            return r.json().get("authorships", [])
        return []
    except Exception:
        return []
    finally:
        time.sleep(RATE)


def main():
    data = json.loads(Path(OUTPUT_FILE).read_text(encoding="utf-8"))
    pubs = data["publications"]

    # מצא פרסומים שיש להם DOI וחסרים מידע מדינה
    needs_enrichment = [
        p for p in pubs
        if p.get("doi") and any(
            not a.get("country") for a in p.get("authors", [])
        )
    ]

    print(f"מעשיר מדינות ל-{len(needs_enrichment)} פרסומים...")
    enriched = 0

    for i, pub in enumerate(needs_enrichment, 1):
        print(f"  [{i}/{len(needs_enrichment)}] {pub['title'][:55]}...", flush=True)

        authorships = fetch_openalex_doi(pub["doi"])
        if not authorships:
            continue

        # בנה מיפוי שם → מדינה ומוסד
        name_to_info = {}
        for a in authorships:
            author_name = (a.get("author") or {}).get("display_name", "")
            institutions = a.get("institutions") or []
            country = None
            institution = None
            for inst in institutions:
                if inst.get("country_code"):
                    country = get_country(inst["country_code"])
                    institution = inst.get("display_name", "")
                    break

            if author_name and (country or institution):
                # תקן שיוכים שגויים
                institution, country = correct_institution(institution, country)
                # שמור לפי שם מלא ולפי שם משפחה
                name_to_info[author_name.lower()] = {
                    "country": country,
                    "institution": institution
                }
                last = author_name.split()[-1].lower() if author_name else ""
                if last:
                    name_to_info.setdefault(last, {
                        "country": country,
                        "institution": institution
                    })

        # עדכן מחברים
        updated = False
        for author in pub.get("authors", []):
            if author.get("country"):
                continue
            name = author.get("name", "")
            name_lower = name.lower()
            last_name = name.split()[-1].lower() if name else ""

            info = name_to_info.get(name_lower) or name_to_info.get(last_name)
            if info:
                if info.get("country"):
                    author["country"] = info["country"]
                if info.get("institution"):
                    author["institution"] = info["institution"]
                updated = True

        if updated:
            enriched += 1

    print(f"\n✅ עודכנו {enriched} פרסומים")

    # ── תיקון רטרואקטיבי של שיוכים שגויים קיימים ──
    fixed = 0
    for pub in pubs:
        for author in pub.get("authors", []):
            inst = author.get("institution", "")
            country = author.get("country", "")
            new_inst, new_country = correct_institution(inst, country)
            if new_inst != inst or new_country != country:
                author["institution"] = new_inst
                author["country"] = new_country
                fixed += 1
    if fixed:
        print(f"   תוקנו {fixed} שיוכים שגויים (כגון Hebrew College → Hebrew University)")

    # סטטיסטיקה
    total_authors = sum(len(p.get("authors", [])) for p in pubs)
    with_country  = sum(
        1 for p in pubs for a in p.get("authors", []) if a.get("country")
    )
    print(f"   מחברים עם מדינה: {with_country}/{total_authors} ({100*with_country//max(total_authors,1)}%)")

    Path(OUTPUT_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"   נשמר: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
