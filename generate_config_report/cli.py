from __future__ import annotations

import argparse
import logging
import logging.config
import tempfile
from datetime import datetime
from pathlib import Path

from .config import ConfigError, ConfigReadError, ProjectConfig, load_config
from .build_xml_overrides import build_xml_overrides
from .diagnostics import Diagnostics
from .generator import EXIT_BAD_ARGS, EXIT_CONFIG_READ_ERROR, Generator
from .settings import DEFAULT_SETTINGS_PATH, load_settings


SIMPLE_REPORT_FILE_NAME = "ОтчетПоКонфигурации.txt"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate_config_report.py",
        description="Generate a 1C configuration report from XML metadata dump.",
    )
    parser.add_argument(
        "target_config_dir",
        nargs="?",
        help=f"Path to 1C XML configuration directory; writes {SIMPLE_REPORT_FILE_NAME} there",
    )
    parser.add_argument("--config", help="Path to project config JSON")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without writing the report")
    args = parser.parse_args(argv)

    if args.target_config_dir and args.config:
        parser.error("Specify either target_config_dir or --config, not both")
    if not args.target_config_dir and not args.config:
        parser.error("Specify target_config_dir or --config")
    if args.target_config_dir:
        return _run_simple_config(Path(args.target_config_dir).expanduser(), verbose=args.verbose, strict=args.strict, dry_run=args.dry_run)

    config_path = Path(args.config).expanduser()
    try:
        config = load_config(config_path, strict=args.strict)
    except ConfigReadError as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.error("%s", exc)
        return EXIT_CONFIG_READ_ERROR
    except ConfigError as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.error("%s", exc)
        return EXIT_BAD_ARGS

    return _run_config(config, verbose=args.verbose, dry_run=args.dry_run)


def _run_simple_config(target_config_dir: Path, *, verbose: bool, strict: bool, dry_run: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="generate-config-report-") as tmp:
        config = ProjectConfig(
            project=target_config_dir.name or "configuration",
            repo_path=target_config_dir,
            main_config_path=Path("."),
            main_config_required=True,
            extension_path=None,
            extension_required=False,
            output_path=target_config_dir,
            report_file_name=SIMPLE_REPORT_FILE_NAME,
            diagnostics_path=None,
            logs_path=None,
            generator_settings_path=Path(tmp) / "xml-overrides.json",
            build_xml_overrides=True,
            encoding="utf-16",
            warnings_as_errors=strict,
        )
        return _run_config(config, verbose=verbose, dry_run=dry_run)


def _run_config(config: ProjectConfig, *, verbose: bool, dry_run: bool) -> int:
    _configure_logging(config.logs_path, verbose=verbose)
    generator_settings_path = config.generator_settings_path
    if config.build_xml_overrides:
        generator_settings_path = _resolve_xml_overrides_output_path(config)
        build_xml_overrides(
            repo_path=config.repo_path,
            main_config_path=config.main_config_path,
            extension_path=config.extension_path,
            output_path=generator_settings_path,
        )
    settings = load_settings(generator_settings_path)
    diagnostics = Diagnostics(config.project)
    logging.info("Starting Report.txt generation for project %s", config.project)
    logging.info("Main configuration path: %s", config.main_config_dir if config.main_config_dir is not None else "disabled")
    logging.info("Extension path: %s", config.extension_dir if config.extension_dir is not None else "disabled")
    if config.build_xml_overrides:
        logging.info("XML overrides generated at: %s", generator_settings_path)
    try:
        effective_config = config if generator_settings_path == config.generator_settings_path else config.__class__(
            project=config.project,
            repo_path=config.repo_path,
            main_config_path=config.main_config_path,
            output_path=config.output_path,
            report_file_name=config.report_file_name,
            main_config_required=config.main_config_required,
            extension_path=config.extension_path,
            extension_required=config.extension_required,
            diagnostics_path=config.diagnostics_path,
            logs_path=config.logs_path,
            generator_settings_path=generator_settings_path,
            build_xml_overrides=config.build_xml_overrides,
            encoding=config.encoding,
            warnings_as_errors=config.warnings_as_errors,
        )
        return Generator(effective_config, diagnostics, settings, dry_run=dry_run).run()
    finally:
        logging.shutdown()


def _configure_logging(logs_path: Path | None, *, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if logs_path is not None:
        logs_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        handlers.append(logging.FileHandler(logs_path / f"generate-config-report-{timestamp}.log", encoding="utf-8"))
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


def _resolve_xml_overrides_output_path(config) -> Path:
    if config.generator_settings_path is not None:
        return config.generator_settings_path
    return DEFAULT_SETTINGS_PATH.parent / "generated" / f"{config.project}.xml-overrides.json"
