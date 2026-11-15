"""Behaviour shared by the two debaters (Argument and Counter-Argument agents)."""

from __future__ import annotations

import json

from pydantic import BaseModel

from legal_brief.agents.base import BaseLegalAgent
from legal_brief.corpus import Judgment, first_sentence
from legal_brief.doctrines import DOCTRINES, opposite
from legal_brief.memory import Issue
from legal_brief.models import ArgumentPoint, DebateTurn


# ----------------------------------------------------------------- LLM schema
class _LLMFramedIssue(BaseModel):
    issue_id: str
    question: str
    client_needs: str  # "pro" (answer yes) or "contra" (answer no)


class _LLMNewIssue(BaseModel):
    question: str
    doctrine: str
    reason: str


class PrepareLLM(BaseModel):
    framed_issues: list[_LLMFramedIssue]
    new_issues: list[_LLMNewIssue]


class _LLMPoint(BaseModel):
    issue_id: str
    text: str
    citations: list[str]
    responds_to: str  # opponent point id, or "" for an opening point


class _LLMStance(BaseModel):
    issue_id: str
    judgment_id: str
    use: str  # "rely" = an authority this speaker relies on; "attack" = one it distinguishes or attacks


class DebateTurnLLM(BaseModel):
    points: list[_LLMPoint]
    stances: list[_LLMStance]


CITATION_RULES = (
    "Citation rules (strict): every point must carry citations. Cite judgments ONLY by the passage ids shown to "
    "you, in the form 'J06:p3', and facts by 'F2'. A point that applies law to facts cites both. Issue ids such as "
    "'I1' are labels, not citations: never put them in a citations list. Never cite or name "
    "a case that is not in the material provided, and never invent passage ids. Keep each point to 1-3 sentences."
)


