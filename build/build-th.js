/* build-th.js — generate th/index.html (static Thai page) from index.html.
 *
 * Reads the English source (index.html), the Thai dictionary embedded in it
 * (const TH = {...}), and produces a fully pre-rendered Thai page at th/index.html
 * with Thai baked into the HTML, <html lang="th">, Thai <title>/meta/JSON-LD,
 * reciprocal hreflang, and the language switch set to Thai.
 *
 * Run:  node build/build-th.js   (from the repo root)
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const src = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");

/* 1. Extract the TH dictionary from the source. */
const m = src.match(/const TH = (\{[\s\S]*?\n  \});/);
if (!m) { console.error("Could not find TH dictionary in index.html"); process.exit(1); }
const TH = new Function("return " + m[1])();

const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
let warnings = 0;
const replaceOne = (html, find, repl, label) => {
  if (html.indexOf(find) === -1) { console.warn("  ! not found:", label); warnings++; return html; }
  return html.split(find).join(repl);
};

/* Thai metadata (hand-written — refine as needed). */
const TH_TITLE   = "รับทำเว็บไซต์โหลดเร็ว สร้างด้วยมือ — Vibe Crafted";
const TH_DESC    = "Vibe Crafted สตูดิโอดิจิทัล รับทำเว็บไซต์โหลดเร็วสร้างด้วยมือ พร้อมโลโก้และโฮสติ้ง สำหรับร้านอาหาร รีสอร์ต และธุรกิจท้องถิ่น เริ่มต้น ฿2,999";
const TH_OG_DESC = "เว็บไซต์ โลโก้ และโฮสติ้งที่สร้างด้วยมือ โหลดเร็ว สำหรับธุรกิจท้องถิ่น เริ่มต้น ฿2,999";
const TH_TW_DESC = "เว็บไซต์และโลโก้ที่สร้างด้วยมือ เปิดตัวได้ในสองสัปดาห์";
const TH_PS_DESC = "สตูดิโอดิจิทัล รับทำเว็บไซต์โหลดเร็วสร้างด้วยมือ พร้อมโลโก้และโฮสติ้ง สำหรับร้านอาหาร รีสอร์ต และธุรกิจท้องถิ่น";

/* English FAQ strings (as they appear in the JSON-LD) → mapped to Thai by key. */
const FAQ_EN = {
  "faq1.q": "How long does a website take?",
  "faq1.a": "Two weeks is typical from the moment you send content and photos. A simple one-page site can be live in three or four days. If you have a hard deadline, say so on the first call and I'll tell you honestly whether it's possible.",
  "faq2.q": "What does the monthly upkeep actually cover?",
  "faq2.a": "Hosting, SSL, daily backups, software and security updates, uptime monitoring, and up to an hour of small content changes each month — new prices, new photos, opening hours. Cancel any month and I'll hand over the files.",
  "faq3.q": "Do I need my own domain name?",
  "faq3.a": "Yes, and you should own it yourself rather than have an agency hold it. I'll register it in your name and bill you what it costs. You keep the account.",
  "faq4.q": "Who owns the site and the content?",
  "faq4.a": "You do, entirely. The code, the design, the logo, the domain, the logins. There's no licence to renew and no lock-in. If you ever move to another developer, everything transfers.",
  "faq5.q": "Can you work with a business remotely?",
  "faq5.a": "Yes — most communication happens over email, WhatsApp or a video call anyway. I work in Indochina Time (UTC+7) and reply within a day. Payment by international transfer or card.",
  "faq6.q": "Will it be fast, and will Google like it?",
  "faq6.a": "Every site is hand-built and lands under two seconds on a normal 4G connection, with green Core Web Vitals. Structured data, sitemap, meta descriptions and Google Business Profile are part of the base price, not an upsell."
};

let html = src;

/* 2. <html lang> */
html = replaceOne(html, '<html lang="en">', '<html lang="th">', "html lang");

/* 3. Placeholders (data-i18n-ph) — do before leaf pass. */
["form.name.ph", "form.biz.ph", "form.msg.ph"].forEach(key => {
  const re = new RegExp('placeholder="[^"]*"(\\s+data-i18n-ph="' + esc(key) + '")');
  if (!re.test(html)) { console.warn("  ! placeholder not found:", key); warnings++; return; }
  html = html.replace(re, (mm, g1) => 'placeholder="' + TH[key] + '"' + g1);
});

/* 4. data-i18n-html (hero title, contains markup) */
html = html.replace(/(data-i18n-html="hero\.title"[^>]*>)([\s\S]*?)(<\/h1>)/,
  (mm, a, b, c) => a + TH["hero.title"] + c);

