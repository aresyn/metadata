from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


Severity = Literal["warning", "error"]


@dataclass(slots=True)
class DiagnosticEvent:
    severity: Severity
    code: str
    message: str
    path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReportStats:
    project: str
    mainConfigPath: str | None
    mainConfigFound: bool
    mainConfigRequired: bool
    extensionPath: str | None
    extensionFound: bool
    extensionRequired: bool
    generatedAt: str
    mainConfigurationObjects: int = 0
    extensionObjects: int = 0
    objectsByType: dict[str, int] = field(default_factory=dict)
    warnings: int = 0
    warningEvents: int = 0
    warningGroups: int = 0
    errors: int = 0


class Diagnostics:
    def __init__(self, project: str) -> None:
        self.project = project
        self.events: list[DiagnosticEvent] = []

    def warning(self, code: str, message: str, path: Path | str | None = None, **details: Any) -> None:
        self.events.append(DiagnosticEvent("warning", code, message, _path_to_str(path), details))

    def error(self, code: str, message: str, path: Path | str | None = None, **details: Any) -> None:
        self.events.append(DiagnosticEvent("error", code, message, _path_to_str(path), details))

    @property
    def warnings_count(self) -> int:
        return sum(1 for event in self.events if event.severity == "warning")

    @property
    def errors_count(self) -> int:
        return sum(1 for event in self.events if event.severity == "error")

    @property
    def warning_groups_count(self) -> int:
        return len(aggregate_events([event for event in self.events if event.severity == "warning"]))

    def to_dict(self) -> dict[str, Any]:
        warnings = aggregate_events([event for event in self.events if event.severity == "warning"])
        errors = [asdict(event) for event in self.events if event.severity == "error"]
        return {"project": self.project, "warnings": warnings, "errors": errors}

    def write(self, diagnostics_path: Path, encoding: str = "utf-8") -> None:
        diagnostics_path.mkdir(parents=True, exist_ok=True)
        target = diagnostics_path / "report-diagnostics.json"
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding=encoding)


def write_stats(stats: ReportStats, diagnostics_path: Path, encoding: str = "utf-8") -> None:
    diagnostics_path.mkdir(parents=True, exist_ok=True)
    target = diagnostics_path / "report-stats.json"
    target.write_text(json.dumps(asdict(stats), ensure_ascii=False, indent=2), encoding=encoding)


def utc_timestamp() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _path_to_str(path: Path | str | None) -> str | None:
    if path is None:
        return None
    return str(path)


def aggregate_events(events: list[DiagnosticEvent]) -> list[dict[str, Any]]:
    aggregate_codes = {"unsupportedComplexProperty", "unsupportedType"}
    result: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}

    for event in events:
        if event.code not in aggregate_codes:
            result.append(asdict(event))
            continue

        group_key = _aggregate_key(event)
        if group_key not in grouped:
            grouped[group_key] = {
                "severity": event.severity,
                "code": event.code,
                "message": event.message,
                "count": 0,
                "samplePaths": [],
                "details": event.details,
            }
        item = grouped[group_key]
        item["count"] += 1
        if event.path and len(item["samplePaths"]) < 10:
            item["samplePaths"].append(event.path)

    result.extend(grouped.values())
    return result


def _aggregate_key(event: DiagnosticEvent) -> tuple[str, str, str]:
    if event.code == "unsupportedType":
        return event.code, str(event.details.get("typeKey", "")), event.message
    if event.code == "unsupportedComplexProperty":
        property_name = event.message.rsplit(": ", 1)[-1]
        return event.code, property_name, event.message
    return event.code, event.message, ""
