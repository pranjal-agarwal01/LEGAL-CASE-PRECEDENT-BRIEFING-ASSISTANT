"""Exercise the LLM code path without network access.

A scripted Agent Framework chat client stands in for the model: it answers each
agent's structured-output request with canned JSON, calls one of the agents'
tools first (so tool invocation through Agent Framework is exercised), and
deliberately returns a hallucinated citation and an invented case name, which the
citation checker must catch.
"""

import asyncio
import json
import re

from agent_framework import BaseChatClient, ChatResponse, Content, FunctionInvocationLayer, Message

from legal_brief.orchestration import run_case


class ScriptedChatClient(FunctionInvocationLayer, BaseChatClient):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.requests: list[str] = []
        self.tool_results: list[str] = []
        self.turn_calls: list[tuple[int, str]] = []  # (messages in the request, newest user message)

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        return self._respond(messages, options)

    async def _respond(self, messages, options):
        fmt = options.get("response_format")
        name = getattr(fmt, "__name__", "text")
        self.requests.append(name)
        text = "\n".join(c.text or "" for m in messages for c in m.contents if c.type == "text")
        if name == "DebateTurnLLM":
            users = [m for m in messages if str(getattr(m.role, "value", m.role)) == "user"]
            newest = "\n".join(c.text or "" for c in users[-1].contents if c.type == "text") if users else ""
            self.turn_calls.append((len(messages), newest))
        results = [c for m in messages for c in m.contents if c.type == "function_result"]
        tools = {getattr(t, "name", "") for t in (options.get("tools") or [])}
        if name == "DebateTurnLLM" and "list_issues" in tools and not results:
            call = Content("function_call", call_id="call-1", name="list_issues", arguments={})
            return ChatResponse(messages=[Message("assistant", [call])])
        self.tool_results += [str(r.result) for r in results]
        issue_ids = sorted(set(re.findall(r'"issue_id": "(I\d+)"', text))) or ["I1"]
        if name == "SupportCheckLLM":
            return ChatResponse(messages=[Message("assistant", [json.dumps(self._support(text))])])
        return ChatResponse(messages=[Message("assistant", [json.dumps(self._payload(name, issue_ids))])])

    @staticmethod
    def _support(text):
        """Grade every statement 'supported', except the proposition attributed to J240377, which the
        scripted checker rejects so the test can see an unsupported authority removed."""
        items = json.loads(text[text.index("["):])
        return {"verdicts": [{"id": it["id"],
                              "verdict": "unsupported" if ("one party" in it["statement"]
                                                           or "preserved" in it["statement"]) else "supported",
                              "relevance": "on_point",
                              "helps": "other_side" if "undermines the seller" in it["statement"]
                              else "client" if "for the client" in it.get("written_for", "")
                              else "other_side" if "other side" in it.get("written_for", "") else "neutral",
                              "note": "passage is about something else" if "one party" in it["statement"] else ""}
                             for it in items]}

    @staticmethod
    def _payload(name, issue_ids):
        if name == "FactExtractionLLM":
            return {
                "client_role": "defendant",
                "parties": [{"name": "Venkata Reddy", "role": "claimant", "description": "purchaser"},
                            {"name": "K. Srinivasulu", "role": "defendant", "description": "owner of the plot"}],
                "chronology": [{"date": "20 September 2019", "event": "Legal notice cancelling", "fact_ref": "F3"},
                               {"date": "4 March 2019", "event": "Agreement to sell", "fact_ref": "[F1]"},
                               {"date": "1 July 2099", "event": "invented", "fact_ref": "F99"}],
                "claims": [{"claimant": "Venkata Reddy", "respondent": "K. Srinivasulu",
                            "claim": "Specific performance", "legal_basis": "Specific Relief Act, 1963",
                            "fact_refs": ["F1", "F5"]}],
                "key_facts": [{"text": "The balance was not paid by the agreed date.", "citations": ["F3"]}],
                "candidate_issues": [{"question": "Was the plaintiff continuously ready and willing?",
                                      "doctrine": "readiness_willingness", "reason": "balance never paid"}],
            }
        if name == "RetrievalSelectionLLM":
            # many picks on purpose: the hybrid shortlist must still survive in full
            return {"selections": [{"issue_id": i, "judgment_ids": ["J240778", "J999999", "J240377", "J250825",
                                                                    "J251309", "J250956", "J240875", "J230429",
                                                                    "J200487", "J190120", "J190159"],
                                    "queries_used": ["readiness and willingness balance consideration"],
                                    "reason": "on point", "coverage": "good", "coverage_note": ""}
                                   for i in issue_ids]}
        if name == "PrepareLLM":
            return {"framed_issues": [{"issue_id": "I1", "question": "Was Mr Reddy continuously ready and willing?",
                                       "client_needs": "contra"}], "new_issues": []}
        if name == "DebateTurnLLM":
            return {"points": [{"issue_id": "I1", "text": "Janardan Das applies: readiness must be continuous.",
                                "citations": ["J240778:p8.1", "F4"], "responds_to": ""}],
                    "stances": [{"issue_id": "I1", "judgment_id": "J240778", "use": "rely"},
                                {"issue_id": "I1", "judgment_id": "J240377", "use": "attack"}]}
        if name == "BriefLLM":
            return {
                "summary": [{"text": "The suit will probably fail for want of readiness.",
                             "citations": ["J240778:p8.1", "F4"]},
                            {"text": "The client's defence is preserved by his notice.", "citations": ["F3"]},
                            {"text": "Grimes v Watersports Ltd is directly on point.", "citations": ["J888888:p1"]}],
                "issues": [{"issue_id": "I1", "question": "Was the plaintiff ready and willing?",
                            "precedents": [{"judgment_id": "J240778", "stance": "supporting",
                                            "proposition": "Readiness and willingness must be proved throughout.",
                                            "citations": ["J240778:p8.1"],
                                            "quote": "must aver and prove that they have performed or have always "
                                                     "been ready and willing to perform the essential terms of the "
                                                     "contract"},
                                           {"judgment_id": "J240377", "stance": "opposing",
                                            "proposition": "A purchaser need only show one party's default.",
                                            "citations": ["J240377:p3"], "quote": ""},
                                           {"judgment_id": "J240778", "stance": "opposing",
                                            "proposition": "Readiness is judged from the plaintiff's conduct.",
                                            "citations": ["J240778:p8.1"],
                                            "quote": "readiness need not be shown after the date fixed for performance"}],
                            "supporting_argument": [{"text": "The plaintiff had less than Rs 2,00,000 in 2019.",
                                                     "citations": ["F4"]},
                                                    {"text": "The bank loan plea undermines the seller's defence.",
                                                     "citations": ["F4"]}],
                            "opposing_argument": [{"text": "The plaintiff pleaded readiness.",
                                                   "citations": ["F5", "J240377:p2"]}],
                            "assessment": {"text": "Favourable but contested.",
                                           "citations": ["J240778:p9", "J240377:p3"]}}],
                "conclusion": [{"text": "Defend the suit.", "citations": ["F7"]}],
                "remedies": [{"text": "If readiness is not proved, specific performance is refused.",
                              "citations": ["J240778:p8.1"]}],
                "time_limits": [],
                "evidence": [{"text": "Obtain the plaintiff's 2019 bank statements.", "citations": ["F4"]}],
                "questions_for_client": ["Did the plaintiff ever offer the balance in writing?"],
            }
        return {}


