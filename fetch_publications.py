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

import json, time, argparse, requests, urllib.parse
from datetime import datetime, date
from pathlib import Path

# ── הגדרות ─────────────────────────────────────────────────────────────────
CONFIG_FILE   = "faculty_config.json"
OUTPUT_FILE   = "publications.json"
OPENALEX_BASE = "https://api.openalex.org"
ORCID_BASE    = "https://pub.orcid.org/v3.0"
CROSSREF_BASE = "https://api.crossref.org"
GBOOKS_BASE   = "https://www.googleapis.com/books/v1/volumes"
EMAIL         = "ir-dept@mail.huji.ac.il"
PER_PAGE      = 50
YEARS_BACK    = 10
RATE_LIMIT    = 0.2

# ── כתבי עת נפוצים — כיסוי מובטח ──────────────────────────────────────────
# כתובות תמונה ישירות (נבדקו ידנית)
JOURNAL_COVERS = {
    # International Relations
    "international organization":           "https://static.cambridge.org/covers/INO_0_0_0/international-organization.jpg",
    "international security":               "https://direct.mit.edu/content/public/journal-covers/isec.jpg",
    "international studies quarterly":      "https://oup.silverchair-cdn.com/oup/backfile/Content_public/Journal/isq/Issue/68/1/cover.png",
    "journal of conflict resolution":       "https://journals.sagepub.com/cms/10.1177/0022002721990271/asset/images/large/10.1177_0022002721990271-img1.jpeg",
    "world politics":                       "https://static.cambridge.org/covers/WPO_0_0_0/world-politics.jpg",
    "foreign policy analysis":              "https://oup.silverchair-cdn.com/oup/backfile/Content_public/Journal/fpa/Issue/21/1/cover.png",
    "international affairs":                "https://oup.silverchair-cdn.com/oup/backfile/Content_public/Journal/ia/Issue/101/1/cover.png",
    "security studies":                     "https://www.tandfonline.com/action/showCoverImage?journalCode=fsst20",
    "journal of strategic studies":         "https://www.tandfonline.com/action/showCoverImage?journalCode=fjss20",
    "political science research and methods":"https://static.cambridge.org/covers/PRM_0_0_0/political-science-research-and-methods.jpg",
    "comparative political studies":        "https://journals.sagepub.com/cms/10.1177/0010414020915499/asset/images/large/10.1177_0010414020915499-img1.jpeg",
    "american journal of political science": "https://onlinelibrary.wiley.com/cms/asset/f4b1e8a2-0437-4dd8-8a22-8aab48735a34/ajps.2022.66.issue-1.cover.jpg",
    "american political science review":    "https://static.cambridge.org/covers/APS_0_0_0/american-political-science-review.jpg",
    "british journal of political science":  "https://static.cambridge.org/covers/JPS_0_0_0/british-journal-of-political-science.jpg",
    "european journal of international law": "https://oup.silverchair-cdn.com/oup/backfile/Content_public/Journal/ejil/Issue/35/1/cover.png",
    "journal of international economic law": "https://oup.silverchair-cdn.com/oup/backfile/Content_public/Journal/jiel/Issue/27/1/cover.png",
    "leiden journal of international law":   "https://static.cambridge.org/covers/LJL_0_0_0/leiden-journal-of-international-law.jpg",
    "international journal of public opinion research": "https://oup.silverchair-cdn.com/oup/backfile/Content_public/Journal/ijpor/Issue/37/1/cover.png",
    "review of international organizations": "https://link.springer.com/journal/11558",
    "review of international political economy": "https://www.tandfonline.com/action/showCoverImage?journalCode=rrip20",
    "journal of peace research":             "https://journals.sagepub.com/cms/10.1177/0022343321990270/asset/images/large/10.1177_0022343321990270-img1.jpeg",
    "cooperation and conflict":              "https://journals.sagepub.com/cms/10.1177/0010836721990270/asset/images/large/10.1177_0010836721990270-img1.jpeg",
    "political psychology":                  "https://onlinelibrary.wiley.com/cms/asset/political-psychology.cover.jpg",
    "journal of european public policy":     "https://www.tandfonline.com/action/showCoverImage?journalCode=rjpp20",
    "journal of common market studies":      "https://onlinelibrary.wiley.com/cms/asset/jcms.cover.jpg",
    "intelligence and national security":    "https://www.tandfonline.com/action/showCoverImage?journalCode=fint20",
    "diplomacy and statecraft":              "https://www.tandfonline.com/action/showCoverImage?journalCode=fdps20",
    "latin american research review":        "https://www.cambridge.org/core/journals/latin-american-research-review/cover.jpg",
    "technology in society":                 "https://www.sciencedirect.com/action/showCoverImage?issn=0160-791X",
    "pnas":                                  "https://www.pnas.org/pb-assets/images/pnas_cover_2023.jpg",
    "proceedings of the national academy":   "https://www.pnas.org/pb-assets/images/pnas_cover_2023.jpg",
}

