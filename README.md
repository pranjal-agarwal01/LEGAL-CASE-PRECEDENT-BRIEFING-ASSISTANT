# Precedent (India): research briefs on Indian property and land law

A research assistant for Indian property and land disputes. You describe the facts of a matter; five agents
built on **Microsoft Agent Framework** read the facts, search a library of Supreme Court of India judgments (and
any Acts or High Court judgments you upload), argue both sides over two rounds, and compile a brief in which
**every statement cites a judgment paragraph or a statutory provision**. A final source check reads each cited
passage against the claim it supports and removes anything the source does not say.

> Precedent prepares research for review by a qualified advocate. It does not give legal advice, and every
> authority should be checked against the official report before it is relied on.

This branch (`precedent-india`) is the India-only version. The England and Wales version is on
`precedent-web-app`.

---

## The product

| | |
|---|---|
| **Matters** | Facts typed or imported from Word / PDF, numbered so the brief can cite each paragraph. |
| **Briefs** | Issues, authorities for and against the client, both sides' arguments, an assessment and a conclusion, with live progress. Export to Word or Markdown. |
| **Source check** | Every statement that cites law is graded *verified*, *partly supported* or *not supported* against the cited passage; unsupported or off-point authorities are removed. Time limits count as verified only if the provision states that exact period. |
| **Verbatim quotes** | Each authority carries the exact words relied on, matched character by character against the source. |
| **Headnotes kept apart** | The reporter's editorial headnote is stored as `h1, h2 ...` and labelled "Headnote", so it is never presented as the court's own words; search ranks the court's paragraphs first. |
| **Next steps** | Remedies, time limits with worked-out dates, evidence to obtain and questions for the client. |
| **Library** | 1,507 Supreme Court of India judgments on property and land (2005–2025), split into the court's numbered paragraphs (about two thirds) or ~200-word parts for older reports without numbering; your own uploads of Acts, state rent laws and High Court judgments. |

### Where the law comes from

| Source | Licence | How it is used |
|---|---|---|
| Supreme Court of India judgments | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/), [Indian Supreme Court Judgments open dataset](https://registry.opendata.aws/indian-supreme-court-judgments/) (from eCourts) | Selected by `scripts/india/select_judgments.py` (civil matters on title, possession, sale, tenancy, partition, succession, mortgage, easements; land acquisition compensation left out) and built into the library file by `scripts/india/build_library.py`. |
| Central and state Acts | Indian government works | Not bundled yet (India Code did not respond to automated requests). Upload them in the app, or put PDFs in `var/india/acts/` before building the library (see `ACTS` in `build_library.py`). |
| High Court judgments | Your own copies | Upload them in the app; they stay in your account. |

---

## How the database works on Render's free plan

Render's free Postgres has 1 GB and **expires 30 days after it is created**. Precedent is built so that losing the
database loses nothing:

1. **The law is a file, not data you have to keep.** The whole library (judgments, passages and their search
   vectors) is one gzip file (`precedent-india-library.jsonl.gz`, about 115 MB). Publish it as a GitHub release
   asset and set `LIBRARY_SEED_URL` to its download URL. When the app starts on an empty database it creates the
   tables and loads the file by itself; the library page shows a note while it loads.
2. **Your work is backed up every night.** The *Database backup and rotation* GitHub Action
   ([`.github/workflows/database.yml`](.github/workflows/database.yml)) copies your accounts, matters, briefs and
   uploads, encrypts the copy with `BACKUP_PASSPHRASE` (the repository is public) and keeps it as a workflow
   artifact for 30 days.
3. **The database is replaced before it expires.** The same Action checks the database's expiry date every night.
   Five days before it, it backs up, deletes the old database, creates a new free one, points the web service's
   `DATABASE_URL` at it, redeploys, and restores your work. The app reloads the library from the file.

Search runs inside Postgres: a generated `tsvector` column with a GIN index for keywords, and a pgvector
`halfvec(512)` column with an HNSW index for meaning, fused 0.6 / 0.4. The web server holds no index in memory,
so it fits Render's 512 MB free web plan. Locally, SQLite is used instead (FTS5 for keywords, vectors compared in
memory).

### Deploy

1. Build the library file (below) and publish it: GitHub → Releases → *Draft a new release* → attach
   `var/india/precedent-india-library.jsonl.gz`. Copy the asset's download URL.
2. Render → **New → Blueprint** → this repository, branch `precedent-india`. Enter `FOUNDRY_ENDPOINT`,
   `FOUNDRY_API_KEY` and `LIBRARY_SEED_URL` when prompted.
