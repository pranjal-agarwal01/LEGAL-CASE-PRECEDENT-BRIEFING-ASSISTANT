"""FastAPI application: JSON API under /api and the built web UI (web/dist) at /.

    uvicorn legal_brief.web.app:app --reload        (development)
    uvicorn legal_brief.web.app:app --host 0.0.0.0 --port $PORT   (Render)
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from legal_brief.config import PROJECT_ROOT, Settings
from legal_brief.corpus import KIND_LABELS
from legal_brief.doctrines import AREA_LABELS, DOCTRINES
from legal_brief.ingest import UnsupportedFile, extract_text
from legal_brief.web import export
from legal_brief.web.db import (AuditEvent, Authority, Firm, Matter, Run, User, audit, get_session, init_db)
from legal_brief.web.jobs import JobManager, runs_today
from legal_brief.web.library import LibraryManager, upload_id
from legal_brief.web.security import (SESSION_COOKIE, SESSION_DAYS, hash_password, login_limiter, make_token,
                                      password_problem, read_token, verify_password)

log = logging.getLogger("legal_brief.web")
DIST = Path(os.environ.get("WEB_DIST", PROJECT_ROOT / "web" / "dist"))
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_MB", "15")) * 1024 * 1024
RUNS_PER_DAY = int(os.environ.get("RUNS_PER_FIRM_PER_DAY", "40"))
ALLOW_SIGNUP = os.environ.get("ALLOW_SIGNUP", "true").lower() in {"1", "true", "yes"}
SECURE_COOKIES = bool(os.environ.get("RENDER")) or os.environ.get("SECURE_COOKIES", "").lower() == "true"


def web_settings() -> Settings:
    s = Settings.from_env()
    return s.with_overrides(include_legislation=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    init_db()
    settings = web_settings()
    app.state.settings = settings
    app.state.library = LibraryManager(settings)
    app.state.jobs = JobManager(settings, app.state.library, int(os.environ.get("MAX_CONCURRENT_RUNS", "2")))
    app.state.jobs.recover()
    app.state.jobs.bind_loop()
    import asyncio

    warm = asyncio.get_running_loop().run_in_executor(None, app.state.library.warm)
    yield
    warm.cancel()


app = FastAPI(title="Precedent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")


# --------------------------------------------------------------------------------------------- plumbing
@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Mutating API calls must come from our own UI (custom header => no cross-site form posts).
    if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("x-requested-with") != "precedent":
            return JSONResponse({"detail": "Missing request header."}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def db_session():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(db_session)) -> User:
    tok = request.cookies.get(SESSION_COOKIE)
    parsed = read_token(tok) if tok else None
    if not parsed:
        raise HTTPException(401, "Please sign in.")
    user = db.get(User, parsed[0])
    if not user or not user.active or user.token_version != parsed[1]:
        raise HTTPException(401, "Please sign in.")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Only a firm administrator can do this.")
    return user


def _set_session(response: Response, user: User) -> None:
    response.set_cookie(SESSION_COOKIE, make_token(user.id, user.token_version), max_age=SESSION_DAYS * 86400,
                        httponly=True, secure=SECURE_COOKIES, samesite="lax", path="/")


def _owned(db: Session, model, obj_id: int, user: User):
    obj = db.get(model, obj_id)
    if not obj or obj.firm_id != user.firm_id:
        raise HTTPException(404, "Not found.")
    return obj


def iso(dt: datetime | None) -> str | None:
    """UTC timestamps with an explicit offset (SQLite returns naive datetimes)."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def user_json(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "firm_id": u.firm_id,
            "firm": u.firm.name, "must_change_password": u.must_change_password,
            "include_summaries": u.firm.include_summaries}


# ------------------------------------------------------------------------------------------------- auth
class SignupIn(BaseModel):
    firm_name: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta(request: Request):
    s: Settings = request.app.state.settings
    lib = request.app.state.library
    base = lib.base(True)
    acts = [j for j in base.judgments if j.is_legislation]
    return {
        "signup": ALLOW_SIGNUP, "model": s.model if s.uses_llm else None, "provider": s.provider,
        "llm_ready": s.uses_llm, "search_mode": lib.search_mode, "runs_per_day": RUNS_PER_DAY,
        "practice_areas": [{"key": k, "label": v} for k, v in AREA_LABELS.items()],
        "doctrines": [{"key": d.key, "label": d.label, "area": d.area} for d in DOCTRINES.values()],
        "library": {"statutes": len(acts), "statute_passages": sum(len(a.passages) for a in acts),
                    "summaries": len([j for j in base.judgments if j.kind == "summary"]),
                    "legislation_imported": base.meta.get("imported")},
    }


