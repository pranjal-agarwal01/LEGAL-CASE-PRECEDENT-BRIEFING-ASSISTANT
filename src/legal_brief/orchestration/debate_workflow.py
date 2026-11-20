"""Debate architecture with a compiler, as a Microsoft Agent Framework workflow graph.

    FactSheet
       |
  [fact_extractor] --> [precedent_retrieval] <------------------------+
                          |            ^                               |
               next=argument|            | new issues need research    |
                          v            |                               |
                     [argument]  <-------------- next round ---------- [counter_argument]
                          |                                            ^      |
                          +------------------ next=counter ------------+      | rounds done
                                                                              v
                                                                      [brief_compiler] --> CompiledBrief

Routing uses conditional edges on DebateState.next. Agents share the IssueBoard
(the shared issue list) held in the CaseSession; the workflow's own state also
receives a snapshot of the board after every step.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from agent_framework import Executor, Workflow, WorkflowBuilder, WorkflowContext, handler

from legal_brief.agents import (ArgumentAgent, BriefCompilerAgent, CaseSession, CompiledBrief,
                                CounterArgumentAgent, FactExtractorAgent, PrecedentRetrievalAgent)
from legal_brief.agents.debate_base import DebaterAgent
from legal_brief.config import Settings
from legal_brief.corpus import Corpus, load_library
from legal_brief.factsheet import load_fact_sheet
from legal_brief.llm import build_chat_client
from legal_brief.models import FactSheet
from legal_brief.retrieval import HybridRetriever


@dataclass
class DebateState:
    round: int = 1
    next: str = "retrieval"
    return_to: str = "argument"
    prepared: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)


def _snapshot(ctx: WorkflowContext, session: CaseSession) -> None:
    ctx.set_state("issue_board", session.board.snapshot())


class FactExtractionExecutor(Executor):
    def __init__(self, agent: FactExtractorAgent):
        super().__init__(id="fact_extractor")
        self.agent = agent

    @handler
    async def handle(self, fact_sheet: FactSheet, ctx: WorkflowContext[DebateState]) -> None:
        await self.agent.run()
        _snapshot(ctx, self.agent.session)
        await ctx.send_message(DebateState(next="retrieval", return_to="argument", steps=["fact_extractor"]))


class RetrievalExecutor(Executor):
    def __init__(self, agent: PrecedentRetrievalAgent):
        super().__init__(id="precedent_retrieval")
        self.agent = agent

    @handler
    async def handle(self, state: DebateState, ctx: WorkflowContext[DebateState]) -> None:
        await self.agent.run()
        _snapshot(ctx, self.agent.session)
        state.steps.append("precedent_retrieval")
        state.next = state.return_to
        await ctx.send_message(state)


class DebaterExecutor(Executor):
    def __init__(self, agent: DebaterAgent, executor_id: str, rounds: int):
        super().__init__(id=executor_id)
        self.agent, self.rounds = agent, rounds

    @handler
    async def handle(self, state: DebateState, ctx: WorkflowContext[DebateState]) -> None:
        session, side = self.agent.session, self.agent.side
        if state.round == 1 and side not in state.prepared:
            state.prepared.append(side)
            await self.agent.prepare()
            if session.board.pending_retrieval():  # new issues: research them before arguing
                state.next, state.return_to = "retrieval", side
                state.steps.append(f"{side}:prepare")
                _snapshot(ctx, session)
                await ctx.send_message(state)
                return
        await self.agent.take_turn(state.round)
        state.steps.append(f"{side}:round{state.round}")
        if side == "argument":
            state.next = "counter"
        elif state.round < self.rounds:
            state.round, state.next = state.round + 1, "argument"
        else:
            state.next = "compiler"
        _snapshot(ctx, session)
        await ctx.send_message(state)


class CompilerExecutor(Executor):
    def __init__(self, agent: BriefCompilerAgent):
        super().__init__(id="brief_compiler")
        self.agent = agent

    @handler
    async def handle(self, state: DebateState, ctx: WorkflowContext[None, CompiledBrief]) -> None:
        compiled = await self.agent.run()
        state.steps.append("brief_compiler")
        self.agent.session.log("workflow", "path", " -> ".join(state.steps))
        _snapshot(ctx, self.agent.session)
        await ctx.yield_output(compiled)


def build_debate_workflow(session: CaseSession) -> Workflow:
    rounds = max(1, session.settings.debate_rounds)
    fx = FactExtractionExecutor(FactExtractorAgent(session))
    rt = RetrievalExecutor(PrecedentRetrievalAgent(session))
    ar = DebaterExecutor(ArgumentAgent(session), "argument", rounds)
    ca = DebaterExecutor(CounterArgumentAgent(session), "counter_argument", rounds)
    bc = CompilerExecutor(BriefCompilerAgent(session))
    to = lambda name: (lambda s: isinstance(s, DebateState) and s.next == name)  # noqa: E731
    return (
        WorkflowBuilder(name="legal-precedent-debate", start_executor=fx, max_iterations=60)
        .add_edge(fx, rt)
        .add_edge(rt, ar, condition=to("argument"))
        .add_edge(rt, ca, condition=to("counter"))
        .add_edge(ar, rt, condition=to("retrieval"))
        .add_edge(ar, ca, condition=to("counter"))
        .add_edge(ca, rt, condition=to("retrieval"))
        .add_edge(ca, ar, condition=to("argument"))
        .add_edge(ca, bc, condition=to("compiler"))
        .build()
    )


@dataclass
class CaseResult:
    session: CaseSession
    compiled: CompiledBrief
    seconds: float

    @property
    def brief(self):
        return self.compiled.final


def make_session(fact_sheet: FactSheet, settings: Settings, client=None, corpus: Corpus | None = None,
                 retriever: HybridRetriever | None = None) -> CaseSession:
    if retriever is not None:
        corpus = retriever.corpus
    corpus = corpus or load_library(settings)
    if retriever is None:
        embedder = None
        if settings.embedding_model and settings.uses_llm:  # same semantic search as the web app
            from legal_brief.config import PROJECT_ROOT
            from legal_brief.embeddings import FileCache, build_embedder

            embedder = build_embedder(settings, FileCache(PROJECT_ROOT / "var" / "embeddings.npz"))
        retriever = HybridRetriever(corpus, doctrine_boost=settings.doctrine_boost, embedder=embedder)
    if client is None and settings.uses_llm:
        client = build_chat_client(settings)
    strong = None
    if client is not None and settings.compiler_model and settings.compiler_model != settings.model:
        strong = build_chat_client(settings.with_overrides(model=settings.compiler_model))
    return CaseSession(settings=settings, corpus=corpus, retriever=retriever, fact_sheet=fact_sheet, client=client,
                       strong_client=strong)


async def run_case(fact_sheet: FactSheet | str | Path, settings: Settings, client=None, *,
                   retriever: HybridRetriever | None = None, on_event=None) -> CaseResult:
    """Run the full multi-agent debate for one fact sheet and return the compiled brief.

    `retriever` lets a caller (the web app) reuse a library index across runs; `on_event`
    receives every trace entry as the agents work, for live progress."""
    if not isinstance(fact_sheet, FactSheet):
        fact_sheet = load_fact_sheet(fact_sheet)
    session = make_session(fact_sheet, settings, client, retriever=retriever)
    session.on_event = on_event
    start = time.perf_counter()
    workflow = build_debate_workflow(session)
    result = await workflow.run(fact_sheet)
    outputs = result.get_outputs()
    if not outputs:
        raise RuntimeError(f"The debate workflow produced no brief (status: {result.get_final_state()}).")
    return CaseResult(session=session, compiled=outputs[-1], seconds=time.perf_counter() - start)
