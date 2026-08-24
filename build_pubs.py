#!/usr/bin/env python3
"""
Generate site/publications.html from ORCID + Crossref.

Single source of truth = the lab PI's ORCID record. ORCID gives the curated
list of works (and DOIs); Crossref provides rich, consistent citation metadata
(full author list, journal, volume/issue, pages). No PDFs are hosted: every
work links to its DOI.

Usage:
    python3 build_pubs.py            # regenerate site/publications.html + site/data/publications.json

Re-run whenever you add a publication to your ORCID profile.
"""

import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ORCID_ID   = "0000-0003-2253-6204"          # J. Benjamin Hutchinson
PI_CANONICAL = "Hutchinson JB"                # how the PI is rendered in author lists

# Some Crossref/ORCID records store an author's name reversed (family in the
# given field and vice versa). Keyed by (family, given) as stored, lowercase;
# value is the correct "Family Initials" rendering.
NAME_FIXES = {
    ("wanjia", "guo"): "Guo W",               # Wanjia Guo (family name Guo)
}
MAILTO     = "bhutch@uoregon.edu"             # Crossref "polite pool" contact
SCHOLAR_ID = "8a7uEYIAAAAJ"                   # optional, for a profile link
HERE       = Path(__file__).resolve().parent
OUT_HTML   = HERE / "site" / "publications.html"
OUT_JSON   = HERE / "site" / "data" / "publications.json"
UA         = f"hulacon-site/1.0 (mailto:{MAILTO})"


def get_json(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def doi_of(summary):
    for e in summary.get("external-ids", {}).get("external-id", []) or []:
        if e.get("external-id-type") == "doi":
            return e.get("external-id-value", "").strip().lower()
    return None


def initials(given):
    if not given:
        return ""
    parts = re.split(r"[\s\-]+", given.strip())
    return "".join(p[0].upper() for p in parts if p and p[0].isalpha())


def fmt_authors(authors):
    """Crossref author list -> 'Family AB, Family CD, ...'.

    The PI is identified by the ORCID iD that Crossref embeds per author (some
    records store the name malformed, so the match normalises it to
    'Hutchinson JB'). Surname matching is deliberately NOT used — other
    Hutchinsons appear as co-authors.
    """
    out = []
    for a in authors:
        orcid = (a.get("ORCID") or "").lower()
        fam = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        if ORCID_ID in orcid:
            out.append(PI_CANONICAL)
            continue
        fix = NAME_FIXES.get((fam.lower(), given.lower()))
        if fix:
            out.append(esc(fix))
            continue
        if not fam:
            out.append(esc((a.get("name") or "").strip()))  # consortia / group authors
            continue
        out.append(esc(f"{fam} {initials(given)}".strip()))
    return ", ".join(out)


def crossref(doi):
    try:
        m = get_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}")["message"]
    except Exception as e:
        print(f"    ! Crossref miss for {doi}: {e}", file=sys.stderr)
        return None
    issued = (m.get("issued", {}).get("date-parts") or [[None]])[0]
    year = issued[0] if issued else None
    ct = m.get("container-title") or []
    wtype = m.get("type", "")
    if ct:
        venue = ct[0]
    elif m.get("institution"):
        venue = (m["institution"][0] or {}).get("name", "")
    elif wtype == "posted-content":
        venue = "Preprint"        # bioRxiv / PsyArXiv / OSF, etc.
    else:
        venue = ""
    bits = venue or ""
    if venue != "Preprint":
        if m.get("volume"):
            bits += f", {m['volume']}"
        if m.get("issue"):
            bits += f"({m['issue']})"
        if m.get("page"):
            bits += f", {m['page']}"
    return {
        "authors": fmt_authors(m.get("author", []) or []),
        "title": (m.get("title") or ["Untitled"])[0],
        "venue": bits.strip(", "),
        "year": year,
        "doi": doi,
        "url": m.get("URL") or f"https://doi.org/{doi}",
        "type": m.get("type", ""),
    }


