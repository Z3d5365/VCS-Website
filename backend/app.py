"""
ZZ Digital — client portal backend (FastAPI + Postgres).

Replaces Supabase with your own Postgres + app-level auth, matching the
FastAPI / JWT-in-HttpOnly-cookie / bcrypt pattern used elsewhere.

Run (dev):
    cd backend
    cp .env.example .env          # then fill in DATABASE_URL + JWT_SECRET
    uvicorn app:app --reload --port 8000

Env vars:
    DATABASE_URL   postgres://user:pass@host:5432/dbname
    JWT_SECRET     long random string
    ALLOWED_ORIGINS  comma-separated origins allowed to call the API with cookies
                     (e.g. https://zzdigitaldesign.com). Omit if the portal is served
                     from this same backend.
    COOKIE_SECURE  "1" in production (HTTPS), "0" for local http.
"""
import os, json, base64, datetime as dt, uuid
from contextlib import asynccontextmanager
from urllib.parse import quote, unquote

import asyncpg, jwt, bcrypt, boto3, httpx
from fastapi import FastAPI, Request, Response, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr

DATABASE_URL   = os.environ["DATABASE_URL"]
JWT_SECRET     = os.environ.get("JWT_SECRET", "dev-only-change-me")
COOKIE_SECURE  = os.environ.get("COOKIE_SECURE", "0") == "1"
ALLOWED_ORIGINS= [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
COOKIE_NAME    = "zz_session"
TOKEN_DAYS     = 30
UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "vibecraftedsoftware-client-uploads")
AWS_REGION     = os.environ.get("AWS_REGION", "ap-southeast-1")
ALLOWED_IMG    = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/svg+xml", "image/avif"}
VISION_IMG     = {"image/jpeg", "image/png", "image/webp", "image/gif"}   # image types the vision model accepts
# AI theme generator via OpenRouter (OpenAI-compatible). Model is swappable via env.
OPENROUTER_KEY   = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free")
OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
s3 = boto3.client("s3", region_name=AWS_REGION)   # AWS creds come from env (AWS_ACCESS_KEY_ID / SECRET)

def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")

def verify_pw(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False

# Additive tables created on startup so an existing DB gets them without a manual
# migration (the schema.sql init script only runs on a fresh data dir).
TYPO_SCHEMA = """
create table if not exists typography_sets (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references projects(id) on delete cascade,
  title             text not null,
  brief             text,                                   -- client's description of the thing
  notes             text,                                   -- admin's typography notes (fonts, pairings)
  status            text not null default 'requested',      -- requested / in progress / delivered
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),     -- bumped by studio
  client_updated_at timestamptz                             -- bumped by client
);
create index if not exists typo_sets_project_idx on typography_sets(project_id);

create table if not exists typography_images (
  id         uuid primary key default gen_random_uuid(),
  set_id     uuid not null references typography_sets(id) on delete cascade,
  url        text not null,
  role       text not null check (role in ('reference','result')),  -- client refs vs studio deliverables
  created_at timestamptz not null default now()
);
create index if not exists typo_images_set_idx on typography_images(set_id);

-- Client's preferred website theme (colours / font / light-dark), free-form JSON.
alter table projects add column if not exists theme jsonb;
"""

async def _init_con(con):
    # round-trip jsonb as Python dict/list instead of raw text
    await con.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10, init=_init_con)
    async with app.state.pool.acquire() as con:
        await con.execute(TYPO_SCHEMA)
    yield
    await app.state.pool.close()

app = FastAPI(title="ZZ Digital Portal API", lifespan=lifespan)
if ALLOWED_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ── auth helpers ─────────────────────────────────────────
def make_token(user_id: str) -> str:
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=TOKEN_DAYS)
    return jwt.encode({"sub": user_id, "exp": exp}, JWT_SECRET, algorithm="HS256")

def set_cookie(resp: Response, token: str):
    resp.set_cookie(COOKIE_NAME, token, httponly=True, secure=COOKIE_SECURE,
                    samesite="none" if COOKIE_SECURE else "lax",
                    max_age=TOKEN_DAYS * 86400, path="/")

async def current_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not signed in")
    try:
        uid = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid session")
    row = await request.app.state.pool.fetchrow(
        "select id, email, name, business, is_admin from users where id = $1", uid)
    if not row:
        raise HTTPException(401, "User not found")
    return dict(row)

