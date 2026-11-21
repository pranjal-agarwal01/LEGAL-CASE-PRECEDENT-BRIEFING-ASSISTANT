"""The web API end to end, offline (no model), on a temporary SQLite database.

The shared library is loaded from the committed sample library file, the same way the deployed app loads
the full Indian library into a new database (LIBRARY_SEED_URL)."""

import os
import time

import pytest

from legal_brief.config import PROJECT_ROOT

FACTS = """1. Meena Sharma owns a shop on the ground floor of her building in Lajpat Nagar, New Delhi. Bansal Traders has been her tenant since 1996 at a rent of Rs 3,500 a month.
2. Her son completed a pharmacy degree in 2023 and needs the shop to start a chemist's business. The family owns no other commercial premises in Delhi.
3. In 2024 she filed an eviction petition before the Rent Controller under section 14(1)(e) of the Delhi Rent Control Act, 1958, on the ground of bona fide requirement.
4. The tenant says the requirement is a pretext to raise the rent and has applied for leave to defend."""

JUDGMENT = "\n".join(
    ["IN THE HIGH COURT OF DELHI AT NEW DELHI", "RC.REV. 123/2024", "Date of decision: 12 March 2024", "",
     "Anil Kapoor v Sunil Mehta", ""]
    + [f"{n}. Under section 14(1)(e) of the Delhi Rent Control Act, 1958 the landlord's bona fide requirement of the "
       f"premises for a member of the family dependent on him is presumed unless the tenant raises a triable issue "
       f"in the application for leave to defend. Point {n} considers the requirement and alternative accommodation."
       for n in range(1, 13)]
)

SAMPLE = PROJECT_ROOT / "data" / "library" / "india-sample.jsonl.gz"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("web")
    os.environ.update({"DATABASE_URL": f"sqlite:///{(d / 'test.db').as_posix()}", "LLM_PROVIDER": "offline",
                       "EMBEDDING_MODEL": "", "SECRET_KEY": "test-secret", "WEB_DIST": str(d / "nodist"),
                       "LIBRARY_SEED_URL": str(SAMPLE)})
    from fastapi.testclient import TestClient

    import legal_brief.web.app as webapp

    with TestClient(webapp.app) as c:
        c.headers.update({"X-Requested-With": "precedent"})
        deadline = time.time() + 60  # the library loads into the new database in the background
        while time.time() < deadline and c.get("/api/meta").json()["library"]["judgments"] < 12:
            time.sleep(0.2)
        yield c


def _signup(c, firm, email):
    r = c.post("/api/auth/signup", json={"firm_name": firm, "name": "Ada Partner", "email": email,
                                         "password": "Correct-horse-9"})
    assert r.status_code == 200, r.text
    return r.json()