class DebaterAgent(BaseLegalAgent):
    side: str = "argument"  # or "counter"
    tool_profile = "read"

    # ------------------------------------------------------------ perspective
    @property
    def facts(self):
        return self.session.facts

    def my_label(self) -> str:
        f = self.facts
        client = f.claimant_label if f.client_role == "claimant" else f.defendant_label
        other = f.defendant_label if f.client_role == "claimant" else f.claimant_label
        return client if self.side == "argument" else other

    def my_position(self, issue: Issue) -> str:
        return issue.client_position if self.side == "argument" else opposite(issue.client_position)

    def favours_me(self, issue: Issue, j: Judgment) -> bool:
        tag = j.doctrines.get(issue.doctrine or "")
        return tag is not None and (tag == self.my_position(issue) or tag == "mixed")

    def my_precedents(self, issue: Issue) -> list[Judgment]:
        cands = sorted(issue.candidates, key=lambda c: -c.score)
        js = [self.session.corpus.get(c.judgment_id) for c in cands]
        return [j for j in js if j and self.favours_me(issue, j)]

    @property
    def stance_word(self) -> str:
        return "supporting" if self.side == "argument" else "opposing"

    # ------------------------------------------------------------- public API
    async def prepare(self) -> None:
        await self.with_fallback("prepare", self._prepare_llm, self._prepare_offline)

    async def take_turn(self, round_no: int) -> DebateTurn:
        s = self.session
        s.board.round = round_no
        turn = await self.with_fallback(f"turn{round_no}", lambda: self._turn_llm(round_no),
                                        lambda: self._turn_offline(round_no))
        for i, p in enumerate(turn.points, 1):
            p.point_id = p.point_id or f"{self.side[0].upper()}{round_no}.{i}"
        by_issue: dict[str, int] = {}
        for p in turn.points:
            by_issue[p.issue_id] = by_issue.get(p.issue_id, 0) + 1
        for issue_id, n in by_issue.items():
            s.board.add_note(issue_id, f"round {round_no}: {n} point(s) for {self.my_label()}", self.name)
        s.turns.append(turn)
        s.log(self.name, f"turn_{round_no}", f"{len(turn.points)} points")
        return turn

    def opponent_last_turn(self) -> DebateTurn | None:
        other = "counter" if self.side == "argument" else "argument"
        turns = self.session.turns_by(other)
        return turns[-1] if turns else None

    # --------------------------------------------------------------- offline
    def _prepare_offline(self) -> None:  # overridden by subclasses
        return None

    def _principle_ref(self, j: Judgment) -> str:
        p = j.section("principle") or j.passages[-1]
        return p.ref

    def _used_facts(self, issue: Issue) -> set[str]:
        """Fact refs this side already relied on for the issue, so each point adds a new fact."""
        return {c for t in self.session.turns_by(self.side) for p in t.points if p.issue_id == issue.id
                for c in p.citations if c.startswith("F")}

    def _opening_points(self, issue: Issue, round_no: int, used: set[str], limit: int = 2) -> list[ArgumentPoint]:
        s = self.session
        points: list[ArgumentPoint] = []
        used_facts = self._used_facts(issue)
        for j in [j for j in self.my_precedents(issue) if j.id not in used][:limit]:
            used.add(j.id)
            s.board.mark_stance(issue.id, j.id, self.stance_word, self.name, "doctrine tag matches position")
            principle = first_sentence(s.corpus.passage(self._principle_ref(j)).text)
            precedent_text = " ".join(p.text for p in j.passages)
            fact = s.best_fact(f"{precedent_text} {DOCTRINES[issue.doctrine].query_terms if issue.doctrine else ''}",
                               prefer_defendant=self.side == "counter", doctrine=issue.doctrine,
                               exclude=used_facts) or s.best_fact(precedent_text, doctrine=issue.doctrine)
            text = f"{j.name} {j.citation} supports {self.my_label()} on this issue: {principle}"
            cites = [self._principle_ref(j)]
            if fact:
                used_facts.add(fact)
                text += f" That reasoning applies here: {s.fact_text(fact)}"
                cites.append(fact)
            points.append(ArgumentPoint(issue_id=issue.id, text=text, citations=cites))
        if not points and round_no == 1:
            fact = s.best_fact(issue.question, prefer_defendant=self.side == "counter")
            if fact:
                points.append(ArgumentPoint(
                    issue_id=issue.id, citations=[fact],
                    text=f"No retrieved authority squarely favours {self.my_label()} on this issue, so the argument rests "
                         f"on the facts: {s.fact_text(fact)}"))
        return points

    def _rebuttals(self, issue: Issue, opponent: DebateTurn | None, limit: int = 2) -> list[ArgumentPoint]:
        s = self.session
        if not opponent:
            return []
        out, answered = [], set()
        used_facts = self._used_facts(issue)
        # Answer the opponent's affirmative points first, then its rebuttals.
        targets = sorted((p for p in opponent.points if p.issue_id == issue.id), key=lambda p: p.responds_to is not None)
        for op in targets:
            if len(out) >= limit:
                break
            # Only distinguish authorities the opponent relies on, never our own.
            js = [s.corpus.get(c.split(":")[0]) for c in op.citations if c.startswith("J")]
            js = [j for j in js if j and not self.favours_me(issue, j) and j.id not in answered]
            if not js:
                continue
            j = js[0]
            answered.add(j.id)
            fact = s.best_fact(issue.question + " " + j.passages[0].text, prefer_defendant=self.side == "counter",
                               doctrine=issue.doctrine, exclude=used_facts) or s.best_fact(j.passages[0].text)
            if fact:
                used_facts.add(fact)
            text = (f"{j.name} is distinguishable on its facts: {first_sentence(j.passages[0].text)} "
                    f"By contrast, in this case: {s.fact_text(fact) if fact else 'the facts differ materially.'}")
            out.append(ArgumentPoint(issue_id=issue.id, text=text, responds_to=op.point_id,
                                     citations=[f"{j.id}:{j.passages[0].pid}"] + ([fact] if fact else [])))
        return out

    def _turn_offline(self, round_no: int) -> DebateTurn:
        used = {jid for t in self.session.turns_by(self.side) for p in t.points
                for jid in (c.split(":")[0] for c in p.citations if c.startswith("J"))}
        points: list[ArgumentPoint] = []
        for issue in self.session.board.issues:
            if round_no == 1:
                points += self._opening_points(issue, round_no, used)
            else:
                points += self._rebuttals(issue, self.opponent_last_turn())
                points += self._opening_points(issue, round_no, used, limit=1)
        return DebateTurn(speaker=self.side, round=round_no, points=points, mode="offline")

    # ------------------------------------------------------------------- LLM
    def material(self) -> str:
        """Facts, issue list and the full text of every retrieved passage (the only citable law)."""
        s = self.session
        lines = [f"Case: {s.fact_sheet.title}. Acting for the {s.fact_sheet.acting_for}.", "", "FACTS:"]
        lines += [f"[{p.ref}] {p.text}" for p in s.fact_sheet.paragraphs]
        lines += ["", "SHARED ISSUE LIST:", s.board.compact_view(s.corpus), "", "RETRIEVED AUTHORITIES (citable):"]
        for jid in s.board.all_candidate_ids():
            j = s.corpus.get(jid)
            lines.append(f"{j.id} {j.full_name} ({j.court}) tags={json.dumps(j.doctrines)}")
            lines += [f"  [{p.ref}] {p.text}" for p in j.passages]
        return "\n".join(lines)

    async def _prepare_llm(self) -> None:
        raise NotImplementedError

    async def _turn_llm(self, round_no: int) -> DebateTurn:
        s = self.session
        opp = self.opponent_last_turn()
        mine = self.session.turns_by(self.side)
        prompt = [self.material(), "",
                  f"ROUND {round_no} of {s.settings.debate_rounds}. You argue for {self.my_label()}."]
        if opp:
            prompt += ["OPPONENT'S LATEST POINTS:"] + [f"- {p.point_id} [{p.issue_id}] {p.text} {p.citations}" for p in opp.points]
        if mine:
            prompt += ["YOUR EARLIER POINTS:"] + [f"- {p.point_id} [{p.issue_id}] {p.text}" for t in mine for p in t.points]
        prompt += ["", "Round 1: open your case on every issue with your best authorities. Later rounds: rebut each "
                       "opponent point (set responds_to to its id) by distinguishing their authorities on the facts, "
                       "and reinforce your position. In 'stances', list every authority you used: use='rely' if it "
                       "supports YOUR side, use='attack' if it is the other side's authority that you distinguish.",
                   CITATION_RULES]
        out = await self.ask("\n".join(prompt), DebateTurnLLM)
        valid_issues = {i.id for i in s.board.issues}
        points = [ArgumentPoint(issue_id=p.issue_id, text=p.text, citations=[c.strip() for c in p.citations],
                                responds_to=p.responds_to or None)
                  for p in out.points if p.issue_id in valid_issues]
        for st in out.stances:
            if st.issue_id in valid_issues and s.corpus.get(st.judgment_id):
                # Convert the speaker's own perspective into a stance relative to the client.
                helps_speaker = not st.use.lower().startswith("attack")
                helps_client = helps_speaker == (self.side == "argument")
                s.board.mark_stance(st.issue_id, st.judgment_id, "supporting" if helps_client else "opposing",
                                    self.name, f"{self.side} {'relies on' if helps_speaker else 'attacks'} it")
        return DebateTurn(speaker=self.side, round=round_no, points=points, mode=s.mode)
