"""Root-relative Azure configuration; importing this module makes no API calls."""
from dataclasses import dataclass, field
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_environment():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class AzureSettings:
    endpoint: str
    key: str = field(repr=False)
    deployment: str
    api_version: str = "2024-10-21"

    @classmethod
    def load(cls):
        load_environment()
        names = ("AZURE_OAI_ENDPOINT", "AZURE_OAI_KEY", "AZURE_OAI_DEPLOYMENT")
        values = [os.getenv(name, "").strip() for name in names]
        missing = [name for name, value in zip(names, values)
                   if not value or value.lower().startswith(("your-", "replace-", "https://your-"))]
        if missing:
            raise ValueError("Configure " + ", ".join(missing) + " in the root .env or environment.")
        return cls(*values, os.getenv("AZURE_OAI_API_VERSION") or "2024-10-21")
