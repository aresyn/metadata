from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from .diagnostics import Diagnostics
from .metadata_model import ReportProperty
from .settings import GeneratorSettings


GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def extract_name(root: ET.Element, settings: GeneratorSettings, fallback: str | None = None) -> str:
    value = _attribute_value(root, settings.property_aliases.get(translate_value("Name"), ("name", "Name")))
    if value:
        return value
    prop = extract_property(root, translate_value("Name"), settings)
    if prop and isinstance(prop.value, str) and prop.value:
        return prop.value
    return fallback or ""


def extract_properties(
    root: ET.Element,
    whitelist: tuple[str, ...],
    diagnostics: Diagnostics,
    settings: GeneratorSettings,
    *,
    include_extra_properties: bool = True,
    owner_name: str | None = None,
    owner_type_key: str | None = None,
    path: str | None = None,
) -> list[ReportProperty]:
    properties: list[ReportProperty] = []
    used_xml_names: set[str] = set()
    used_output_names: set[str] = set()

    for output_name in whitelist:
        prop, xml_names = extract_property_with_used_names(
            root,
            output_name,
            settings,
            owner_name=owner_name,
            owner_type_key=owner_type_key,
        )
        used_xml_names.update(xml_names)
        if prop is None:
            continue
        properties.append(prop)
        used_output_names.add(output_name)

    if include_extra_properties:
        extras = extract_extra_properties(
            root,
            used_xml_names,
            used_output_names,
            diagnostics,
            settings,
            owner_name=owner_name,
            owner_type_key=owner_type_key,
            path=path,
        )
        properties.extend(sorted(extras, key=lambda item: item.name.casefold()))
    return properties


def extract_property(root: ET.Element, output_name: str, settings: GeneratorSettings) -> ReportProperty | None:
    prop, _ = extract_property_with_used_names(root, output_name, settings)
    return prop


def extract_property_with_used_names(
    root: ET.Element,
    output_name: str,
    settings: GeneratorSettings,
    *,
    owner_name: str | None = None,
    owner_type_key: str | None = None,
) -> tuple[ReportProperty | None, set[str]]:
    if output_name in settings.blocked_output_property_names:
        return None, set()
    aliases = settings.property_aliases.get(output_name, (output_name,))
    values: list[str] = []
    used: set[str] = set()
    force_marker = owner_type_key is not None and output_name in settings.marker_property_names_by_type.get(owner_type_key, ())

    attr = _attribute_value(root, aliases)
    if attr is not None:
        values.append(_format_property_value(output_name, attr))
        used.update(aliases)

    for node in _candidate_property_nodes(root, aliases):
        used.add(local_name(node.tag))
        if output_name == translate_value("Name"):
            name_value = _direct_property_value(node)
            if name_value is not None:
                values.append(name_value)
                continue
        if output_name == "\u041a\u043b\u044e\u0447":
            key_value = _direct_property_value(node, allow_unsafe=True)
            if key_value is not None:
                values.append(key_value)
                continue
        special = _special_property(
            output_name,
            node,
            settings,
            owner_name=owner_name,
            owner_type_key=owner_type_key,
        )
        if special is not None:
            return special, used
        converted = simple_value(node)
        if converted is None:
            continue
        if isinstance(converted, str):
            converted = _normalize_fill_value(output_name, converted, root, settings)
        if isinstance(converted, list):
            values.extend(converted)
        else:
            values.append(converted)

    values = [_translate_property_value(output_name, value, settings) for value in _deduplicate(values)]
    if force_marker and used:
        return ReportProperty(output_name, "", "marker"), used
    if not values:
        if output_name in settings.marker_default_property_names:
            return ReportProperty(output_name, "", "marker"), used
        if output_name in settings.empty_quoted_list_property_names and used:
            return ReportProperty(output_name, [""], "list"), used
        if output_name in settings.empty_list_property_names and used:
            return ReportProperty(output_name, [], "list"), used
        if output_name in settings.property_defaults:
            default = format_value(settings.property_defaults[output_name])
            return ReportProperty(output_name, default, "scalar"), used
        return None, used
    if output_name in settings.inline_joined_list_property_names:
        return ReportProperty(output_name, ", ".join(values), "scalar"), used
    if values == [""] and output_name in settings.suppressed_empty_property_names:
        return None, used
    if values == [""] and output_name in settings.empty_list_property_names:
        return ReportProperty(output_name, [], "list"), used
    if len(values) == 1 and output_name not in settings.list_property_names:
        return ReportProperty(output_name, values[0], "scalar"), used
    return ReportProperty(output_name, values, "list"), used


