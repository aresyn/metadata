from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from .property_extractors import (
    _attribute_value_by_local_name,
    _properties_root,
    configure_extractor,
    extract_name,
    local_name,
    payload_element,
)
from .settings import GeneratorSettings, load_settings


def build_xml_overrides(
    repo_path: Path,
    main_config_path: str | Path,
    extension_path: str | Path,
    output_path: Path,
    generator_settings_path: Path | None = None,
) -> Path:
    settings = load_settings(generator_settings_path) if generator_settings_path is not None and generator_settings_path.exists() else load_settings()
    configure_extractor(settings)

    repo_path = repo_path.expanduser()
    output_path = output_path.expanduser()

    pairs = collect_standard_attribute_keep_empty_overrides(
        repo_path / Path(main_config_path),
        repo_path / Path(extension_path),
        settings,
    )
    keep_default_triplets = collect_standard_attribute_keep_default_overrides(
        repo_path / Path(main_config_path),
        repo_path / Path(extension_path),
        settings,
    )
    output = {
        "standardAttributeKeepEmptyValueOwnerAttributes": pairs,
        "standardAttributeKeepDefaultOwnerAttributeProperties": keep_default_triplets,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate-config-report-build-overrides")
    parser.add_argument("--repo-path", required=True, help="Path to repository root")
    parser.add_argument("--main-config-path", default="src/cf", help="Main configuration relative path")
    parser.add_argument("--extension-path", default="src/cfe", help="Extension relative path")
    parser.add_argument("--output", required=True, help="Output override JSON path")
    parser.add_argument("--generator-settings", help="Optional custom base generator settings path")
    args = parser.parse_args(argv)

    build_xml_overrides(
        repo_path=Path(args.repo_path),
        main_config_path=args.main_config_path,
        extension_path=args.extension_path,
        output_path=Path(args.output),
        generator_settings_path=Path(args.generator_settings).expanduser() if args.generator_settings else None,
    )
    return 0


def collect_standard_attribute_keep_empty_overrides(
    main_config_dir: Path,
    extension_dir: Path,
    settings: GeneratorSettings,
) -> list[str]:
    configure_extractor(settings)
    pairs: set[str] = set()
    pairs.update(_collect_catalog_pairs(main_config_dir, settings))
    if extension_dir.is_dir():
        pairs.update(_collect_catalog_pairs(extension_dir, settings))
    return sorted(pairs)


def collect_standard_attribute_keep_default_overrides(
    main_config_dir: Path,
    extension_dir: Path,
    settings: GeneratorSettings,
) -> list[str]:
    configure_extractor(settings)
    pairs: set[str] = set()
    pairs.update(_collect_catalog_default_pairs(main_config_dir, settings))
    if extension_dir.is_dir():
        pairs.update(_collect_catalog_default_pairs(extension_dir, settings))
    return sorted(pairs)


def _collect_catalog_pairs(config_dir: Path, settings: GeneratorSettings) -> set[str]:
    folder = config_dir / "Catalogs"
    if not folder.is_dir():
        return set()
    catalog_plural = _catalog_plural(settings)
    owner_name = settings.standard_attribute_name_translations.get("Owner", "Owner")
    parent_name = settings.standard_attribute_name_translations.get("Parent", "Parent")
    result: set[str] = set()
    for xml_file in sorted(folder.glob("*.xml"), key=lambda item: item.name.casefold()):
        root = _parse_payload(xml_file, settings)
        if root is None:
            continue
        properties = _properties_root(root)
        if properties is None:
            continue
        name = extract_name(root, settings, fallback=xml_file.stem)
        if not name:
            continue
        catalog = _catalog_signature(properties)
        standard_attributes = next((child for child in list(properties) if local_name(child.tag) == "StandardAttributes"), None)
        if standard_attributes is None:
            continue
        full_name = f"{catalog_plural}.{name}"
        if _should_keep_empty_parent(name, catalog) and _standard_attribute_has_empty_fill(standard_attributes, "Parent"):
            result.add(f"{full_name}|{parent_name}")
        if _should_keep_empty_owner(name, catalog) and _standard_attribute_has_empty_fill(standard_attributes, "Owner"):
            result.add(f"{full_name}|{owner_name}")
    return result


def _collect_catalog_default_pairs(config_dir: Path, settings: GeneratorSettings) -> set[str]:
    folder = config_dir / "Catalogs"
    if not folder.is_dir():
        return set()
    catalog_plural = _catalog_plural(settings)
    description_name = settings.standard_attribute_name_translations.get("Description", "Description")
    fill_checking_name = next(
        (output_name for output_name, aliases in settings.property_aliases.items() if "FillChecking" in aliases),
        "FillChecking",
    )
    result: set[str] = set()
    for xml_file in sorted(folder.glob("*.xml"), key=lambda item: item.name.casefold()):
        root = _parse_payload(xml_file, settings)
        if root is None:
            continue
        properties = _properties_root(root)
        if properties is None:
            continue
        name = extract_name(root, settings, fallback=xml_file.stem)
        if not name:
            continue
        standard_attributes = next((child for child in list(properties) if local_name(child.tag) == "StandardAttributes"), None)
        if standard_attributes is None:
            continue
        if not _standard_attribute_has_fill_checking(standard_attributes, "Description", "DontCheck"):
            continue
        result.add(f"{catalog_plural}.{name}|{description_name}|{fill_checking_name}")
    return result


def _catalog_signature(properties: ET.Element) -> dict[str, str | int | bool | None]:
    hierarchical = _property_text(properties, "Hierarchical") == "true"
    subordination_use = _property_text(properties, "SubordinationUse")
    comment = _property_text(properties, "Comment") or ""
    return {
        "hierarchical": hierarchical,
        "subordination_use": subordination_use,
        "use_standard_commands": _property_text(properties, "UseStandardCommands"),
        "code_length": _property_text(properties, "CodeLength"),
        "description_length": _property_text(properties, "DescriptionLength"),
        "create_on_input": _property_text(properties, "CreateOnInput"),
        "has_input_by_string": _property_has_content(properties, "InputByString"),
        "quick_choice": _property_text(properties, "QuickChoice"),
        "owners_count": _collection_count(properties, "Owners"),
        "comment": comment,
        "has_comment": bool(comment),
    }


def _should_keep_empty_owner(name: str, catalog: dict[str, str | int | bool | None]) -> bool:
    if catalog["hierarchical"] or not _uses_subordination(_text_value(catalog["subordination_use"])):
        return False
    if _is_attached_file_catalog(name, catalog):
        return True
    if _is_files_root_catalog(name, catalog):
        return True
    if _is_owner_account_catalog(name, catalog):
        return True
    return False


def _should_keep_empty_parent(name: str, catalog: dict[str, str | int | bool | None]) -> bool:
    if not catalog["hierarchical"]:
        return False
    return _is_extension_hierarchy_catalog(name, catalog)


def _is_attached_file_catalog(name: str, catalog: dict[str, str | int | bool | None]) -> bool:
    return (
        name.endswith("ПрисоединенныеФайлы")
        and _text_value(catalog["use_standard_commands"]) == "false"
        and _text_value(catalog["code_length"]) == "0"
        and _text_value(catalog["description_length"]) == "150"
        and _text_value(catalog["create_on_input"]) == "DontUse"
        and _bool_value(catalog["has_input_by_string"])
        and _int_value(catalog["owners_count"]) == 0
        and not _bool_value(catalog["has_comment"])
    )


def _is_files_root_catalog(name: str, catalog: dict[str, str | int | bool | None]) -> bool:
    return (
        name == "Файлы"
        and _text_value(catalog["use_standard_commands"]) == "false"
        and _text_value(catalog["code_length"]) == "0"
        and _text_value(catalog["description_length"]) == "150"
        and _int_value(catalog["owners_count"]) == 0
    )


def _is_owner_account_catalog(name: str, catalog: dict[str, str | int | bool | None]) -> bool:
    return (
        name.startswith("УчетныеЗаписи")
        and _text_value(catalog["code_length"]) == "0"
        and _text_value(catalog["description_length"]) == "100"
        and _int_value(catalog["owners_count"]) == 1
    )


def _is_extension_hierarchy_catalog(name: str, catalog: dict[str, str | int | bool | None]) -> bool:
    comment = _text_value(catalog["comment"]).casefold()
    marker = "расширен"
    return (
        _text_value(catalog["code_length"]) == "0"
        and _text_value(catalog["description_length"]) == "150"
        and _bool_value(catalog["has_comment"])
        and ("расширен" in name.casefold() or marker in comment)
    )


def _collection_count(properties: ET.Element, name: str) -> int:
    node = next((child for child in list(properties) if local_name(child.tag) == name), None)
    if node is None:
        return 0
    return len(list(node))


def _text_value(value: str | int | bool | None) -> str:
    return "" if value is None else str(value)


def _int_value(value: str | int | bool | None) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(_text_value(value))
    except ValueError:
        return 0


def _bool_value(value: str | int | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return _text_value(value).casefold() == "true"


def _catalog_plural(settings: GeneratorSettings) -> str:
    for spec in settings.object_types:
        if spec.type_key == "catalog":
            return spec.report_plural
    return "Справочники"


def _parse_payload(xml_file: Path, settings: GeneratorSettings) -> ET.Element | None:
    try:
        root = ET.parse(xml_file).getroot()
    except (OSError, ET.ParseError):
        return None
    return payload_element(root, settings)


def _property_text(properties: ET.Element, name: str) -> str | None:
    node = next((child for child in list(properties) if local_name(child.tag) == name), None)
    if node is None or node.text is None:
        return None
    return node.text.strip()


def _property_has_content(properties: ET.Element, name: str) -> bool:
    node = next((child for child in list(properties) if local_name(child.tag) == name), None)
    if node is None:
        return False
    if node.text and node.text.strip():
        return True
    for child in node.iter():
        if child is node:
            continue
        if child.text and child.text.strip():
            return True
    return False


def _uses_subordination(value: str | None) -> bool:
    return value not in {None, "", "NotUse"}


def _standard_attribute_has_empty_fill(standard_attributes: ET.Element, name: str) -> bool:
    for standard_attribute in list(standard_attributes):
        if local_name(standard_attribute.tag) != "StandardAttribute":
            continue
        if standard_attribute.attrib.get("name") != name:
            continue
        fill_value = next((child for child in list(standard_attribute) if local_name(child.tag) == "FillValue"), None)
        if fill_value is None:
            return False
        if _attribute_value_by_local_name(fill_value, "nil") == "true":
            return True
        if fill_value.text is None:
            return True
        return fill_value.text.strip().endswith(".EmptyRef")
    return False


def _standard_attribute_has_fill_checking(standard_attributes: ET.Element, name: str, expected: str) -> bool:
    for standard_attribute in list(standard_attributes):
        if local_name(standard_attribute.tag) != "StandardAttribute":
            continue
        if standard_attribute.attrib.get("name") != name:
            continue
        fill_checking = next((child for child in list(standard_attribute) if local_name(child.tag) == "FillChecking"), None)
        if fill_checking is None or fill_checking.text is None:
            return False
        return fill_checking.text.strip() == expected
    return False


if __name__ == "__main__":
    raise SystemExit(main())