async def require_admin(user=Depends(current_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "Admins only")
    return user

def pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool

# ── models ───────────────────────────────────────────────
class SignUp(BaseModel):
    email: EmailStr; password: str; name: str | None = None; business: str | None = None
class SignIn(BaseModel):
    email: EmailStr; password: str
class ProjectIn(BaseModel):
    user_id: str; title: str; kind: str | None = None; status: str = "In build"
    web_url: str | None = None; next_step: str | None = None
class ProjectPatch(BaseModel):
    brief: str | None = None; notes: str | None = None; status: str | None = None
    web_url: str | None = None; next_step: str | None = None
class ImageIn(BaseModel):
    url: str
class MessageIn(BaseModel):
    body: str
class ThemeIn(BaseModel):
    preset: str | None = None
    accent: str | None = None; accent2: str | None = None
    font: str | None = None; mode: str | None = None
class TypoSetIn(BaseModel):
    title: str; brief: str | None = None
class TypoSetPatch(BaseModel):
    title: str | None = None; brief: str | None = None
    notes: str | None = None; status: str | None = None

def public_user(u): return {k: u[k] for k in ("id", "email", "name", "business", "is_admin")}

# ── auth routes ──────────────────────────────────────────
@app.post("/api/auth/signup")
async def signup(body: SignUp, request: Request, resp: Response):
    p = pool(request)
    if await p.fetchrow("select 1 from users where email=$1", body.email.lower()):
        raise HTTPException(409, "That email already has an account")
    row = await p.fetchrow(
        "insert into users(email,password_hash,name,business) values($1,$2,$3,$4) returning *",
        body.email.lower(), hash_pw(body.password), body.name, body.business)
    set_cookie(resp, make_token(str(row["id"])))
    return public_user(row)

@app.post("/api/auth/signin")
async def signin(body: SignIn, request: Request, resp: Response):
    row = await pool(request).fetchrow("select * from users where email=$1", body.email.lower())
    if not row or not verify_pw(body.password, row["password_hash"]):
        raise HTTPException(401, "Wrong email or password")
    set_cookie(resp, make_token(str(row["id"])))
    return public_user(row)

@app.post("/api/auth/signout")
async def signout(resp: Response):
    resp.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}

@app.get("/api/auth/me")
async def me(user=Depends(current_user)):
    return public_user(user)

# ── projects ─────────────────────────────────────────────
@app.get("/api/projects")
async def list_projects(request: Request, user=Depends(current_user), user_id: str | None = None):
    p = pool(request)
    if user["is_admin"]:
        if user_id:
            rows = await p.fetch("select * from projects where user_id=$1 order by created_at", user_id)
        else:
            rows = await p.fetch("select * from projects order by created_at")
    else:
        rows = await p.fetch("select * from projects where user_id=$1 order by created_at", user["id"])
    return [dict(r) for r in rows]

@app.post("/api/projects")
async def create_project(body: ProjectIn, request: Request, admin=Depends(require_admin)):
    row = await pool(request).fetchrow(
        """insert into projects(user_id,title,kind,status,web_url,next_step)
           values($1,$2,$3,$4,$5,$6) returning *""",
        body.user_id, body.title, body.kind, body.status, body.web_url, body.next_step)
    return dict(row)

def _slug(text, fallback):
    # Readable S3 folder/file name: keep letters/digits (incl. non-ASCII), turn
    # spaces & punctuation into single hyphens, trim, cap length.
    out = "".join(c if (c.isalnum() or c in " -_.") else "-" for c in (text or "").strip())
    out = "-".join(out.split())
    out = out.strip("-_.")[:60]
    return out or fallback

def _taken_names(rows):
    # filenames already used (from stored URLs) so new uploads never overwrite them
    return {unquote(r["url"].rstrip("/").rsplit("/", 1)[-1]) for r in rows}

async def _put_images(files, key_prefix, taken):
    # Validate + store each image under key_prefix/<filename>, de-duping names
    # against `taken` (photo.jpg → photo-2.jpg…). Returns [(filename, url), …].
    stored = []
    for f in files:
        data = await f.read()
        if len(data) > 15 * 1024 * 1024:
            raise HTTPException(413, (f.filename or "file") + " is too large (max 15 MB)")
        ctype = (f.content_type or "").lower()
        if ctype not in ALLOWED_IMG:
            raise HTTPException(400, (f.filename or "file") + ": only image files are allowed")
        base = _slug(f.filename, "image")
        n, candidate = 1, base
        while candidate in taken:
            n += 1
            stem, dot, ext = base.rpartition(".")
            candidate = f"{stem}-{n}.{ext}" if dot else f"{base}-{n}"
        taken.add(candidate)
        key = f"{key_prefix}/{candidate}"
        await run_in_threadpool(s3.put_object, Bucket=UPLOADS_BUCKET, Key=key, Body=data, ContentType=ctype)
        url = f"https://{UPLOADS_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{quote(key)}"
        stored.append((candidate, url))
    return stored