def _special_property(
    output_name: str,
    node: ET.Element,
    settings: GeneratorSettings,
    *,
    owner_name: str | None = None,
    owner_type_key: str | None = None,
) -> ReportProperty | None:
    node_name = local_name(node.tag)
    if node_name == "StandardAttributes":
        groups = _standard_attributes(
            node,
            settings,
            owner_name=owner_name,
            owner_type_key=owner_type_key,
        )
        if not groups:
            return ReportProperty(output_name, "", "marker")
        return ReportProperty(output_name, groups, "named_object_list")
    if node_name == "Characteristics":
        groups = _characteristics(node)
        if not groups:
            return ReportProperty(output_name, "", "marker")
        return ReportProperty(output_name, groups, "object_list")
    return None


def extract_extra_properties(
    root: ET.Element,
    used_xml_names: set[str],
    used_output_names: set[str],
    diagnostics: Diagnostics,
    settings: GeneratorSettings,
    *,
    owner_name: str | None = None,
    owner_type_key: str | None = None,
    path: str | None = None,
) -> list[ReportProperty]:
    properties_root = _properties_root(root)
    candidates = list(properties_root) if properties_root is not None else list(root)
    result: list[ReportProperty] = []

    for node in candidates:
        name = local_name(node.tag)
        output_name = _output_name_for_xml_name(name, settings) or name
        if (
            name in used_xml_names
            or output_name in used_output_names
            or output_name in settings.blocked_output_property_names
            or is_blocked_property_name(name, settings)
        ):
            continue
        special = _special_property(
            output_name,
            node,
            settings,
            owner_name=owner_name,
            owner_type_key=owner_type_key,
        )
        if special is not None:
            result.append(special)
            continue
        converted = simple_value(node)
        if converted is None:
            if list(node):
                diagnostics.warning("unsupportedComplexProperty", f"Skipped complex XML property: {name}", path)
            continue
        if isinstance(converted, str):
            converted = _normalize_fill_value(output_name, converted, root, settings)
        if isinstance(converted, list):
            if converted:
                converted = [_translate_property_value(output_name, value, settings) for value in converted]
                if output_name in settings.inline_joined_list_property_names:
                    result.append(ReportProperty(output_name, ", ".join(converted), "scalar"))
                    continue
                kind = "list" if output_name in settings.list_property_names else "scalar"
                value: str | list[str] = converted if kind == "list" or len(converted) != 1 else converted[0]
                result.append(ReportProperty(output_name, value, kind))
            elif output_name in settings.empty_list_property_names:
                result.append(ReportProperty(output_name, [], "list"))
        else:
            converted = _translate_property_value(output_name, converted, settings)
            if converted == "" and output_name in settings.suppressed_empty_property_names:
                continue
            if converted == "" and output_name in settings.empty_list_property_names:
                result.append(ReportProperty(output_name, [], "list"))
                continue
            if output_name in settings.list_property_names:
                result.append(ReportProperty(output_name, [converted], "list"))
            else:
                result.append(ReportProperty(output_name, converted, "scalar"))
    return result


def _translate_property_value(output_name: str, value: str, settings: GeneratorSettings) -> str:
    for prefix in settings.suppressed_property_value_prefixes.get(output_name, ()):
        if value.startswith(prefix):
            return ""
    prefix_translations = settings.property_value_prefix_translations.get(output_name)
    if prefix_translations:
        for source_prefix, target_prefix in prefix_translations.items():
            if value.startswith(source_prefix):
                value = target_prefix + value[len(source_prefix):]
                break
    translations = settings.property_value_translations.get(output_name)
    if not translations:
        return value
    return translations.get(value, value)


def simple_value(node: ET.Element) -> str | list[str] | None:
    name = local_name(node.tag)
    if name == "Type":
        return _type_values(node)
    if name in {"XDTOReturningValueType", "XDTOValueType"}:
        return _xdto_type_value(node)
    if name == "ToolTip":
        return _localized_content(list(node)) or ""
    if name == "ChoiceParameterLinks":
        return _choice_parameter_links(node)
    if name == "ChoiceParameters":
        return _choice_parameters(node)
    if name == "Content":
        return _content_values(node)
    if name == "InputByString":
        return _input_by_string_values(node)
    if name in {"XDTOPackages", "RegisteredDocuments", "Source", "BasedOn", "References", "DataLockFields"}:
        return _metadata_reference_values(node)
    if name == "Picture":
        return _first_descendant_value(node, {"Ref"})
    if name == "Value":
        return _style_value(node)
    if name == "FillValue":
        return _fill_value(node)
    if name == "StandardAttributes":
        return []

    children = [child for child in list(node) if _has_content(child)]
    text = _clean_text(node.text)
    if not children:
        if text is None:
            return ""
        if is_unsafe_value(text):
            return None
        return format_value(text)

    localized = _localized_content(children)
    if localized is not None:
        return localized

    values: list[str] = []
    for child in children:
        if list(child):
            return None
        child_text = _clean_text(child.text)
        child_attr = _attribute_value(child, ("name", "Name", "value", "Value", "ref", "Ref"))
        value = child_text if child_text is not None else child_attr
        if value is None:
            return None
        if is_unsafe_value(value):
            return None
        values.append(format_value(value))
    return _deduplicate(values)


