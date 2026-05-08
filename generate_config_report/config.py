from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .settings import load_settings


class ConfigError(Exception):
    pass


class ConfigReadError(ConfigError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    project: str
    repo_path: Path
    main_config_path: Path
    output_path: Path
    report_file_name: str
    extension_path: Path = Path("src/cfe")
    extension_required: bool = False
    diagnostics_path: Path | None = None
    logs_path: Path | None = None
    generator_settings_path: Path | None = None
    build_xml_overrides: bool = False
    encoding: str = "utf-8"
    warnings_as_errors: bool = False

    @property
    def main_config_dir(self) -> Path:
        return _join_if_relative(self.repo_path, self.main_config_path)

    @property
    def extension_dir(self) -> Path:
        return _join_if_relative(self.repo_path, self.extension_path)

    @property
    def report_path(self) -> Path:
        return self.output_path / self.report_file_name


def load_config(path: Path, *, strict: bool = False) -> ProjectConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ConfigReadError(f"Cannot read config file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigReadError(f"Cannot parse config JSON: {path}") from exc

    required = ("project", "repoPath", "mainConfigPath", "outputPath", "reportFileName")
    missing = [name for name in required if not raw.get(name)]
    if missing:
        raise ConfigError(f"Missing required config fields: {', '.join(missing)}")

    generator_settings_path = _optional_path(raw.get("generatorSettingsPath"))
    build_xml_overrides = bool(raw.get("buildXmlOverrides", False))
    settings = load_settings(generator_settings_path) if (generator_settings_path is not None and generator_settings_path.exists()) else load_settings()

    encoding = str(raw.get("encoding", "utf-8")).lower()
    if encoding not in settings.supported_encodings:
        raise ConfigError(f"Unsupported encoding: {encoding}")

    warnings_as_errors = bool(raw.get("warningsAsErrors", False)) or strict
    diagnostics_path = _optional_path(raw.get("diagnosticsPath"))
    logs_path = _optional_path(raw.get("logsPath"))

    return ProjectConfig(
        project=str(raw["project"]),
        repo_path=Path(str(raw["repoPath"])).expanduser(),
        main_config_path=Path(str(raw["mainConfigPath"])),
        extension_path=Path(str(raw.get("extensionPath", "src/cfe"))),
        extension_required=bool(raw.get("extensionRequired", False)),
        output_path=Path(str(raw["outputPath"])).expanduser(),
        report_file_name=str(raw["reportFileName"]),
        diagnostics_path=diagnostics_path,
        logs_path=logs_path,
        generator_settings_path=generator_settings_path,
        build_xml_overrides=build_xml_overrides,
        encoding=encoding,
        warnings_as_errors=warnings_as_errors,
    )


def _optional_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value)).expanduser()


def _join_if_relative(base: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return base / path