async def _project_prefix(request, proj):
    # S3 key prefix "<Client Name>/<Project Title>" for a project's uploads
    owner = await pool(request).fetchrow(
        "select name, business, email from users where id=$1", proj["user_id"])
    client_name = owner and (owner["name"] or owner["business"] or owner["email"].split("@")[0])
    return f"{_slug(client_name, 'client')}/{_slug(proj['title'], 'project')}"

async def _owned_project(request, user, pid):
    row = await pool(request).fetchrow("select * from projects where id=$1", pid)
    if not row: raise HTTPException(404, "Project not found")
    if not user["is_admin"] and str(row["user_id"]) != str(user["id"]):
        raise HTTPException(403, "Not your project")
    return row

async def _owned_set(request, user, sid):
    s = await pool(request).fetchrow("select * from typography_sets where id=$1", sid)
    if not s: raise HTTPException(404, "Typography set not found")
    proj = await _owned_project(request, user, str(s["project_id"]))
    return s, proj

@app.patch("/api/projects/{pid}")
async def patch_project(pid: str, body: ProjectPatch, request: Request, user=Depends(current_user)):
    await _owned_project(request, user, pid)
    # clients may only edit brief/notes; admins may edit anything
    fields = {"brief": body.brief, "notes": body.notes}
    if user["is_admin"]:
        fields.update({"status": body.status, "web_url": body.web_url, "next_step": body.next_step})
    sets, vals = [], []
    for i, (k, v) in enumerate([(k, v) for k, v in fields.items() if v is not None], start=1):
        sets.append(f"{k}=${i}"); vals.append(v)
    if user["is_admin"]:
        sets.append("updated_at=now()")          # client's ping
    else:
        sets.append("client_updated_at=now()")   # admin's ping
    if not sets: return {"ok": True}
    vals.append(pid)
    row = await pool(request).fetchrow(
        f"update projects set {', '.join(sets)} where id=${len(vals)} returning *", *vals)
    return dict(row)

@app.put("/api/projects/{pid}/theme")
async def set_theme(pid: str, body: ThemeIn, request: Request, user=Depends(current_user)):
    await _owned_project(request, user, pid)
    col = "updated_at" if user["is_admin"] else "client_updated_at"
    row = await pool(request).fetchrow(
        f"update projects set theme=$1, {col}=now() where id=$2 returning *",
        body.model_dump(), pid)
    return dict(row)

THEME_SYSTEM = (
    "You are a senior brand and web designer. From the client's description and any reference "
    "images, propose ONE cohesive website theme. Reply with ONLY a JSON object (no markdown, no "
    "commentary) with exactly these keys: "
    '"preset" (a short human name, e.g. "Sunlit Terracotta"), '
    '"accent" (main brand colour as #rrggbb hex), '
    '"accent2" (complementary secondary colour as #rrggbb hex), '
    '"font" (one of: sans, serif, rounded, mono), '
    '"mode" (one of: auto, light, dark), '
    '"rationale" (one or two sentences). '
    "Pick tasteful, accessible colours with good contrast.")

def _extract_json(text):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j > i:
            return json.loads(text[i:j + 1])
        raise

@app.post("/api/projects/{pid}/theme/generate")
async def generate_theme(pid: str, request: Request, user=Depends(current_user),
                         prompt: str = Form(""), files: list[UploadFile] = File(default=[])):
    await _owned_project(request, user, pid)
    if not OPENROUTER_KEY:
        raise HTTPException(503, "The AI theme generator isn't set up yet (missing OPENROUTER_API_KEY).")
    prompt = (prompt or "").strip()
    parts = []
    for f in (files or [])[:6]:
        data = await f.read()
        ctype = (f.content_type or "").lower()
        if ctype not in VISION_IMG or len(data) > 5 * 1024 * 1024:
            continue   # skip oversized / unsupported images rather than fail the whole request
        b64 = base64.standard_b64encode(data).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{ctype};base64,{b64}"}})
    if not prompt and not parts:
        raise HTTPException(400, "Describe the look you want, or add a reference image.")
    parts.append({"type": "text", "text": prompt or "Suggest a website theme based on these reference images."})

    payload = {
        "model": OPENROUTER_MODEL,
        "max_tokens": 700,
        "messages": [{"role": "system", "content": THEME_SYSTEM},
                     {"role": "user", "content": parts}],
    }
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json",
               "X-Title": "ZZ Digital Portal", "HTTP-Referer": "https://portal.zzdigitaldesign.com"}
    try:
        async with httpx.AsyncClient(timeout=60) as hc:
            r = await hc.post(OPENROUTER_URL, headers=headers, json=payload)
        if r.status_code >= 400:
            raise HTTPException(502, "Theme generation failed: " + r.text[:200])
        text = r.json()["choices"][0]["message"]["content"]
        theme = _extract_json(text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, "Theme generation failed: " + str(e)[:200])

    if theme.get("font") not in ("sans", "serif", "rounded", "mono"): theme["font"] = "sans"
    if theme.get("mode") not in ("auto", "light", "dark"): theme["mode"] = "auto"
    return {k: theme.get(k) for k in ("preset", "accent", "accent2", "font", "mode", "rationale")}