def payload_element(root: ET.Element, settings: GeneratorSettings) -> ET.Element:
    if local_name(root.tag) != settings.xml_structure.metadata_object_wrapper:
        return root
    for child in list(root):
        if local_name(child.tag) not in settings.xml_structure.internal_info_element_names:
            return child
    return root


def format_value(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    lowered = text.lower()
    translated_lower = translate_value(lowered)
    if translated_lower != lowered:
        return translated_lower
    return translate_value(text)


def _format_property_value(output_name: str, value: object) -> str:
    if output_name == translate_value("Name"):
        return str(value).strip()
    return format_value(value)


def is_blocked_property_name(name: str, settings: GeneratorSettings) -> bool:
    if name in settings.blocked_property_names:
        return True
    return any(fragment in name for fragment in settings.blocked_property_fragments)


def is_unsafe_value(value: str) -> bool:
    text = value.strip()
    if GUID_RE.match(text):
        return True
    if "\x00" in text:
        return True
    lowered = text.lower()
    if lowered.endswith((".bsl", ".os", ".xml")) and ("/" in text or "\\" in text):
        return True
    return False


def _candidate_property_nodes(root: ET.Element, aliases: tuple[str, ...]) -> list[ET.Element]:
    candidates: list[ET.Element] = []
    properties = _properties_root(root)
    search_roots = [properties, root] if properties is not None else [root]
    for search_root in search_roots:
        if search_root is None:
            continue
        for child in list(search_root):
            if local_name(child.tag) in aliases:
                candidates.append(child)
    return candidates


def _properties_root(root: ET.Element) -> ET.Element | None:
    for child in list(root):
        if local_name(child.tag) in _CURRENT_PROPERTIES_NAMES:
            return child
    return None


def _localized_content(children: list[ET.Element]) -> str | None:
    contents: list[str] = []
    for child in children:
        for grandchild in child.iter():
            if local_name(grandchild.tag) == _CURRENT_LOCALIZED_CONTENT_NAME:
                value = _clean_localized_text(grandchild.text)
                if value is not None:
                    contents.append(value)
    if not contents:
        return None
    return contents[0]


def _attribute_value(root: ET.Element, names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in root.attrib and str(root.attrib[name]).strip():
            return str(root.attrib[name]).strip()
    for attr_name, attr_value in root.attrib.items():
        if local_name(attr_name) in names and str(attr_value).strip():
            return str(attr_value).strip()
    return None


def _attribute_value_by_local_name(root: ET.Element, name: str) -> str | None:
    for attr_name, attr_value in root.attrib.items():
        if local_name(attr_name) == name:
            return str(attr_value).strip()
    return None


def _output_name_for_xml_name(xml_name: str, settings: GeneratorSettings) -> str | None:
    for output_name, aliases in settings.property_aliases.items():
        if xml_name in aliases:
            return output_name
    return None


_CURRENT_PROPERTIES_NAMES: set[str] = set()
_CURRENT_LOCALIZED_CONTENT_NAME = ""
_CURRENT_VALUE_TRANSLATIONS: dict[str, str] = {}
_CURRENT_VALUE_PREFIX_TRANSLATIONS: dict[str, str] = {}
_CURRENT_VALUE_SEGMENT_TRANSLATIONS: dict[str, str] = {}
_CURRENT_XML_NAME_TO_OUTPUT_NAME: dict[str, str] = {}
_CURRENT_STANDARD_ATTRIBUTE_NAME_TRANSLATIONS: dict[str, str] = {}
_CURRENT_CHARACTERISTIC_DATA_PATH_FIELD_STRATEGY = ""
_CURRENT_CHARACTERISTIC_BLANK_FIELD_VALUES: set[str] = set()
_CURRENT_TYPE_VALUE_PRIORITY_VALUES: tuple[str, ...] = ()
_CURRENT_TYPE_VALUE_PRIORITY_PREFIXES: tuple[str, ...] = ()
_CURRENT_TYPE_VALUE_LATE_VALUES: tuple[str, ...] = ()
_CURRENT_COMPACT_METADATA_REFERENCE_PROPERTY_NAMES: set[str] = set()


def configure_extractor(settings: GeneratorSettings) -> None:
    global _CURRENT_PROPERTIES_NAMES, _CURRENT_LOCALIZED_CONTENT_NAME, _CURRENT_VALUE_TRANSLATIONS, _CURRENT_VALUE_PREFIX_TRANSLATIONS, _CURRENT_VALUE_SEGMENT_TRANSLATIONS, _CURRENT_XML_NAME_TO_OUTPUT_NAME, _CURRENT_STANDARD_ATTRIBUTE_NAME_TRANSLATIONS, _CURRENT_CHARACTERISTIC_DATA_PATH_FIELD_STRATEGY, _CURRENT_CHARACTERISTIC_BLANK_FIELD_VALUES, _CURRENT_TYPE_VALUE_PRIORITY_VALUES, _CURRENT_TYPE_VALUE_PRIORITY_PREFIXES, _CURRENT_TYPE_VALUE_LATE_VALUES, _CURRENT_COMPACT_METADATA_REFERENCE_PROPERTY_NAMES
    _CURRENT_PROPERTIES_NAMES = set(settings.xml_structure.properties_element_names)
    _CURRENT_LOCALIZED_CONTENT_NAME = settings.xml_structure.localized_content_element_name
    _CURRENT_VALUE_TRANSLATIONS = settings.value_translations
    _CURRENT_VALUE_PREFIX_TRANSLATIONS = settings.value_prefix_translations
    _CURRENT_VALUE_SEGMENT_TRANSLATIONS = settings.value_segment_translations
    _CURRENT_XML_NAME_TO_OUTPUT_NAME = {
        alias: output_name
        for output_name, aliases in settings.property_aliases.items()
        for alias in aliases
    }
    _CURRENT_STANDARD_ATTRIBUTE_NAME_TRANSLATIONS = settings.standard_attribute_name_translations
    _CURRENT_CHARACTERISTIC_DATA_PATH_FIELD_STRATEGY = settings.characteristic_data_path_field_strategy
    _CURRENT_CHARACTERISTIC_BLANK_FIELD_VALUES = set(settings.characteristic_blank_field_values)
    _CURRENT_TYPE_VALUE_PRIORITY_VALUES = settings.type_value_priority_values
    _CURRENT_TYPE_VALUE_PRIORITY_PREFIXES = settings.type_value_priority_prefixes
    _CURRENT_TYPE_VALUE_LATE_VALUES = settings.type_value_late_values
    _CURRENT_COMPACT_METADATA_REFERENCE_PROPERTY_NAMES = set(settings.compact_metadata_reference_property_names)


def translate_value(text: str) -> str:
    if text in _CURRENT_VALUE_TRANSLATIONS:
        return _CURRENT_VALUE_TRANSLATIONS[text]
    result = text
    for source_prefix, target_prefix in _CURRENT_VALUE_PREFIX_TRANSLATIONS.items():
        if result.startswith(source_prefix):
            result = target_prefix + result[len(source_prefix):]
            break
    for source_segment, target_segment in _CURRENT_VALUE_SEGMENT_TRANSLATIONS.items():
        result = result.replace(source_segment, target_segment)
    return result


def _type_values(node: ET.Element) -> list[str] | None:
    values: list[tuple[str, str]] = []
    qualifiers: dict[str, ET.Element] = {}
    for child in node.iter():
        if child is node:
            continue
        child_name = local_name(child.tag)
        if child_name in {"StringQualifiers", "NumberQualifiers", "DateQualifiers"} and child_name not in qualifiers:
            qualifiers[child_name] = child
    for child in node.iter():
        if child is node or local_name(child.tag) not in {"Type", "TypeSet"}:
            continue
        value = _clean_text(child.text)
        if value is None:
            continue
        values.append((value, _format_type_value(value, qualifiers)))
    if not values:
        direct_value = _clean_text(node.text)
        if direct_value is not None:
            return [format_value(direct_value)]
    return _deduplicate(_order_type_values(values)) if values else []


def _order_type_values(values: list[tuple[str, str]]) -> list[str]:
    if not _CURRENT_TYPE_VALUE_PRIORITY_VALUES and not _CURRENT_TYPE_VALUE_PRIORITY_PREFIXES and not _CURRENT_TYPE_VALUE_LATE_VALUES:
        return [formatted for _, formatted in values]
    decorated: list[tuple[int, int, str]] = []
    for index, (raw_value, formatted_value) in enumerate(values):
        priority = len(_CURRENT_TYPE_VALUE_PRIORITY_VALUES) + len(_CURRENT_TYPE_VALUE_PRIORITY_PREFIXES) + 2
        for value_index, priority_value in enumerate(_CURRENT_TYPE_VALUE_PRIORITY_VALUES):
            if raw_value == priority_value:
                priority = value_index
                break
        else:
            base_priority = len(_CURRENT_TYPE_VALUE_PRIORITY_VALUES)
            for prefix_index, prefix in enumerate(_CURRENT_TYPE_VALUE_PRIORITY_PREFIXES):
                if raw_value.startswith(prefix):
                    priority = base_priority + prefix_index
                    break
            else:
                base_priority += len(_CURRENT_TYPE_VALUE_PRIORITY_PREFIXES)
                if "." in formatted_value:
                    priority = base_priority
                elif formatted_value in _CURRENT_TYPE_VALUE_LATE_VALUES:
                    priority = base_priority + 2
                else:
                    priority = base_priority + 1
        decorated.append((priority, index, formatted_value))
    decorated.sort()
    return [formatted for _, _, formatted in decorated]


def _format_type_value(value: str, qualifiers: dict[str, ET.Element]) -> str:
    base = _format_type_name(value)
    if value == "xs:string":
        qualifier = qualifiers.get("StringQualifiers")
        if qualifier is not None:
            length = _child_text(qualifier, "Length")
            allowed_length = _child_text(qualifier, "AllowedLength")
            parts = [part for part in (length, translate_value(allowed_length) if allowed_length else None) if part]
            if parts:
                return f"{base}({', '.join(parts)})"
    if value == "xs:decimal":
        qualifier = qualifiers.get("NumberQualifiers")
        if qualifier is not None:
            precision = _child_text(qualifier, "Digits") or _child_text(qualifier, "Precision")
            scale = _child_text(qualifier, "FractionDigits") or _child_text(qualifier, "Scale")
            non_negative = _child_text(qualifier, "NonNegative")
            allowed_sign = _child_text(qualifier, "AllowedSign")
            if allowed_sign and allowed_sign != "Any":
                non_negative = allowed_sign
            parts = [part for part in (precision, scale, translate_value(non_negative) if non_negative else None) if part]
            if parts:
                return f"{base}({', '.join(parts)})"
    if value == "xs:dateTime":
        qualifier = qualifiers.get("DateQualifiers")
        fraction = _child_text(qualifier, "DateFractions") if qualifier is not None else None
        if fraction:
            return f"{base}({translate_value(fraction)})"
    return base


def _format_type_name(value: str) -> str:
    return translate_value(value)


def _choice_parameter_links(node: ET.Element) -> list[str]:
    result: list[str] = []
    for link in list(node):
        name = _child_text(link, "Name")
        data_path = _child_text(link, "DataPath")
        if not name or not data_path:
            continue
        result.append(f"{name}({_compact_data_path(data_path)})")
    return result


def _choice_parameters(node: ET.Element) -> list[str]:
    result: list[str] = []
    for item in list(node):
        name = _attribute_value(item, ("name", "Name"))
        value_node = next((child for child in list(item) if local_name(child.tag) == "value"), None)
        value = _choice_parameter_value(value_node) if value_node is not None else None
        value_type = _attribute_value(value_node, ("type",)) or _attribute_value_by_local_name(value_node, "type") if value_node is not None else None
        if not name or value is None:
            continue
        type_label = _choice_parameter_type_label(value_type) if value_type else None
        if type_label:
            result.append(f"{name}({type_label}:{value})")
        else:
            result.append(f"{name}({value})")
    return result


def _choice_parameter_value(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    value_type = _attribute_value(node, ("type",)) or _attribute_value_by_local_name(node, "type") or ""
    if value_type.endswith("DesignTimeRef"):
        value = _clean_text(node.text)
        return _format_design_time_ref(value) if value is not None else None
    if value_type.endswith("FixedArray"):
        return _format_type_name(value_type)
    value = _clean_text(node.text)
    return format_value(value) if value is not None else None


def _choice_parameter_type_label(value_type: str) -> str | None:
    if value_type.endswith("DesignTimeRef"):
        return None
    return _format_type_name(value_type)


def _xdto_type_value(node: ET.Element) -> list[str]:
    value = _clean_text(node.text)
    if value is None:
        return []
    if ":" in value:
        namespace, local = value.split(":", 1)
        return [f"{translate_value('XDTONamespaceLabel')} - {translate_value(namespace)}", f"{translate_value('XDTOLocalNameLabel')} - {local}"]
    return [format_value(value)]


def _metadata_reference_values(node: ET.Element) -> list[str]:
    result: list[str] = []
    is_xdto_packages = local_name(node.tag) == "XDTOPackages"
    output_name = _CURRENT_XML_NAME_TO_OUTPUT_NAME.get(local_name(node.tag))
    compact_values = output_name in _CURRENT_COMPACT_METADATA_REFERENCE_PROPERTY_NAMES if output_name else False
    for child in node.iter():
        if child is node:
            continue
        name = local_name(child.tag)
        if name in {"Type", "TypeSet", "Item", "Value", "Metadata", "Field"}:
            value = _clean_text(child.text) or _attribute_value(child, ("ref", "Ref", "value", "Value"))
            if value and not is_unsafe_value(value):
                if is_xdto_packages and name == "Value":
                    xsi_type = _attribute_value(child, ("type",)) or _attribute_value_by_local_name(child, "type") or ""
                    if xsi_type.endswith("MDObjectRef"):
                        result.append(translate_value("UnknownObject"))
                        continue
                result.append(_last_metadata_part(value) if compact_values else format_value(value))
    return _deduplicate(result)


def _input_by_string_values(node: ET.Element) -> list[str]:
    result: list[str] = []
    for child in node.iter():
        if child is node or local_name(child.tag) != "Field":
            continue
        value = _clean_text(child.text)
        if value:
            result.append(_last_metadata_part(value))
    return _deduplicate(result)


def _content_values(node: ET.Element) -> list[str]:
    result: list[str] = []
    for item in list(node):
        metadata = _child_text(item, "Metadata")
        use = _child_text(item, "Use")
        if metadata:
            if use:
                result.append(f"{format_value(metadata)}, {format_value(use)}")
            else:
                result.append(format_value(metadata))
            continue
        value = _clean_text(item.text) or _attribute_value(item, ("ref", "Ref", "value", "Value"))
        if value and not is_unsafe_value(value):
            result.append(format_value(value))
    return _deduplicate(result)


def _first_descendant_value(node: ET.Element, names: set[str]) -> str | None:
    for child in node.iter():
        if child is node:
            continue
        if local_name(child.tag) not in names:
            continue
        value = _clean_text(child.text) or _attribute_value(child, ("ref", "Ref", "value", "Value"))
        if value and not is_unsafe_value(value):
            return format_value(value)
    return ""


def _style_value(node: ET.Element) -> str:
    value = _attribute_value(node, ("ref", "Ref", "value", "Value", "name", "Name"))
    return format_value(value) if value else ""


def _fill_value(node: ET.Element) -> str | None:
    if _attribute_value_by_local_name(node, "nil") == "true":
        return None
    value_type = _attribute_value(node, ("type",))
    text = _clean_text(node.text)
    if value_type == "xs:boolean":
        if text is None or text.lower() == "false":
            return ""
        return f"{_format_type_name(value_type)}:{format_value(text)}"
    if value_type == "xs:decimal":
        if text is None or _is_zero_number(text):
            return ""
        return f"{_format_type_name(value_type)}:{_format_fill_number(text)}"
    if value_type == "xs:dateTime":
        if text is None or text == "0001-01-01T00:00:00":
            return ""
        return f"{_format_type_name(value_type)}:{format_value(text)}"
    if value_type == "xr:DesignTimeRef" and text is not None:
        return _format_fill_reference(text)
    if value_type == "xs:string" and node.text is not None:
        return f"{_format_type_name(value_type)}:{node.text}"
    return format_value(text) if text is not None else ""


def _normalize_fill_value(output_name: str, value: str, root: ET.Element, settings: GeneratorSettings) -> str:
    if output_name != translate_value("FillValue"):
        return value
    string_prefix = f"{translate_value('xs:string')}:"
    if not value.startswith(string_prefix):
        return value
    fill_text = value[len(string_prefix):]
    if fill_text == "" or fill_text.strip() != "":
        return value
    if _has_fixed_string_type(root, settings):
        return ""
    return value


def _has_fixed_string_type(root: ET.Element, settings: GeneratorSettings) -> bool:
    aliases = settings.property_aliases.get(translate_value("Type"), ("Type",))
    for node in _candidate_property_nodes(root, aliases):
        converted = simple_value(node)
        values = converted if isinstance(converted, list) else [converted]
        for value in values:
            if isinstance(value, str) and value.startswith(f"{translate_value('xs:string')}(") and translate_value("Fixed") in value:
                return True
    return False


def _is_zero_number(value: str) -> bool:
    normalized = value.replace(",", ".")
    try:
        return float(normalized) == 0
    except ValueError:
        return False


def _format_fill_number(value: str) -> str:
    normalized = value.replace(",", ".")
    if re.fullmatch(r"\d+(\.0+)?", normalized):
        return f"{int(float(normalized)):,}".replace(",", "\u00a0")
    return format_value(value)


def _format_fill_reference(value: str) -> str:
    if value.endswith(".EmptyRef"):
        return ""
    parts = value.split(".")
    if len(parts) >= 4 and parts[-2] == "EnumValue":
        prefix = translate_value(f"{parts[0]}Ref")
        if prefix != f"{parts[0]}Ref":
            return f"{prefix}.{parts[1]}:{parts[-1]}"
    if len(parts) >= 3:
        prefix = translate_value(f"{parts[0]}Ref")
        if prefix != f"{parts[0]}Ref":
            return f"{prefix}.{parts[1]}:{parts[-1]}"
    return format_value(value)


def _format_design_time_ref(value: str) -> str:
    parts = value.split(".")
    if len(parts) >= 3 and parts[-1] == "EmptyRef":
        prefix = translate_value(f"{parts[0]}Ref")
        if prefix != f"{parts[0]}Ref":
            return f"{prefix}.{parts[1]}:"
    return _format_fill_reference(value)


def _standard_attributes(
    node: ET.Element,
    settings: GeneratorSettings,
    *,
    owner_name: str | None = None,
    owner_type_key: str | None = None,
) -> list[tuple[str, list[ReportProperty]]]:
    groups: list[tuple[str, list[ReportProperty]]] = []
    keep_empty_owner_attributes = set(settings.standard_attribute_keep_empty_value_owner_attributes)
    keep_default_properties_by_name = settings.standard_attribute_keep_default_properties_by_name
    keep_default_owner_attribute_properties = set(settings.standard_attribute_keep_default_owner_attribute_properties)
    suppressed_properties_by_name = settings.standard_attribute_suppressed_properties_by_name
    suppressed_properties_by_type_and_name = settings.standard_attribute_suppressed_properties_by_type_and_name
    for standard_attr in list(node):
        if local_name(standard_attr.tag) != "StandardAttribute":
            continue
        raw_name = _attribute_value(standard_attr, ("name", "Name"))
        if not raw_name:
            continue
        translated_name = _standard_attribute_name(raw_name, settings)
        suppressed_properties = set(suppressed_properties_by_name.get(translated_name, ()))
        if owner_type_key is not None:
            suppressed_properties.update(
                suppressed_properties_by_type_and_name.get(owner_type_key, {}).get(translated_name, ())
            )
        items: list[ReportProperty] = []
        forced_items_present = False
        for child in list(standard_attr):
            name = local_name(child.tag)
            output_name = _output_name_for_xml_name(name, settings) or name
            keep_default = output_name in keep_default_properties_by_name.get(translated_name, ())
            if not keep_default and owner_name is not None:
                keep_default = f"{owner_name}|{translated_name}|{output_name}" in keep_default_owner_attribute_properties
            if is_blocked_property_name(name, settings):
                continue
            if output_name == translate_value("FillValue") and _attribute_value_by_local_name(child, "nil") == "true":
                converted = ""
            else:
                converted = simple_value(child)
            if converted is None:
                continue
            if output_name in suppressed_properties and not keep_default:
                continue
            if isinstance(converted, list):
                if converted:
                    items.append(ReportProperty(output_name, converted, "list"))
                continue
            keep_empty = (
                output_name == translate_value("FillValue")
                and (
                    translated_name in settings.standard_attribute_keep_empty_value_names
                    or (
                        owner_name is not None
                        and f"{owner_name}|{translated_name}" in keep_empty_owner_attributes
                    )
                )
            )
            forced_items_present = forced_items_present or keep_default
            if (converted != "" or keep_empty) and (
                keep_default or not _is_standard_attribute_default(output_name, converted, settings)
            ):
                items.append(ReportProperty(output_name, converted, "scalar"))
        if items and (forced_items_present or not _is_noisy_standard_attribute(translated_name, items, settings)):
            groups.append((translated_name, items))
    return groups


def _standard_attribute_name(name: str, settings: GeneratorSettings) -> str:
    return settings.standard_attribute_name_translations.get(name, name)


def _is_standard_attribute_default(output_name: str, value: str, settings: GeneratorSettings) -> bool:
    default = settings.standard_attribute_property_defaults.get(output_name)
    if default is not None and format_value(default) == value:
        return True
    if value in settings.standard_attribute_suppressed_values.get(output_name, ()):
        return True
    return any(value.endswith(suffix) for suffix in settings.standard_attribute_suppressed_value_suffixes)


def _is_noisy_standard_attribute(name: str, items: list[ReportProperty], settings: GeneratorSettings) -> bool:
    if name not in settings.standard_attribute_suppressed_names:
        return False
    noisy = set(settings.standard_attribute_noisy_properties)
    return all(item.name in noisy for item in items)


def _characteristics(node: ET.Element) -> list[list[ReportProperty]]:
    groups: list[list[ReportProperty]] = []
    for characteristic in list(node):
        if local_name(characteristic.tag) != "Characteristic":
            continue
        values: list[ReportProperty] = []
        types = next((child for child in list(characteristic) if local_name(child.tag) == "CharacteristicTypes"), None)
        characteristic_values = next((child for child in list(characteristic) if local_name(child.tag) == "CharacteristicValues"), None)

        if types is not None:
            values.extend(
                _characteristic_properties(
                    (
                        (translate_value("CharacteristicTypes"), _format_metadata_path(_attribute_value(types, ("from",)) or "")),
                        (translate_value("KeyField"), _last_metadata_part(_child_text(types, "KeyField"))),
                        (translate_value("TypesFilterField"), _last_metadata_part(_child_text(types, "TypesFilterField"))),
                        (translate_value("TypesFilterValue"), _child_text(types, "TypesFilterValue") or ""),
                        (translate_value("DataPathField"), _data_path_field(types)),
                    )
                )
            )
        if characteristic_values is not None:
            values.extend(
                _characteristic_properties(
                    (
                        (translate_value("CharacteristicValues"), _format_metadata_path(_attribute_value(characteristic_values, ("from",)) or "")),
                        (translate_value("ObjectField"), _last_metadata_part(_child_text(characteristic_values, "ObjectField"))),
                        (translate_value("TypeField"), _last_metadata_part(_child_text(characteristic_values, "TypeField"))),
                        (translate_value("ValueField"), _last_metadata_part(_child_text(characteristic_values, "ValueField"))),
                        (translate_value("MultipleValuesUseField"), _blank_if_minus_one(_child_text(characteristic_values, "MultipleValuesUseField"))),
                        (translate_value("MultipleValuesKeyField"), _blank_if_minus_one(_child_text(characteristic_values, "MultipleValuesKeyField"))),
                        (translate_value("MultipleValuesOrderField"), _blank_if_minus_one(_child_text(characteristic_values, "MultipleValuesOrderField"))),
                    )
                )
            )
        if values:
            groups.append(values)
    return groups


def _characteristic_properties(items: tuple[tuple[str, str | None], ...]) -> list[ReportProperty]:
    return [ReportProperty(name, format_value(value or "")) for name, value in items]


def _data_path_field(types: ET.Element) -> str:
    value = _child_text(types, "DataPathField")
    if value and value.endswith(".StandardAttribute.Ref"):
        filter_field = _last_metadata_part(_child_text(types, "TypesFilterField"))
        ref = translate_value("Ref")
        return f"{filter_field}.{ref}" if filter_field else ref
    if _CURRENT_CHARACTERISTIC_DATA_PATH_FIELD_STRATEGY == "typesFilterField":
        if value == "-1":
            return _last_metadata_part(_child_text(types, "TypesFilterField"))
        filter_field = _last_metadata_part(_child_text(types, "TypesFilterField"))
        if value in _CURRENT_CHARACTERISTIC_BLANK_FIELD_VALUES and filter_field:
            return filter_field
        data_field = _last_metadata_part(value)
        if filter_field and data_field and value and ".Attribute." in value:
            return f"{filter_field}.{data_field}"
    if value in _CURRENT_CHARACTERISTIC_BLANK_FIELD_VALUES:
        return ""
    return _last_metadata_part(value)


def _blank_if_minus_one(value: str | None) -> str:
    if value is None or value in _CURRENT_CHARACTERISTIC_BLANK_FIELD_VALUES:
        return ""
    return _last_metadata_part(value)


def _last_metadata_part(value: str | None) -> str:
    if not value:
        return ""
    parts = value.split(".")
    if len(parts) >= 2 and parts[-2] == "StandardAttribute":
        return _CURRENT_STANDARD_ATTRIBUTE_NAME_TRANSLATIONS.get(parts[-1], translate_value(parts[-1]))
    last = value.rsplit(".", 1)[-1]
    return translate_value(last)


def _format_metadata_path(value: str) -> str:
    if not value:
        return ""
    parts = value.split(".")
    return ".".join(translate_value(part) for part in parts)


def _compact_data_path(value: str) -> str:
    parts = [part for part in value.split(".") if part]
    if "StandardAttribute" in parts:
        return _last_metadata_part(value)
    if "TabularSection" in parts and "Attribute" in parts:
        section_index = parts.index("TabularSection")
        attribute_index = parts.index("Attribute")
        if section_index + 1 < len(parts) and attribute_index + 1 < len(parts):
            return f"{parts[section_index + 1]}.{parts[attribute_index + 1]}"
    if "Attribute" in parts:
        attribute_index = parts.index("Attribute")
        if attribute_index + 1 < len(parts):
            return parts[attribute_index + 1]
    return translate_value(value)


def _child_text(node: ET.Element, child_name: str) -> str | None:
    for child in list(node):
        if local_name(child.tag) == child_name:
            return _clean_text(child.text)
    return None


def _direct_property_value(node: ET.Element, *, allow_unsafe: bool = False) -> str | None:
    value = _clean_text(node.text) or _attribute_value(node, ("name", "Name", "value", "Value", "ref", "Ref"))
    if value is None or (not allow_unsafe and is_unsafe_value(value)):
        return None
    return value


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _clean_localized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip("\n\t")
    return normalized if normalized != "" else (value if value != "" else None)


def _has_content(node: ET.Element) -> bool:
    return _clean_text(node.text) is not None or bool(list(node)) or bool(node.attrib)


def _deduplicate(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