@app.post("/api/auth/signup")
def signup(body: SignupIn, response: Response, db: Session = Depends(db_session)):
    if not ALLOW_SIGNUP:
        raise HTTPException(403, "Sign-up is closed. Ask your firm administrator for an account.")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(422, problem)
    email = body.email.lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise HTTPException(409, "An account with this email already exists.")
    firm = Firm(name=body.firm_name.strip())
    db.add(firm)
    db.flush()
    user = User(firm_id=firm.id, email=email, name=body.name.strip(), password_hash=hash_password(body.password),
                role="admin", last_login=datetime.now(timezone.utc))
    db.add(user)
    db.flush()
    audit(db, firm.id, user.id, "firm.created", firm.name)
    db.commit()
    db.refresh(user)
    _set_session(response, user)
    return user_json(user)


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(db_session)):
    ip = request.client.host if request.client else "?"
    if not login_limiter.allow(ip) or not login_limiter.allow("email:" + body.email.lower()):
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    user = db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect.")
    user.last_login = datetime.now(timezone.utc)
    audit(db, user.firm_id, user.id, "user.login")
    db.commit()
    _set_session(response, user)
    return user_json(user)


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return user_json(user)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


@app.post("/api/auth/password")
def change_password(body: PasswordIn, response: Response, user: User = Depends(current_user),
                    db: Session = Depends(db_session)):
    user = db.get(User, user.id)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(422, problem)
    user.password_hash, user.must_change_password = hash_password(body.new_password), False
    user.token_version += 1  # signs out other sessions
    audit(db, user.firm_id, user.id, "user.password_changed")
    db.commit()
    _set_session(response, user)
    return {"ok": True}


# ------------------------------------------------------------------------------------------------- team
class MemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    role: str = "member"

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in ("admin", "member"):
            raise ValueError("role must be admin or member")
        return v


@app.get("/api/team")
def team(user: User = Depends(current_user), db: Session = Depends(db_session)):
    rows = db.execute(select(User).where(User.firm_id == user.firm_id).order_by(User.created_at)).scalars()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role, "active": u.active,
             "last_login": iso(u.last_login) if u.last_login else None} for u in rows]


@app.post("/api/team")
def add_member(body: MemberIn, admin: User = Depends(admin_user), db: Session = Depends(db_session)):
    email = body.email.lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise HTTPException(409, "That email already has an account.")
    temp = secrets.token_urlsafe(9) + "A7"
    u = User(firm_id=admin.firm_id, email=email, name=body.name.strip(), role=body.role,
             password_hash=hash_password(temp), must_change_password=True)
    db.add(u)
    audit(db, admin.firm_id, admin.id, "team.added", email)
    db.commit()
    return {"id": u.id, "email": u.email, "temporary_password": temp}


@app.delete("/api/team/{member_id}")
def remove_member(member_id: int, admin: User = Depends(admin_user), db: Session = Depends(db_session)):
    u = _owned(db, User, member_id, admin)
    if u.id == admin.id:
        raise HTTPException(400, "You cannot remove yourself.")
    u.active, u.token_version = False, u.token_version + 1
    audit(db, admin.firm_id, admin.id, "team.removed", u.email)
    db.commit()
    return {"ok": True}


class FirmIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    include_summaries: bool | None = None


@app.patch("/api/firm")
def update_firm(body: FirmIn, admin: User = Depends(admin_user), db: Session = Depends(db_session)):
    firm = db.get(Firm, admin.firm_id)
    if body.name:
        firm.name = body.name.strip()
    if body.include_summaries is not None:
        firm.include_summaries = body.include_summaries
    audit(db, firm.id, admin.id, "firm.updated", body.model_dump_json(exclude_none=True))
    db.commit()
    return {"ok": True}


@app.get("/api/audit")
def audit_log(admin: User = Depends(admin_user), db: Session = Depends(db_session)):
    rows = db.execute(select(AuditEvent, User.name).outerjoin(User, User.id == AuditEvent.user_id)
                      .where(AuditEvent.firm_id == admin.firm_id).order_by(AuditEvent.at.desc()).limit(200)).all()
    return [{"at": iso(e.at), "user": name, "action": e.action, "detail": e.detail} for e, name in rows]