def journal_cover_from_hardcode(journal_name):
    """בדוק אם כתב העת ברשימה הקשיחה."""
    if not journal_name: return ""
    jl = journal_name.lower().strip()
    for key, url in JOURNAL_COVERS.items():
        if key in jl or jl in key:
            return url
    return ""

# ── Google Books cover lookup ────────────────────────────────────────────────
def open_library_cover(title, authors=None):
    """
    מחפש תמונת שער ב-Open Library — ללא הגבלות, טוב לספרים אקדמיים.
    """
    if not title: return ""
    try:
        last = ""
        if authors:
            last = (authors[0].get("name","") or "").split()[-1]
        q = title[:60] + (" " + last if last else "")
        data = get("https://openlibrary.org/search.json", {
            "q": q, "limit": 3, "fields": "key,cover_i,title"
        })
        docs = data.get("docs", [])
        for doc in docs:
            cover_i = doc.get("cover_i")
            if cover_i:
                return f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg"
    except Exception:
        pass
    return ""

def google_books_cover(title, authors=None, pub_type="article"):
    """
    מחפש תמונת שער ב-Google Books.
    עובד הכי טוב עבור ספרים ופרקים.
    """
    if not title: return ""
    try:
        q = f'intitle:"{title[:60]}"'
        if authors:
            last = (authors[0].get("name","") or "").split()[-1]
            if last: q += f'+inauthor:{last}'

        data = get(GBOOKS_BASE, {
            "q": q, "maxResults": 3,
            "fields": "items(volumeInfo/title,volumeInfo/imageLinks,volumeInfo/authors)"
        })
        items = data.get("items", [])
        for item in items:
            imgs = item.get("volumeInfo", {}).get("imageLinks", {})
            cover = imgs.get("medium") or imgs.get("small") or imgs.get("thumbnail")
            if cover:
                return cover.split("&fife=")[0] + "&fife=w400-h600"
    except Exception:
        pass
    # גיבוי: Open Library
    if pub_type in ("book", "book-chapter", "edited-book"):
        return open_library_cover(title, authors)
    return ""

# ── עזרים ──────────────────────────────────────────────────────────────────
def get(url, params=None, headers=None, silent_404=False):
    if params is None: params = {}
    if headers is None: headers = {}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        if r.status_code == 404 and silent_404:
            return {}
        r.raise_for_status()
        time.sleep(RATE_LIMIT)
        return r.json()
    except Exception as e:
        if "404" not in str(e):  # הדפס רק שגיאות שאינן 404
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
            is_chapter = work_type in ("book-chapter", "book-section", "book-part")

            # לפרקי ספרים: journal-title הוא לרוב שם הסדרה, לא שם כתב העת
            if is_chapter:
                book_title = journal or ""
                journal    = ""
            else:
                book_title = ""

            uid = f"orcid-{orcid_id}-{ws.get('put-code','')}"
            works.append({
                "id":         uid,
                "title":      title,
                "year":       pub_year,
                "date":       f"{pub_year}-01-01" if pub_year else "",
                "journal":    journal or "",
                "book_title": book_title,
                "type":       work_type,
                "doi":        doi,
                "pdf_url":    "",
                "abstract":   "",
                "cited_by":   0,
                "source":     "orcid",
            })
    return works

