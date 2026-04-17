#!/usr/bin/env python3
"""
fetch_publications.py
=====================
שואב פרסומים של חברי סגל מחלקת יחסים בינלאומיים באוניברסיטה העברית.

מקורות (לפי סדר עדיפות לכל חבר סגל):
  1. ORCID API    — אם יש ORCID ID → הכי מדויק, מעודכן ע"י החוקר עצמו
  2. Crossref     — השלמה לספרים ופרקי ספרים (לפי שם)
  3. OpenAlex     — כיסוי רחב של מאמרים (לפי שם + מוסד)

שימוש:
    python3 fetch_publications.py                    ← סריקה מלאה
    python3 fetch_publications.py --test             ← 2 חברי סגל בלבד
    python3 fetch_publications.py --recent           ← שנתיים אחרונות בלבד
    python3 fetch_publications.py --until-year 2023 ← עד סוף 2023
"""

import json, time, argparse, requests
from datetime import datetime, date
from pathlib import Path

# ── הגדרות ─────────────────────────────────────────────────────────────────
CONFIG_FILE   = "faculty_config.json"
OUTPUT_FILE   = "publications.json"
OPENALEX_BASE = "https://api.openalex.org"
ORCID_BASE    = "https://pub.orcid.org/v3.0"
CROSSREF_BASE = "https://api.crossref.org"
EMAIL         = "ir-dept@mail.huji.ac.il"
PER_PAGE      = 50
YEARS_BACK    = 10
RATE_LIMIT    = 0.2

# ── עזרים ──────────────────────────────────────────────────────────────────
def get(url, params=None, headers=None):
    if params is None: params = {}
    if headers is None: headers = {}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        time.sleep(RATE_LIMIT)
        return r.json()
    except Exception as e:
        print(f"\n    ⚠ {e}")
        return {}

def reconstruct_abstract(inv):
    if not inv: return ""
    words = {}
    for word, positions in inv.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words[i] for i in sorted(words))

# ── ORCID ───────────────────────────────────────────────────────────────────
def fetch_from_orcid(orcid_id, from_year, until_year=None):
    """שואב פרסומים ישירות מפרופיל ORCID של החוקר."""
    works = []
    data = get(f"{ORCID_BASE}/{orcid_id}/works",
               headers={"Accept": "application/json"})
    if not data:
        return works

    for group in data.get("group", []):
        for ws in group.get("work-summary", []):
            pub_year = None
            pd = ws.get("publication-date")
            if pd and pd.get("year"):
                pub_year = int(pd["year"]["value"])
            if pub_year and pub_year < from_year:
                continue
            if until_year and pub_year and pub_year > until_year:
                continue

            title = ""
            tt = ws.get("title", {})
            if tt and tt.get("title"):
                title = tt["title"].get("value", "")

            doi = ""
            for eid in ws.get("external-ids", {}).get("external-id", []):
                if eid.get("external-id-type") == "doi":
                    doi = eid.get("external-id-value", "")
                    if doi and not doi.startswith("http"):
                        doi = f"https://doi.org/{doi}"
                    break

            journal = ws.get("journal-title", {})
            if isinstance(journal, dict):
                journal = journal.get("value", "")

            work_type = ws.get("type", "journal-article").lower().replace("_", "-")

            uid = f"orcid-{orcid_id}-{ws.get('put-code','')}"
            works.append({
                "id":      uid,
                "title":   title,
                "year":    pub_year,
                "date":    f"{pub_year}-01-01" if pub_year else "",
                "journal": journal or "",
                "type":    work_type,
                "doi":     doi,
                "pdf_url": "",
                "abstract": "",
                "cited_by":  0,
                "source":    "orcid",
            })
    return works

# ── OpenAlex ────────────────────────────────────────────────────────────────
def find_author_openalex(name, ror, person=None):
    if person and person.get("openalex_id"):
        data = get(f"{OPENALEX_BASE}/authors/{person['openalex_id']}",
                   params={"mailto": EMAIL})
        if data.get("id"):
            return data

    data = get(f"{OPENALEX_BASE}/authors", {
        "search": name,
        "filter": f"affiliations.institution.ror:https://ror.org/{ror}",
        "per-page": 10, "mailto": EMAIL
    })
    results = data.get("results", [])
    if results:
        return results[0]

    data = get(f"{OPENALEX_BASE}/authors", {
        "search": name, "per-page": 5, "mailto": EMAIL
    })
    results = data.get("results", [])
    last = name.split()[-1].lower()
    for r in results:
        if last in r.get("display_name", "").lower():
            return r
    return results[0] if results else None