# ── images ───────────────────────────────────────────────
@app.get("/api/projects/{pid}/images")
async def list_images(pid: str, request: Request, user=Depends(current_user)):
    await _owned_project(request, user, pid)
    rows = await pool(request).fetch(
        "select * from project_images where project_id=$1 order by created_at", pid)
    return [dict(r) for r in rows]

@app.post("/api/projects/{pid}/images")
async def add_image(pid: str, body: ImageIn, request: Request, user=Depends(current_user)):
    await _owned_project(request, user, pid)
    if not body.url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "URL must start with http")
    row = await pool(request).fetchrow(
        "insert into project_images(project_id,url) values($1,$2) returning *", pid, body.url)
    if not user["is_admin"]:
        await pool(request).execute("update projects set client_updated_at=now() where id=$1", pid)
    return dict(row)

@app.delete("/api/images/{iid}")
async def del_image(iid: str, request: Request, user=Depends(current_user)):
    p = pool(request)
    img = await p.fetchrow("select project_id from project_images where id=$1", iid)
    if not img: raise HTTPException(404, "Not found")
    await _owned_project(request, user, str(img["project_id"]))
    await p.execute("delete from project_images where id=$1", iid)
    return {"ok": True}

@app.post("/api/projects/{pid}/upload")
async def upload_images(pid: str, request: Request, user=Depends(current_user), files: list[UploadFile] = File(...)):
    proj = await _owned_project(request, user, pid)
    prefix = await _project_prefix(request, proj)
    existing = await pool(request).fetch(
        "select url from project_images where project_id=$1", pid)
    taken = _taken_names(existing)
    stored = await _put_images(files, prefix, taken)
    saved = []
    for _base, url in stored:
        row = await pool(request).fetchrow(
            "insert into project_images(project_id,url) values($1,$2) returning *", pid, url)
        saved.append(dict(row))
    if not user["is_admin"]:
        await pool(request).execute("update projects set client_updated_at=now() where id=$1", pid)
    return saved

# ── typography (a website-project perk) ──────────────────
# Client makes named "sets" (one per thing) and uploads reference images;
# the studio delivers back result images + typography notes per set.
async def _set_with_images(request, s):
    imgs = await pool(request).fetch(
        "select * from typography_images where set_id=$1 order by created_at", s["id"])
    d = dict(s)
    d["reference"] = [dict(i) for i in imgs if i["role"] == "reference"]
    d["result"]    = [dict(i) for i in imgs if i["role"] == "result"]
    return d

@app.get("/api/projects/{pid}/typography")
async def list_typography(pid: str, request: Request, user=Depends(current_user)):
    await _owned_project(request, user, pid)
    sets = await pool(request).fetch(
        "select * from typography_sets where project_id=$1 order by created_at", pid)
    return [await _set_with_images(request, s) for s in sets]

@app.post("/api/projects/{pid}/typography")
async def create_typography(pid: str, body: TypoSetIn, request: Request, user=Depends(current_user)):
    await _owned_project(request, user, pid)
    if not (body.title or "").strip():
        raise HTTPException(400, "Give the set a name")
    row = await pool(request).fetchrow(
        "insert into typography_sets(project_id,title,brief) values($1,$2,$3) returning *",
        pid, body.title.strip(), body.brief)
    col = "updated_at" if user["is_admin"] else "client_updated_at"
    await pool(request).execute(f"update projects set {col}=now() where id=$1", pid)
    return await _set_with_images(request, row)

