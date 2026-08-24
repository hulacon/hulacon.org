/* ============================================================================
   Live publications — fetches the lab's publication list directly from ORCID
   (source of truth) and enriches each entry with Crossref citation metadata.

   Zero maintenance: when a paper appears on the PI's ORCID record, it shows up
   here on the next page load. No build step, no re-upload.

   The page already contains a server-generated baseline list inside #pub-root
   (see build_pubs.py). This script REPLACES it with live data when the APIs are
   reachable; if they are not, the baseline simply remains. Results are cached
   in localStorage for a few hours so repeat visits don't re-hit the APIs.
   ========================================================================== */
(function () {
  "use strict";

  var ORCID_ID   = "0000-0003-2253-6204";
  var MAILTO     = "bhutch@uoregon.edu";        // Crossref "polite pool" contact
  var PI_CANON   = "Hutchinson JB";
  // Records that store an author's name reversed (family in the given field),
  // keyed "family|given" as stored, lowercase -> correct "Family Initials".
  var NAME_FIXES = { "wanjia|guo": "Guo W" };   // Wanjia Guo (family name Guo)
  var CACHE_KEY  = "hulacon_pubs_v2";
  var CACHE_TTL  = 6 * 60 * 60 * 1000;          // 6 hours

  var root = document.getElementById("pub-root");
  if (!root) return;

  // ---- helpers -------------------------------------------------------------

  function initials(given) {
    if (!given) return "";
    return given.trim().split(/[\s\-]+/)
      .filter(function (p) { return p && /[A-Za-z]/.test(p[0]); })
      .map(function (p) { return p[0].toUpperCase(); })
      .join("");
  }

  function fmtAuthors(authors) {
    if (!authors) return "";
    return authors.map(function (a) {
      var orcid = (a.ORCID || "").toLowerCase();
      var fam = (a.family || "").trim();
      var given = (a.given || "").trim();
      // ORCID-iD match only — other Hutchinsons appear as co-authors, so no
      // surname fallback. The match normalises malformed name records.
      if (orcid.indexOf(ORCID_ID) !== -1) return esc(PI_CANON);
      var fix = NAME_FIXES[fam.toLowerCase() + "|" + given.toLowerCase()];
      if (fix) return esc(fix);
      if (!fam) return esc((a.name || "").trim());            // consortia
      return esc((fam + " " + initials(given)).trim());
    }).join(", ");
  }

  // Crossref sometimes returns strings already HTML-escaped (e.g.
  // "Learning &amp; Memory"), so decode entities before re-escaping.
  function unesc(s) {
    var t = document.createElement("textarea");
    t.innerHTML = s || "";
    return t.value;
  }

  function esc(s) {
    return unesc(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function venueOf(m) {
    var ct = m["container-title"] || [];
    var venue = "";
    if (ct.length) venue = ct[0];
    else if (m.institution && m.institution.length) venue = m.institution[0].name || "";
    else if (m.type === "posted-content") return "Preprint";
    var bits = venue;
    if (m.volume) bits += ", " + m.volume;
    if (m.issue)  bits += "(" + m.issue + ")";
    if (m.page)   bits += ", " + m.page;
    return bits.replace(/^[,\s]+|[,\s]+$/g, "");
  }

  function yearOf(m) {
    var d = (m.issued && m.issued["date-parts"] && m.issued["date-parts"][0]) || [];
    return d[0] || null;
  }

  // ---- fetching ------------------------------------------------------------

  function fetchJSON(url) {
    return fetch(url, { headers: { "Accept": "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function delay(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // Run async tasks (functions returning promises) with bounded concurrency.
  // Firing all ~28 Crossref requests at once causes "Failed to fetch" throttling,
  // so we cap how many are in flight at a time.
  function runPool(tasks, limit) {
    var results = new Array(tasks.length);
    var next = 0;
    function worker() {
      if (next >= tasks.length) return Promise.resolve();
      var i = next++;
      return tasks[i]().then(function (v) { results[i] = v; }).then(worker);
    }
    var workers = [];
    for (var w = 0; w < Math.min(limit, tasks.length); w++) workers.push(worker());
    return Promise.all(workers).then(function () { return results; });
  }

  function doiOf(summary) {
    var ids = (summary["external-ids"] && summary["external-ids"]["external-id"]) || [];
    for (var i = 0; i < ids.length; i++) {
      if (ids[i]["external-id-type"] === "doi") {
        return (ids[i]["external-id-value"] || "").trim().toLowerCase();
      }
    }
    return null;
  }

  function crossref(doi) {
    var url = "https://api.crossref.org/works/" + encodeURIComponent(doi) +
              "?mailto=" + encodeURIComponent(MAILTO);
    function attempt(retriesLeft) {
      return fetchJSON(url).catch(function (e) {     // one retry on transient failure
        if (retriesLeft <= 0) throw e;
        return delay(500).then(function () { return attempt(retriesLeft - 1); });
      });
    }
    return attempt(1)
      .then(function (d) {
        var m = d.message;
        return {
          authors: fmtAuthors(m.author || []),
          title: (m.title && m.title[0]) || "Untitled",
          venue: venueOf(m),
          year: yearOf(m),
          doi: doi,
          url: m.URL || ("https://doi.org/" + doi)
        };
      });
  }

  function fromOrcid(summary) {
    var jt = summary["journal-title"];
    var yr = summary["publication-date"] && summary["publication-date"].year &&
             summary["publication-date"].year.value;
    return {
      authors: "",
      title: summary.title.title.value,
      venue: (jt && jt.value) || "",
      year: yr ? parseInt(yr, 10) : null,
      doi: null,
      url: null
    };
  }

  function titleKey(t) { return (t || "").toLowerCase().replace(/\W+/g, ""); }

  function loadOverrides() {
    return fetchJSON("data/pub_overrides.json")
      .then(function (d) { return (d && d.overrides) || {}; })
      .catch(function () { return {}; });        // optional file
  }

  function applyOverride(p, overrides) {
    var ov = (p.doi && overrides[p.doi]) || overrides[titleKey(p.title)];
    if (ov) { for (var k in ov) if (ov.hasOwnProperty(k)) p[k] = ov[k]; }
    return p;
  }

  function loadLive() {
    var ovPromise = loadOverrides();
    return fetchJSON("https://pub.orcid.org/v3.0/" + ORCID_ID + "/works")
      .then(function (data) {
        var groups = data.group || [];
        var seen = {};
        var tasks = [];
        groups.forEach(function (g) {
          var s = g["work-summary"][0];
          var doi = doiOf(s);
          var key = doi || s.title.title.value.toLowerCase().replace(/\W+/g, "");
          if (seen[key]) return;
          seen[key] = true;
          // Defer the fetch (thunk) so the pool controls how many run at once.
          if (doi) {
            tasks.push(function () { return crossref(doi).catch(function () { return fromOrcid(s); }); });
          } else {
            tasks.push(function () { return Promise.resolve(fromOrcid(s)); });
          }
        });
        return runPool(tasks, 4);     // at most 4 Crossref requests in flight
      })
      .then(function (pubs) {
        return ovPromise.then(function (overrides) {
          pubs = pubs.map(function (p) { return applyOverride(p, overrides); });
          pubs.sort(function (a, b) { return (b.year || 0) - (a.year || 0); });
          return pubs;
        });
      });
  }

  // ---- rendering -----------------------------------------------------------

  function render(pubs) {
    var items = pubs.map(function (p) {
      var year = p.year || "";
      var title = esc(p.title);
      var titleHtml = '<span class="title">' + title + "</span>";
      var venue = esc(p.venue);
      var doiLink = p.doi
        ? '<a href="https://doi.org/' + p.doi + '" target="_blank" rel="noopener">doi</a>'
        : (p.url ? '<a href="' + p.url + '" target="_blank" rel="noopener">link</a>' : "");
      var venueHtml = (venue && doiLink) ? (venue + " &middot; " + doiLink) : (venue || doiLink);
      var authorsLine = p.authors
        ? '<span class="authors">' + p.authors + (year ? " (" + year + ")" : "") + ".</span>" : "";
      return '<li class="pub">' + authorsLine +
             titleHtml +
             '<span class="venue">' + venueHtml + "</span></li>";
    }).join("");

    root.innerHTML = '<ul class="pub-list">' + items + "</ul>" +
      '<p class="muted" style="margin-top:40px;font-size:.9rem;">' +
      'Also on <a href="https://scholar.google.com/citations?user=8a7uEYIAAAAJ" target="_blank" rel="noopener">Google Scholar</a> ' +
      'and <a href="https://orcid.org/' + ORCID_ID + '" target="_blank" rel="noopener">ORCID</a>.</p>';
  }

  // ---- orchestration: cache -> live -> (baseline stays on failure) ---------

  try {
    var cached = JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
    if (cached && (Date.now() - cached.t) < CACHE_TTL && cached.pubs && cached.pubs.length) {
      render(cached.pubs);
    }
  } catch (e) { /* ignore bad cache */ }

  loadLive().then(function (pubs) {
    if (!pubs.length) return;                 // keep baseline if empty
    render(pubs);
    try { localStorage.setItem(CACHE_KEY, JSON.stringify({ t: Date.now(), pubs: pubs })); }
    catch (e) { /* storage full / disabled — fine */ }
  }).catch(function (err) {
    // APIs unreachable: the server-generated baseline in #pub-root remains.
    if (window.console) console.warn("Live publications unavailable, using baseline.", err);
  });
})();