def fetch_from_openalex(author_id, from_year, until_year=None):
    works, cursor = [], "*"
    year_filter = f"publication_year:>{from_year - 1}"
    if until_year:
        year_filter += f",publication_year:<{until_year + 1}"
    while cursor:
        data = get(f"{OPENALEX_BASE}/works", {
            "filter": f"author.id:{author_id},{year_filter}",
            "sort": "publication_date:desc",
            "per-page": PER_PAGE, "cursor": cursor,
            "select": ("id,doi,title,publication_year,publication_date,"
                       "primary_location,authorships,abstract_inverted_index,"
                       "cited_by_count,type,best_oa_location"),
            "mailto": EMAIL
        })
        batch = data.get("results", [])
        works.extend(batch)
        cursor = data.get("meta", {}).get("next_cursor")
        if not batch: break
    return works

def normalize_openalex(work, faculty_name):
    authors = [{"name": a.get("author", {}).get("display_name", "")}
               for a in work.get("authorships", [])]
    loc    = work.get("primary_location") or {}
    source = loc.get("source") or {}
    doi    = work.get("doi", "") or ""
    oa     = work.get("best_oa_location") or {}
    return {
        "id":             work.get("id", ""),
        "title":          work.get("title", ""),
        "year":           work.get("publication_year"),
        "date":           work.get("publication_date", ""),
        "journal":        source.get("display_name", ""),
        "type":           work.get("type", "article"),
        "doi":            doi if doi.startswith("http") else (f"https://doi.org/{doi}" if doi else ""),
        "pdf_url":        oa.get("pdf_url", "") or "",
        "abstract":       reconstruct_abstract(work.get("abstract_inverted_index")),
        "cited_by":       work.get("cited_by_count", 0),
        "faculty_author": faculty_name,
        "authors":        authors,
        "source":         "openalex",
    }

# ── Crossref ────────────────────────────────────────────────────────────────
def fetch_from_crossref(name, from_year, until_year=None, orcid=None):
    """
    חיפוש פרסומים ב-Crossref.
    אם יש ORCID — מחפש לפי ORCID (מדויק 100%).
    אחרת — מחפש לפי שם עם אימות שם מלא.
    """
    works = []

    if orcid:
        # ── חיפוש לפי ORCID — הכי מדויק ──────────────────────────
        params = {
            "filter": f"orcid:{orcid},from-pub-date:{from_year}",
            "rows": 100,
            "mailto": EMAIL,
            "select": "DOI,title,published,type,container-title,author,abstract"
        }
        if until_year:
            params["filter"] += f",until-pub-date:{until_year}"
        data = get(f"{CROSSREF_BASE}/works", params)
        items = data.get("message", {}).get("items", [])
        for item in items:
            doi_val  = item.get("DOI", "")
            pub_date = item.get("published", {})
            parts    = pub_date.get("date-parts", [[None]])[0]
            year     = parts[0] if parts else None
            titles   = item.get("title", [])
            title    = titles[0] if titles else ""
            journals = item.get("container-title", [])
            journal  = journals[0] if journals else ""
            works.append({
                "id":       f"crossref-{doi_val.replace('/', '-')}",
                "title":    title,
                "year":     year,
                "date":     f"{year}-01-01" if year else "",
                "journal":  journal,
                "type":     item.get("type", "journal-article"),
                "doi":      f"https://doi.org/{doi_val}" if doi_val else "",
                "pdf_url":  "",
                "abstract": item.get("abstract", ""),
                "cited_by": 0,
                "source":   "crossref",
            })
    else:
        # ── חיפוש לפי שם — דורש אימות שם מלא ────────────────────
        name_parts = name.lower().split()
        first_name = name_parts[0]
        last_name  = name_parts[-1]

        params = {
            "query.author": name,
            "filter": f"from-pub-date:{from_year}",
            "rows": 50,
            "mailto": EMAIL,
            "select": "DOI,title,published,type,container-title,author,abstract"
        }
        if until_year:
            params["filter"] += f",until-pub-date:{until_year}"

        data = get(f"{CROSSREF_BASE}/works", params)
        items = data.get("message", {}).get("items", [])
        for item in items:
            authors = item.get("author", [])
            # אימות שם מלא: שם משפחה + ראשית שם פרטי
            match = any(
                last_name in (a.get("family", "") or "").lower() and
                (a.get("given", "") or "").lower().startswith(first_name[0])
                for a in authors
            )
            if not match:
                continue
            doi_val  = item.get("DOI", "")
            pub_date = item.get("published", {})
            parts    = pub_date.get("date-parts", [[None]])[0]
            year     = parts[0] if parts else None
            titles   = item.get("title", [])
            title    = titles[0] if titles else ""
            journals = item.get("container-title", [])
            journal  = journals[0] if journals else ""
            works.append({
                "id":       f"crossref-{doi_val.replace('/', '-')}",
                "title":    title,
                "year":     year,
                "date":     f"{year}-01-01" if year else "",
                "journal":  journal,
                "type":     item.get("type", "journal-article"),
                "doi":      f"https://doi.org/{doi_val}" if doi_val else "",
                "pdf_url":  "",
                "abstract": item.get("abstract", ""),
                "cited_by": 0,
                "source":   "crossref",
            })
    return works

