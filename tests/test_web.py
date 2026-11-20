"""The web API end to end, offline (no model), on a temporary SQLite database."""

import os
import time

import pytest

FACTS = """1. On 2 March 2025 Priya Shah rented a flat from Mr Doyle on an assured shorthold tenancy for 12 months.
2. In April 2025 the bathroom ceiling began to leak. She told Mr Doyle in writing on 3 April, 20 April and 9 May.
3. Mr Doyle did not repair the leak. On 14 August 2025 part of the ceiling fell, damaging her laptop.
4. She stayed in a hotel for two weeks while the ceiling was made safe.
5. The tenancy agreement says the landlord is not responsible for any damage to tenant belongings."""

JUDGMENT = "\n".join(
    ["Neutral Citation Number: [2024] EWCA Civ 999", "Case No: CA-2024-000123",
     "IN THE COURT OF APPEAL (CIVIL DIVISION)", "Date: 12 March 2024", "",
     "Hartley v Brookfield Lettings Ltd", ""]
    + [f"{n}. The landlord's covenant to repair the structure and exterior of the dwelling under section 11 of the "
       f"Landlord and Tenant Act 1985 arises only once the landlord has notice of the disrepair. Point {n} of the "
       f"reasoning considers notice, the tenant's complaints and the reasonable time for repair." for n in range(1, 13)]
)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("web")
    os.environ.update({"DATABASE_URL": f"sqlite:///{(d / 'test.db').as_posix()}", "LLM_PROVIDER": "offline",
                       "EMBEDDING_MODEL": "", "SECRET_KEY": "test-secret", "WEB_DIST": str(d / "nodist")})
    from fastapi.testclient import TestClient

    import legal_brief.web.app as webapp

    with TestClient(webapp.app) as c:
        c.headers.update({"X-Requested-With": "precedent"})
        yield c


def _signup(c, firm, email):
    r = c.post("/api/auth/signup", json={"firm_name": firm, "name": "Ada Partner", "email": email,
                                         "password": "Correct-horse-9"})
    assert r.status_code == 200, r.text
    return r.json()


def test_auth_and_csrf(client):
    me = _signup(client, "Shah & Co", "ada@shah-law.example.com")
    assert me["role"] == "admin" and me["firm"] == "Shah & Co"
    assert client.get("/api/auth/me").json()["email"] == "ada@shah-law.example.com"
    # mutating calls without the UI header are refused
    r = client.post("/api/matters", json={"title": "x"}, headers={"X-Requested-With": ""})
    assert r.status_code == 403
    weak = client.post("/api/auth/signup", json={"firm_name": "B", "name": "B", "email": "b@b-firm.example.com", "password": "short"})
    assert weak.status_code == 422


def test_matter_run_export(client):
    m = client.post("/api/matters", json={
        "title": "Shah v Doyle", "client_name": "Priya Shah", "client_role": "claimant", "opponent": "Mr Doyle",
        "practice_area": "property", "facts": FACTS, "objective": "Recover the laptop, hotel costs and deposit."}).json()
    run = client.post(f"/api/matters/{m['id']}/runs", json={"rounds": 1}).json()
    deadline = time.time() + 60
    while time.time() < deadline:
        r = client.get(f"/api/runs/{run['id']}").json()
        if r["status"] in ("done", "failed"):
            break
        time.sleep(0.3)
    assert r["status"] == "done", r.get("error")
    res = r["result"]
    assert res["brief"]["issues"] and res["final_report"]["existence_rate"] == 1.0
    assert any(e["stage"] == "research" for e in r["events"])
    # the shared library now includes legislation: the landlord's repairing covenant is found
    cited = set(res["authorities"])
    assert "L21" in cited, cited
    docx = client.get(f"/api/runs/{run['id']}/export.docx")
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    md = client.get(f"/api/runs/{run['id']}/export.md")
    assert "Shah v Doyle" in md.text and "not legal advice" in md.text
    listing = client.get("/api/matters").json()
    assert listing[0]["last_run"]["status"] == "done"


def test_library_upload_and_search(client):
    files = {"file": ("hartley.txt", JUDGMENT.encode(), "text/plain")}
    up = client.post("/api/library/upload", files=files).json()
    deadline = time.time() + 30
    while time.time() < deadline:
        item = client.get(f"/api/library/{up['id']}").json()
        if item["status"] != "processing":
            break
        time.sleep(0.2)
    assert item["status"] == "ready", item
    assert item["citation"] == "[2024] EWCA Civ 999" and item["name"] == "Hartley v Brookfield Lettings Ltd"
    assert item["passages"][1]["pid"] == "p1" and item["passages"][1]["label"] == "¶1"
    hits = client.get("/api/library/search", params={"q": "landlord repair notice of disrepair"}).json()
    ids = [h["id"] for h in hits]
    assert up["id"] in ids and "L21" in ids
    lib = client.get("/api/library").json()
    assert any(i["id"] == "L01" and i["kind"] == "legislation" for i in lib["items"])


def test_firms_are_isolated(client):
    mine = client.get("/api/matters").json()
    assert mine
    client.post("/api/auth/logout")
    _signup(client, "Other LLP", "bob@other-llp.example.com")
    assert client.get("/api/matters").json() == []
    assert client.get(f"/api/matters/{mine[0]['id']}").status_code == 404
    uploads = [i for i in client.get("/api/library").json()["items"] if i["id"].startswith("U")]
    assert uploads == []


def test_team_member_temp_password(client):
    r = client.post("/api/team", json={"name": "Cara Associate", "email": "cara@other-llp.example.com", "role": "member"})
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    client.post("/api/auth/logout")
    me = client.post("/api/auth/login", json={"email": "cara@other-llp.example.com", "password": temp}).json()
    assert me["must_change_password"] and me["role"] == "member"
    assert client.post("/api/team", json={"name": "X", "email": "x@other-llp.example.com"}).status_code == 403