/* 5. Leaf data-i18n elements */
Object.keys(TH).forEach(key => {
  if (key === "hero.title") return; // handled as html
  const re = new RegExp('(\\sdata-i18n="' + esc(key) + '"[^>]*>)([\\s\\S]*?)(<\\/)', 'g');
  html = html.replace(re, (mm, a, b, c) => a + TH[key] + c);
});

/* 6. Title + social meta */
html = replaceOne(html, "Fast, Hand-Built Websites — Vibe Crafted", TH_TITLE, "title/og:title/twitter:title");
html = replaceOne(html, "Fast, hand-built websites, logos and hosting for restaurants, resorts and local businesses. Launch in two weeks — from R1,499.", TH_DESC, "meta description");
html = replaceOne(html, "Fast, hand-built websites, logos and hosting for restaurants, resorts and local businesses. From R1,499.", TH_OG_DESC, "og:description");
html = replaceOne(html, "Fast, hand-built websites, logos and hosting. Launch in two weeks.", TH_TW_DESC, "twitter:description");

/* 7. Canonical + og:url + locales → Thai URL */
html = replaceOne(html, '<link rel="canonical" href="https://websites.vibecraftedsoftware.com/">', '<link rel="canonical" href="https://websites.vibecraftedsoftware.com/th/">', "canonical");
html = replaceOne(html, '<meta property="og:url" content="https://websites.vibecraftedsoftware.com/">', '<meta property="og:url" content="https://websites.vibecraftedsoftware.com/th/">', "og:url");
html = replaceOne(html, '<meta property="og:locale" content="en_US">', '<meta property="og:locale" content="th_TH">', "og:locale");
html = replaceOne(html, '<meta property="og:locale:alternate" content="th_TH">', '<meta property="og:locale:alternate" content="en_US">', "og:locale:alternate");
html = replaceOne(html, 'content="Vibe Crafted — Small studio. Serious websites.">', 'content="Vibe Crafted — สตูดิโอเล็ก ๆ เว็บไซต์ที่จริงจัง">', "og:image:alt");

/* 8. JSON-LD — ProfessionalService description + FAQ to Thai */
html = replaceOne(html, TH_PS_DESC ? "Digital studio in Chiang Mai building fast, hand-built websites, logos and hosting for restaurants, resorts and local businesses across Thailand." : "", TH_PS_DESC, "ProfessionalService description");
Object.keys(FAQ_EN).forEach(key => {
  html = replaceOne(html, FAQ_EN[key], TH[key], "JSON-LD " + key);
});

/* 9. Language switch active state → Thai */
html = replaceOne(html,
  '<a class="lang-opt is-active" href="/" data-lang="en" hreflang="en" aria-current="true">EN</a>',
  '<a class="lang-opt" href="/" data-lang="en" hreflang="en">EN</a>', "lang-opt EN active off");
html = replaceOne(html,
  '<a class="lang-opt" href="/th/" data-lang="th" hreflang="th">ไทย</a>',
  '<a class="lang-opt is-active" href="/th/" data-lang="th" hreflang="th" aria-current="true">ไทย</a>', "lang-opt TH active on");

/* 9b. Rewrite internal service links to the Thai tree (/services/… → /th/services/…) */
html = html.split('href="/services/').join('href="/th/services/');
/* 9b2. Search link → Thai search page */
html = html.split('href="/search/"').join('href="/th/search/"');
html = replaceOne(html, 'aria-label="Search the site" title="Search (press /)"', 'aria-label="ค้นหาในเว็บไซต์" title="ค้นหา"', "search button labels");

/* 9c. The brand/home link → Thai home */
html = html.split('href="/" aria-label').join('href="/th/" aria-label');

/* 9d. Prices: bake baht in and drop the currency switch (Thai page is THB only). */
html = html.replace(/(<b data-thb="([^"]*)"[^>]*>)[^<]*(<\/b>)/g, (mm, a, thb, c) => a + thb + c);
{
  const before = html;
  html = html.replace(/[ \t]*<!-- cur-switch:start -->[\s\S]*?<!-- cur-switch:end -->\r?\n?/, "");
  if (html === before) { console.warn("  ! not found: cur-switch block"); warnings++; }
}

/* 10. Write output */
const outDir = path.join(ROOT, "th");
fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(path.join(outDir, "index.html"), html);

console.log(`Wrote th/index.html (${html.length} bytes). Warnings: ${warnings}`);
