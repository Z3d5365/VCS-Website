/* search.js — the /search/ and /th/search/ results page.
 *
 * Talks to the Pagefind index that `scripts/deploy.sh` builds into /pagefind/
 * on every deploy. Reads ?q= from the URL, searches as you type (debounced),
 * keeps the URL in sync so results can be shared and the back button works,
 * and renders per-page results with their matching sections underneath.
 *
 * Pagefind keeps a separate index per <html lang>, and pagefind.js picks the
 * right one from the document, so this same file serves EN and TH.
 */
(() => {
  "use strict";

  const TH = document.documentElement.lang === "th";
  const T = TH ? {
    placeholder: "ค้นหาในเว็บไซต์…",
    idle:     "พิมพ์เพื่อค้นหาทุกหน้าในเว็บไซต์",
    loading:  "กำลังค้นหา…",
    none:     q => `ไม่พบผลลัพธ์สำหรับ “${q}”`,
    count:    (n, q) => `${n} ผลลัพธ์สำหรับ “${q}”`,
    one:      q => `1 ผลลัพธ์สำหรับ “${q}”`,
    broken:   "ขออภัย ระบบค้นหาใช้งานไม่ได้ในขณะนี้",
    sections: "ในหน้านี้:"
  } : {
    placeholder: "Search the site…",
    idle:     "Start typing to search every page on the site.",
    loading:  "Searching…",
    none:     q => `No results for “${q}”.`,
    count:    (n, q) => `${n} results for “${q}”`,
    one:      q => `1 result for “${q}”`,
    broken:   "Search is unavailable right now. Sorry about that.",
    sections: "On this page:"
  };

  const input    = document.getElementById("q");
  const statusEl = document.getElementById("search-status");
  const listEl   = document.getElementById("search-results");
  const formEl   = document.getElementById("search-form");
  if (!input || !statusEl || !listEl) return;

  input.placeholder = T.placeholder;

  /* Pagefind is loaded lazily — nobody pays for the index until they search. */
  let pagefindPromise = null;
  const pagefind = () => {
    if (!pagefindPromise) {
      pagefindPromise = import("/pagefind/pagefind.js")
        .then(mod => { mod.options({ excerptLength: 28 }); return mod; })
        .catch(() => null);
    }
    return pagefindPromise;
  };

  const esc = s => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  /* Pagefind's own excerpts arrive with <mark> around the hits, so those we
     keep as HTML — everything else is escaped before it goes near innerHTML. */
  const cleanExcerpt = html => String(html || "")
    .replace(/<(?!\/?mark\b)[^>]*>/g, "");

  let token = 0;   // guards against a slow query overwriting a newer one

  async function run(q) {
    const mine = ++token;
    q = q.trim();

    if (!q) {
      listEl.innerHTML = "";
      statusEl.textContent = T.idle;
      return;
    }

    statusEl.textContent = T.loading;

    const pf = await pagefind();
    if (mine !== token) return;
    if (!pf) { listEl.innerHTML = ""; statusEl.textContent = T.broken; return; }

    const search = await pf.search(q);
    if (mine !== token) return;

    const results = await Promise.all(search.results.slice(0, 20).map(r => r.data()));
    if (mine !== token) return;

    const n = search.results.length;
    statusEl.textContent = n === 0 ? T.none(q) : n === 1 ? T.one(q) : T.count(n, q);
    listEl.innerHTML = results.map(card).join("");
  }

  function card(d) {
    const title = esc((d.meta && d.meta.title) || d.url);
    const subs = (d.sub_results || [])
      .filter(s => s.anchor)          // only sections we can actually link to
      .slice(0, 4)
      .map(s => `<li><a href="${esc(s.url)}">${esc(s.title)}</a></li>`)
      .join("");

    /* The whole card is the link: .sr__title a carries a stretched ::after
       overlay, and the section links sit above it on their own z-index. */
    return `<article class="sr">
      <span class="sr__go" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></span>
      <h2 class="sr__title"><a href="${esc(d.url)}">${title}</a></h2>
      <p class="sr__url">${esc(pretty(d.url))}</p>
      <p class="sr__excerpt">${cleanExcerpt(d.excerpt)}</p>
      ${subs ? `<p class="sr__subhead">${esc(T.sections)}</p><ul class="sr__subs">${subs}</ul>` : ""}
    </article>`;
  }

  const pretty = url => {
    try { return decodeURIComponent(url).replace(/index\.html$/, "") || "/"; }
    catch { return url; }
  };

  /* ── URL <-> input ─────────────────────────────── */
  const readQ = () => new URLSearchParams(location.search).get("q") || "";

  let urlTimer = 0;
  const syncUrl = q => {
    clearTimeout(urlTimer);
    urlTimer = setTimeout(() => {
      const next = location.pathname + (q.trim() ? "?q=" + encodeURIComponent(q.trim()) : "");
      if (next !== location.pathname + location.search) history.replaceState({ q }, "", next);
    }, 400);
  };

  let searchTimer = 0;
  input.addEventListener("input", () => {
    const q = input.value;
    syncUrl(q);
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => run(q), 180);
  });

  if (formEl) formEl.addEventListener("submit", e => { e.preventDefault(); clearTimeout(searchTimer); run(input.value); });

  input.addEventListener("keydown", e => {
    if (e.key === "Escape") { input.value = ""; syncUrl(""); run(""); }
  });

  addEventListener("popstate", () => { input.value = readQ(); run(input.value); });

  /* ── first paint ───────────────────────────────── */
  const initial = readQ();
  input.value = initial;
  run(initial);
  /* Don't steal the viewport on a phone when someone lands on a shared link. */
  if (matchMedia("(min-width: 700px)").matches || !initial) input.focus({ preventScroll: true });
})();