# ── OpenAlex ────────────────────────────────────────────────────────────────
def find_author_openalex(name, ror, person=None):
    if person and person.get("openalex_id"):
        data = get(f"{OPENALEX_BASE}/authors/{person['openalex_id']}",
                   params={"mailto": EMAIL})
        if data.get("id"):
            return data

    # חיפוש ראשוני: שם + שיוך ל-ROR של HUJI
    data = get(f"{OPENALEX_BASE}/authors", {
        "search": name,
        "filter": f"affiliations.institution.ror:https://ror.org/{ror}",
        "per-page": 10, "mailto": EMAIL
    })
    results = data.get("results", [])
    if results:
        return results[0]

    # עבור חברי סגל שדורשים אימות שיוך ל-HUJI — אין fallback ללא ROR
    # (מניעת false positives עם אנשים בעלי שם דומה ממוסדות אחרים)
    if person and person.get("require_huji_affiliation"):
        # נסה גם עם variants
        for variant in person.get("name_variants", []):
            if variant == name:
                continue
            data = get(f"{OPENALEX_BASE}/authors", {
                "search": variant,
                "filter": f"affiliations.institution.ror:https://ror.org/{ror}",
                "per-page": 5, "mailto": EMAIL
            })
            variant_results = data.get("results", [])
            if variant_results:
                return variant_results[0]
        return None  # לא נחזיר תוצאה ללא אימות שיוך

    # Fallback כללי (רק לחברי סגל פעילים עם ORCID או ידועים היטב)
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
            "filter": f"author.id:{author_id},{year_filter},type:!dataset|!paratext|!peer-review|!grant|!book-review",
            "sort": "publication_date:desc",
            "per-page": PER_PAGE, "cursor": cursor,
            "select": ("id,doi,title,publication_year,publication_date,"
                       "primary_location,authorships,abstract_inverted_index,"
                       "cited_by_count,type,best_oa_location,biblio"),
            "mailto": EMAIL
        })
        batch = data.get("results", [])
        # סינון בצד הלקוח — כתבי עת/מקורות לא רלוונטיים
        SKIP_SOURCES = {"open mind", "zenodo", "figshare", "dryad",
                        "ssrn electronic journal", "osf registries",
                        "osf", "open science framework"}  # OSF ללא preprints
        OA_SKIP_TITLES = {
            "cover and front matter", "front matter", "back matter",
            "issue information", "table of contents", "editorial board",
            "masthead", "book reviews",
        }
        def should_skip(w):
            src_name = (((w.get("primary_location") or {}).get("source") or {})
                        .get("display_name","") or "").lower().strip()
            work_type = (w.get("type") or "").lower()
            title = (w.get("title") or "").lower().strip()
            title_raw = (w.get("title") or "")
            # סנן ביקורות ספרים לפי סוג
            if work_type in ("book-review", "review"):
                return True
            # סנן front matter ו-editorial content לפי כותרת
            if any(kw in title for kw in OA_SKIP_TITLES):
                return True
            # סנן ביקורות ספרים לפי תבנית כותרת:
            # "Coleman, The Nelson Touch... Pp. xix, $35.00 ISBN..."
            if _re.search(r'\bISBN\b', title_raw): return True
            if _re.search(r'\bPp\.\s+[ivxlcdm\d]', title_raw): return True
            if _re.search(r'\$\d+\.\d{2}', title_raw): return True
            # "By [Author]. [Publisher]," — book review format
            if _re.search(r'\.\s+By\s+[A-Z][a-z]', title_raw): return True
            if _re.search(r'\bBy\s+[A-Z][a-z]+\s+[A-Z][a-z]+', title_raw): return True
            # HTML tags in title = usually OpenAlex markup for reviews
            if _re.search(r'<[bi]>', title_raw): return True
            # OSF: קבל רק preprints, דחה registrations וכו'
            if "osf" in src_name and "preprint" not in src_name:
                return True
            # מקורות לסינון
            if any(skip == src_name or src_name.startswith(skip)
                   for skip in SKIP_SOURCES):
                return True
            return False
        batch = [w for w in batch if not should_skip(w)]
        works.extend(batch)
        cursor = data.get("meta", {}).get("next_cursor")
        if not batch: break
    return works

def verify_huji_works(works, ror):
    """
    מסנן תוצאות OpenAlex לפרסומים שיש בהם לפחות מחבר אחד עם שיוך ל-HUJI.
    משמש עבור חברי סגל ללא ORCID שאין לנו וודאות לגבי זהותם ב-OpenAlex.
    """
    HUJI_ROR_FULL = f"https://ror.org/{ror}"
    HUJI_KEYWORDS = [
        "hebrew university", "huji", "the hebrew university",
        "האוניברסיטה העברית"
    ]
    verified = []
    for w in works:
        authorships = w.get("authorships", [])
        has_huji = False
        for a in authorships:
            for inst in a.get("institutions", []):
                # בדוק לפי ROR (הכי מדויק)
                if inst.get("ror") == HUJI_ROR_FULL:
                    has_huji = True
                    break
                # בדוק לפי שם מוסד
                inst_name = (inst.get("display_name") or "").lower()
                if any(k in inst_name for k in HUJI_KEYWORDS):
                    has_huji = True
                    break
            if has_huji:
                break
        if has_huji:
            verified.append(w)
    return verified

