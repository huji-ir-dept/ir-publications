#!/usr/bin/env python3
"""
enrich_covers.py
================
מחפש תמונות שער לפרסומים ב-publications.json.

שכבות לפי סדר עדיפות:
  1. ISSN → רשימת homepages ידועים + OpenAlex sources API → publisher URL pattern
  2. ISSN → Open Library ישיר
  3. ISBN → Open Library ישיר (ספרים)
  4. כותרת → Google Books (ספרים, גיבוי)

שימוש:
    python3 enrich_covers.py              ← רק חסרים
    python3 enrich_covers.py --force      ← הכל מחדש
    python3 enrich_covers.py --report     ← דוח בלבד
"""

import json, time, re, argparse, requests, sys
from pathlib import Path

OUTPUT_FILE = "publications.json"
RATE        = 0.15
BOOK_TYPES  = {"book", "book-chapter", "edited-book", "monograph", "reference-book"}

_issn_cache = {}   # ISSN → homepage URL (נבנה בזמן ריצה)

# ── ISSNs עם homepage ידוע — מונע קריאות מיותרות ל-OpenAlex ─────────────────
KNOWN_ISSNS = {
    "0020-8183": "https://www.cambridge.org/core/journals/international-organization",
    "1531-5088": "https://www.cambridge.org/core/journals/international-organization",
    "0162-2889": "https://direct.mit.edu/isec",
    "1531-5010": "https://direct.mit.edu/isec",
    "0020-8833": "https://academic.oup.com/isq",
    "1468-2478": "https://academic.oup.com/isq",
    "0022-0027": "https://journals.sagepub.com/home/jcr",
    "1552-8766": "https://journals.sagepub.com/home/jcr",
    "0043-8871": "https://www.cambridge.org/core/journals/world-politics",
    "1086-3338": "https://www.cambridge.org/core/journals/world-politics",
    "1743-8586": "https://academic.oup.com/fpa",
    "1743-8594": "https://academic.oup.com/fpa",
    "0020-5850": "https://academic.oup.com/ia",
    "1468-2346": "https://academic.oup.com/ia",
    "0966-2839": "https://www.tandfonline.com/journals/fsst/current-issue",
    "1556-1852": "https://www.tandfonline.com/journals/fsst/current-issue",
    "0022-3433": "https://journals.sagepub.com/home/jpr",
    "1460-3578": "https://journals.sagepub.com/home/jpr",
    "0010-8367": "https://journals.sagepub.com/home/cps",
    "1552-3829": "https://journals.sagepub.com/home/cps",
    "0092-5853": "https://onlinelibrary.wiley.com/journal/15405907",
    "1540-5907": "https://onlinelibrary.wiley.com/journal/15405907",
    "0003-0554": "https://www.cambridge.org/core/journals/american-political-science-review",
    "1537-5943": "https://www.cambridge.org/core/journals/american-political-science-review",
    "0007-1234": "https://www.cambridge.org/core/journals/british-journal-of-political-science",
    "1469-2112": "https://www.cambridge.org/core/journals/british-journal-of-political-science",
    "0938-2529": "https://academic.oup.com/ejil",
    "1464-3596": "https://academic.oup.com/ejil",
    "1369-3034": "https://academic.oup.com/jiel",
    "1464-3634": "https://academic.oup.com/jiel",
    "0922-1565": "https://www.cambridge.org/core/journals/leiden-journal-of-international-law",
    "1478-9698": "https://www.cambridge.org/core/journals/leiden-journal-of-international-law",
    "1559-7431": "https://link.springer.com/journal/11558",
    "1559-744X": "https://link.springer.com/journal/11558",
    "0960-3107": "https://www.tandfonline.com/journals/rrip/current-issue",
    "1466-4526": "https://www.tandfonline.com/journals/rrip/current-issue",
    "0010-3640": "https://journals.sagepub.com/home/cac",
    "1460-3691": "https://journals.sagepub.com/home/cac",
    "0162-895X": "https://onlinelibrary.wiley.com/journal/14679221",
    "1467-9221": "https://onlinelibrary.wiley.com/journal/14679221",
    "1350-1763": "https://www.tandfonline.com/journals/rjpp/current-issue",
    "1466-4429": "https://www.tandfonline.com/journals/rjpp/current-issue",
    "0021-9886": "https://onlinelibrary.wiley.com/journal/14685965",
    "1468-5965": "https://onlinelibrary.wiley.com/journal/14685965",
    "0268-4527": "https://www.tandfonline.com/journals/fint/current-issue",
    "1743-9019": "https://www.tandfonline.com/journals/fint/current-issue",
    "0959-2296": "https://www.tandfonline.com/journals/fdps/current-issue",
    "1557-301X": "https://www.tandfonline.com/journals/fdps/current-issue",
    "0023-8791": "https://www.cambridge.org/core/journals/latin-american-research-review",
    "1542-4278": "https://www.cambridge.org/core/journals/latin-american-research-review",
    "0160-791X": "https://www.sciencedirect.com/journal/technology-in-society",
    "0027-8424": "https://www.pnas.org",
    "1091-6490": "https://www.pnas.org",
    "0955-2359": "https://academic.oup.com/isr",
    "1468-2486": "https://academic.oup.com/isr",
    "0140-2382": "https://www.tandfonline.com/journals/geui/current-issue",
    "1364-9574": "https://www.tandfonline.com/journals/rpcb/current-issue",
    "1469-3062": "https://www.tandfonline.com/journals/rpcb/current-issue",
    "0143-6597": "https://www.tandfonline.com/journals/ctwq/current-issue",
    "1360-2241": "https://www.tandfonline.com/journals/ctwq/current-issue",
    "0956-7976": "https://journals.sagepub.com/home/pss",
    "1467-9280": "https://journals.sagepub.com/home/pss",
    "2058-0020": "https://academic.oup.com/jogss",
    "2058-0039": "https://academic.oup.com/jogss",
    "2169-0375": "https://www.tandfonline.com/journals/rglo/current-issue",
    "2169-0383": "https://www.tandfonline.com/journals/rglo/current-issue",
    "0738-6729": "https://www.tandfonline.com/journals/ufpa/current-issue",
    "1743-7962": "https://www.tandfonline.com/journals/ufpa/current-issue",
    "0022-1953": "https://www.cambridge.org/core/journals/journal-of-modern-history",
    "1537-5390": "https://www.cambridge.org/core/journals/journal-of-modern-history",
    "0190-9320": "https://link.springer.com/journal/11558",

    # ── Wiley (expanded) ──
    "0967-0106": "https://onlinelibrary.wiley.com/journal/14745836",
    "1468-5965": "https://onlinelibrary.wiley.com/journal/14685965",
    "1758-5880": "https://onlinelibrary.wiley.com/journal/17585899",
    "1758-5899": "https://onlinelibrary.wiley.com/journal/17585899",
    "1748-5983": "https://onlinelibrary.wiley.com/journal/17485991",
    "1748-5991": "https://onlinelibrary.wiley.com/journal/17485991",
    "1354-5078": "https://onlinelibrary.wiley.com/journal/14698129",
    "1469-8129": "https://onlinelibrary.wiley.com/journal/14698129",
    "1475-6765": "https://onlinelibrary.wiley.com/journal/14756765",
    "1540-5907": "https://onlinelibrary.wiley.com/journal/15405907",
    "0176-5310": "https://onlinelibrary.wiley.com/journal/14680491",
    "1468-0491": "https://onlinelibrary.wiley.com/journal/14680491",
    "1468-2486": "https://onlinelibrary.wiley.com/journal/14682486",
    "1521-0758": "https://onlinelibrary.wiley.com/journal/15210758",
    "0951-2441": "https://onlinelibrary.wiley.com/journal/14679507",
    "1467-9507": "https://onlinelibrary.wiley.com/journal/14679507",

    # ── Sage (expanded) ──
    "1741-2757": "https://journals.sagepub.com/home/eup",
    "1460-3705": "https://journals.sagepub.com/home/eup",
    "1354-0661": "https://journals.sagepub.com/home/ppq",
    "1460-3683": "https://journals.sagepub.com/home/ppq",
    "0951-6298": "https://journals.sagepub.com/home/ips",
    "1460-373X": "https://journals.sagepub.com/home/ips",
    "1369-1481": "https://journals.sagepub.com/home/ejt",
    "1460-3713": "https://journals.sagepub.com/home/ejt",
    "0263-3957": "https://journals.sagepub.com/home/mss",
    "1477-2728": "https://journals.sagepub.com/home/mss",
    "0010-4140": "https://journals.sagepub.com/home/cpx",
    "1552-3829": "https://journals.sagepub.com/home/cpx",
    "0738-9299": "https://journals.sagepub.com/home/pan",
    "1476-4989": "https://journals.sagepub.com/home/pan",
    "0163-6545": "https://journals.sagepub.com/home/psx",
    "1467-9248": "https://journals.sagepub.com/home/psx",
    "0090-5917": "https://journals.sagepub.com/home/jpr",
    "1177-1119": "https://journals.sagepub.com/home/cdi",
    "1749-9623": "https://journals.sagepub.com/home/cdi",

    # ── Cambridge (expanded) ──
    "0260-2105": "https://www.cambridge.org/core/journals/review-of-international-studies",
    "1469-9044": "https://www.cambridge.org/core/journals/review-of-international-studies",
    "1474-7480": "https://www.cambridge.org/core/journals/perspectives-on-politics",
    "1537-5927": "https://www.cambridge.org/core/journals/perspectives-on-politics",
    "1049-0965": "https://www.cambridge.org/core/journals/latin-american-politics-and-society",
    "1548-2456": "https://www.cambridge.org/core/journals/latin-american-politics-and-society",
    "1558-5069": "https://www.cambridge.org/core/journals/annual-review-of-political-science",
    "1094-2939": "https://www.cambridge.org/core/journals/annual-review-of-political-science",
    "0022-0507": "https://www.cambridge.org/core/journals/journal-of-cold-war-studies",
    "1531-3298": "https://www.cambridge.org/core/journals/journal-of-cold-war-studies",
    "0022-0779": "https://www.cambridge.org/core/journals/journal-of-modern-history",
    "1537-5374": "https://www.cambridge.org/core/journals/international-studies-quarterly",

    # ── Springer (expanded) ──
    "0925-853X": "https://link.springer.com/journal/11127",
    "1573-7101": "https://link.springer.com/journal/11127",
    "0039-3606": "https://link.springer.com/journal/12116",
    "1387-6996": "https://link.springer.com/journal/12116",
    "0165-0009": "https://link.springer.com/journal/10584",
    "1573-1480": "https://link.springer.com/journal/10584",
    "0925-9856": "https://link.springer.com/journal/11558",
    "0047-2352": "https://link.springer.com/journal/12117",
    "1573-7608": "https://link.springer.com/journal/12117",
    "1572-5545": "https://link.springer.com/journal/11366",
    "0924-6460": "https://link.springer.com/journal/11077",

    # ── Taylor & Francis (expanded) ──
    "1474-2829": "https://www.tandfonline.com/journals/urst/current-issue",
    "1521-0731": "https://www.tandfonline.com/journals/urst/current-issue",
    "0967-0688": "https://www.tandfonline.com/journals/fcsp/current-issue",
    "1743-8292": "https://www.tandfonline.com/journals/fcsp/current-issue",
    "1357-1516": "https://www.tandfonline.com/journals/ftpv/current-issue",
    "1556-1836": "https://www.tandfonline.com/journals/ftpv/current-issue",
    "0090-5992": "https://www.tandfonline.com/journals/cnms/current-issue",
    "1465-3923": "https://www.tandfonline.com/journals/cnms/current-issue",
    "1478-2804": "https://www.tandfonline.com/journals/cjea/current-issue",
    "1478-2796": "https://www.tandfonline.com/journals/cjea/current-issue",
    "0305-0629": "https://www.tandfonline.com/journals/cjpi/current-issue",
    "1469-9613": "https://www.tandfonline.com/journals/cjpi/current-issue",
    "1362-9395": "https://www.tandfonline.com/journals/rmed/current-issue",
    "1743-9418": "https://www.tandfonline.com/journals/rmed/current-issue",
    "1060-586X": "https://www.tandfonline.com/journals/cpos/current-issue",
    "1557-301X": "https://www.tandfonline.com/journals/fdps/current-issue",

    # ── Oxford (expanded) ──
    "1477-7053": "https://academic.oup.com/irap",
    "1470-482X": "https://academic.oup.com/irap",
    "1464-3529": "https://academic.oup.com/jrs",
    "1471-6925": "https://academic.oup.com/jrs",
    "1752-1734": "https://academic.oup.com/migration",
    "2049-5846": "https://academic.oup.com/migration",
    "1465-7341": "https://academic.oup.com/publius",
    "1747-7107": "https://academic.oup.com/publius",

    # ── MIT Press ──
    "1536-0075": "https://direct.mit.edu/glep",
    "1526-3800": "https://direct.mit.edu/glep",
    "1530-9150": "https://direct.mit.edu/daed",
    "0011-5266": "https://direct.mit.edu/daed",
}