@app.patch("/api/typography/{sid}")
async def patch_typography(sid: str, body: TypoSetPatch, request: Request, user=Depends(current_user)):
    s, proj = await _owned_set(request, user, sid)
    # clients own title/brief (their request); the studio owns notes/status/title
    allowed = ("title", "brief", "notes", "status") if user["is_admin"] else ("title", "brief")
    fields = {k: getattr(body, k) for k in allowed if getattr(body, k) is not None}
    if not fields:
        return await _set_with_images(request, s)
    sets, vals = [], []
    for k, v in fields.items():
        vals.append(v); sets.append(f"{k}=${len(vals)}")
    sets.append("updated_at=now()" if user["is_admin"] else "client_updated_at=now()")
    vals.append(sid)
    row = await pool(request).fetchrow(
        f"update typography_sets set {', '.join(sets)} where id=${len(vals)} returning *", *vals)
    col = "updated_at" if user["is_admin"] else "client_updated_at"
    await pool(request).execute(f"update projects set {col}=now() where id=$1", proj["id"])
    return await _set_with_images(request, row)

@app.delete("/api/typography/{sid}")
async def del_typography(sid: str, request: Request, user=Depends(current_user)):
    await _owned_set(request, user, sid)
    await pool(request).execute("delete from typography_sets where id=$1", sid)
    return {"ok": True}

@app.post("/api/typography/{sid}/upload")
async def upload_typography(sid: str, request: Request, user=Depends(current_user), files: list[UploadFile] = File(...)):
    s, proj = await _owned_set(request, user, sid)
    role = "result" if user["is_admin"] else "reference"   # studio delivers results; client sends references
    prefix = await _project_prefix(request, proj)
    set_folder = _slug(s["title"], str(s["id"])[:8])
    key_prefix = f"{prefix}/typography/{set_folder}/{role}"
    existing = await pool(request).fetch(
        "select url from typography_images where set_id=$1 and role=$2", sid, role)
    stored = await _put_images(files, key_prefix, _taken_names(existing))
    saved = []
    for _base, url in stored:
        row = await pool(request).fetchrow(
            "insert into typography_images(set_id,url,role) values($1,$2,$3) returning *", sid, url, role)
        saved.append(dict(row))
    col = "updated_at" if user["is_admin"] else "client_updated_at"
    await pool(request).execute(f"update typography_sets set {col}=now() where id=$1", sid)
    await pool(request).execute(f"update projects set {col}=now() where id=$1", proj["id"])
    return saved

@app.delete("/api/typography-images/{iid}")
async def del_typography_image(iid: str, request: Request, user=Depends(current_user)):
    img = await pool(request).fetchrow("select set_id from typography_images where id=$1", iid)
    if not img: raise HTTPException(404, "Not found")
    await _owned_set(request, user, str(img["set_id"]))
    await pool(request).execute("delete from typography_images where id=$1", iid)
    return {"ok": True}

# ── messages ─────────────────────────────────────────────
@app.get("/api/projects/{pid}/messages")
async def list_messages(pid: str, request: Request, user=Depends(current_user)):
    await _owned_project(request, user, pid)
    rows = await pool(request).fetch(
        "select * from support_messages where project_id=$1 order by created_at", pid)
    return [dict(r) for r in rows]

@app.post("/api/projects/{pid}/messages")
async def add_message(pid: str, body: MessageIn, request: Request, user=Depends(current_user)):
    proj = await _owned_project(request, user, pid)
    sender = "studio" if user["is_admin"] else "client"
    row = await pool(request).fetchrow(
        "insert into support_messages(user_id,project_id,sender,body) values($1,$2,$3,$4) returning *",
        proj["user_id"], pid, sender, body.body)
    col = "updated_at" if sender == "studio" else "client_updated_at"
    await pool(request).execute(f"update projects set {col}=now() where id=$1", pid)
    return dict(row)

# ── admin ────────────────────────────────────────────────
@app.get("/api/clients")
async def list_clients(request: Request, admin=Depends(require_admin)):
    rows = await pool(request).fetch(
        """select u.id, u.name, u.business, u.email, u.created_at,
                  (select max(p.client_updated_at) from projects p where p.user_id = u.id) as client_activity
           from users u where u.is_admin = false order by u.created_at""")
    return [dict(r) for r in rows]

@app.get("/api/health")
async def health(request: Request):
    await pool(request).fetchval("select 1")
    return {"ok": True}

# ── serve the portal + admin static files ────────────────
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
_STATIC = os.environ.get("STATIC_DIR", "static")   # Docker copies the portal/ folder here

@app.get("/")
def _root():
    return RedirectResponse("/portal/")

if os.path.isdir(_STATIC):
    # /portal/ -> static/index.html, /portal/admin/ -> static/admin/index.html
    app.mount("/portal", StaticFiles(directory=_STATIC, html=True), name="portal")