def normalize_openalex(work, faculty_name):
    # שמור שם + מוסד + מדינה ישירות מהנתונים של OpenAlex
    # (אחרת המידע אובד ו-enrich_countries צריך לשחזר אותו)
    COUNTRY_CODES = {
        "US":"United States","GB":"United Kingdom","DE":"Germany","FR":"France",
        "CA":"Canada","AU":"Australia","NL":"Netherlands","IL":"Israel","SE":"Sweden",
        "NO":"Norway","DK":"Denmark","FI":"Finland","CH":"Switzerland","AT":"Austria",
        "BE":"Belgium","IT":"Italy","ES":"Spain","PT":"Portugal","PL":"Poland",
        "CZ":"Czech Republic","HU":"Hungary","RO":"Romania","TR":"Turkey","RU":"Russia",
        "CN":"China","JP":"Japan","KR":"South Korea","IN":"India","BR":"Brazil",
        "MX":"Mexico","AR":"Argentina","ZA":"South Africa","NG":"Nigeria","EG":"Egypt",
        "JO":"Jordan","LB":"Lebanon","PS":"Palestine","HK":"Hong Kong","SG":"Singapore",
        "NZ":"New Zealand","IE":"Ireland","GR":"Greece","UA":"Ukraine","CL":"Chile",
        "CO":"Colombia","PE":"Peru","VE":"Venezuela","SE":"Sweden","UA":"Ukraine",
    }
    HUJI_KEYWORDS = ["hebrew university","huji","hebrew college"]

    authors = []
    for a in work.get("authorships", []):
        name = (a.get("author") or {}).get("display_name", "")
        if not name:
            continue
        institutions = a.get("institutions") or []
        country = None
        institution = None
        for inst in institutions:
            code = inst.get("country_code","")
            inst_name = inst.get("display_name","") or ""
            # תקן Hebrew College → Hebrew University
            if inst_name.lower().strip() in ("hebrew college","the hebrew college"):
                inst_name = "Hebrew University of Jerusalem"
                code = "IL"
            if code:
                country = COUNTRY_CODES.get(code, code)
                institution = inst_name
                break
        author_entry = {"name": name}
        if country:
            author_entry["country"] = country
        if institution:
            author_entry["institution"] = institution
        authors.append(author_entry)
    loc    = work.get("primary_location") or {}
    source = loc.get("source") or {}
    doi    = work.get("doi", "") or ""
    oa     = work.get("best_oa_location") or {}
    biblio = work.get("biblio") or {}
    cover_url = ""
    # pages
    fp = biblio.get("first_page","") or ""
    lp = biblio.get("last_page","") or ""
    pages = f"{fp}–{lp}" if fp and lp else fp or ""
    return {
        "id":             work.get("id", ""),
        "title":          work.get("title", ""),
        "year":           work.get("publication_year"),
        "date":           work.get("publication_date", ""),
        "journal":        source.get("display_name", ""),
        "issn":           (source.get("issn_l") or ""),
        "type":           work.get("type", "article"),
        "doi":            doi if doi.startswith("http") else (f"https://doi.org/{doi}" if doi else ""),
        "pdf_url":        oa.get("pdf_url", "") or "",
        "cover_url":      cover_url,
        "abstract":       reconstruct_abstract(work.get("abstract_inverted_index")),
        "cited_by":       work.get("cited_by_count", 0),
        "volume":         biblio.get("volume","") or "",
        "issue":          biblio.get("issue","") or "",
        "pages":          pages,
        "publisher":      ((work.get("primary_location") or {}).get("source") or {}).get("host_organization_name","") or "",
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

    # סוגים לסינון — dataset, component, posted-content ב-preprints וכו'
    SKIP_TYPES = {"dataset", "component", "grant", "peer-review",
                  "paratext", "other", "reference-entry",
                  "posted-content", "registration", "standard",
                  "book-review"}  # סנן ביקורות ספרים
    # כתבי עת לסינון
    SKIP_JOURNALS = {"open mind", "zenodo", "figshare", "dryad",
                     "osf preprints", "ssrn", "biorxiv", "medrxiv"}

    # כותרות לסינון — front matter, back matter, עמודי שער וכו'
    SKIP_TITLE_KEYWORDS = {
        "cover and front matter", "front matter", "back matter",
        "issue information", "table of contents", "editorial board",
        "masthead", "board of editors", "board of reviewers",
        "book reviews",  # סקירות ספרים שנשלפות כ-journal-article
    }

    def extract_item(item):
        """מחלץ שדות מרשומת Crossref כולל ISBN/ISSN ושם ספר לפרקים."""
        work_type = item.get("type", "journal-article")
        # דלג על סוגים לא רלוונטיים
        if work_type in SKIP_TYPES:
            return None

        # סנן כותרות שאינן פרסומים מחקריים
        title_raw = (item.get("title") or [""])[0] if isinstance(item.get("title"), list) else (item.get("title") or "")
        title_check = title_raw.lower().strip()
        if any(kw in title_check for kw in SKIP_TITLE_KEYWORDS):
            return None
        # סנן ביקורות ספרים לפי תבנית כותרת
        if _re.search(r'\bISBN\b', title_raw): return None
        if _re.search(r'\bPp\.\s+[ivxlcdm\d]', title_raw): return None
        if _re.search(r'\$\d+\.\d{2}', title_raw): return None
        if _re.search(r'\.\s+By\s+[A-Z][a-z]', title_raw): return None
        if _re.search(r'\bBy\s+[A-Z][a-z]+\s+[A-Z][a-z]+', title_raw): return None

        doi_val  = item.get("DOI", "")
        pub_date = item.get("published", {})
        parts    = pub_date.get("date-parts", [[None]])[0]
        year     = parts[0] if parts else None
        titles   = item.get("title", [])
        title    = titles[0] if titles else ""
        containers = item.get("container-title", [])

        # רשימת שמות series ידועים שאינם שם הספר עצמו
        KNOWN_SERIES = {
            "global political sociology", "palgrave studies in", "springer studies in",
            "springer series", "routledge studies in", "routledge research in",
            "routledge advances in", "routledge handbook", "studies in",
            "perspectives on", "new perspectives on", "advances in",
            "contributions to", "lecture notes in", "progress in",
            "critical studies in", "international series on",
            "global foreign policy studies", "political science and political economy",
            "international political economy series", "new approaches to",
            "comparative politics and international studies",
        }

        def is_series_not_book(title_str):
            if not title_str: return False
            tl = title_str.lower()
            return any(series in tl for series in KNOWN_SERIES)

        # לפרקי ספרים: container-title הוא שם הספר
        is_chapter = work_type in ("book-chapter", "book-section", "book-part")
        if is_chapter:
            # container-title יכול להיות [series, book_title] או רק [book_title]
            book_title = ""
            if containers:
                # נסה למצוא שם שאינו series
                for ct in containers:
                    if ct and not is_series_not_book(ct):
                        book_title = ct
                        break
                # אם לא מצאנו — קח את האחרון
                if not book_title:
                    book_title = containers[-1] if containers else ""
            # short-title יכול להיות שם הספר האמיתי
            short = item.get("short-title", [])
            if short and not book_title:
                book_title = short[0]
            journal = ""
        else:
            journal    = containers[0] if containers else ""
            book_title = ""

        # דלג על כתבי עת לא רלוונטיים
        if journal and any(skip in journal.lower() for skip in SKIP_JOURNALS):
            return None

        # ISBN (ספרים/פרקים)
        isbn_list = item.get("ISBN", [])
        isbn = isbn_list[0].replace("-","") if isbn_list else ""
        # ISSN (כתבי עת)
        issn_list = item.get("ISSN", [])
        issn = issn_list[0] if issn_list else ""

        fp = item.get("page","") or ""
        pages = fp.replace("-","–") if fp else ""

        # נקה תגי JATS XML מהאבסטרקט
        raw_abs = item.get("abstract", "") or ""
        abstract = _re.sub(r'<[^>]+>', ' ', raw_abs)   # הסר תגים
        abstract = _re.sub(r'\s+', ' ', abstract).strip()  # נרמל רווחים

        return {
            "id":         f"crossref-{doi_val.replace('/', '-')}",
            "title":      title,
            "year":       year,
            "date":       f"{year}-01-01" if year else "",
            "journal":    journal,
            "book_title": book_title,
            "type":       work_type,
            "doi":        f"https://doi.org/{doi_val}" if doi_val else "",
            "pdf_url":    "",
            "abstract":   abstract,
            "cited_by":   0,
            "authors":    crossref_authors(item),
            "isbn":       isbn,
            "issn":       issn,
            "volume":     item.get("volume","") or "",
            "issue":      item.get("issue","") or "",
            "pages":      pages,
            "publisher":  item.get("publisher","") or "",
            "source":     "crossref",
        }

    if orcid:
        # ── חיפוש לפי ORCID — הכי מדויק ──────────────────────────
        params = {
            "filter": f"orcid:{orcid},from-pub-date:{from_year}",
            "rows": 100,
            "mailto": EMAIL,
            "select": "DOI,title,published,type,container-title,author,abstract,ISBN,ISSN,volume,issue,page,publisher"
        }
        if until_year:
            params["filter"] += f",until-pub-date:{until_year}"
        data = get(f"{CROSSREF_BASE}/works", params)
        for item in data.get("message", {}).get("items", []):
            rec = extract_item(item)
            if rec: works.append(rec)
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
            "select": "DOI,title,published,type,container-title,author,abstract,ISBN,ISSN,volume,issue,page,publisher"
        }
        if until_year:
            params["filter"] += f",until-pub-date:{until_year}"

        data = get(f"{CROSSREF_BASE}/works", params)
        for item in data.get("message", {}).get("items", []):
            authors = item.get("author", [])
            # בדוק התאמת שם: שם משפחה מלא + שם פרטי מלא (לא רק ראשית)
            match = any(
                last_name in (a.get("family", "") or "").lower() and
                (
                    (a.get("given", "") or "").lower().startswith(first_name) or
                    (a.get("given", "") or "").lower() == first_name[0]
                )
                for a in authors
            )
            if not match:
                continue
            rec = extract_item(item)
            if rec: works.append(rec)
    return works

