from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .object_registry import ChildCollectionSpec, ObjectTypeSpec


DEFAULT_SETTINGS_PATH = Path(__file__).with_name("settings") / "defaults.json"


@dataclass(frozen=True, slots=True)
class ReportFormatSettings:
    encoding: str
    base_indent: int
    indent: str
    line_ending: str
    blank_line_between_root_sections: bool


@dataclass(frozen=True, slots=True)
class XmlStructureSettings:
    configuration_file_name: str
    metadata_object_wrapper: str
    properties_element_names: tuple[str, ...]
    child_objects_element_names: tuple[str, ...]
    internal_info_element_names: tuple[str, ...]
    localized_content_element_name: str
    special_nested_object_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RootObjectSettings:
    report_plural: str
    type_key: str


@dataclass(frozen=True, slots=True)
class GeneratorSettings:
    supported_encodings: tuple[str, ...]
    report_format: ReportFormatSettings
    xml_structure: XmlStructureSettings
    root_object: RootObjectSettings
    root_source_property_overrides: dict[str, dict[str, str]]
    property_aliases: dict[str, tuple[str, ...]]
    property_defaults: dict[str, str]
    blocked_output_property_names: tuple[str, ...]
    blocked_property_names: tuple[str, ...]
    blocked_property_fragments: tuple[str, ...]
    list_property_names: tuple[str, ...]
    inline_joined_list_property_names: tuple[str, ...]
    joined_list_property_names: tuple[str, ...]
    marker_property_names_with_colon: tuple[str, ...]
    empty_quoted_list_property_names: tuple[str, ...]
    empty_list_property_names: tuple[str, ...]
    suppressed_empty_property_names: tuple[str, ...]
    marker_default_property_names: tuple[str, ...]
    marker_property_names_by_type: dict[str, tuple[str, ...]]
    extension_inherited_property_names: tuple[str, ...]
    extension_synthetic_property_defaults_by_type: dict[str, dict[str, str]]
    extension_adopted_empty_property_names: tuple[str, ...]
    extension_adopted_suppressed_marker_property_names: tuple[str, ...]
    property_value_translations: dict[str, dict[str, str]]
    property_value_prefix_translations: dict[str, dict[str, str]]
    suppressed_property_value_prefixes: dict[str, tuple[str, ...]]
    compact_metadata_reference_property_names: tuple[str, ...]
    value_translations: dict[str, str]
    value_prefix_translations: dict[str, str]
    value_segment_translations: dict[str, str]
    standard_attribute_name_translations: dict[str, str]
    standard_attribute_property_defaults: dict[str, str]
    standard_attribute_keep_default_properties_by_name: dict[str, tuple[str, ...]]
    standard_attribute_keep_default_owner_attribute_properties: tuple[str, ...]
    standard_attribute_suppressed_properties_by_name: dict[str, tuple[str, ...]]
    standard_attribute_suppressed_properties_by_type_and_name: dict[str, dict[str, tuple[str, ...]]]
    standard_attribute_suppressed_values: dict[str, tuple[str, ...]]
    standard_attribute_suppressed_value_suffixes: tuple[str, ...]
    standard_attribute_suppressed_names: tuple[str, ...]
    standard_attribute_noisy_properties: tuple[str, ...]
    standard_attribute_keep_empty_value_names: tuple[str, ...]
    standard_attribute_keep_empty_value_owner_attributes: tuple[str, ...]
    characteristic_data_path_field_strategy: str
    characteristic_blank_field_values: tuple[str, ...]
    type_value_priority_values: tuple[str, ...]
    type_value_priority_prefixes: tuple[str, ...]
    type_value_late_values: tuple[str, ...]
    configuration_whitelist: tuple[str, ...]
    child_collections: dict[str, ChildCollectionSpec]
    object_types: tuple[ObjectTypeSpec, ...]
    raw: dict[str, Any]


