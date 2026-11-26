"""
Persisted application preferences that survive across runs.

Currently stores the user's preferred default yield percentages so that
clicking "Set as default" in the GUI saves whatever values are currently
in the YIELD % boxes; the next NEW job picks those up automatically.

The file lives next to saws.json (parent of the jobs/ folder).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


SETTINGS_FILENAME = "app_settings.json"


# Hard-coded fallback if no settings file exists yet.
FALLBACK_YIELD_125 = 80.0
FALLBACK_YIELD_175 = 110.0
FALLBACK_YIELD_250 = 110.0


@dataclass
class AppSettings:
    yield_125_pct: float = FALLBACK_YIELD_125
    yield_175_pct: float = FALLBACK_YIELD_175
    yield_250_pct: float = FALLBACK_YIELD_250


class AppSettingsStore:
    def __init__(self, base_dir):
        self.path = Path(base_dir) / SETTINGS_FILENAME

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppSettings()
        return AppSettings(
            yield_125_pct=float(d.get("yield_125_pct", FALLBACK_YIELD_125)),
            yield_175_pct=float(d.get("yield_175_pct", FALLBACK_YIELD_175)),
            yield_250_pct=float(d.get("yield_250_pct", FALLBACK_YIELD_250)),
        )

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(settings), indent=2),
            encoding="utf-8",
        )