def cover_from_homepage(homepage_url, issn=""):
    """בונה cover URL מה-homepage של כתב העת לפי pattern של ההוצאה."""
    if not homepage_url:
        return ""
    url = homepage_url.rstrip("/")

    # Edward Elgar
    if "elgaronline.com" in url or "e-elgar.com" in url or "elgar.com" in url:
        # Elgar journals: try ISBN/ISSN based lookup via Open Library
        return ""  # handled separately via isbn lookup

    # Taylor & Francis (alternate domain)
    m = re.search(r'tandfonline\.com/journals/([a-z]{3,6})', url, re.I)
    if m:
        code = m.group(1).lower()
        return f"https://www.tandfonline.com/action/showCoverImage?journalCode={code}"

    # Sage
    m = re.search(r'sagepub\.com/(?:home|journal)/([a-z]{2,8})', url, re.I)
    if m:
        code = m.group(1).upper()
        return f"https://journals.sagepub.com/pb-assets/Covers/{code}-cover-2400.jpg"

    # Oxford OUP
    m = re.search(r'academic\.oup\.com/([a-z]{2,12})(?:/|$)', url, re.I)
    if m:
        abbr = m.group(1).lower()
        return f"https://academic.oup.com/{abbr}/images/{abbr}_logo_240.png"

    # Cambridge
    m = re.search(r'cambridge\.org/core/journals/([a-z0-9-]+)', url, re.I)
    if m:
        slug = m.group(1)
        abbr = "".join(w[0].upper() for w in slug.replace("-", " ").split())
        return f"https://static.cambridge.org/covers/{abbr}_0_0_0/{slug}.jpg"

    # MIT Press
    m = re.search(r'direct\.mit\.edu/([a-z]+)(?:/|$)', url, re.I)
    if m:
        abbr = m.group(1).lower()
        return f"https://direct.mit.edu/content/public/journal-covers/{abbr}.jpg"

    # Springer
    m = re.search(r'link\.springer\.com/journal/(\d+)', url, re.I)
    if m:
        jid = m.group(1)
        return f"https://media.springernature.com/full/springer-static/cover-hires/journal/{jid}"

    # Wiley
    if "onlinelibrary.wiley.com" in url and issn:
        issn_clean = issn.replace("-", "")
        return f"https://onlinelibrary.wiley.com/cms/asset/{issn_clean}/cover.jpg"

    # Brill
    m = re.search(r'brill\.com/view/journals/([a-z]+)', url, re.I)
    if m:
        code = m.group(1)
        return f"https://brill.com/cover/journals/{code}/{code}_overview.jpg"

    # PNAS
    if "pnas.org" in url:
        return "https://www.pnas.org/pb-assets/images/pnas_cover_2023.jpg"

    # Elsevier / ScienceDirect
    if "sciencedirect.com" in url and issn:
        return f"https://www.sciencedirect.com/action/showCoverImage?issn={issn}"

    return ""