def from_orcid(summary):
    """Fallback when a work has no DOI (e.g. some conference proceedings)."""
    title = summary["title"]["title"]["value"]
    yr = ((summary.get("publication-date") or {}).get("year") or {}).get("value")
    jt = (summary.get("journal-title") or {})
    venue = jt.get("value", "") if isinstance(jt, dict) else ""
    return {
        "authors": "", "title": title, "venue": venue,
        "year": int(yr) if yr else None, "doi": None, "url": None, "type": "",
    }


def title_key(title):
    return re.sub(r"\W+", "", (title or "").lower())


def load_overrides():
    path = HERE / "site" / "data" / "pub_overrides.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get("overrides", {})


def apply_override(rec, overrides):
    ov = overrides.get(rec.get("doi")) or overrides.get(title_key(rec.get("title")))
    if ov:
        rec.update({k: v for k, v in ov.items()})
    return rec


def fetch_all():
    overrides = load_overrides()
    data = get_json(f"https://pub.orcid.org/v3.0/{ORCID_ID}/works")
    groups = data.get("group", [])
    pubs, seen = [], set()
    for g in groups:
        s = g["work-summary"][0]
        doi = doi_of(s)
        key = doi or title_key(s["title"]["title"]["value"])
        if key in seen:
            continue
        seen.add(key)
        title = s["title"]["title"]["value"]
        print(f"  - {title[:60]}")
        rec = crossref(doi) if doi else None
        if not rec:
            rec = from_orcid(s)
        rec = apply_override(rec, overrides)   # manual corrections win
        pubs.append(rec)
        if doi:
            time.sleep(0.15)  # be polite to Crossref
    # Sort newest first; untitled-year last
    pubs.sort(key=lambda p: (p["year"] or 0), reverse=True)
    return pubs


# ----------------------------- HTML rendering ------------------------------ #

NAV = """  <header class="site-header">
    <nav class="nav container" aria-label="Primary">
      <a class="nav__logo" href="index.html"><img src="assets/logo.png" alt="Hutchinson Lab of Cognitive Neuroscience, University of Oregon"></a>
      <button class="nav__toggle" aria-label="Menu" aria-expanded="false"><span></span><span></span><span></span></button>
      <ul class="nav__links">
        <li><a href="index.html">About</a></li>
        <li><a href="people.html">People</a></li>
        <li><a href="publications.html" class="is-active">Publications</a></li>
        <li><a href="code.html">Code</a></li>
        <li><a href="join.html">Join Us</a></li>
        <li><a href="contact.html">Contact</a></li>
      </ul>
    </nav>
  </header>"""

FOOTER = """  <footer class="site-footer">
    <div class="container">
      <div class="footer-grid">
        <div class="footer-brand">
          <img src="assets/logo-white.png" alt="Hutchinson Lab of Cognitive Neuroscience">
          <p>Studying how the brain enables memory and attention, in the Department of Psychology at the University of Oregon.</p>
        </div>
        <div>
          <h4>Explore</h4>
          <ul>
            <li><a href="index.html">About</a></li>
            <li><a href="people.html">People</a></li>
            <li><a href="publications.html">Publications</a></li>
            <li><a href="code.html">Code &amp; Tools</a></li>
            <li><a href="join.html">Join Us</a></li>
            <li><a href="contact.html">Contact</a></li>
          </ul>
        </div>
        <div>
          <h4>Affiliations</h4>
          <ul>
            <li><a href="http://oregonmemorygroup.uoregon.edu/" target="_blank" rel="noopener">Oregon Memory Group</a></li>
            <li><a href="http://psychology.uoregon.edu/" target="_blank" rel="noopener">Psychology Department</a></li>
            <li><a href="https://www.uoregon.edu/" target="_blank" rel="noopener">University of Oregon</a></li>
            <li><a href="https://github.com/hulacon" target="_blank" rel="noopener">GitHub (hulacon)</a></li>
            <li><a href="mailto:bhutch@uoregon.edu">bhutch@uoregon.edu</a></li>
          </ul>
        </div>
      </div>
      <div class="footer-bottom">
        <span>&copy; 2026 Hutchinson Lab of Cognitive Neuroscience &middot; University of Oregon</span>
        <span>Lewis Integrative Sciences Building, Eugene, OR 97403</span>
      </div>
    </div>
  </footer>"""


