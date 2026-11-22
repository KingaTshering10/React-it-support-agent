"""
tools.py
--------
Custom LangChain tools for IT infrastructure operations.

Each tool:
  1. Declares a structured input contract via `args_schema` (Pydantic).
  2. Wraps its backend call in try/except and returns a clear,
     LLM-readable error string instead of raising — so the agent can
     reason about the failure ("server not found", "transient timeout")
     and decide what to do next (retry, ask the user, try another tool)
     instead of the whole run crashing.
  3. Logs the call (and, for the critical tool, the HITL decision) to
     the audit trail in hitl.py.

Read-only tools: check_server_health, lookup_incident, analyze_logs
Critical (state-changing) tool: restart_server — gated by human approval.
"""

from __future__ import annotations

from langchain_core.tools import tool

from . import mock_data
from .hitl import log_tool_call, request_approval
from .schemas import (
    IncidentLookupInput,
    LogAnalysisInput,
    RestartServerInput,
    ServerHealthInput,
)


@tool("check_server_health", args_schema=ServerHealthInput)
def check_server_health(server_id: str) -> str:
    """Check the current health status (CPU, memory, disk, overall status)
    of a specific server by its server ID. Use this to answer questions
    about whether a server is healthy, degraded, or in a critical state."""
    try:
        data = mock_data.get_server_health(server_id)
    except KeyError:
        result = (
            f"ERROR: No server found with id '{server_id}'. "
            f"Known servers: {', '.join(mock_data.SERVERS.keys())}."
        )
        log_tool_call("check_server_health", {"server_id": server_id}, result)
        return result
    except ConnectionError as e:
        result = f"ERROR: transient failure querying monitoring API - {e}. Consider retrying."
        log_tool_call("check_server_health", {"server_id": server_id}, result)
        return result

    result = (
        f"Server {data['server_id']} ({data['role']}) status={data['status']} "
        f"cpu={data['cpu']}% mem={data['mem']}% disk={data['disk']}% "
        f"(checked_at={data['checked_at']})"
    )
    log_tool_call("check_server_health", {"server_id": server_id}, result)
    return result


@tool("lookup_incident", args_schema=IncidentLookupInput)
def lookup_incident(incident_id: str) -> str:
    """Look up an IT incident ticket by its ID and return its title,
    severity, status, assigned team, and description. Use this when a
    user references an incident number like 'INC1001'."""
    try:
        data = mock_data.get_incident(incident_id)
    except KeyError:
        result = f"ERROR: No incident found with id '{incident_id}'. Double-check the ID and try again."
        log_tool_call("lookup_incident", {"incident_id": incident_id}, result)
        return result

    result = (
        f"[{data['incident_id']}] {data['title']} | severity={data['severity']} "
        f"status={data['status']} assigned_to={data['assigned_to']} "
        f"server={data['server_id']} opened_at={data['opened_at']}\n"
        f"Description: {data['description']}"
    )
    log_tool_call("lookup_incident", {"incident_id": incident_id}, result)
    return result


@tool("analyze_logs", args_schema=LogAnalysisInput)
def analyze_logs(server_id: str, lines: int = 50, keyword: str | None = None) -> str:
    """Pull and summarize generated log lines for a mock server, optionally
    filtered by message text or log level (e.g. 'ERROR', 'timeout'). Use this to
    investigate the root cause behind a health alert or incident."""
    try:
        entries = mock_data.get_logs(server_id, lines=lines, keyword=keyword)
    except KeyError:
        result = f"ERROR: No server found with id '{server_id}'."
        log_tool_call("analyze_logs", {"server_id": server_id, "lines": lines, "keyword": keyword}, result)
        return result
    except ValueError as e:
        result = f"ERROR: invalid input - {e}"
        log_tool_call("analyze_logs", {"server_id": server_id, "lines": lines, "keyword": keyword}, result)
        return result

    if not entries:
        result = f"No log lines matched keyword='{keyword}' for {server_id} in the last {lines} lines."
        log_tool_call("analyze_logs", {"server_id": server_id, "lines": lines, "keyword": keyword}, result)
        return result

    level_counts: dict[str, int] = {}
    for e in entries:
        level_counts[e["level"]] = level_counts.get(e["level"], 0) + 1

    sample = entries[-5:]
    sample_lines = "\n".join(f"  [{e['timestamp']}] {e['level']}: {e['message']}" for e in sample)
    result = (
        f"Analyzed {len(entries)} matching log lines for {server_id} "
        f"(level counts: {level_counts}).\nMost recent sample:\n{sample_lines}"
    )
    log_tool_call("analyze_logs", {"server_id": server_id, "lines": lines, "keyword": keyword}, result)
    return result


@tool("restart_server", args_schema=RestartServerInput)
def restart_server(server_id: str, reason: str) -> str:
    """Restart a server. This is a CRITICAL, state-changing action that
    requires human approval before it is executed — the agent must always
    call this tool to perform a restart rather than claiming it did so
    itself. Provide a specific reason so the human approver has context."""
    if server_id not in mock_data.SERVERS:
        result = f"ERROR: No server found with id '{server_id}'. Restart was not requested."
        log_tool_call("restart_server", {"server_id": server_id, "reason": reason}, result)
        return result

    approved = request_approval(
        action_description=f"Restart server '{server_id}'",
        details={"server_id": server_id, "reason": reason},
    )

    if not approved:
        result = (
            f"Action DENIED by operator: restart of '{server_id}' was not performed. "
            "Do not retry this action; report the denial to the user."
        )
        log_tool_call("restart_server", {"server_id": server_id, "reason": reason}, result)
        return result

    try:
        outcome = mock_data.perform_restart(server_id)
    except KeyError:
        result = f"ERROR: No server found with id '{server_id}'. Restart was not performed."
        log_tool_call("restart_server", {"server_id": server_id, "reason": reason}, result)
        return result

    result = (
        f"Server '{outcome['server_id']}' restarted successfully at {outcome['completed_at']}."
    )
    log_tool_call("restart_server", {"server_id": server_id, "reason": reason}, result)
    return result


# Read-only tools the ReAct agent can call freely.
READ_ONLY_TOOLS = [check_server_health, lookup_incident, analyze_logs]

# Critical tools gated behind human-in-the-loop approval.
CRITICAL_TOOLS = [restart_server]

ALL_TOOLS = READ_ONLY_TOOLS + CRITICAL_TOOLS


def _validation_handler(tool_name):
    def handle(error):
        fields = sorted({".".join(str(x) for x in item["loc"]) for item in error.errors()})
        result = f"ERROR: invalid input for {tool_name}; check fields: {', '.join(fields)}."
        log_tool_call(tool_name, {"validation_error_fields": fields}, result)
        return result
    return handle


for _tool in ALL_TOOLS:
    _tool.handle_validation_error = _validation_handler(_tool.name)