def get_json(url, params=None):
    try:
        r = requests.get(url, params=params or {}, timeout=12,
                         headers={"User-Agent": "HUJI-IR-Publications/1.0"})
        r.raise_for_status()
        time.sleep(RATE)
        return r.json()
    except Exception:
        return {}


def image_exists(url):
    try:
        r = requests.head(url, timeout=8, allow_redirects=True)
        ct = r.headers.get("content-type", "")
        return r.status_code == 200 and "image" in ct
    except Exception:
        return False


_journal_name_cache = {}  # journal_name → homepage

def journal_name_to_cover(journal_name):
    """
    מחפש תמונת שער לפי שם כתב העת:
    1. OpenAlex sources search → homepage → publisher pattern
    2. Wikipedia API → תמונת שער מדף כתב העת
    """
    if not journal_name: return "", ""
    jl = journal_name.strip()
    if jl in _journal_name_cache:
        return _journal_name_cache[jl]

    # ── 1. OpenAlex sources ───────────────────────────────────────
    data = get_json("https://api.openalex.org/sources", {
        "search": jl, "per-page": 3,
        "select": "homepage_url,issn_l,display_name"
    })
    for src in data.get("results", []):
        name_match = src.get("display_name","").lower()
        # ודא שמדובר באותו כתב עת (לפחות 80% מהמילים תואמות)
        jl_words = set(jl.lower().split())
        nm_words = set(name_match.split())
        if len(jl_words & nm_words) / max(len(jl_words), 1) >= 0.6:
            homepage = src.get("homepage_url","")
            issn     = src.get("issn_l","")
            if homepage:
                cover = cover_from_homepage(homepage, issn)
                if cover:
                    _journal_name_cache[jl] = (cover, "openalex-name")
                    return cover, "openalex-name"
            if issn:
                url, src_name = cover_by_issn(issn)
                if url:
                    _journal_name_cache[jl] = (url, src_name)
                    return url, src_name

    # ── 2. Wikipedia API ──────────────────────────────────────────
    try:
        # חפש דף בוויקיפדיה
        search_data = get_json("https://en.wikipedia.org/w/api.php", {
            "action": "query", "list": "search",
            "srsearch": jl, "srlimit": 3, "format": "json",
            "srnamespace": 0
        })
        for result in search_data.get("query",{}).get("search",[]):
            title = result.get("title","")
            # וודא שמדובר בכתב עת ולא במאמר אחר
            title_lower = title.lower()
            if not any(w in title_lower for w in ["journal","review","studies",
                        "quarterly","annual","policy","politics","relations",
                        "security","law","science","affairs","research"]):
                continue
            # קבל תמונה מהדף
            img_data = get_json("https://en.wikipedia.org/w/api.php", {
                "action": "query", "titles": title,
                "prop": "pageimages", "pithumbsize": 300,
                "format": "json", "piprop": "thumbnail"
            })
            pages = img_data.get("query",{}).get("pages",{})
            for page in pages.values():
                thumb = page.get("thumbnail",{}).get("source","")
                if thumb and "logo" not in thumb.lower() and "icon" not in thumb.lower():
                    _journal_name_cache[jl] = (thumb, "wikipedia")
                    return thumb, "wikipedia"
    except Exception:
        pass

    _journal_name_cache[jl] = ("", "")
    return "", ""
    if not issn:
        return "", ""
    issn = issn.strip()
    if issn in _issn_cache:
        cached = _issn_cache[issn]
    else:
        # רשימה ידועה קודם
        homepage = KNOWN_ISSNS.get(issn, "")
        # אחרת — OpenAlex
        if not homepage:
            data = get_json("https://api.openalex.org/sources",
                            {"filter": f"issn:{issn}", "select": "homepage_url", "per-page": 1})
            results = data.get("results", [])
            homepage = results[0].get("homepage_url", "") if results else ""
        _issn_cache[issn] = homepage
        cached = homepage

    if cached:
        cover = cover_from_homepage(cached, issn)
        if cover:
            return cover, "publisher-pattern"

    # גיבוי: Open Library ישיר
    ol_url = f"https://covers.openlibrary.org/b/issn/{issn}-M.jpg"
    if image_exists(ol_url):
        return ol_url, "openlibrary-issn"

    return "", ""