def esc(s):
    """Escape plain text (titles, venues, names) for HTML.

    Crossref sometimes returns strings that are already HTML-escaped (e.g.
    'Learning &amp; Memory'), so unescape first to avoid double-escaping."""
    s = html.unescape(s or "")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(pubs):
    items = []
    for p in pubs:                       # pubs are pre-sorted newest-first
        year = p["year"]
        authors = p["authors"]           # already escaped by fmt_authors
        title = esc(p["title"])
        venue = esc(p["venue"])
        title_html = f'<span class="title">{title}</span>'
        if p.get("doi"):
            doi_link = f'<a href="https://doi.org/{p["doi"]}" target="_blank" rel="noopener">doi</a>'
        elif p.get("url"):
            doi_link = f'<a href="{p["url"]}" target="_blank" rel="noopener">link</a>'
        else:
            doi_link = ""
        if venue and doi_link:
            venue_html = f"{venue} &middot; {doi_link}"
        else:
            venue_html = venue or doi_link
        year_str = f" ({year})" if year else ""
        authors_line = f'<span class="authors">{authors}{year_str}.</span>' if authors else ""
        items.append(
            '        <li class="pub">\n'
            f'          {authors_line}\n'
            f'          {title_html}\n'
            f'          <span class="venue">{venue_html}</span>\n'
            '        </li>'
        )
    pubs_html = '      <ul class="pub-list">\n' + "\n".join(items) + "\n      </ul>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Publications &mdash; Hutchinson Lab of Cognitive Neuroscience</title>
  <meta name="description" content="Publications from the Hutchinson Lab of Cognitive Neuroscience at the University of Oregon.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Spectral:ital,wght@0,500;0,600;1,500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="css/style.css">
  <!-- This page is GENERATED from ORCID {ORCID_ID} by build_pubs.py. Do not edit by hand. -->
</head>
<body>

{NAV}

  <section class="page-head">
    <div class="container">
      <h1>Publications</h1>
    </div>
  </section>

  <section class="section">
    <div class="container" style="max-width:880px;">

      <!-- Baseline list below is a server-generated snapshot. js/pubs.js fetches
           live data from ORCID + Crossref on load and replaces it when reachable. -->
      <div id="pub-root">

{pubs_html}

      <p class="muted" style="margin-top:40px;font-size:.9rem;">
        Also on <a href="https://scholar.google.com/citations?user={SCHOLAR_ID}" target="_blank" rel="noopener">Google Scholar</a>
        and <a href="https://orcid.org/{ORCID_ID}" target="_blank" rel="noopener">ORCID</a>.
      </p>

      </div><!-- /#pub-root -->

    </div>
  </section>

{FOOTER}

  <script src="js/main.js"></script>
  <script src="js/pubs.js"></script>
  <!-- Cloudflare Web Analytics --><script type='module' src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{{"token": "a704ad2ca6104a5793aed3b8f172d8c7"}}'></script><!-- End Cloudflare Web Analytics -->
</body>
</html>
"""


def main():
    print(f"Fetching works for ORCID {ORCID_ID} ...")
    pubs = fetch_all()
    print(f"Collected {len(pubs)} unique publications.")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(pubs, indent=2))
    OUT_HTML.write_text(render(pubs))
    print(f"Wrote {OUT_HTML.relative_to(HERE)} and {OUT_JSON.relative_to(HERE)}")


if __name__ == "__main__":
    main()
