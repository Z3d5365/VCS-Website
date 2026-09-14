/* site-nav.js — the shared header behaviour for every page outside the
 * homepage (/services/…, /th/services/…, /search/, /th/search/).
 *
 * The homepage carries the same logic inline, because its styles are inline
 * too. Everything here mirrors it: theme toggle, sticky-on-scroll header,
 * scroll progress bar, burger menu, remembered language choice, footer year
 * and the "/" hotkey that jumps to search.
 */
(() => {
  "use strict";
  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  /* localStorage throws in private mode and sandboxed frames. */
  const store = {
    get(k)    { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); }    catch { /* no-op */ } }
  };

  const root = document.documentElement;
  const isTH = root.lang === "th";
  const searchUrl = isTH ? "/th/search/" : "/search/";

  /* ── theme ─────────────────────────────────────── */
  root.dataset.theme = store.get("zz-theme") || "light";   // light-first brand
  const themeBtn = $("#theme");
  if (themeBtn) themeBtn.addEventListener("click", () => {
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    store.set("zz-theme", next);
    root.dataset.theme = next;
  });

  /* Remember an explicit language choice so nothing auto-redirects over it. */
  $$(".lang-opt").forEach(a => a.addEventListener("click", () => store.set("zz-lang", a.dataset.lang)));

  /* ── sticky header + scroll progress ───────────── */
  const header = $(".header"), progress = $("#progress");
  let queued = false;
  const onScroll = () => {
    const y = scrollY;
    if (header) y > 8 ? header.setAttribute("data-stuck", "") : header.removeAttribute("data-stuck");
    if (progress) {
      const max = document.documentElement.scrollHeight - innerHeight;
      progress.style.scale = `${max > 0 ? Math.min(y / max, 1) : 0} 1`;
    }
    queued = false;
  };
  addEventListener("scroll", () => {
    if (!queued) { queued = true; requestAnimationFrame(onScroll); }
  }, { passive: true });
  onScroll();

  /* ── mobile nav ────────────────────────────────── */
  const nav = $("#nav"), burger = $("#burger");
  if (nav && burger) {
    const setNav = open => {
      nav.toggleAttribute("data-open", open);
      burger.setAttribute("aria-expanded", String(open));
    };
    burger.addEventListener("click", () => setNav(!nav.hasAttribute("data-open")));
    nav.addEventListener("click", e => { if (e.target.closest("a")) setNav(false); });
    addEventListener("keydown", e => { if (e.key === "Escape") setNav(false); });
    matchMedia("(min-width: 881px)").addEventListener("change", e => { if (e.matches) setNav(false); });
  }

  /* ── "/" jumps to search ───────────────────────── */
  addEventListener("keydown", e => {
    if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
    const el = document.activeElement;
    if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
    e.preventDefault();
    location.href = searchUrl;
  });

  /* ── year ──────────────────────────────────────── */
  const y = $("#year");
  if (y) y.textContent = new Date().getFullYear();
})();