def cover_by_issn(issn):
    if not issn:
        return "", ""
    issn = issn.strip()
    if issn in _issn_cache:
        cached = _issn_cache[issn]
    else:
        homepage = KNOWN_ISSNS.get(issn, "")
        if not homepage:
            data = get_json("https://api.openalex.org/sources",
                            {"filter": f"issn:{issn}", "select": "homepage_url", "per-page": 1})
            results = data.get("results", [])
            homepage = results[0].get("homepage_url", "") if results else ""
        _issn_cache[issn] = homepage
        cached = homepage

    if cached:
        cover = cover_from_homepage(cached, issn)
        if cover:
            return cover, "publisher-pattern"

    ol_url = f"https://covers.openlibrary.org/b/issn/{issn}-M.jpg"
    if image_exists(ol_url):
        return ol_url, "openlibrary-issn"

    return "", ""


def cover_by_isbn(isbn):
    if not isbn:
        return "", ""
    isbn = isbn.replace("-", "").strip()
    url  = f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"
    if image_exists(url):
        return url, "openlibrary-isbn"
    return "", ""


def cover_by_google(title, authors=None):
    if not title:
        return "", ""
    last = ""
    if authors:
        last = (authors[0].get("name", "") or "").split()[-1]
    q = f'intitle:"{title[:55]}"'
    if last:
        q += f"+inauthor:{last}"
    data = get_json("https://www.googleapis.com/books/v1/volumes",
                    {"q": q, "maxResults": 3,
                     "fields": "items(volumeInfo/imageLinks,volumeInfo/industryIdentifiers)"})
    for item in data.get("items", []):
        vi   = item.get("volumeInfo", {})
        imgs = vi.get("imageLinks", {})
        cover = imgs.get("medium") or imgs.get("small") or imgs.get("thumbnail")
        if cover:
            return cover.split("&fife=")[0] + "&fife=w400-h600", "google_books"
        for ii in vi.get("industryIdentifiers", []):
            if ii.get("type", "") in ("ISBN_13", "ISBN_10"):
                ol_url = f"https://covers.openlibrary.org/b/isbn/{ii['identifier']}-M.jpg"
                if image_exists(ol_url):
                    return ol_url, "openlibrary-isbn-via-google"
    return "", ""