import re as _re

def normalize_title(title):
    """מנרמל כותרת להשוואה מלאה."""
    if not title: return ""
    t = title.lower()
    t = _re.sub(r'[^\w\s]', ' ', t)
    t = _re.sub(r'\s+', ' ', t).strip()
    return t

def title_fingerprint(title):
    """
    מחזיר טביעת אצבע של כותרת — 6 המילים המשמעותיות הראשונות
    מהכותרת הראשית בלבד (לפני : או –).
    מאפשר זיהוי כפילויות גם אם כותרת-משנה שונה.
    """
    if not title: return ""
    stop = {"a","an","the","of","in","on","at","to","for","and","or","but",
            "is","are","was","were","be","been","by","with","from","that","this","its"}
    # גזור כותרת-משנה
    main = _re.split(r'[:\u2013\u2014]', title)[0]
    t = normalize_title(main)
    words = [w for w in t.split() if w not in stop and len(w) > 2]
    return " ".join(words[:6])

# ── MAIN ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test",        action="store_true")
    parser.add_argument("--recent",      action="store_true")
    parser.add_argument("--from-year",   type=int, dest="from_year",  help="שאב מאיזו שנה (למשל: 2020)")
    parser.add_argument("--until-year",  type=int, dest="until_year")
    args = parser.parse_args()

    config = json.loads(Path(CONFIG_FILE).read_text(encoding="utf-8"))
    ror    = config["institution_ror"]
    flist  = [f for f in config["faculty"] if f.get("active", True)]
    if args.test:
        flist = flist[:2]

    if args.from_year:
        from_year = args.from_year
    else:
        from_year = date.today().year - (1 if args.recent else YEARS_BACK)
    until_year = args.until_year

    output_path = Path(OUTPUT_FILE)
    if output_path.exists():
        existing     = json.loads(output_path.read_text(encoding="utf-8"))
        existing_ids = {p["id"]: p for p in existing.get("publications", [])}
        fac_meta     = {f["name"]: f for f in existing.get("faculty_meta", [])}
    else:
        existing_ids = {}
        fac_meta     = {}

    all_works = list(existing_ids.values())
    seen_ids  = set(existing_ids.keys())
    # deduplication לפי DOI וגם לפי טביעת אצבע של כותרת (fuzzy — לספרים ופרקים ללא DOI)
    seen_dois        = {p["doi"].lower() for p in all_works if p.get("doi")}
    seen_fingerprints = {title_fingerprint(p["title"]) for p in all_works if p.get("title")}

    print(f"\n{'='*62}")
    print(f"HUJI IR Department — Publication Fetcher (multi-source)")
    print(f"מקורות: ORCID → Crossref → OpenAlex")
    print(f"טווח שנים: {from_year}–{until_year or 'היום'}")
    if args.test: print("מצב: בדיקה (2 חברי סגל)")
    print(f"{'='*62}\n")
    updated_meta = []

    for i, person in enumerate(flist, 1):
        name    = person["name"]
        orcid   = person.get("orcid", "")
        skip_oa = person.get("skip_openalex", False)
        new_count = 0

        print(f"[{i:02d}/{len(flist):02d}] {name}", end=" ")

        # ── מקור 1: ORCID ──────────────────────────────────────────
        if orcid:
            print(f"[ORCID]", end=" ", flush=True)
            orcid_works = fetch_from_orcid(orcid, from_year, until_year)
            for w in orcid_works:
                uid   = w["id"]
                doi   = (w.get("doi") or "").lower()
                nfp = title_fingerprint(w.get("title",""))
                if uid not in seen_ids and (not doi or doi not in seen_dois) and (not nfp or nfp not in seen_fingerprints):
                    w["faculty_author"] = name
                    w["authors"]        = [{"name": name}]
                    all_works.append(w)
                    seen_ids.add(uid)
                    if doi:    seen_dois.add(doi)
                    if nfp: seen_fingerprints.add(nfp)
                    new_count += 1
            print(f"✓ {len(orcid_works)} pubs from ORCID, {new_count} new", end="")

        # ── מקור 2: Crossref ───────────────────────────────────────
        cr_works = fetch_from_crossref(name, from_year, until_year, orcid=orcid)
        cr_new = 0
        for w in cr_works:
            uid    = w["id"]
            doi    = (w.get("doi") or "").lower()
            nfp = title_fingerprint(w.get("title",""))
            if uid not in seen_ids and (not doi or doi not in seen_dois) and (not nfp or nfp not in seen_fingerprints):
                w["faculty_author"] = name
                w["authors"]        = [{"name": name}]
                all_works.append(w)
                seen_ids.add(uid)
                if doi:    seen_dois.add(doi)
                if nfp: seen_fingerprints.add(nfp)
                new_count += 1
                cr_new += 1
        if cr_new:
            print(f" | +{cr_new} from Crossref", end="")

        # ── מקור 3: OpenAlex ───────────────────────────────────────
        oa_new = 0
        if not skip_oa:
            author = find_author_openalex(name, ror, person)
            if author:
                oa_works  = fetch_from_openalex(author["id"], from_year, until_year)
                works_cnt = author.get("works_count", 0)
                cited_cnt = author.get("cited_by_count", 0)
                person["openalex_id"]  = author["id"]
                person["cited_total"]  = cited_cnt
                for w in oa_works:
                    uid = w.get("id")
                    if uid and uid not in seen_ids:
                        norm   = normalize_openalex(w, name)
                        doi    = (norm.get("doi") or "").lower()
                        nfp = title_fingerprint(norm.get("title",""))
                        if (doi and doi in seen_dois) or (nfp and nfp in seen_fingerprints):
                            continue   # כפילות ממקור אחר
                        all_works.append(norm)
                        seen_ids.add(uid)
                        if doi:    seen_dois.add(doi)
                        if nfp: seen_fingerprints.add(nfp)
                        new_count += 1
                        oa_new += 1
                if oa_new:
                    print(f" | +{oa_new} from OpenAlex", end="")
            elif not orcid:
                print(f" ⚠ NOT FOUND in OpenAlex", end="")
        else:
            print(f" [OpenAlex skipped]", end="")

        print(f"\n         ↳ סה\"כ חדשים: {new_count}")
        updated_meta.append(person)

    # ── מיון ושמירה ────────────────────────────────────────────────
    all_works.sort(key=lambda w: (w.get("year") or 0, w.get("date") or ""), reverse=True)

    output = {
        "generated_at": datetime.now().isoformat() + "Z",
        "until_year":   until_year,
        "department":   config["department"],
        "institution":  config["institution"],
        "total_pubs":   len(all_works),
        "faculty_meta": updated_meta,
        "publications": all_works,
    }
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*62}")
    print(f"✅ סיום! סה\"כ פרסומים: {len(all_works)}")
    if until_year:
        print(f"   ⚠ חיתוך עד שנת {until_year} — הרץ שוב ללא --until-year לעדכון מלא")
    print(f"   קובץ: {output_path.resolve()}")
    print(f"{'='*62}\n")

if __name__ == "__main__":
    main()