def _wait(client, run_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/runs/{run_id}").json()
        if r["status"] not in ("queued", "running"):
            return r
        time.sleep(0.3)
    raise AssertionError("run did not finish")


def test_library_loads_from_the_library_file(client):
    meta = client.get("/api/meta").json()
    assert meta["jurisdictions"] == ["India"]
    assert meta["library"]["judgments"] == 12 and meta["library"]["passages"] > 300 and not meta["library"]["loading"]


def test_auth_and_csrf(client):
    me = _signup(client, "Sharma & Associates", "ada@sharma-law.example.com")
    assert me["role"] == "admin" and me["firm"] == "Sharma & Associates"
    assert client.get("/api/auth/me").json()["email"] == "ada@sharma-law.example.com"
    # mutating calls without the UI header are refused
    r = client.post("/api/matters", json={"title": "x"}, headers={"X-Requested-With": ""})
    assert r.status_code == 403
    weak = client.post("/api/auth/signup", json={"firm_name": "B", "name": "B", "email": "b@b-firm.example.com", "password": "short"})
    assert weak.status_code == 422


def test_matter_run_export(client):
    m = client.post("/api/matters", json={
        "title": "Sharma v Bansal Traders", "client_name": "Meena Sharma", "client_role": "claimant",
        "opponent": "Bansal Traders", "practice_area": "property", "facts": FACTS,
        "objective": "An eviction order and refusal of leave to defend."}).json()
    assert m["jurisdiction"] == "India"
    r = _wait(client, client.post(f"/api/matters/{m['id']}/runs", json={"rounds": 1}).json()["id"])
    assert r["status"] == "done", r.get("error")
    res = r["result"]
    assert res["brief"]["issues"] and res["final_report"]["existence_rate"] == 1.0
    assert any(e["stage"] == "research" for e in r["events"])
    # the Supreme Court's bona fide requirement judgments are found in the database library
    cited = set(res["authorities"])
    assert cited & {"J230429", "J190159"}, cited
    docx = client.get(f"/api/runs/{r['id']}/export.docx")
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    md = client.get(f"/api/runs/{r['id']}/export.md")
    assert "Sharma v Bansal Traders" in md.text and "India law" in md.text and "not legal advice" in md.text
    listing = client.get("/api/matters").json()
    assert listing[0]["last_run"]["status"] == "done"


def test_library_upload_search_and_delete(client):
    files = {"file": ("kapoor.txt", JUDGMENT.encode(), "text/plain")}
    up = client.post("/api/library/upload", files=files).json()
    deadline = time.time() + 30
    while time.time() < deadline:
        item = client.get(f"/api/library/{up['id']}").json()
        if item["status"] != "processing":
            break
        time.sleep(0.2)
    assert item["status"] == "ready", item
    assert item["name"] == "Anil Kapoor v Sunil Mehta" and item["jurisdiction"] == "India"
    assert item["court"].startswith("High Court of Delhi")
    assert item["passages"][1]["pid"] == "p1" and item["passages"][1]["label"] == "¶1"
    hits = client.get("/api/library/search", params={"q": "bona fide requirement of the landlord, leave to defend"}).json()
    ids = [h["id"] for h in hits]
    assert up["id"] in ids and ({"J230429", "J190159"} & set(ids)), ids
    lib = client.get("/api/library").json()
    assert any(i["id"] == "J200487" and i["court"] == "Supreme Court of India" for i in lib["items"])
    detail = client.get("/api/library/J200487").json()
    assert detail["passages"] and detail["passages"][0]["label"].startswith("Headnote")
    # removing an upload removes it from search
    assert client.delete(f"/api/library/{up['id']}").json()["ok"]
    ids = [h["id"] for h in client.get("/api/library/search", params={"q": "bona fide requirement leave to defend"}).json()]
    assert up["id"] not in ids


def test_firms_are_isolated(client):
    mine = client.get("/api/matters").json()
    assert mine
    client.post("/api/auth/logout")
    _signup(client, "Other LLP", "bob@other-llp.example.com")
    assert client.get("/api/matters").json() == []
    assert client.get(f"/api/matters/{mine[0]['id']}").status_code == 404
    uploads = [i for i in client.get("/api/library").json()["items"] if i["id"].startswith("U")]
    assert uploads == []


def test_uploads_are_private_to_their_firm(client):
    files = {"file": ("kapoor.txt", JUDGMENT.encode(), "text/plain")}
    up = client.post("/api/library/upload", files=files).json()
    deadline = time.time() + 30
    while time.time() < deadline and client.get(f"/api/library/{up['id']}").json()["status"] == "processing":
        time.sleep(0.2)
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "ada@sharma-law.example.com", "password": "Correct-horse-9"})
    ids = [h["id"] for h in client.get("/api/library/search", params={"q": "bona fide requirement leave to defend"}).json()]
    assert up["id"] not in ids  # another firm's upload never appears in this firm's research
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "bob@other-llp.example.com", "password": "Correct-horse-9"})


def test_team_member_temp_password(client):
    r = client.post("/api/team", json={"name": "Cara Associate", "email": "cara@other-llp.example.com", "role": "member"})
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    client.post("/api/auth/logout")
    me = client.post("/api/auth/login", json={"email": "cara@other-llp.example.com", "password": temp}).json()
    assert me["must_change_password"] and me["role"] == "member"
    assert client.post("/api/team", json={"name": "X", "email": "x@other-llp.example.com"}).status_code == 403


def test_matter_under_another_countrys_law_is_blocked(client):
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "ada@sharma-law.example.com", "password": "Correct-horse-9"})
    m = client.post("/api/matters", json={"title": "Singh v Singh", "client_name": "Hardeep Singh",
                                          "opponent": "Gurpreet Singh", "practice_area": "property",
                                          "jurisdiction": "England and Wales",
                                          "facts": "1. Hardeep Singh owns a house on Cranbrook Avenue, Leeds, "
                                                   "registered at HM Land Registry. 2. In March 2025 his neighbour "
                                                   "built a garden wall 40 centimetres over the boundary shown on "
                                                   "the title plan and refuses to move it.",
                                          "objective": "Remove the wall."}).json()
    r = _wait(client, client.post(f"/api/matters/{m['id']}/runs", json={"rounds": 1}).json()["id"])
    assert r["status"] == "blocked" and r["result"]["blocked"]["kind"] == "no_library"
