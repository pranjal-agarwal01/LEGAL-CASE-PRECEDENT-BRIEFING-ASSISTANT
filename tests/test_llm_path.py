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

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        return self._respond(messages, options)

    async def _respond(self, messages, options):
        fmt = options.get("response_format")
        name = getattr(fmt, "__name__", "text")
        self.requests.append(name)
        text = "\n".join(c.text or "" for m in messages for c in m.contents if c.type == "text")
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
        """Grade every statement 'supported', except the proposition attributed to J38, which the
        scripted checker rejects so the test can see an unsupported authority removed."""
        items = json.loads(text[text.index("["):])
        return {"verdicts": [{"id": it["id"],
                              "verdict": "unsupported" if "one party" in it["statement"] else "supported",
                              "note": "passage is about something else" if "one party" in it["statement"] else ""}
                             for it in items]}

    @staticmethod
    def _payload(name, issue_ids):
        if name == "FactExtractionLLM":
            return {
                "client_role": "claimant",
                "parties": [{"name": "Thomas Rowe", "role": "claimant", "description": "events organiser"},
                            {"name": "Skyline Terraces Ltd", "role": "defendant", "description": "terrace owner"}],
                "chronology": [{"date": "28 June 2025", "event": "Fireworks cancelled", "fact_ref": "F4"},
                               {"date": "10 May 2025", "event": "Hire agreed", "fact_ref": "[F1]"},
                               {"date": "1 July 2099", "event": "invented", "fact_ref": "F99"}],
                "claims": [{"claimant": "Thomas Rowe", "respondent": "Skyline Terraces Ltd",
                            "claim": "Return of deposit", "legal_basis": "Frustration", "fact_refs": ["F1", "F5"]}],
                "key_facts": [{"text": "The fireworks were the purpose of the hire.", "citations": ["F2"]}],
                "candidate_issues": [{"question": "Was the hire contract frustrated?", "doctrine": "frustration",
                                      "reason": "event cancelled"}],
            }
        if name == "RetrievalSelectionLLM":
            # many picks on purpose: the hybrid shortlist must still survive in full
            return {"selections": [{"issue_id": i, "judgment_ids": ["J37", "J99", "J38", "J01", "J02", "J03", "J04",
                                                                    "J05", "J06", "J07", "J08"],
                                    "queries_used": ["coronation procession cancelled hire"], "reason": "analogous",
                                    "coverage": "good", "coverage_note": ""}
                                   for i in issue_ids]}
        if name == "PrepareLLM":
            return {"framed_issues": [{"issue_id": "I1", "question": "Was Mr Rowe's hire frustrated?",
                                       "client_needs": "pro"}], "new_issues": []}
        if name == "DebateTurnLLM":
            return {"points": [{"issue_id": "I1", "text": "Krell v Henry applies: the view was the shared foundation.",
                                "citations": ["J37:p3", "F2"], "responds_to": ""}],
                    "stances": [{"issue_id": "I1", "judgment_id": "J37", "use": "rely"},
                                {"issue_id": "I1", "judgment_id": "J38", "use": "attack"}]}
        if name == "BriefLLM":
            return {
                "summary": [{"text": "The contract was probably frustrated.", "citations": ["J37:p3", "F4"]},
                            {"text": "Grimes v Watersports Ltd is directly on point.", "citations": ["J88:p1"]}],
                "issues": [{"issue_id": "I1", "question": "Was the hire frustrated?",
                            "precedents": [{"judgment_id": "J37", "stance": "supporting",
                                            "proposition": "Cancellation of the shared purpose frustrates.",
                                            "citations": ["J37:p3"]},
                                           {"judgment_id": "J38", "stance": "opposing",
                                            "proposition": "Not where only one party's purpose fails.",
                                            "citations": ["J38:p3"]},
                                           {"judgment_id": "J37", "stance": "opposing",
                                            "proposition": "Frustration needs a shared purpose to fail.",
                                            "citations": ["J37:p3"]}],
                            "supporting_argument": [{"text": "Both parties knew of the fireworks.", "citations": ["F2"]}],
                            "opposing_argument": [{"text": "The terrace was still usable.", "citations": ["F5", "J38:p2"]}],
                            "assessment": {"text": "Favourable but contested.", "citations": ["J37:p2", "J38:p3"]}}],
                "conclusion": [{"text": "Recover the deposit.", "citations": ["F7"]}],
            }
        return {}


def test_llm_mode_end_to_end(settings, fs_dir):
    client = ScriptedChatClient()
    result = asyncio.run(run_case(fs_dir / "FS04_rowe_v_skyline.md", settings.with_overrides(provider="openai"), client=client))
    s, compiled = result.session, result.compiled

    assert s.mode == "llm:openai" and not s.warnings, s.warnings
    assert client.requests.count("FactExtractionLLM") == 1
    assert client.requests.count("BriefLLM") == 1
    assert client.requests.count("DebateTurnLLM") >= 4  # 2 rounds x 2 debaters (plus tool round-trips)
    assert any("frustration" in r for r in client.tool_results), "list_issues tool output should reach the model"

    # fact refs that do not exist are dropped by the extractor
    assert [e.fact_ref for e in s.facts.chronology] == ["F1", "F4"]
    # retrieval keeps only real judgments, and always keeps the hybrid shortlist
    cands = s.board.issues[0].candidate_ids()
    assert cands[:2] == ["J37", "J38"] and "J99" not in cands and {"J36", "J39"} <= set(cands)
    assert s.board.issues[0].question == "Was Mr Rowe's hire frustrated?"
    # Both debaters say "rely on J37, attack J38"; mapped to the client's view, the Argument agent's
    # marks give J37 supporting / J38 opposing, the Counter agent's give the reverse.
    assert "J37" in s.board.issues[0].supporting and "J38" in s.board.issues[0].opposing

    # the hallucinated citation (J88:p1) and invented case are counted, then removed by the guard
    raw, final = compiled.raw_report, compiled.final_report
    assert raw["existence_rate"] < 1.0
    assert any("J88" in x for x in raw["invalid_examples"])
    assert any("Grimes" in x for x in raw["invalid_examples"])
    assert final["existence_rate"] == 1.0 and final["claim_coverage"] == 1.0
    assert any("Grimes" in w for w in compiled.final.warnings)
    assert set(final["cited_judgments"]) >= {"J37", "J38"}

    # the source checker graded the statements; the unsupported J38 proposition was removed
    sup = compiled.support_report
    assert sup["checked"] >= 4 and sup["unsupported"] == 1 and sup["removed_precedents"] == 1
    issue = compiled.final.issues[0]
    # J38 (unsupported) is removed; J37 stays on BOTH sides because only J38's proposition failed
    assert [e.judgment_id for e in issue.supporting_precedents] == ["J37"]
    assert [e.judgment_id for e in issue.opposing_precedents] == ["J37"]
    assert issue.supporting_precedents[0].proposition.support == "supported"
    assert any(w.startswith("Removed J38") for w in compiled.final.warnings)
    assert client.requests.count("SupportCheckLLM") == 1


def test_llm_failure_falls_back_to_offline(settings, fs_dir):
    class BrokenClient(ScriptedChatClient):
        async def _respond(self, messages, options):
            return ChatResponse(messages=[Message("assistant", ["this is not JSON"])])

    result = asyncio.run(run_case(fs_dir / "FS07_brennan_v_castlegate.md",
                                  settings.with_overrides(provider="openai"), client=BrokenClient()))
    assert result.session.warnings and "offline baseline" in result.session.warnings[0]
    assert result.compiled.final_report["existence_rate"] == 1.0
    assert result.brief.issues