3. GitHub → Settings → Secrets and variables → Actions:
   - secrets: `RENDER_API_KEY` (Render → Account settings → API keys), `BACKUP_PASSPHRASE` (any long passphrase;
     keep it, you need it to open a backup)
   - variables: `RENDER_SERVICE_ID` (the web service's `srv-...` id), `APP_URL` (`https://<service>.onrender.com`)
4. Actions → *Database backup and rotation* → **Run workflow** with *Replace the database now* ticked. This creates the
   first database and sets `DATABASE_URL`.
5. Open the app, create your account, then set `ALLOW_SIGNUP` to `false` in Render.

To open a backup: `openssl enc -d -aes-256-cbc -pbkdf2 -in backup.json.gz.enc -out backup.json.gz`, then
`python scripts/ops/render_db.py restore --file backup.json --url <postgres url>`.

---

## Build the library

```bash
pip install -e ".[openai,web,library]"
```

```bash
python scripts/india/select_judgments.py var/india/metadata --from 2005 --to 2025 --out var/india/selection.json
```

```bash
python scripts/india/download_judgments.py var/india/selection.json --out var/india/pdf
```

```bash
python scripts/india/build_library.py
```

`select_judgments.py` reads the dataset's metadata files (download `metadata/parquet/year=YYYY/metadata.parquet`
for each year from the public bucket first). `build_library.py` embeds passages with the `EMBEDDING_MODEL` in
`.env` (one-off cost under a dollar with `text-embedding-3-small`) and caches vectors in
`var/india/embeddings.npz`, so a re-run only embeds what changed. Authority ids are stable: `J` + the year's last two
digits + the INSC number (`2024 INSC 778` → `J240778`); passages are `J240778:p8.1` (paragraph 8, part 1) or
`J240778:h2` (headnote part 2).

## Run locally

```bash
cd web && npm install && npm run build && cd ..
```

```bash
LIBRARY_SEED_URL=var/india/precedent-india-library.jsonl.gz uvicorn legal_brief.web.app:app --reload
```

Open http://localhost:8000 and create an account. Without `LIBRARY_SEED_URL` the library is empty except for
your uploads. The command line (`python -m legal_brief brief data/fact_sheets/FS01_reddy_v_srinivasulu.md`) uses
the 12-judgment sample library in `data/library/india-sample.jsonl.gz`, or the file named by `LIBRARY_FILE`.

---

## Architecture

The coordination pattern is a **debate with a compiler**, an Agent Framework `Workflow` with one executor per
agent: Fact Extractor → Precedent Retrieval → Argument ⇄ Counter-Argument (two rounds; new issues go back to
retrieval) → Brief Compiler (citation guard, source check). Agents share an **issue list** (blackboard) and every
write is logged with its author.

| Agent | Output |
|---|---|
| **Fact Extractor** | parties, dated chronology, claims, key facts with `F#` refs, candidate issues |
| **Precedent Retrieval** | candidate authorities per issue: the hybrid search shortlist plus the model's own queries |
| **Argument** / **Counter-Argument** | cited points for each side; round 2 answers the other side's points |
| **Brief Compiler** | the brief, then the citation guard and the source check |

The [doctrine taxonomy](src/legal_brief/doctrines.py) has 22 Indian property doctrines (specific performance,
readiness and willingness, title, revenue entries, adverse possession, injunction, partition, succession, deed
cancellation, limitation, part performance, lis pendens, bona fide purchaser, registration, benami, eviction,
lease termination, mortgage redemption, pre-emption, easements, Order VII Rule 11, res judicata). It frames issues
in offline mode, tags judgments, and boosts tagged judgments in search.

---

## Evaluation and tests

Five fictional fact sheets in [`data/fact_sheets/`](data/fact_sheets/) (specific performance, adverse possession
and mutation, eviction for bona fide requirement, lis pendens, a daughter's coparcenary share) have known relevant
Supreme Court judgments in [`data/eval/gold.json`](data/eval/gold.json), all in the 12-judgment sample library.

```bash
python -m legal_brief eval
```

```bash
python -m pytest -q
```

On the sample library the offline pipeline finds every gold judgment; with 12 judgments that only shows the
pipeline works. The real test is the full library with a model: run briefs on these and your own matters and
read them against the reports.

---

## Limitations

- **Coverage.** Supreme Court only, property and land only, 2005–2025, selected by keywords in the editorial
  summaries, so some relevant judgments are missing and a few off-topic ones are in. No High Court judgments
  unless you upload them; no Acts until you upload or bundle them.
- **Older reports.** About a third of the judgments (mostly before 2018) have no paragraph numbers that survive
  PDF extraction; they are cited as parts (`c3`), and some still carry stray margin letters from the printed
  report.
- **Outcome tags.** Judgments in the full library are tagged with the doctrines they discuss, not whether the
  doctrine succeeded (`mixed`). With a model this matters little (the debaters read the passages); offline, both
  sides may rely on the same judgment.
- **Currency.** Nothing checks whether a judgment was later overruled or a provision amended.
