"""Offline checks of real tools and a real LangChain graph with a scripted model."""
import contextlib
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.errors import GraphRecursionError
from pydantic import Field

from src import hitl, mock_data
from src.agent import build_agent, run_agent
from src.config import AzureSettings
from src.tools import analyze_logs, check_server_health, lookup_incident, restart_server


class ScriptedModel(BaseChatModel):
    responses: list[AIMessage]
    position: int = 0
    bound_names: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "offline-scripted-model"

    def bind_tools(self, tools, **kwargs):
        self.bound_names = [t.name for t in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        response = self.responses[min(self.position, len(self.responses) - 1)].model_copy(deep=True)
        response.id = None
        for call in response.tool_calls:
            call["id"] = f"offline-call-{self.position}"
        self.position += 1
        return ChatResult(generations=[ChatGeneration(message=response)])


def tool_request(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "offline-call", "type": "tool_call"}])


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.original = deepcopy(mock_data.SERVERS)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.audit = Path(self.directory.name) / "audit.jsonl"
        self.audit_patch = patch.object(hitl, "AUDIT_LOG_PATH", self.audit)
        self.audit_patch.start()
        self.addCleanup(self.audit_patch.stop)
        self.env_patch = patch.dict(os.environ, {"MOCK_FAILURE_MODE": "off"}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def tearDown(self):
        mock_data.SERVERS.clear()
        mock_data.SERVERS.update(self.original)

    def rows(self):
        return [json.loads(line) for line in self.audit.read_text().splitlines()] if self.audit.exists() else []

    def test_health_incident_and_audit(self):
        self.assertIn("cpu=91%", check_server_health.invoke({"server_id": "srv-web-03"}))
        self.assertIn("server=srv-db-02", lookup_incident.invoke({"incident_id": "inc1002"}))
        rows = self.rows()
        self.assertEqual([r["tool"] for r in rows], ["check_server_health", "lookup_incident"])
        self.assertTrue(all("timestamp" in r for r in rows))

    def test_unknown_ids_and_explicit_timeout(self):
        self.assertTrue(check_server_health.invoke({"server_id": "srv-unknown-99"}).startswith("ERROR:"))
        self.assertTrue(lookup_incident.invoke({"incident_id": "INC9999"}).startswith("ERROR:"))
        with patch.dict(os.environ, {"MOCK_FAILURE_MODE": "always"}):
            self.assertIn("transient failure", check_server_health.invoke({"server_id": "srv-web-03"}))
        self.assertEqual(len(self.rows()), 3)

    def test_strict_validation_returns_audited_error(self):
        for arguments in [{"server_id": "srv-web-01", "lines": 9999},
                          {"server_id": "srv-web-01", "lines": "20"},
                          {"server_id": "srv-web-01", "lines": True},
                          {"server_id": "srv-web-01", "extra": 1}]:
            self.assertTrue(analyze_logs.invoke(arguments).startswith("ERROR: invalid input"))
        self.assertTrue(restart_server.invoke({"server_id": "srv-web-03", "reason": " "}).startswith("ERROR:"))
        self.assertEqual(len(self.rows()), 5)
        self.assertTrue(all("validation_error_fields" in r["input"] for r in self.rows()))
        self.assertEqual(mock_data.SERVERS, self.original)

    def test_logs_match_level_and_empty_results(self):
        entries = [{"timestamp": "demo", "level": "ERROR", "message": "Health check OK"},
                   {"timestamp": "demo", "level": "INFO", "message": "Request handled"}]
        with patch("src.mock_data.random.choice", side_effect=["Health check OK", "ERROR", "Request handled", "INFO"]):
            actual = mock_data.get_logs("srv-web-01", lines=2, keyword="error")
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0]["level"], "ERROR")
        with patch("src.mock_data.get_logs", return_value=[]):
            self.assertIn("No log lines matched", analyze_logs.invoke({"server_id": "srv-web-01", "keyword": "absent"}))

    def test_interactive_denial_preserves_state(self):
        with patch("builtins.input", return_value="n"):
            result = restart_server.invoke({"server_id": "srv-web-03", "reason": "Test a denied restart."})
        self.assertIn("DENIED", result)
        self.assertEqual(mock_data.SERVERS, self.original)
        self.assertFalse(self.rows()[0]["approved"])

    def test_interactive_approval_updates_only_mock_state(self):
        with patch("builtins.input", return_value="yes"):
            result = restart_server.invoke({"server_id": "srv-web-03", "reason": "Test an approved restart."})
        self.assertIn("restarted successfully", result)
        self.assertEqual(mock_data.SERVERS["srv-web-03"]["status"], "healthy")
        self.assertEqual(mock_data.SERVERS["srv-db-02"], self.original["srv-db-02"])
        self.assertTrue(self.rows()[0]["approved"])

    def test_eof_and_cancel_deny(self):
        for error in [EOFError, KeyboardInterrupt]:
            with patch("builtins.input", side_effect=error):
                result = restart_server.invoke({"server_id": "srv-web-03", "reason": "Test interrupted approval."})
            self.assertIn("DENIED", result)
        self.assertEqual(mock_data.SERVERS, self.original)
        self.assertTrue(all(not r["approved"] and r["mode"] == "interrupted"
                            for r in self.rows() if r["event"] == "hitl_decision"))

    def test_unknown_server_does_not_prompt(self):
        with patch("builtins.input", side_effect=AssertionError("Should not prompt")):
            self.assertIn("not requested", restart_server.invoke({"server_id": "srv-unknown-99", "reason": "Unknown server."}))

    def test_approval_log_failure_blocks_restart(self):
        with patch("builtins.input", return_value="yes"), patch("src.hitl._write_audit_entry", side_effect=OSError("offline failure")):
            with self.assertRaises(OSError):
                restart_server.invoke({"server_id": "srv-web-03", "reason": "Test failed audit write."})
        self.assertEqual(mock_data.SERVERS, self.original)

    def test_actual_agent_tool_graph(self):
        model = ScriptedModel(responses=[tool_request("lookup_incident", {"incident_id": "INC1002"}),
                                          AIMessage(content="INC1002 concerns mock server srv-db-02.")])
        answer = run_agent(build_agent(model=model), "Look up INC1002", verbose=False)
        self.assertIn("srv-db-02", answer)
        self.assertEqual(self.rows()[0]["tool"], "lookup_incident")

    def test_agent_handles_validation_observation(self):
        model = ScriptedModel(responses=[tool_request("analyze_logs", {"server_id": "srv-web-01", "lines": 9999}),
                                          AIMessage(content="The requested line count is invalid.")])
        graph = build_agent(model=model)
        result = graph.invoke({"messages": [("user", "Inspect too many lines.")]})
        observations = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        self.assertTrue(observations[0].content.startswith("ERROR:"))

    def test_read_only_graph_excludes_restart(self):
        model = ScriptedModel(responses=[AIMessage(content="Read-only mode.")])
        run_agent(build_agent(model=model, read_only=True), "Check available tools", verbose=False)
        self.assertNotIn("restart_server", model.bound_names)
        self.assertEqual(len(model.bound_names), 3)

    def test_graph_step_limit(self):
        model = ScriptedModel(responses=[tool_request("lookup_incident", {"incident_id": "INC1002"})])
        with self.assertRaises(GraphRecursionError):
            run_agent(build_agent(model=model), "Keep investigating", verbose=False, recursion_limit=3)

    def test_config_and_observable_trace(self):
        with patch("src.config.load_environment"):
            with self.assertRaisesRegex(ValueError, "AZURE_OAI"):
                AzureSettings.load()
        self.assertNotIn("offline-test-key", repr(AzureSettings("https://offline.invalid", "offline-test-key", "demo")))
        model = ScriptedModel(responses=[tool_request("check_server_health", {"server_id": "srv-web-01"}), AIMessage(content="Mock server is healthy.")])
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            run_agent(build_agent(model=model), "Check srv-web-01")
        self.assertIn("Tool call:", stream.getvalue())
        self.assertIn("Tool result", stream.getvalue())
        self.assertNotIn("Thought", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
