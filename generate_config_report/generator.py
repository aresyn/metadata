from __future__ import annotations

import logging
from copy import deepcopy

from .config import ProjectConfig
from .diagnostics import Diagnostics, ReportStats, utc_timestamp, write_stats
from .metadata_model import MetadataObject, MetadataSection, ReportProperty
from .property_extractors import translate_value
from .report_writer import ReportWriter
from .settings import GeneratorSettings
from .xml_reader import XmlReader


EXIT_SUCCESS = 0
EXIT_WARNINGS = 1
EXIT_WARNINGS_AS_ERRORS = 2
EXIT_BAD_ARGS = 3
EXIT_MAIN_PATH_MISSING = 4
EXIT_NO_OBJECTS = 5
EXIT_REPORT_WRITE_ERROR = 6
EXIT_EXTENSION_REQUIRED_MISSING = 7
EXIT_CONFIG_READ_ERROR = 8
EXIT_NO_SOURCES = 9


class Generator:
    def __init__(self, config: ProjectConfig, diagnostics: Diagnostics, settings: GeneratorSettings, *, dry_run: bool = False) -> None:
        self.config = config
        self.diagnostics = diagnostics
        self.settings = settings
        self.dry_run = dry_run
        self.logger = logging.getLogger(__name__)

    def run(self) -> int:
        main_config_dir = self.config.main_config_dir
        extension_dir = self.config.extension_dir
        main_found = False
        if main_config_dir is None:
            if self.config.main_config_required:
                self.diagnostics.error("mainConfigPathMissing", "Main configuration path is not configured and mainConfigRequired=true")
                self._write_diagnostics_only(main_found=False, extension_found=False)
                return EXIT_MAIN_PATH_MISSING
        elif main_config_dir.is_dir():
            main_found = True
        elif self.config.main_config_required:
            self.diagnostics.error("mainConfigPathMissing", "Main configuration path not found", main_config_dir)
            self._write_diagnostics_only(main_found=False, extension_found=False)
            return EXIT_MAIN_PATH_MISSING
        else:
            self.diagnostics.warning("mainConfigMissing", "Main configuration path not found and mainConfigRequired=false", main_config_dir)

        extension_found = False
        if extension_dir is None:
            if self.config.extension_required:
                self.diagnostics.error("extensionRequiredMissing", "Extension path is not configured and extensionRequired=true")
                self._write_diagnostics_only(main_found=main_found, extension_found=False)
                return EXIT_EXTENSION_REQUIRED_MISSING
        elif extension_dir.is_dir():
            extension_found = True
        elif self.config.extension_required:
            self.diagnostics.error("extensionRequiredMissing", "Extension path not found and extensionRequired=true", extension_dir)
            self._write_diagnostics_only(main_found=main_found, extension_found=False)
            return EXIT_EXTENSION_REQUIRED_MISSING
        else:
            self.diagnostics.warning("extensionMissing", "Extension path not found and extensionRequired=false", extension_dir)

        if not main_found and not extension_found:
            self.diagnostics.error("noMetadataSources", "No metadata source directories found")
            self._write_diagnostics_only(main_found=False, extension_found=False)
            return EXIT_NO_SOURCES

        reader = XmlReader(self.diagnostics, self.settings)
        sections: list[MetadataSection] = []
        if main_found and main_config_dir is not None:
            main_section = reader.read_section(main_config_dir, "main")
            if main_section is not None:
                sections.append(main_section)
        if extension_found and extension_dir is not None:
            extension_section = reader.read_section(extension_dir, "extension")
            if extension_section is not None:
                sections.append(extension_section)
        self._apply_extension_inheritance(sections)

        object_count = sum(count_objects(section.root) for section in sections)
        if object_count == 0:
            self.diagnostics.error("noMetadataObjects", "No metadata objects found")
            self._write_diagnostics_only(main_found=main_found, extension_found=extension_found)
            return EXIT_NO_OBJECTS

        if not self.dry_run:
            try:
                self._write_report(sections)
            except OSError as exc:
                self.diagnostics.error("reportWriteError", f"Cannot write Report.txt: {exc}", self.config.report_path)
                self._write_diagnostics_only(main_found=main_found, extension_found=extension_found, sections=sections)
                return EXIT_REPORT_WRITE_ERROR

        self._write_diagnostics_only(main_found=main_found, extension_found=extension_found, sections=sections)
        return self._warning_aware_exit_code()

    def _write_report(self, sections: list[MetadataSection]) -> None:
        target = self.config.report_path
        temp_target = target.with_name(f"{target.name}.tmp")
        ReportWriter(
            self.settings.report_format,
            self.settings.joined_list_property_names,
            self.settings.marker_property_names_with_colon,
        ).write(sections, temp_target, self.settings.report_format.encoding)
        temp_target.replace(target)

    def _apply_extension_inheritance(self, sections: list[MetadataSection]) -> None:
        main_section = next((section for section in sections if section.source_kind == "main"), None)
        extension_section = next((section for section in sections if section.source_kind == "extension"), None)
        if main_section is None or extension_section is None:
            return
        main_by_name = {obj.full_name: obj for obj in iter_objects(main_section.root)}
        for extension_obj in iter_objects(extension_section.root):
            if not _is_adopted_object(extension_obj):
                continue
            main_obj = main_by_name.get(extension_obj.full_name)
            _apply_synthetic_defaults(
                extension_obj,
                self.settings.extension_synthetic_property_defaults_by_type.get(extension_obj.type_key, {}),
            )
            if main_obj is None:
                continue
            _suppress_adopted_markers(extension_obj, self.settings.extension_adopted_suppressed_marker_property_names)
            _inherit_properties(extension_obj, main_obj, self.settings.extension_inherited_property_names)
            _force_empty_properties(extension_obj, main_obj, self.settings.extension_adopted_empty_property_names)

    def _write_diagnostics_only(
        self,
        *,
        main_found: bool,
        extension_found: bool,
        sections: list[MetadataSection] | None = None,
    ) -> None:
        diagnostics_path = self.config.diagnostics_path
        if diagnostics_path is None:
            return
        sections = sections or []
        stats = ReportStats(
            project=self.config.project,
            mainConfigPath=str(self.config.main_config_path) if self.config.main_config_path is not None else None,
            mainConfigFound=main_found,
            mainConfigRequired=self.config.main_config_required,
            extensionPath=str(self.config.extension_path) if self.config.extension_path is not None else None,
            extensionFound=extension_found,
            extensionRequired=self.config.extension_required,
            generatedAt=utc_timestamp(),
            mainConfigurationObjects=sum(count_objects(section.root) for section in sections if section.source_kind == "main"),
            extensionObjects=sum(count_objects(section.root) for section in sections if section.source_kind == "extension"),
            objectsByType=objects_by_type(sections),
            warnings=self.diagnostics.warnings_count,
            warningEvents=self.diagnostics.warnings_count,
            warningGroups=self.diagnostics.warning_groups_count,
            errors=self.diagnostics.errors_count,
        )
        try:
            self.diagnostics.write(diagnostics_path, encoding="utf-8")
            write_stats(stats, diagnostics_path, encoding="utf-8")
        except OSError as exc:
            self.logger.error("Cannot write diagnostics: %s", exc)

    def _warning_aware_exit_code(self) -> int:
        if self.diagnostics.errors_count or (self.config.warnings_as_errors and self.diagnostics.warnings_count):
            return EXIT_WARNINGS_AS_ERRORS
        if self.diagnostics.warnings_count:
            return EXIT_WARNINGS
        return EXIT_SUCCESS


