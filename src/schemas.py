"""Strict, bounded inputs used by the LangChain tool interfaces."""
from pydantic import BaseModel, ConfigDict, Field


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class ServerHealthInput(ToolInput):
    server_id: str = Field(min_length=1, max_length=64, pattern=r"^srv-[a-z0-9]+-[0-9]{2}$",
                           description="Mock server ID, for example srv-web-03.")


class IncidentLookupInput(ToolInput):
    incident_id: str = Field(min_length=1, max_length=32, pattern=r"^[Ii][Nn][Cc][0-9]+$",
                             description="Incident ID, for example INC1002.")


class LogAnalysisInput(ServerHealthInput):
    lines: int = Field(default=50, ge=1, le=500,
                       description="Recent generated log entries to inspect before filtering, from 1 to 500.")
    keyword: str | None = Field(default=None, min_length=1, max_length=100,
                                description="Optional substring matched against message text or log level.")


class RestartServerInput(ServerHealthInput):
    reason: str = Field(min_length=1, max_length=500,
                        description="A specific justification to show the human approver.")