def find_cover(pub):
    is_book = pub.get("type", "") in BOOK_TYPES

    if not is_book:
        # א. ISSN ישיר
        issn = pub.get("issn","")
        if issn:
            url, src = cover_by_issn(issn)
            if url: return url, src
        # ב. חיפוש לפי שם כתב העת (כשאין ISSN)
        journal = pub.get("journal","")
        if journal:
            url, src = journal_name_to_cover(journal)
            if url: return url, src

    # ספרים — ISBN
    url, src = cover_by_isbn(pub.get("isbn",""))
    if url: return url, src

    # Google Books לספרים
    if is_book:
        url, src = cover_by_google(pub.get("title",""), pub.get("authors",[]))
        if url: return url, src

    return "", ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force",  action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    path = Path(OUTPUT_FILE)
    if not path.exists():
        print(f"⚠ {OUTPUT_FILE} לא נמצא")
        sys.exit(1)

    data = json.loads(path.read_text(encoding="utf-8"))
    pubs = data.get("publications", [])

    if args.report:
        has   = sum(1 for p in pubs if p.get("cover_url"))
        types = {}
        for p in pubs:
            if not p.get("cover_url"):
                t = p.get("type", "?")
                types[t] = types.get(t, 0) + 1
        no_issn = sum(1 for p in pubs if not p.get("cover_url") and not p.get("issn"))
        no_isbn = sum(1 for p in pubs
                      if p.get("type","") in BOOK_TYPES and not p.get("isbn"))
        print(f"\n  יש שער: {has}/{len(pubs)}")
        print(f"  חסרים ללא ISSN: {no_issn}")
        print(f"  ספרים ללא ISBN: {no_isbn}")
        for t, n in sorted(types.items(), key=lambda x: -x[1]):
            print(f"    {t}: {n}")
        return

    targets = [p for p in pubs if args.force or not p.get("cover_url")]

    print(f"\n{'='*60}")
    print(f"Cover Enrichment — {len(targets)} פרסומים")
    print(f"{'='*60}\n")

    found  = 0
    by_src = {}

    for i, pub in enumerate(targets, 1):
        url, src = find_cover(pub)
        if url:
            pub["cover_url"] = url
            found += 1
            by_src[src] = by_src.get(src, 0) + 1
        if i % 15 == 0 or i == len(targets):
            pct = i / len(targets) * 100
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"\r  [{bar}] {pct:.0f}% — נמצאו: {found}/{i}", end="", flush=True)

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n\n{'='*60}")
    print(f"✅ סיום! נמצאו: {found}/{len(targets)}")
    for src, cnt in sorted(by_src.items(), key=lambda x: -x[1]):
        print(f"   • {src}: {cnt}")
    remaining = sum(1 for p in pubs if not p.get("cover_url"))
    print(f"   עדיין חסרים: {remaining}/{len(pubs)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
