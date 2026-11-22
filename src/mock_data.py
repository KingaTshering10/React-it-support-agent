"""
mock_data.py
------------
Simulated IT-infrastructure data store for the lab.

In a real deployment these functions would be replaced with calls to
actual systems: a monitoring platform (Datadog/Prometheus) for health,
an ITSM tool (ServiceNow/Jira) for incidents, and a log aggregator
(Splunk/ELK) for logs. Keeping them here as an in-memory "fake backend"
lets the lab run without external dependencies while still exercising
realistic tool-calling patterns (lookups that can fail, empty results,
transient errors, etc).
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------

SERVERS = {
    "srv-web-01": {"role": "web", "status": "healthy", "cpu": 22, "mem": 41, "disk": 55},
    "srv-web-02": {"role": "web", "status": "healthy", "cpu": 18, "mem": 38, "disk": 47},
    "srv-web-03": {"role": "web", "status": "degraded", "cpu": 91, "mem": 88, "disk": 72},
    "srv-db-01": {"role": "database", "status": "healthy", "cpu": 35, "mem": 62, "disk": 80},
    "srv-db-02": {"role": "database", "status": "critical", "cpu": 97, "mem": 95, "disk": 91},
    "srv-cache-01": {"role": "cache", "status": "healthy", "cpu": 12, "mem": 30, "disk": 20},
}

# Monitoring failures are opt-in through MOCK_FAILURE_MODE (off/random/always).
FLAKY_SERVER_ID = "srv-web-03"


def get_server_health(server_id: str) -> dict:
    """Return simulated health metrics for a server.

    Raises:
        KeyError: if the server_id does not exist.
        ConnectionError: optional simulated monitoring failure for FLAKY_SERVER_ID.
    """
    mode = os.getenv("MOCK_FAILURE_MODE", "off").strip().lower()
    if server_id == FLAKY_SERVER_ID and (mode == "always" or (mode == "random" and random.random() < 0.33)):
        raise ConnectionError(
            f"Monitoring API timed out while querying '{server_id}'. "
            "The upstream metrics collector did not respond."
        )

    if server_id not in SERVERS:
        raise KeyError(server_id)

    data = dict(SERVERS[server_id])
    data["server_id"] = server_id
    data["checked_at"] = datetime.now(timezone.utc).isoformat()
    return data


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

INCIDENTS = {
    "INC1001": {
        "title": "High CPU on srv-web-03",
        "severity": "P2",
        "status": "investigating",
        "assigned_to": "on-call-web-team",
        "server_id": "srv-web-03",
        "opened_at": "2026-08-24T09:15:00Z",
        "description": "CPU utilization sustained above 90% for 20+ minutes, "
        "correlated with a spike in incoming traffic.",
    },
    "INC1002": {
        "title": "Database replication lag on srv-db-02",
        "severity": "P1",
        "status": "mitigating",
        "assigned_to": "db-reliability-team",
        "server_id": "srv-db-02",
        "opened_at": "2026-08-24T11:02:00Z",
        "description": "Replica lag exceeds 5 minutes; risk of stale reads for "
        "downstream services. Primary node under heavy write load.",
    },
    "INC1003": {
        "title": "Disk usage warning on srv-db-01",
        "severity": "P3",
        "status": "resolved",
        "assigned_to": "db-reliability-team",
        "server_id": "srv-db-01",
        "opened_at": "2026-08-20T08:00:00Z",
        "description": "Disk usage crossed the 75% warning threshold; log "
        "rotation policy was adjusted and usage stabilized.",
    },
}


def get_incident(incident_id: str) -> dict:
    """Return incident details.

    Raises:
        KeyError: if the incident_id does not exist.
    """
    normalized = incident_id.strip().upper()
    if normalized not in INCIDENTS:
        raise KeyError(incident_id)
    data = dict(INCIDENTS[normalized])
    data["incident_id"] = normalized
    return data


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

_LOG_LEVELS = ["INFO", "INFO", "INFO", "WARN", "ERROR"]
_LOG_MESSAGES = {
    "srv-web-03": [
        "Request queue depth exceeded 500",
        "GC pause exceeded 800ms",
        "Upstream timeout calling auth-service",
        "Handled request in 42ms",
        "Autoscaler evaluated: scale-up recommended",
    ],
    "srv-db-02": [
        "Replication lag 312s",
        "Slow query detected (4.2s): SELECT * FROM orders WHERE ...",
        "Connection pool at 95% capacity",
        "Checkpoint completed in 1.1s",
        "Lock wait timeout on table 'orders'",
    ],
}
_DEFAULT_MESSAGES = [
    "Health check OK",
    "Request handled successfully",
    "Scheduled job completed",
    "Cache hit ratio 92%",
]


def get_logs(server_id: str, lines: int = 50, keyword: str | None = None) -> list[dict]:
    """Generate simulated log entries for a server.

    Raises:
        KeyError: if the server_id does not exist.
        ValueError: if `lines` is out of the supported range.
    """
    if server_id not in SERVERS:
        raise KeyError(server_id)
    if lines <= 0 or lines > 500:
        raise ValueError("`lines` must be between 1 and 500.")

    pool = _LOG_MESSAGES.get(server_id, _DEFAULT_MESSAGES)
    now = datetime.now(timezone.utc)
    entries = []
    for i in range(lines):
        msg = random.choice(pool)
        level = random.choice(_LOG_LEVELS)
        entries.append(
            {
                "timestamp": (now - timedelta(seconds=(lines - i) * 7)).isoformat(),
                "level": level,
                "message": msg,
            }
        )

    if keyword:
        keyword_lower = keyword.lower()
        entries = [e for e in entries if keyword_lower in e["message"].lower()
                   or keyword_lower in e["level"].lower()]

    return entries


# ---------------------------------------------------------------------------
# Critical action: restart
# ---------------------------------------------------------------------------

def perform_restart(server_id: str) -> dict:
    """Simulate restarting a server. Only called after HITL approval.

    Raises:
        KeyError: if the server_id does not exist.
    """
    if server_id not in SERVERS:
        raise KeyError(server_id)

    SERVERS[server_id]["status"] = "healthy"
    SERVERS[server_id]["cpu"] = random.randint(5, 20)
    SERVERS[server_id]["mem"] = random.randint(20, 40)
    return {
        "server_id": server_id,
        "result": "restarted",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