def count_objects(root: MetadataObject) -> int:
    return 1 + sum(count_objects(child) for child in root.children)


def iter_objects(root: MetadataObject):
    yield root
    for child in root.children:
        yield from iter_objects(child)


def _is_adopted_object(obj: MetadataObject) -> bool:
    belonging_name = translate_value("ObjectBelonging")
    adopted_value = translate_value("Adopted")
    return any(prop.name == belonging_name and prop.value == adopted_value for prop in obj.properties)


def _suppress_adopted_markers(obj: MetadataObject, marker_names: tuple[str, ...]) -> None:
    if not marker_names:
        return
    marker_set = set(marker_names)
    obj.properties = [prop for prop in obj.properties if not (prop.kind == "marker" and prop.name in marker_set)]


def _inherit_properties(obj: MetadataObject, main_obj: MetadataObject, property_names: tuple[str, ...]) -> None:
    if not property_names:
        return
    existing = {prop.name for prop in obj.properties}
    inherited_by_name = {prop.name: prop for prop in main_obj.properties if prop.name in property_names}
    merged = []
    for prop in main_obj.properties:
        if prop.name in inherited_by_name and prop.name not in existing:
            merged.append(deepcopy(prop))
        elif prop.name in existing:
            merged.append(next(current for current in obj.properties if current.name == prop.name))
    for prop in obj.properties:
        if prop.name not in {item.name for item in merged}:
            merged.append(prop)
    obj.properties = merged


def _force_empty_properties(obj: MetadataObject, main_obj: MetadataObject, property_names: tuple[str, ...]) -> None:
    if not property_names:
        return
    target = set(property_names)
    existing_by_name = {prop.name: prop for prop in obj.properties}
    main_names = {prop.name for prop in main_obj.properties}
    merged = []
    for prop in main_obj.properties:
        if prop.name in target and prop.name in main_names:
            current = existing_by_name.get(prop.name)
            if current is None:
                merged.append(ReportProperty(prop.name, ""))
            elif current.kind == "scalar":
                current.value = ""
                merged.append(current)
            else:
                merged.append(current)
        elif prop.name in existing_by_name:
            merged.append(existing_by_name[prop.name])
    merged_names = {prop.name for prop in merged}
    for prop in obj.properties:
        if prop.name not in merged_names:
            merged.append(prop)
    obj.properties = merged


def _apply_synthetic_defaults(obj: MetadataObject, defaults: dict[str, str]) -> None:
    if not defaults:
        return
    existing_names = {prop.name for prop in obj.properties}
    for prop_name, prop_value in defaults.items():
        if prop_name not in existing_names:
            obj.properties.append(ReportProperty(prop_name, prop_value, "scalar"))


def objects_by_type(sections: list[MetadataSection]) -> dict[str, int]:
    result: dict[str, int] = {}
    for section in sections:
        collect_types(section.root, result)
    return dict(sorted(result.items()))


def collect_types(obj: MetadataObject, result: dict[str, int]) -> None:
    result[obj.type_key] = result.get(obj.type_key, 0) + 1
    for child in obj.children:
        collect_types(child, result)
