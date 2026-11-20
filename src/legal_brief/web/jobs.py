"""Background briefing runs and judgment uploads, executed in the web process."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select, update

from legal_brief.citations import normalise, resolve_passage
from legal_brief.config import Settings
from legal_brief.ingest import judgment_metadata, paragraphs_from_text, split_judgment, split_legislation
from legal_brief.jurisdiction import JurisdictionBlocked
from legal_brief.llm import LLMUnavailable, build_chat_client
from legal_brief.models import FactParagraph, FactSheet
from legal_brief.orchestration import run_case
from legal_brief.web.db import Authority, AuthorityPassage, Firm, Matter, Run, get_session
from legal_brief.web.library import LibraryManager

log = logging.getLogger(__name__)

STAGES = {  # agent name -> step shown in the UI
    "fact_extractor": "facts", "precedent_retrieval": "research", "argument": "debate",
    "counter_argument": "debate", "brief_compiler": "compile", "source_checker": "verify", "workflow": "compile",
    "jurisdiction_check": "facts",
}


def matter_fact_sheet(m: Matter) -> FactSheet:
    role = "defendant" if m.client_role == "defendant" else "claimant"
    other = "claimant" if role == "defendant" else "defendant"
    paras = [FactParagraph(ref=f"F{i}", kind="fact", text=t) for i, t in enumerate(paragraphs_from_text(m.facts), 1)]
    if m.objective.strip():
        paras.append(FactParagraph(ref=f"F{len(paras) + 1}", kind="objective", text=" ".join(m.objective.split())))
    parties = [f"{role.title()}: {m.client_name}"] + ([f"{other.title()}: {m.opponent}"] if m.opponent else [])
    return FactSheet(case_id=f"M{m.id}", title=m.title, acting_for=f"{role.title()} ({m.client_name})",
                     source_path="", practice_area=m.practice_area or "", jurisdiction=m.jurisdiction or "England and Wales",
                     raw_text=m.facts + "\n\n" + m.objective, parties_block=parties, paragraphs=paras)


def _authority_payload(session, refs: set[str]) -> dict:
    """Everything the UI needs to show cited authorities, frozen with the run."""
    out: dict[str, dict] = {}
    for ref in refs:
        c = normalise(ref)
        jid, _, pid = c.partition(":")
        j = session.corpus.get(jid)
        if not j:
            continue
        entry = out.setdefault(jid, {
            "id": j.id, "kind": j.kind, "name": j.name, "citation": j.citation, "court": j.court,
            "url": j.url, "date": j.date, "summary": j.summary, "note": j.source_note, "passages": {}})
        ps = []
        if pid:
            p = resolve_passage(session.corpus, jid, pid)
            if p and p.pid != pid:
                ps = [q for q in j.passages if q.pid.startswith(pid + ".")]
            elif p:
                ps = [p]
        for p in ps:
            entry["passages"][p.pid] = {"label": p.display, "text": p.text}
        if pid and ps and pid not in entry["passages"]:
            entry["passages"][pid] = {"label": ps[0].display.split(" (part")[0], "text": "\n".join(q.text for q in ps)}
    return out


def result_payload(result) -> dict:
    s, c = result.session, result.compiled
    refs: set[str] = set()
    for st in c.final.statements() + c.raw.statements():
        refs.update(x for x in st.citations if x[:1] in "JLU")
    for t in s.turns:
        for p in t.points:
            refs.update(x for x in p.citations if x[:1] in "JLU")
    for i in s.board.issues:
        for cand in i.candidates:
            refs.update(cand.passage_refs or [cand.judgment_id])
    board = s.board.snapshot()
    board["events"] = [e.__dict__ for e in s.board.events]
    return {
        "brief": c.final.model_dump(), "raw_report": c.raw_report, "final_report": c.final_report,
        "support_report": c.support_report, "facts": s.facts.model_dump() if s.facts else None,
        "fact_paragraphs": [p.model_dump() for p in s.fact_sheet.paragraphs],
        "board": board, "turns": [t.model_dump() for t in s.turns], "trace": s.trace,
        "warnings": c.final.warnings, "mode": s.mode, "llm_calls": s.llm_calls, "seconds": round(result.seconds, 1),
        "authorities": _authority_payload(s, refs), "search_mode": s.retriever.dense_mode,
        "jurisdiction_check": s.jurisdiction_check,
    }


class JobManager:
    def __init__(self, settings: Settings, library: LibraryManager, max_concurrent: int = 2):
        self.settings = settings
        self.library = library
        self.sem = asyncio.Semaphore(max_concurrent)
        self.live: dict[int, list[dict]] = {}  # run id -> progress events while running
        self.tasks: set[asyncio.Task] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def recover(self) -> None:
        """Runs that were in flight when the server stopped cannot resume."""
        with get_session() as db:
            db.execute(update(Run).where(Run.status.in_(["queued", "running"]))
                       .values(status="failed", error="Interrupted by a server restart. Run it again."))
            db.execute(update(Authority).where(Authority.status == "processing")
                       .values(status="failed", error="Interrupted by a server restart. Upload it again."))
            db.commit()

    def bind_loop(self) -> None:
        """Remember the server's event loop; sync endpoints run in worker threads and schedule work onto it."""
        self.loop = asyncio.get_running_loop()

    def _spawn(self, coro) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            task = asyncio.create_task(coro)
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        else:
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    # --------------------------------------------------------------- briefs
    def start_run(self, run_id: int) -> None:
        self.live[run_id] = [{"t": 0, "agent": "queue", "action": "queued", "detail": "Waiting for a free worker",
                              "stage": "queued"}]
        self._spawn(self._run(run_id))

    def events(self, run: Run) -> list[dict]:
        return self.live.get(run.id) or run.events or []

    async def _run(self, run_id: int) -> None:
        async with self.sem:
            started = time.perf_counter()
            events = self.live.setdefault(run_id, [])
            with get_session() as db:
                run = db.get(Run, run_id)
                matter = db.get(Matter, run.matter_id)
                firm = db.get(Firm, run.firm_id)
                run.status = "running"
                db.commit()
                fs, include_summaries, rounds = matter_fact_sheet(matter), firm.include_summaries, run.rounds
                firm_id, override = firm.id, bool((run.result or {}).get("jurisdiction_override"))

            def on_event(e: dict) -> None:
                e = dict(e)
                e["stage"] = STAGES.get(e["agent"], "compile")
                events.append(e)

            try:
                events.append({"t": 0, "agent": "library", "action": "start", "detail": "Loading your library",
                               "stage": "facts"})
                retriever = await asyncio.to_thread(self.library.retriever, firm_id, include_summaries, fs.jurisdiction)
                settings = self.settings.with_overrides(debate_rounds=rounds)
                result = await run_case(fs, settings, retriever=retriever, on_event=on_event,
                                        jurisdiction_override=override)
                payload = result_payload(result)
                with get_session() as db:
                    run = db.get(Run, run_id)
                    run.status, run.result = "done", payload
                    run.events, run.llm_calls = events, result.session.llm_calls
                    run.seconds, run.finished_at = round(time.perf_counter() - started, 1), datetime.now(timezone.utc)
                    db.commit()
            except JurisdictionBlocked as e:  # the right outcome, not a crash: explain and stop
                with get_session() as db:
                    run = db.get(Run, run_id)
                    run.status, run.error, run.events = "blocked", str(e), events
                    run.result = {"blocked": e.as_dict()}
                    run.seconds, run.finished_at = round(time.perf_counter() - started, 1), datetime.now(timezone.utc)
                    db.commit()
            except Exception as e:  # noqa: BLE001 - every failure is reported on the run
                log.exception("run %s failed", run_id)
                msg = str(e) if isinstance(e, LLMUnavailable) else f"{type(e).__name__}: {str(e)[:300]}"
                with get_session() as db:
                    run = db.get(Run, run_id)
                    run.status, run.error, run.events = "failed", msg, events
                    run.seconds, run.finished_at = round(time.perf_counter() - started, 1), datetime.now(timezone.utc)
                    db.commit()
            finally:
                self.live.pop(run_id, None)

    # -------------------------------------------------------------- uploads
    def start_upload(self, authority_id: int, text: str, jurisdiction: str = "", kind: str = "") -> None:
        self._spawn(self._ingest(authority_id, text, jurisdiction, kind))

    async def _ingest(self, authority_id: int, text: str, jurisdiction: str = "", kind: str = "") -> None:
        """Index an upload. The uploader's choice of jurisdiction and document type wins over detection."""
        try:
            paras = split_judgment(text)
            if len(paras) < 2:
                raise ValueError("Too little text to index.")
            client = None
            if self.settings.uses_llm:
                try:
                    client = build_chat_client(self.settings)
                except LLMUnavailable:
                    client = None
            with get_session() as db:
                a = db.get(Authority, authority_id)
                filename = a.filename
            meta = await judgment_metadata(text, filename, client)
            with get_session() as db:
                a = db.get(Authority, authority_id)
                a.name, a.citation, a.court, a.date = meta.name, meta.citation, meta.court, meta.date
                a.area, a.summary, a.doctrines = meta.area, meta.summary, meta.doctrines
                a.kind = kind if kind in ("judgment", "legislation") else meta.document_type
                a.jurisdiction = jurisdiction or meta.jurisdiction
                if a.kind == "legislation":  # sections and schedule articles, cited as "s 5" / "Sch, art 65"
                    paras = split_legislation(text)
                a.passages = [AuthorityPassage(seq=i, pid=p.pid, label=p.label, text=p.text)
                              for i, p in enumerate(paras)]
                a.n_passages, a.status = len(paras), "ready"
                db.commit()
                firm_id, include = a.firm_id, db.get(Firm, a.firm_id).include_summaries
            # Index now (embeddings included) so the next brief does not wait for it.
            await asyncio.to_thread(self.library.retriever, firm_id, include)
        except Exception as e:  # noqa: BLE001
            log.exception("upload %s failed", authority_id)
            with get_session() as db:
                a = db.get(Authority, authority_id)
                if a:
                    a.status, a.error = "failed", f"{type(e).__name__}: {str(e)[:300]}"
                    db.commit()


def runs_today(db, firm_id: int) -> int:
    from sqlalchemy import func

    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.execute(select(func.count(Run.id)).where(Run.firm_id == firm_id, Run.created_at >= start)).scalar_one()