# ---------------------------------------------------------------------------------------------- matters
class MatterIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    reference: str = Field(default="", max_length=80)
    client_name: str = Field(min_length=1, max_length=200)
    client_role: str = "claimant"
    opponent: str = Field(default="", max_length=300)
    practice_area: str = Field(default="", max_length=40)
    facts: str = Field(default="", max_length=60000)
    objective: str = Field(default="", max_length=6000)

    @field_validator("client_role")
    @classmethod
    def _role(cls, v):
        if v not in ("claimant", "defendant"):
            raise ValueError("client_role must be claimant or defendant")
        return v


class MatterPatch(MatterIn):
    title: str | None = Field(default=None, max_length=300)  # type: ignore[assignment]
    client_name: str | None = Field(default=None, max_length=200)  # type: ignore[assignment]
    client_role: str | None = None  # type: ignore[assignment]


_DATE_RE = re.compile(r"\b(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|"
                      r"November|December) (\d{4})\b")


def deadlines(result: dict | None) -> list[dict]:
    """Dated time limits from a brief's next steps (dates the brief states, e.g. '... by 2 June 2026')."""
    out = []
    for st in ((result or {}).get("brief") or {}).get("time_limits", []):
        if st.get("support") != "supported":  # only deadlines verified against their provision are diarised
            continue
        dates = []
        for d, mon, y in _DATE_RE.findall(st.get("text", "")):
            try:
                dates.append(datetime.strptime(f"{d} {mon} {y}", "%d %B %Y").date())
            except ValueError:
                continue
        if dates:  # the deadline is the latest date in the statement; earlier ones are start dates
            out.append({"date": max(dates).isoformat(), "text": st["text"], "support": st.get("support", "unchecked")})
    return sorted(out, key=lambda x: x["date"])


def matter_json(m: Matter, last: Run | None = None, author: str | None = None) -> dict:
    out = {k: getattr(m, k) for k in ("id", "reference", "title", "client_name", "client_role", "opponent",
                                      "practice_area", "facts", "objective")}
    out.update(created_at=iso(m.created_at), updated_at=iso(m.updated_at), created_by=author)
    if last is not None:
        res = last.result or {}
        out["last_run"] = {"id": last.id, "status": last.status, "created_at": iso(last.created_at),
                           "issues": len((res.get("brief") or {}).get("issues", [])),
                           "unsupported": (res.get("support_report") or {}).get("unsupported", 0),
                           "deadlines": deadlines(res) if last.status == "done" else []}
    return out


@app.get("/api/matters")
def list_matters(user: User = Depends(current_user), db: Session = Depends(db_session)):
    matters = db.execute(select(Matter, User.name).outerjoin(User, User.id == Matter.created_by)
                         .where(Matter.firm_id == user.firm_id).order_by(Matter.updated_at.desc())).all()
    last_ids = dict(db.execute(select(Run.matter_id, func.max(Run.id)).where(Run.firm_id == user.firm_id)
                               .group_by(Run.matter_id)).all())
    runs = {r.matter_id: r for r in db.execute(select(Run).where(Run.id.in_(list(last_ids.values())))).scalars()} \
        if last_ids else {}
    out = []
    for m, author in matters:
        j = matter_json(m, runs.get(m.id), author)
        j.pop("facts")
        j.pop("objective")
        out.append(j)
    return out


@app.post("/api/matters")
def create_matter(body: MatterIn, user: User = Depends(current_user), db: Session = Depends(db_session)):
    m = Matter(firm_id=user.firm_id, created_by=user.id, **body.model_dump())
    db.add(m)
    db.flush()
    audit(db, user.firm_id, user.id, "matter.created", f"{m.id} {m.title}")
    db.commit()
    return matter_json(m, author=user.name)


