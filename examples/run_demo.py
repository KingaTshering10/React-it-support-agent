"""Exercise the actual tools offline, including simulated approval and denial."""
from copy import deepcopy
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import load_environment
from src import mock_data
from src.tools import analyze_logs, check_server_health, lookup_incident, restart_server


def main():
    load_environment()
    original = deepcopy(mock_data.SERVERS)
    print("OFFLINE DEMO · no Azure calls; all servers are in-memory fixtures.")
    try:
        with patch.dict(os.environ, {"MOCK_FAILURE_MODE": "off"}):
            print(check_server_health.invoke({"server_id": "srv-web-03"}))
        print(lookup_incident.invoke({"incident_id": "INC1002"}))
        print(analyze_logs.invoke({"server_id": "srv-db-02", "lines": 30, "keyword": "timeout"}))
        print(check_server_health.invoke({"server_id": "srv-unknown-99"}))
        print(analyze_logs.invoke({"server_id": "srv-web-01", "lines": 9999}))
        with patch.dict(os.environ, {"MOCK_FAILURE_MODE": "always"}):
            print(check_server_health.invoke({"server_id": "srv-web-03"}))
        with patch.dict(os.environ, {"HITL_AUTO_DECISION": "deny"}):
            print(restart_server.invoke({"server_id": "srv-web-03", "reason": "Demonstrate a denied mock restart."}))
        with patch.dict(os.environ, {"HITL_AUTO_DECISION": "approve"}):
            print(restart_server.invoke({"server_id": "srv-web-03", "reason": "Demonstrate an approved mock restart."}))
        print("Demo complete. Review logs/audit_log.jsonl; automated decisions are labeled mode=auto.")
    finally:
        mock_data.SERVERS.clear()
        mock_data.SERVERS.update(original)


if __name__ == "__main__":
    main()
