# Project Guide (reusable)

> This `CLAUDE.md` keeps a project consistent across chat sessions. Drop it into a project's repo
> root and fill in **Project specifics** at the bottom. The **ASK FIRST** section tells Claude which
> big architectural choices to confirm *before* scaffolding — answer them once per project and
> record the answers below, so every future chat builds the same way.

## Before you build — ASK FIRST

These are big forks and **not every project, page, or feature needs them.** Ask the user before
assuming; **do not scaffold silently.** Record the chosen answers under **Project specifics**.

1. **Hosting / backend — static (S3) or a Postgres database?**  *(the biggest fork)*
   - **Static on S3 + CloudFront** — hand-coded HTML/CSS/JS, no server, no database. Good for
     marketing sites, brochures, landing pages. Deploy = `aws s3 cp` + CloudFront invalidation.
   - **Postgres-backed app** — accounts, stored data, dashboards. **A browser cannot talk to raw
     Postgres**, so this needs a backend server (API + auth) in front of the database, plus hosting
     for it. Much bigger than static. *(Supabase is one option: it **is** Postgres with a ready-made
     auth + API + row-level-security layer usable from a static front-end.)*
2. **Bilingual (EN + TH)?**
   - **Yes →** English is the source (with `data-i18n` attributes + a `TH` dictionary); generate Thai
     to `/th/…` with a build script and reciprocal `hreflang`.
   - **No →** single-locale English only; skip the Thai build and hreflang.
3. **Client portal / login (accounts)?**
   - **Yes →** requires a database/backend (see #1) with auth and per-user access rules. Confirm the
     account model (admin-created vs. public sign-up).
   - **No →** no auth, no database.

Confirm the answers **before creating files** so the structure is right from the start.

## Static (S3 + CloudFront) conventions  *(if chosen)*

- Hand-written HTML; inline or a shared stylesheet; no framework unless asked.
- Deploy **per changed file** — never `sync .` (it would ship `docs/`, `build/`, `*.md`, `CLAUDE.md`):
  ```bash
  aws s3 cp <file> s3://<bucket>/<path> --cache-control "no-cache, must-revalidate" --content-type "<type>"
  aws cloudfront create-invalidation --distribution-id <dist-id> --paths "/*"
  ```
  Content-types: HTML `text/html; charset=utf-8` · CSS `text/css; charset=utf-8` ·
  XML `application/xml` · plain `text/plain`. Use `--paths "/*"` (a multi-path list containing `/`
  is rejected). HTML is `no-cache` → live after invalidation + a hard refresh.

## Postgres / backend conventions  *(if chosen)*

- The browser talks to an **API server** (or a BaaS like Supabase) — **never to raw Postgres.**
- Auth: hashed passwords + tokens/sessions; enforce per-user access (row-level security or
  app-level checks).
- **Never put a DB password or a service/admin/secret key in client code or the repo.** A public
  anon/publishable key is fine (data must be protected by access rules, not by hiding the key).
- Keep schema + migrations in the repo (`schema.sql`, migrations, or an ORM).

## Bilingual build  *(if chosen)*

English source carries `data-i18n` attributes + a `TH` dictionary; a build script bakes Thai into
`/th/…` (translated text, `<html lang="th">`, Thai `<title>`/meta, reciprocal `hreflang`, internal
link rewrites). **Never hand-edit generated locale files** — edit the source and rebuild.

## Git conventions

- Work on `main`; put big/risky changes (migrations, rewrites, DB swaps) on their **own branch**.
- End commit messages with a `Co-Authored-By: Claude` trailer.
- **Never commit secrets** (DB passwords, service/API secret keys, cloud credentials).

## Conventions & gotchas (defaults)

- Dark/light theme via `prefers-color-scheme` + `data-theme` + a `localStorage` key.
- Prefer a system font stack (no web fonts) for speed unless asked.
- Auth'd pages (portal/admin): `noindex`, reachable by URL then gated by auth.
- Keep the brand name consistent in `<title>`/meta/JSON-LD for SEO even if the visible wordmark is styled differently.

---

## Project specifics  *(fill in per project — example below is this repo)*

- **Project:** ZZ Digital — website & client portal (studio: Quickeasy Asia Co.,Ltd.,
  Tax ID `0505569001285`, Chiang Mai)
- **Public URL:** https://websites.vibecraftedsoftware.com · **Repo:** github.com/Z3d5365/VCS-Website (branch `main`)
- **Hosting choice:** Static on **S3 + CloudFront**
- **Bilingual:** **Yes** (EN source in `index.html` → `th/index.html` via `node build/build-th.js`)
- **Client portal:** **Yes** — Supabase (admin-created + public sign-up); `/portal/` (client),
  `/portal/admin/` (admin, gated by `is_admin`)
- **Static infra:** S3 bucket **`websites.vibecraftedsoftware.com`** (`ap-southeast-1`, public
  static-website endpoint; deploy target), CloudFront `EBJNRLIZ8CTTY`, Route 53 zones
  `Z00211972T0UGXJIDKRSH` (zzdigitaldesign.com) + `Z06117583DJPW9PSW2YWH` (vibecraftedsoftware.com),
  image bucket `zzdigital-website-images` (`us-east-1`). Live at
  `https://websites.vibecraftedsoftware.com`; `zzdigitaldesign.com` 301-redirects there via the
  CloudFront function `zzdigital-www-to-apex`. (Old `zzdigitaldesign.com` bucket retired.)
- **Backend:** Supabase project `vdgdbjesjoyfkfhqgdna` (`https://vdgdbjesjoyfkfhqgdna.supabase.co`);
  tables `clients / projects / project_images / support_messages / admins`; setup in
  `supabase/schema.sql` + `supabase/admin.sql`. Anon key is public; never add the service_role key.
- **Design tokens:** accent violet `#6d5efc` (dark `#8b7dff`), mint `#0fb894` (dark `#2ee0b5`),
  gradient violet→mint; bg `#fbfaf8` / `#0a0a0f`
- **Contact / forms:** Web3Forms → `info@zzdigital.awsapps.com`; phone/LINE `+66 83 9696 555`
- **Deploy:** rebuild Thai (`node build/build-th.js`) if `index.html`/`TH` changed, then
  `aws s3 cp <file> s3://websites.vibecraftedsoftware.com/<path>` each changed file (see Static
  conventions), then invalidate `EBJNRLIZ8CTTY` with `/*`
- **Brand:** name `ZZDigital` in titles/meta/schema; visible nav wordmark `ZZ Digital`
- **More detail:** `docs/SEO-PLAYBOOK.md` (SEO plan + audit)