@app.get("/api/matters/{matter_id}")
def get_matter(matter_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    m = _owned(db, Matter, matter_id, user)
    runs = db.execute(select(Run).where(Run.matter_id == m.id).order_by(Run.id.desc())).scalars().all()
    out = matter_json(m, runs[0] if runs else None)
    out["runs"] = [{"id": r.id, "status": r.status, "created_at": iso(r.created_at), "seconds": r.seconds,
                    "model": r.model} for r in runs]
    return out


@app.patch("/api/matters/{matter_id}")
def update_matter(matter_id: int, body: MatterPatch, user: User = Depends(current_user),
                  db: Session = Depends(db_session)):
    m = _owned(db, Matter, matter_id, user)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(m, k, v)
    m.updated_at = datetime.now(timezone.utc)
    db.commit()
    return matter_json(m)


@app.delete("/api/matters/{matter_id}")
def delete_matter(matter_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    m = _owned(db, Matter, matter_id, user)
    db.execute(delete(Run).where(Run.matter_id == m.id))
    db.delete(m)
    audit(db, user.firm_id, user.id, "matter.deleted", f"{matter_id} {m.title}")
    db.commit()
    return {"ok": True}


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"Files are limited to {MAX_UPLOAD // (1024 * 1024)} MB.")
    if not data:
        raise HTTPException(400, "The file is empty.")
    return data


@app.post("/api/extract-text")
async def extract(file: UploadFile = File(...), user: User = Depends(current_user)):
    """Read a client document (instructions, witness statement) so its text can be edited into the facts."""
    data = await _read_upload(file)
    try:
        text = extract_text(file.filename or "upload", data)
    except UnsupportedFile as e:
        raise HTTPException(415, str(e)) from e
    return {"text": text[:60000], "truncated": len(text) > 60000}


# ------------------------------------------------------------------------------------------------- runs
class RunIn(BaseModel):
    rounds: int = Field(default=2, ge=1, le=3)


@app.post("/api/matters/{matter_id}/runs")
def start_run(matter_id: int, body: RunIn, request: Request, user: User = Depends(current_user),
              db: Session = Depends(db_session)):
    m = _owned(db, Matter, matter_id, user)
    if len(m.facts.split()) < 25:
        raise HTTPException(422, "Add the facts first (at least a short paragraph).")
    if runs_today(db, user.firm_id) >= RUNS_PER_DAY:
        raise HTTPException(429, f"Your firm has reached today's limit of {RUNS_PER_DAY} briefs.")
    s: Settings = request.app.state.settings
    run = Run(firm_id=user.firm_id, matter_id=m.id, created_by=user.id, rounds=body.rounds,
              model=f"{s.provider}:{s.model}" if s.uses_llm else "offline")
    db.add(run)
    db.flush()
    audit(db, user.firm_id, user.id, "run.started", f"matter {m.id} run {run.id}")
    db.commit()
    request.app.state.jobs.start_run(run.id)
    return {"id": run.id, "status": run.status}


@app.get("/api/runs/{run_id}")
def get_run(run_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(db_session)):
    r = _owned(db, Run, run_id, user)
    return {"id": r.id, "matter_id": r.matter_id, "status": r.status, "error": r.error, "model": r.model,
            "rounds": r.rounds, "events": request.app.state.jobs.events(r), "result": r.result,
            "seconds": r.seconds, "llm_calls": r.llm_calls, "created_at": iso(r.created_at)}


def _run_for_export(db, run_id, user):
    r = _owned(db, Run, run_id, user)
    if r.status != "done" or not r.result:
        raise HTTPException(409, "This brief is not finished.")
    m = db.get(Matter, r.matter_id)
    return {k: getattr(m, k) for k in ("title", "client_name", "client_role", "opponent")}, r.result


def _filename(title: str, ext: str) -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:60] or "brief") + ext