def load_settings(path: Path | None = None) -> GeneratorSettings:
    settings_path = path or DEFAULT_SETTINGS_PATH
    if path is not None and settings_path != DEFAULT_SETTINGS_PATH:
        base = json.loads(DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8-sig"))
        override = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        raw = _deep_merge(base, override)
    else:
        raw = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    _validate_required_sections(raw, settings_path)
    common = tuple(raw.get("commonProperties", ()))
    child_collections = _build_child_collections(raw, common)
    return GeneratorSettings(
        supported_encodings=tuple(raw["supportedEncodings"]),
        report_format=_build_report_format(raw["reportFormat"]),
        xml_structure=_build_xml_structure(raw["xmlStructure"]),
        root_object=_build_root_object(raw["rootObject"]),
        root_source_property_overrides={
            str(source_kind): {str(name): str(value) for name, value in properties.items()}
            for source_kind, properties in raw.get("rootSourcePropertyOverrides", {}).items()
        },
        property_aliases={key: tuple(value) for key, value in raw.get("propertyAliases", {}).items()},
        property_defaults={str(key): str(value) for key, value in raw.get("propertyDefaults", {}).items()},
        blocked_output_property_names=tuple(raw.get("blockedOutputPropertyNames", ())),
        blocked_property_names=tuple(raw.get("blockedPropertyNames", ())),
        blocked_property_fragments=tuple(raw.get("blockedPropertyFragments", ())),
        list_property_names=tuple(raw.get("listPropertyNames", ())),
        inline_joined_list_property_names=tuple(raw.get("inlineJoinedListPropertyNames", ())),
        joined_list_property_names=tuple(raw.get("joinedListPropertyNames", ())),
        marker_property_names_with_colon=tuple(raw.get("markerPropertyNamesWithColon", ())),
        empty_quoted_list_property_names=tuple(raw.get("emptyQuotedListPropertyNames", ())),
        empty_list_property_names=tuple(raw.get("emptyListPropertyNames", ())),
        suppressed_empty_property_names=tuple(raw.get("suppressedEmptyPropertyNames", ())),
        marker_default_property_names=tuple(raw.get("markerDefaultPropertyNames", ())),
        marker_property_names_by_type={
            str(type_key): tuple(str(item) for item in value)
            for type_key, value in raw.get("markerPropertyNamesByType", {}).items()
        },
        extension_inherited_property_names=tuple(raw.get("extensionInheritedPropertyNames", ())),
        extension_synthetic_property_defaults_by_type={
            str(type_key): {str(prop): str(value) for prop, value in properties.items()}
            for type_key, properties in raw.get("extensionSyntheticPropertyDefaultsByType", {}).items()
        },
        extension_adopted_empty_property_names=tuple(raw.get("extensionAdoptedEmptyPropertyNames", ())),
        extension_adopted_suppressed_marker_property_names=tuple(raw.get("extensionAdoptedSuppressedMarkerPropertyNames", ())),
        property_value_translations={str(key): {str(source): str(target) for source, target in value.items()} for key, value in raw.get("propertyValueTranslations", {}).items()},
        property_value_prefix_translations={str(key): {str(source): str(target) for source, target in value.items()} for key, value in raw.get("propertyValuePrefixTranslations", {}).items()},
        suppressed_property_value_prefixes={str(key): tuple(str(item) for item in value) for key, value in raw.get("suppressedPropertyValuePrefixes", {}).items()},
        compact_metadata_reference_property_names=tuple(str(item) for item in raw.get("compactMetadataReferencePropertyNames", ())),
        value_translations={str(key): str(value) for key, value in raw["valueTranslations"].items()},
        value_prefix_translations={str(key): str(value) for key, value in raw["valuePrefixTranslations"].items()},
        value_segment_translations={str(key): str(value) for key, value in raw.get("valueSegmentTranslations", {}).items()},
        standard_attribute_name_translations={str(key): str(value) for key, value in raw.get("standardAttributeNameTranslations", {}).items()},
        standard_attribute_property_defaults={str(key): str(value) for key, value in raw.get("standardAttributePropertyDefaults", {}).items()},
        standard_attribute_keep_default_properties_by_name={str(key): tuple(str(item) for item in value) for key, value in raw.get("standardAttributeKeepDefaultPropertiesByName", {}).items()},
        standard_attribute_keep_default_owner_attribute_properties=tuple(
            str(item) for item in raw.get("standardAttributeKeepDefaultOwnerAttributeProperties", ())
        ),
        standard_attribute_suppressed_properties_by_name={str(key): tuple(str(item) for item in value) for key, value in raw.get("standardAttributeSuppressedPropertiesByName", {}).items()},
        standard_attribute_suppressed_properties_by_type_and_name={
            str(type_key): {
                str(name): tuple(str(item) for item in properties)
                for name, properties in value.items()
            }
            for type_key, value in raw.get("standardAttributeSuppressedPropertiesByTypeAndName", {}).items()
        },
        standard_attribute_suppressed_values={str(key): tuple(str(item) for item in value) for key, value in raw.get("standardAttributeSuppressedValues", {}).items()},
        standard_attribute_suppressed_value_suffixes=tuple(str(item) for item in raw.get("standardAttributeSuppressedValueSuffixes", ())),
        standard_attribute_suppressed_names=tuple(str(item) for item in raw.get("standardAttributeSuppressedNames", ())),
        standard_attribute_noisy_properties=tuple(str(item) for item in raw.get("standardAttributeNoisyProperties", ())),
        standard_attribute_keep_empty_value_names=tuple(str(item) for item in raw.get("standardAttributeKeepEmptyValueNames", ())),
        standard_attribute_keep_empty_value_owner_attributes=tuple(str(item) for item in raw.get("standardAttributeKeepEmptyValueOwnerAttributes", ())),
        characteristic_data_path_field_strategy=str(raw.get("characteristicDataPathFieldStrategy", "")),
        characteristic_blank_field_values=tuple(str(item) for item in raw.get("characteristicBlankFieldValues", ())),
        type_value_priority_values=tuple(str(item) for item in raw.get("typeValuePriorityValues", ())),
        type_value_priority_prefixes=tuple(str(item) for item in raw.get("typeValuePriorityPrefixes", ())),
        type_value_late_values=tuple(str(item) for item in raw.get("typeValueLateValues", ())),
        configuration_whitelist=_expand_whitelist(raw.get("configurationWhitelist", ()), common, child_collections),
        child_collections=child_collections,
        object_types=tuple(_build_object_type(item, common, child_collections) for item in raw.get("objectTypes", ())),
        raw=raw,
    )


def _build_report_format(raw: dict[str, Any]) -> ReportFormatSettings:
    return ReportFormatSettings(
        encoding=str(raw.get("encoding", "utf-16")),
        base_indent=int(raw["baseIndent"]),
        indent=str(raw["indent"]),
        line_ending=str(raw["lineEnding"]),
        blank_line_between_root_sections=bool(raw["blankLineBetweenRootSections"]),
    )


def _build_xml_structure(raw: dict[str, Any]) -> XmlStructureSettings:
    return XmlStructureSettings(
        configuration_file_name=str(raw["configurationFileName"]),
        metadata_object_wrapper=str(raw["metadataObjectWrapper"]),
        properties_element_names=tuple(raw["propertiesElementNames"]),
        child_objects_element_names=tuple(raw["childObjectsElementNames"]),
        internal_info_element_names=tuple(raw["internalInfoElementNames"]),
        localized_content_element_name=str(raw["localizedContentElementName"]),
        special_nested_object_files=tuple(raw["specialNestedObjectFiles"]),
    )


def _build_root_object(raw: dict[str, Any]) -> RootObjectSettings:
    return RootObjectSettings(
        report_plural=str(raw["reportPlural"]),
        type_key=str(raw["typeKey"]),
    )


def _validate_required_sections(raw: dict[str, Any], path: Path) -> None:
    required = (
        "supportedEncodings",
        "reportFormat",
        "xmlStructure",
        "rootObject",
        "commonProperties",
        "propertyAliases",
        "blockedOutputPropertyNames",
        "blockedPropertyNames",
        "blockedPropertyFragments",
        "valueTranslations",
        "valuePrefixTranslations",
        "childCollections",
        "configurationWhitelist",
        "objectTypes",
    )
    missing = [name for name in required if name not in raw]
    if missing:
        raise ValueError(f"Generator settings {path} missing required sections: {', '.join(missing)}")


def _build_child_collections(raw: dict[str, Any], common: tuple[str, ...]) -> dict[str, ChildCollectionSpec]:
    definitions: dict[str, Any] = raw.get("childCollections", {})
    built: dict[str, ChildCollectionSpec] = {}

    def build(name: str) -> ChildCollectionSpec:
        if name in built:
            return built[name]
        item = definitions[name]
        whitelist = _resolve_whitelist(item, common, built, definitions)
        nested = tuple(build(child_name) for child_name in item.get("childCollections", ()))
        spec = ChildCollectionSpec(
            folder_names=tuple(item.get("folderNames", ())),
            report_plural=str(item["reportPlural"]),
            type_key=str(item["typeKey"]),
            whitelist=whitelist,
            child_collections=nested,
            xml_element_names=tuple(item.get("xmlElementNames", ())),
            include_extra_properties=bool(item.get("includeExtraProperties", True)),
        )
        built[name] = spec
        return spec

    for key in definitions:
        build(key)
    return built


def _build_object_type(raw: dict[str, Any], common: tuple[str, ...], child_collections: dict[str, ChildCollectionSpec]) -> ObjectTypeSpec:
    folder_names = tuple(raw.get("folderNames", ()))
    return ObjectTypeSpec(
        type_key=str(raw["typeKey"]),
        folder_names=folder_names,
        report_plural=str(raw["reportPlural"]),
        whitelist=_expand_whitelist(raw.get("whitelist", ()), common, child_collections),
        child_collections=tuple(child_collections[name] for name in raw.get("childCollections", ())),
        xml_element_names=tuple(raw.get("xmlElementNames", ())) or _default_xml_element_names(folder_names),
        include_extra_properties=bool(raw.get("includeExtraProperties", True)),
        fallback_enabled=bool(raw.get("fallbackEnabled", False)),
        warn_on_fallback=bool(raw.get("warnOnFallback", False)),
    )


def _default_xml_element_names(folder_names: tuple[str, ...]) -> tuple[str, ...]:
    aliases = {
        "Enumerations": "Enum",
        "Enums": "Enum",
    }
    result: list[str] = []
    for folder_name in folder_names:
        if not folder_name or not folder_name.isascii():
            continue
        value = aliases.get(folder_name)
        if value is None:
            value = folder_name[:-1] if folder_name.endswith("s") else folder_name
        if value and value not in result:
            result.append(value)
    return tuple(result)


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _deep_merge(merged[key], value) if key in merged else value
        return merged
    return override


def _resolve_whitelist(
    raw: dict[str, Any],
    common: tuple[str, ...],
    built: dict[str, ChildCollectionSpec],
    definitions: dict[str, Any],
) -> tuple[str, ...]:
    if "whitelistRef" in raw:
        ref = str(raw["whitelistRef"])
        if ref in built:
            return built[ref].whitelist
        ref_raw = definitions[ref]
        return _resolve_whitelist(ref_raw, common, built, definitions)
    return _expand_whitelist(raw.get("whitelist", ()), common, built)


def _expand_whitelist(values: Any, common: tuple[str, ...], child_collections: dict[str, ChildCollectionSpec]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value == "@common":
            result.extend(common)
        elif isinstance(value, str) and value.startswith("@child:"):
            result.extend(child_collections[value.removeprefix("@child:")].whitelist)
        else:
            result.append(str(value))
    return tuple(result)