def test_llm_mode_end_to_end(settings, fs_dir):
    client = ScriptedChatClient()
    result = asyncio.run(run_case(fs_dir / "FS01_reddy_v_srinivasulu.md", settings.with_overrides(provider="openai"),
                                  client=client))
    s, compiled = result.session, result.compiled

    assert s.mode == "llm:openai" and not s.warnings, s.warnings
    assert client.requests.count("FactExtractionLLM") == 1
    assert client.requests.count("BriefLLM") == 1
    assert client.requests.count("DebateTurnLLM") >= 4  # 2 rounds x 2 debaters (plus tool round-trips)
    assert any("readiness_willingness" in r for r in client.tool_results), "list_issues output should reach the model"
    # Each debater keeps one conversation: its round-2 request carries the earlier messages, and the
    # new message does not resend the facts, only the opponent's new points and the issue list.
    later = [(n, msg) for n, msg in client.turn_calls if "ROUND 2" in msg]
    assert later and all(n > 4 for n, _ in later), client.turn_calls
    assert all("FACTS:" not in msg and "OPPONENT'S NEW POINTS" in msg for _, msg in later)

    # fact refs that do not exist are dropped by the extractor
    assert [e.fact_ref for e in s.facts.chronology] == ["F1", "F3"]
    # retrieval keeps only real judgments, and always keeps the hybrid shortlist
    cands = s.board.issues[0].candidate_ids()
    assert cands[:2] == ["J240778", "J240377"] and "J999999" not in cands and "J240533" in cands
    assert s.board.issues[0].question == "Was Mr Reddy continuously ready and willing?"
    # Both debaters say "rely on J240778, attack J240377"; mapped to the client's view, the Argument agent's
    # marks give J240778 supporting / J240377 opposing, the Counter agent's give the reverse.
    assert "J240778" in s.board.issues[0].supporting and "J240377" in s.board.issues[0].opposing

    # the hallucinated citation (J888888:p1) and invented case are counted, then removed by the guard
    raw, final = compiled.raw_report, compiled.final_report
    assert raw["existence_rate"] < 1.0
    assert any("J888888" in x for x in raw["invalid_examples"])
    assert any("Grimes" in x for x in raw["invalid_examples"])
    assert final["existence_rate"] == 1.0 and final["claim_coverage"] == 1.0
    assert any("Grimes" in w for w in compiled.final.warnings)
    assert set(final["cited_judgments"]) >= {"J240778", "J240377"}

    # the source checker graded the statements; the unsupported J240377 proposition was removed
    sup = compiled.support_report
    assert sup["checked"] >= 4 and sup["unsupported"] == 2 and sup["removed_precedents"] == 1
    issue = compiled.final.issues[0]
    # J240377 (unsupported) is removed from the opposing side only; J240778 was listed on both sides for the
    # SAME passage, which says nothing, so it is kept once, on the side its proposition supports
    assert [e.judgment_id for e in issue.supporting_precedents] == ["J240778"]
    assert issue.opposing_precedents == [] and sup["duplicates"] == 1
    assert issue.supporting_precedents[0].proposition.support == "supported"
    assert any(w.startswith("Removed J240377") for w in compiled.final.warnings)
    assert client.requests.count("SupportCheckLLM") == 1
    # an argument written for the client that actually helps the other side is moved across
    assert any("undermines the seller" in st.text for st in issue.opposing_argument)
    assert not any("undermines the seller" in st.text for st in issue.supporting_argument)
    assert sup["moved_sides"] == 1
    # a legal conclusion resting on facts alone is marked unsupported; a factual one stays 'facts_only'
    preserved = next(st for st in compiled.final.summary if "preserved" in st.text)
    assert preserved.support == "unsupported" and sup["legal_without_law"] == 1
    assert compiled.final.reliability in ("low", "medium", "high")

    # quotes are checked by exact text match: the real one is kept, the invented one is removed
    q = compiled.support_report["quotes"]
    assert q == {"quotes": 2, "verified": 1, "removed": 1}
    assert issue.supporting_precedents[0].quote_verified
    assert issue.supporting_precedents[0].quote_ref == "J240778:p8.1"
    # next steps are carried into the brief and checked like every other statement
    b = compiled.final
    assert b.remedies and b.evidence and b.questions_for_client and b.time_limits == []
    assert b.remedies[0].support == "supported" and b.evidence[0].support == "facts_only"


def test_llm_failure_falls_back_to_offline(settings, fs_dir):
    class BrokenClient(ScriptedChatClient):
        async def _respond(self, messages, options):
            return ChatResponse(messages=[Message("assistant", ["this is not JSON"])])

    result = asyncio.run(run_case(fs_dir / "FS05_deshpande_v_deshpande.md",
                                  settings.with_overrides(provider="openai"), client=BrokenClient()))
    assert result.session.warnings and "offline baseline" in result.session.warnings[0]
    assert result.compiled.final_report["existence_rate"] == 1.0
    assert result.brief.issues
