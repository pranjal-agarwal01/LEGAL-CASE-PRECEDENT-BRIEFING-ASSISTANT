"""Keep Precedent running on Render's free Postgres, which expires 30 days after it is created.

Commands (run by the GitHub Actions in .github/workflows, or by hand):

    python scripts/ops/render_db.py status
    python scripts/ops/render_db.py due                    # prints due=true|false (and to $GITHUB_OUTPUT)
    python scripts/ops/render_db.py backup --out backup.json
    python scripts/ops/render_db.py rotate --backup backup.json
    python scripts/ops/render_db.py restore --file backup.json [--url postgresql://...]

`rotate` deletes the current free database (only one may exist), creates a new one, points the web
service's DATABASE_URL at it, redeploys, waits until the app has created its tables, then restores the
backup. The law library is not in the backup: the app reloads it from LIBRARY_SEED_URL by itself.

Environment:
    RENDER_API_KEY      Render API key (Account settings -> API keys)
    RENDER_SERVICE_ID   the web service id (srv-...)
    RENDER_DB_NAME      database name on Render (default precedent-india-db)
    RENDER_REGION       default frankfurt
    APP_URL             the app's public URL, used to wait for /api/health
    ROTATE_DAYS_LEFT    rotate when the database expires within this many days (default 5)

Only the standard library, SQLAlchemy and psycopg are needed.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

API = "https://api.render.com/v1"
# The firm's own work, in foreign-key order. Library tables are rebuilt from the library file instead.
TABLES = ["firms", "users", "matters", "runs", "authorities", "authority_passages", "audit_events"]


# ------------------------------------------------------------------------------------------ Render API
def _api(method: str, path: str, body: dict | None = None):
    key = os.environ.get("RENDER_API_KEY", "")
    if not key:
        raise SystemExit("RENDER_API_KEY is not set.")
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Render API {method} {path}: HTTP {e.code} {e.read()[:400]!r}") from e
    return json.loads(raw) if raw else None


def db_name() -> str:
    return os.environ.get("RENDER_DB_NAME", "precedent-india-db")


def owner_id() -> str:
    """The workspace that owns the web service: the database lives there too, even if the API key reaches others."""
    service = os.environ.get("RENDER_SERVICE_ID", "")
    if not service:
        raise SystemExit("RENDER_SERVICE_ID is not set.")
    return _api("GET", f"/services/{service}")["ownerId"]


def find_db() -> dict | None:
    owner = owner_id()
    rows = _api("GET", f"/postgres?name={db_name()}&ownerId={owner}&limit=20") or []
    dbs = [r["postgres"] for r in rows if r.get("postgres", {}).get("name") == db_name()
           and r["postgres"].get("owner", {}).get("id", owner) == owner]
    dbs.sort(key=lambda d: d["createdAt"], reverse=True)
    return dbs[0] if dbs else None


def connection(db_id: str) -> dict:
    return _api("GET", f"/postgres/{db_id}/connection-info")


def days_left(db: dict) -> float | None:
    exp = db.get("expiresAt")
    if not exp:
        return None
    t = datetime.fromisoformat(exp.replace("Z", "+00:00"))
    return (t - datetime.now(timezone.utc)).total_seconds() / 86400


def is_due(db: dict | None) -> bool:
    if db is None:
        return True
    left = days_left(db)
    return left is not None and left <= float(os.environ.get("ROTATE_DAYS_LEFT", "5"))


# ------------------------------------------------------------------------------------------ backup
def _engine(url: str):
    from sqlalchemy import create_engine

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return create_engine(url, pool_pre_ping=True)


def _plain(v):
    if isinstance(v, (datetime, date)):
        return {"__dt__": v.isoformat()}
    if isinstance(v, (bytes, memoryview)):
        return {"__b64__": base64.b64encode(bytes(v)).decode()}
    return v


def _unplain(v):
    if isinstance(v, dict) and "__dt__" in v:
        return datetime.fromisoformat(v["__dt__"])
    if isinstance(v, dict) and "__b64__" in v:
        return base64.b64decode(v["__b64__"])
    return v


def backup(url: str, out: str) -> dict:
    from sqlalchemy import MetaData, select

    eng = _engine(url)
    meta = MetaData()
    meta.reflect(eng, only=[t for t in TABLES if eng.dialect.has_table(eng.connect(), t)])
    data: dict = {"format": "precedent-backup/1", "taken": datetime.now(timezone.utc).isoformat(), "tables": {}}
    with eng.connect() as c:
        for t in TABLES:
            if t not in meta.tables:
                continue
            rows = c.execute(select(meta.tables[t])).mappings().all()
            data["tables"][t] = [{k: _plain(v) for k, v in r.items()} for r in rows]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f)
    counts = {t: len(r) for t, r in data["tables"].items()}
    print(f"backup written to {out}: {counts}")
    return counts


def restore(url: str, path: str, wait_seconds: int = 600) -> None:
    from sqlalchemy import MetaData, func, inspect, select, text

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    eng = _engine(url)
    deadline = time.time() + wait_seconds
    while True:  # the app creates the tables on its first start
        missing = [t for t in data["tables"] if t not in inspect(eng).get_table_names()]
        if not missing:
            break
        if time.time() > deadline:
            raise SystemExit(f"tables still missing after {wait_seconds}s: {missing}")
        time.sleep(10)
    meta = MetaData()
    meta.reflect(eng, only=list(data["tables"]))
    with eng.begin() as c:
        for t in TABLES:
            rows = data["tables"].get(t)
            if not rows:
                continue
            table = meta.tables[t]
            if c.execute(select(func.count()).select_from(table)).scalar_one():
                print(f"{t}: already has rows, skipped")
                continue
            cols = set(table.c.keys())
            c.execute(table.insert(), [{k: _unplain(v) for k, v in r.items() if k in cols} for r in rows])
            if eng.dialect.name == "postgresql" and "id" in cols:
                c.execute(text(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                               f"(SELECT coalesce(max(id), 1) FROM {t}))"))
            print(f"{t}: restored {len(rows)} rows")


# ------------------------------------------------------------------------------------------ rotate
def wait_for(db_id: str, minutes: int = 15) -> dict:
    for _ in range(minutes * 4):
        db = _api("GET", f"/postgres/{db_id}")
        if db.get("status") == "available":
            return db
        time.sleep(15)
    raise SystemExit(f"database {db_id} was not available after {minutes} minutes")


def wait_healthy(minutes: int = 15) -> None:
    url = os.environ.get("APP_URL", "").rstrip("/")
    if not url:
        return
    for _ in range(minutes * 4):
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=30) as r:
                if r.status == 200:
                    return
        except Exception:  # noqa: BLE001 - still deploying
            pass
        time.sleep(15)
    print("warning: the app did not answer /api/health in time; continuing", file=sys.stderr)


def rotate(backup_path: str | None, force: bool = False) -> None:
    service = os.environ.get("RENDER_SERVICE_ID", "")
    if not service:
        raise SystemExit("RENDER_SERVICE_ID is not set.")
    old = find_db()
    if old and not force and not is_due(old):
        print(f"{old['name']} has {days_left(old):.1f} days left; nothing to do")
        return
    if old:
        if backup_path and not os.path.exists(backup_path):
            backup(connection(old["id"])["externalConnectionString"], backup_path)
        print(f"deleting {old['name']} ({old['id']})")
        _api("DELETE", f"/postgres/{old['id']}")
        time.sleep(20)
    new = _api("POST", "/postgres", {
        "name": db_name(), "ownerId": owner_id(), "plan": "free", "version": "16",
        "region": os.environ.get("RENDER_REGION", "frankfurt"), "databaseName": "precedent", "databaseUser": "precedent",
        # The restore runs from GitHub's servers, so the database must accept outside connections (TLS + password).
        "ipAllowList": [{"cidrBlock": "0.0.0.0/0", "description": "restore from GitHub Actions"}],
    })
    db_id = new["id"]
    print(f"created {db_id}; waiting until it is available")
    wait_for(db_id)
    info = connection(db_id)
    _api("PUT", f"/services/{service}/env-vars/DATABASE_URL", {"value": info["internalConnectionString"]})
    _api("POST", f"/services/{service}/deploys", {"deployMode": "deploy_only"})
    print("DATABASE_URL updated; redeploying")
    wait_healthy()
    if backup_path and os.path.exists(backup_path):
        restore(info["externalConnectionString"], backup_path)
    print("rotation finished")


# ------------------------------------------------------------------------------------------ cli
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("due")
    b = sub.add_parser("backup")
    b.add_argument("--out", required=True)
    b.add_argument("--url", default="")
    r = sub.add_parser("restore")
    r.add_argument("--file", required=True)
    r.add_argument("--url", default="")
    ro = sub.add_parser("rotate")
    ro.add_argument("--backup", default="backup.json")
    ro.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "status":
        db = find_db()
        if not db:
            print("no database named", db_name())
        else:
            print(f"{db['name']} {db['id']} status={db['status']} plan={db['plan']} created={db['createdAt']} "
                  f"expires={db.get('expiresAt')} days_left={days_left(db)}")
    elif a.cmd == "due":
        due = is_due(find_db())
        print(f"due={'true' if due else 'false'}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
                f.write(f"due={'true' if due else 'false'}\n")
    elif a.cmd == "backup":
        url = a.url
        if not url:
            db = find_db()
            if not db:
                raise SystemExit("no database to back up")
            url = connection(db["id"])["externalConnectionString"]
        backup(url, a.out)
    elif a.cmd == "restore":
        url = a.url or connection(find_db()["id"])["externalConnectionString"]
        restore(url, a.file)
    elif a.cmd == "rotate":
        rotate(a.backup, a.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