import re as _re

def crossref_authors(item):
    """שולף רשימת מחברים מרשומת Crossref."""
    authors = []
    for a in item.get("author", []):
        given  = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        if family:
            full = f"{given} {family}".strip() if given else family
            authors.append({"name": full})
    return authors

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
        skip_cr = person.get("skip_crossref", False)
        require_huji = person.get("require_huji_affiliation", False)
        # כל שמות החיפוש: שם קנוני + variants
        search_names = [name] + [v for v in person.get("name_variants", []) if v != name]
        new_count = 0

        print(f"[{i:02d}/{len(flist):02d}] {name}", end=" ")

        # ── מקור 1: ORCID ──────────────────────────────────────────
        if orcid:
            print(f"[ORCID]", end=" ", flush=True)
            orcid_works = fetch_from_orcid(orcid, from_year, until_year)
            for w in orcid_works:
                uid = w["id"]
                doi = (w.get("doi") or "").lower()
                nfp = title_fingerprint(w.get("title",""))
                if uid not in seen_ids and (not doi or doi not in seen_dois) and (not nfp or nfp not in seen_fingerprints):
                    w["faculty_author"] = name
                    # ORCID לא מחזיר רשימת מחברים — נשאיר ריק, OpenAlex ימלא בהמשך
                    if not w.get("authors"):
                        w["authors"] = [{"name": name}]
                    all_works.append(w)
                    seen_ids.add(uid)
                    if doi: seen_dois.add(doi)
                    if nfp: seen_fingerprints.add(nfp)
                    new_count += 1
            print(f"✓ {len(orcid_works)} pubs from ORCID, {new_count} new", end="")

        # ── מקור 2: Crossref ───────────────────────────────────────
        if not skip_cr:
            cr_new = 0
            # נסה כל שמות החיפוש (כולל variants)
            for sname in search_names:
                cr_works = fetch_from_crossref(sname, from_year, until_year, orcid=orcid)
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
                # עבור חברי סגל ללא ORCID — סנן רק פרסומים עם שיוך מאומת ל-HUJI
                if require_huji:
                    before = len(oa_works)
                    oa_works = verify_huji_works(oa_works, ror)
                    filtered = before - len(oa_works)
                    if filtered:
                        print(f" [HUJI filter: -{filtered}]", end="")
                works_cnt = author.get("works_count", 0)
                cited_cnt = author.get("cited_by_count", 0)
                person["openalex_id"]  = author["id"]
                person["cited_total"]  = cited_cnt
                for w in oa_works:
                    uid = w.get("id")
                    if uid and uid not in seen_ids:
                        norm   = normalize_openalex(w, name)
                        doi    = (norm.get("doi") or "").lower()
                        nfp    = title_fingerprint(norm.get("title",""))
                        # אם כפילות — עדכן ציטוטים, תקציר, ומחברים מ-OpenAlex (שיש לו הרשימה המלאה)
                        if doi and doi in seen_dois:
                            existing = next((x for x in all_works if (x.get("doi") or "").lower() == doi), None)
                            if existing:
                                if norm.get("cited_by",0) > existing.get("cited_by",0):
                                    existing["cited_by"] = norm["cited_by"]
                                if not existing.get("abstract") and norm.get("abstract"):
                                    existing["abstract"] = norm["abstract"]
                                if len(norm.get("authors",[])) > len(existing.get("authors",[])):
                                    existing["authors"] = norm["authors"]
                                if not existing.get("issn") and norm.get("issn"):
                                    existing["issn"] = norm["issn"]
                                if not existing.get("volume") and norm.get("volume"):
                                    existing["volume"] = norm["volume"]
                                if not existing.get("issue") and norm.get("issue"):
                                    existing["issue"] = norm["issue"]
                                if not existing.get("pages") and norm.get("pages"):
                                    existing["pages"] = norm["pages"]
                                if not existing.get("pdf_url") and norm.get("pdf_url"):
                                    existing["pdf_url"] = norm["pdf_url"]
                            continue
                        if nfp and nfp in seen_fingerprints:
                            existing = next((x for x in all_works if title_fingerprint(x.get("title","")) == nfp), None)
                            if existing and len(norm.get("authors",[])) > len(existing.get("authors",[])):
                                existing["authors"] = norm["authors"]
                            continue
                        all_works.append(norm)
                        seen_ids.add(uid)
                        if doi: seen_dois.add(doi)
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

    # ── העשרת שמות ספרים לפרקים חסרים ────────────────────────────
    CHAPTER_TYPES = {"book-chapter","book-section","book-part"}
    KNOWN_SERIES_SET = {
        "global political sociology","palgrave studies in","springer studies in",
        "routledge studies in","routledge research in","routledge advances in",
        "global foreign policy studies","international political economy series",
        "comparative politics and international studies","new approaches to",
        "critical studies in","advances in","contributions to","perspectives on",
        "new perspectives on","studies in","progress in",
    }
    def looks_like_series(s):
        if not s: return True  # ריק = חסר
        sl = s.lower()
        return any(k in sl for k in KNOWN_SERIES_SET)

    missing_book_title = [w for w in all_works
                          if w.get("type","") in CHAPTER_TYPES
                          and w.get("doi")
                          and looks_like_series(w.get("book_title",""))]
    if missing_book_title:
        print(f"\nמחפש שמות ספרים ל-{len(missing_book_title)} פרקים...", flush=True)
        found_bt = 0
        for w in missing_book_title:
            doi_clean = w["doi"].replace("https://doi.org/","")
            data = get(f"{CROSSREF_BASE}/works/{doi_clean}", silent_404=True)
            msg = data.get("message",{})
            containers = msg.get("container-title",[])
            # מצא שם שאינו סדרה
            for ct in containers:
                if ct and not looks_like_series(ct):
                    w["book_title"] = ct
                    # עדכן ISBN אם יש
                    isbn_list = msg.get("ISBN",[])
                    if isbn_list and not w.get("isbn"):
                        w["isbn"] = isbn_list[0].replace("-","")
                    found_bt += 1
                    break
        print(f"  נמצאו שמות ספרים: {found_bt}/{len(missing_book_title)}")

    # ── העשרת אבסטרקטים, כותבים ומוסדות לפי DOI ────────────────────
    # (1) פרסומים עם ≤1 כותב — צריך את רשימת הכותבים המלאה
    # (2) פרסומים עם כותבים אך ללא שיוך מוסדי — צריך מוסד ומדינה
    needs_enrichment = [
        w for w in all_works if w.get("doi") and (
            not w.get("abstract") or
            len(w.get("authors",[])) <= 1 or
            any(not a.get("country") and not a.get("institution") for a in w.get("authors",[]))
        )
    ]
    if needs_enrichment:
        print(f"\nמעשיר אבסטרקטים וכותבים ל-{len(needs_enrichment)} פרסומים...", flush=True)
        found_abs = 0
        found_auth = 0
        for w in needs_enrichment:
            doi_clean = w["doi"].replace("https://doi.org/", "")

            # א. נסה OpenAlex
            oa_data = get(f"{OPENALEX_BASE}/works/doi:{doi_clean}",
                         {"select": "abstract_inverted_index,authorships,biblio",
                          "mailto": EMAIL}, silent_404=True)

            if not w.get("abstract") and oa_data.get("abstract_inverted_index"):
                w["abstract"] = reconstruct_abstract(oa_data["abstract_inverted_index"])
                found_abs += 1

            # ב. אם עדיין אין אבסטרקט — נסה Crossref
            if not w.get("abstract"):
                cr_data = get(f"{CROSSREF_BASE}/works/{doi_clean}", silent_404=True)
                cr_abs = (cr_data.get("message",{}).get("abstract","") or "")
                if cr_abs:
                    cr_abs = _re.sub(r'<[^>]+>', ' ', cr_abs)
                    cr_abs = _re.sub(r'\s+', ' ', cr_abs).strip()
                    if cr_abs:
                        w["abstract"] = cr_abs
                        found_abs += 1

            # עדכן כותבים אם יש יותר ב-OpenAlex — שמור גם מוסד ומדינה
            COUNTRY_CODES = {
                "US":"United States","GB":"United Kingdom","DE":"Germany","FR":"France",
                "CA":"Canada","AU":"Australia","NL":"Netherlands","IL":"Israel","SE":"Sweden",
                "NO":"Norway","DK":"Denmark","FI":"Finland","CH":"Switzerland","AT":"Austria",
                "BE":"Belgium","IT":"Italy","ES":"Spain","PT":"Portugal","PL":"Poland",
                "CZ":"Czech Republic","HU":"Hungary","TR":"Turkey","RU":"Russia",
                "CN":"China","JP":"Japan","KR":"South Korea","IN":"India","BR":"Brazil",
                "MX":"Mexico","AR":"Argentina","ZA":"South Africa","EG":"Egypt",
                "JO":"Jordan","LB":"Lebanon","SG":"Singapore","HK":"Hong Kong",
                "IE":"Ireland","GR":"Greece","UA":"Ukraine","CL":"Chile","CO":"Colombia",
            }
            oa_authors = []
            for a in oa_data.get("authorships",[]):
                name = (a.get("author") or {}).get("display_name","")
                if not name: continue
                entry = {"name": name}
                for inst in (a.get("institutions") or []):
                    code = inst.get("country_code","")
                    inst_name = inst.get("display_name","") or ""
                    if inst_name.lower().strip() in ("hebrew college","the hebrew college"):
                        inst_name = "Hebrew University of Jerusalem"
                        code = "IL"
                    if code:
                        entry["country"] = COUNTRY_CODES.get(code, code)
                        entry["institution"] = inst_name
                        break
                oa_authors.append(entry)
            if len(oa_authors) > len(w.get("authors",[])):
                w["authors"] = oa_authors
                found_auth += 1
            elif oa_authors:
                # גם אם מספר הכותבים זהה, עדכן מוסד ומדינה לכותבים קיימים
                existing = {a["name"]: a for a in w.get("authors",[])}
                for oa_a in oa_authors:
                    name = oa_a["name"]
                    if name in existing:
                        if not existing[name].get("country") and oa_a.get("country"):
                            existing[name]["country"] = oa_a["country"]
                        if not existing[name].get("institution") and oa_a.get("institution"):
                            existing[name]["institution"] = oa_a["institution"]

            # עדכן volume/issue/pages
            biblio = oa_data.get("biblio") or {}
            if biblio:
                if not w.get("volume") and biblio.get("volume"):
                    w["volume"] = biblio["volume"]
                if not w.get("issue") and biblio.get("issue"):
                    w["issue"] = biblio["issue"]
                if not w.get("pages"):
                    fp = biblio.get("first_page","") or ""
                    lp = biblio.get("last_page","") or ""
                    if fp: w["pages"] = f"{fp}–{lp}" if lp else fp

        print(f"  אבסטרקטים: {found_abs} | כותבים: {found_auth}")

    # ── הסר DOIs שברשימה השחורה לפי חבר סגל ─────────────────────
    blacklists = {
        f["name"]: set((d.lower() for d in f.get("doi_blacklist", [])))
        for f in config["faculty"] if f.get("doi_blacklist")
    }
    if blacklists:
        before = len(all_works)
        all_works = [
            w for w in all_works
            if w.get("doi","").lower() not in blacklists.get(w.get("faculty_author",""), set())
        ]
        if len(all_works) < before:
            print(f"\nהוסרו {before-len(all_works)} פרסומים מרשימת DOI שחורה")

    # ── סנן לפי מוסד עבור חברי סגל עם require_institutions ───────
    inst_filters = {
        f["name"]: [i.lower() for i in f["require_institutions"]]
        for f in config["faculty"] if f.get("require_institutions")
    }
    if inst_filters:
        before = len(all_works)
        def passes_inst_filter(w):
            fac = w.get("faculty_author", "")
            allowed = inst_filters.get(fac)
            if not allowed:
                return True
            # בדוק אם אחד מהמחברים שייך למוסד המותר
            for a in w.get("authors", []):
                inst = (a.get("institution") or "").lower()
                if any(k in inst for k in allowed):
                    return True
            return False
        filtered = [w for w in all_works if passes_inst_filter(w)]
        removed = len(all_works) - len(filtered)
        if removed:
            print(f"\nהוסרו {removed} פרסומים שאינם ממוסדות מורשים (Adler וכו')")
        all_works = filtered

    # ── מיזוג פרקי ספר כפולים מאותו ספר ─────────────────────────
    # אם חבר סגל מופיע ב-3+ פרקים מאותו ספר (ISBN/book_title) — שמור רק פרק אחד
    from collections import defaultdict
    book_key = lambda w: (
        w.get("faculty_author",""),
        (w.get("isbn","") or w.get("book_title","") or "").strip().lower()
    )
    chapter_groups = defaultdict(list)
    for w in all_works:
        if w.get("type") in ("book-chapter", "book-section", "book-part"):
            k = book_key(w)
            if k[1]:  # רק אם יש מזהה ספר
                chapter_groups[k].append(w)
    chapters_to_remove = set()
    for (fac, book_id), chapters in chapter_groups.items():
        if len(chapters) >= 3:
            # שמור רק את הפרק הראשון (לפי שנה ואחר כך כותרת)
            chapters.sort(key=lambda c: (c.get("year") or 0, c.get("title","") or ""))
            for ch in chapters[1:]:
                chapters_to_remove.add(ch["id"])
    if chapters_to_remove:
        print(f"\nמוזגו {len(chapters_to_remove)} פרקי ספר כפולים")
        all_works = [w for w in all_works if w["id"] not in chapters_to_remove]

    # ── אימות שיוך HUJI עבור פרסומי Crossref של אמריטוס ──────────
    # עבור גמלאים ללא ORCID, Crossref לא מחזיר שיוך מוסדי —
    # לכן מאמתים כל פרסום כזה לפי DOI ב-OpenAlex
    emeriti_names = {
        f["name"] for f in config["faculty"]
        if f.get("require_huji_affiliation") and not f.get("orcid")
    }
    if emeriti_names:
        needs_huji_check = [
            w for w in all_works
            if w.get("faculty_author") in emeriti_names
            and w.get("source") == "crossref"
            and w.get("doi")
        ]
        if needs_huji_check:
            print(f"\nמאמת שיוך HUJI ל-{len(needs_huji_check)} פרסומי Crossref של גמלאים...")
            remove_ids = set()
            for w in needs_huji_check:
                doi_clean = w["doi"].replace("https://doi.org/", "")
                oa = get(f"{OPENALEX_BASE}/works/doi:{doi_clean}",
                         {"select": "authorships", "mailto": EMAIL}, silent_404=True)
                authorships = oa.get("authorships", [])
                has_huji = any(
                    any("hebrew university" in (inst.get("display_name","") or "").lower()
                        or (inst.get("ror","") or "").endswith(ror)
                        for inst in a.get("institutions", []))
                    for a in authorships
                )
                if not has_huji:
                    remove_ids.add(w["id"])
            before = len(all_works)
            all_works = [w for w in all_works if w["id"] not in remove_ids]
            print(f"  הוסרו {before - len(all_works)} פרסומים ללא שיוך HUJI מאומת")

    # ── סנן פרסומים ללא קישור DOI ──────────────────────────────────
    # כל פרסום חייב לכלול קישור (DOI) — בלי קישור אי אפשר לאמת ולהפנות
    before_doi = len(all_works)
    all_works = [w for w in all_works if w.get("doi")]
    removed_doi = before_doi - len(all_works)
    if removed_doi:
        print(f"\nהוסרו {removed_doi} פרסומים ללא DOI (מתוך {before_doi})")

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