@app.get("/api/runs/{run_id}/export.docx")
def export_docx(run_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    matter, result = _run_for_export(db, run_id, user)
    data = export.to_docx(matter, result)
    audit(db, user.firm_id, user.id, "run.exported", f"run {run_id} docx")
    db.commit()
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{_filename(matter["title"], ".docx")}"'})


@app.get("/api/runs/{run_id}/export.md")
def export_md(run_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    matter, result = _run_for_export(db, run_id, user)
    return Response(export.to_markdown(matter, result), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{_filename(matter["title"], ".md")}"'})


# ---------------------------------------------------------------------------------------------- library
@app.get("/api/library")
def library(request: Request, user: User = Depends(current_user), db: Session = Depends(db_session)):
    lib: LibraryManager = request.app.state.library
    base = lib.base(True)
    items = [{"id": j.id, "kind": j.kind, "name": j.name, "citation": j.citation, "court": j.court,
              "year": j.year, "areas": j.area.split(","), "passages": len(j.passages), "url": j.url,
              "date": j.date, "doctrines": list(j.doctrines)} for j in base.judgments]
    uploads = db.execute(select(Authority, User.name).outerjoin(User, User.id == Authority.uploaded_by)
                         .where(Authority.firm_id == user.firm_id).order_by(Authority.id.desc())).all()
    items = [{"id": upload_id(a.id), "kind": "judgment", "name": a.name or a.filename, "citation": a.citation,
              "court": a.court, "year": int(a.date[:4]) if a.date[:4].isdigit() else None, "areas": [a.area],
              "passages": a.n_passages, "status": a.status, "error": a.error, "date": a.date,
              "doctrines": list(a.doctrines or {}), "uploaded_by": name, "filename": a.filename,
              "created_at": iso(a.created_at)} for a, name in uploads] + items
    return {"items": items, "meta": base.meta, "kinds": KIND_LABELS}


@app.get("/api/library/search")
def library_search(q: str, request: Request, kind: str = "", user: User = Depends(current_user),
                   db: Session = Depends(db_session)):
    if len(q.strip()) < 3:
        return []
    firm = db.get(Firm, user.firm_id)
    r = request.app.state.library.retriever(user.firm_id, firm.include_summaries)
    hits = r.search(q[:500], top_k=12, kinds=(kind,) if kind else None)
    out = []
    for h in hits:
        j = r.corpus.get(h.judgment_id)
        out.append({"id": j.id, "kind": j.kind, "name": j.name, "citation": j.citation, "score": round(h.score, 3),
                    "passages": [{"ref": p.ref, "label": r.corpus.passage(p.ref).display,
                                  "text": r.corpus.passage(p.ref).text[:700]} for p in h.passages[:2]]})
    return out


@app.get("/api/library/{authority_id}")
def library_item(authority_id: str, request: Request, user: User = Depends(current_user),
                 db: Session = Depends(db_session)):
    lib: LibraryManager = request.app.state.library
    if authority_id.startswith("U"):
        a = _owned(db, Authority, int(authority_id[1:]) if authority_id[1:].isdigit() else -1, user)
        return {"id": authority_id, "kind": "judgment", "name": a.name, "citation": a.citation, "court": a.court,
                "date": a.date, "summary": a.summary, "doctrines": a.doctrines, "status": a.status,
                "note": "Uploaded by your firm.", "url": a.url,
                "passages": [{"pid": p.pid, "label": p.label, "text": p.text} for p in a.passages]}
    j = lib.base(True).get(authority_id)
    if not j:
        raise HTTPException(404, "Not found.")
    return {"id": j.id, "kind": j.kind, "name": j.name, "citation": j.citation, "court": j.court, "date": j.date,
            "summary": j.summary, "doctrines": j.doctrines, "note": j.source_note, "url": j.url,
            "passages": [{"pid": p.pid, "label": p.display, "title": p.title, "text": p.text} for p in j.passages]}


@app.post("/api/library/upload")
async def upload_judgment(request: Request, file: UploadFile = File(...), user: User = Depends(current_user)):
    data = await _read_upload(file)
    try:
        text = extract_text(file.filename or "upload", data)
    except UnsupportedFile as e:
        raise HTTPException(415, str(e)) from e
    if len(text.split()) < 150:
        raise HTTPException(422, "That document is too short to be a judgment.")
    with get_session() as db:
        a = Authority(firm_id=user.firm_id, uploaded_by=user.id, filename=(file.filename or "upload")[:300],
                      status="processing")
        db.add(a)
        db.flush()
        audit(db, user.firm_id, user.id, "library.uploaded", f"{a.id} {a.filename}")
        db.commit()
        aid = a.id
    request.app.state.jobs.start_upload(aid, text)
    return {"id": upload_id(aid), "status": "processing"}


@app.delete("/api/library/{authority_id}")
def delete_upload(authority_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    if not authority_id.startswith("U") or not authority_id[1:].isdigit():
        raise HTTPException(400, "Only judgments your firm uploaded can be removed.")
    a = _owned(db, Authority, int(authority_id[1:]), user)
    db.delete(a)
    audit(db, user.firm_id, user.id, "library.deleted", f"{authority_id} {a.name}")
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------------------------- web UI
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not found.")
    candidate = (DIST / path).resolve()
    if path and candidate.is_file() and DIST.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = DIST / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "The web UI has not been built. Run: cd web && npm install && npm run build"},
                        status_code=503)
