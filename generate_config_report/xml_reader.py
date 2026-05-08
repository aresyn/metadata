from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from .diagnostics import Diagnostics
from .metadata_model import MetadataObject, MetadataSection, ReportProperty
from .object_registry import ChildCollectionSpec, ObjectTypeSpec
from .property_extractors import _clean_text, _properties_root, configure_extractor, extract_name, extract_properties, local_name, payload_element, translate_value
from .settings import GeneratorSettings


class XmlReader:
    def __init__(self, diagnostics: Diagnostics, settings: GeneratorSettings) -> None:
        self.diagnostics = diagnostics
        self.settings = settings
        configure_extractor(settings)

    def read_section(self, section_path: Path, source_kind: str) -> MetadataSection | None:
        configuration_xml = section_path / self.settings.xml_structure.configuration_file_name
        if not configuration_xml.exists():
            self.diagnostics.error("configurationXmlMissing", f"{self.settings.xml_structure.configuration_file_name} not found", configuration_xml)
            return None

        parsed_root = self._parse(configuration_xml)
        if parsed_root is None:
            return None
        root_element = payload_element(parsed_root, self.settings)

        config_name = extract_name(root_element, self.settings, fallback=configuration_xml.stem)
        if not config_name:
            self.diagnostics.error("configurationNameMissing", "Configuration name not found", configuration_xml)
            return None

        root_properties = extract_properties(
            root_element,
            self.settings.configuration_whitelist,
            self.diagnostics,
            self.settings,
            owner_name=f"{self.settings.root_object.report_plural}.{config_name}",
            path=str(configuration_xml),
        )
        _apply_root_source_property_overrides(root_properties, source_kind, self.settings)

        root_object = MetadataObject(
            full_name=f"{self.settings.root_object.report_plural}.{config_name}",
            type_key=self.settings.root_object.type_key,
            name=config_name,
            properties=root_properties,
            xml_path=configuration_xml,
        )

        children = self._read_top_level_objects(section_path, root_element, source_kind)
        root_object.children.extend(_sort_by_reference_order(children, _reference_order(root_element, self.settings.object_types, self.settings)))
        return MetadataSection(source_kind=source_kind, root=root_object)  # type: ignore[arg-type]

    def _read_top_level_objects(self, section_path: Path, root_element: ET.Element, source_kind: str) -> list[MetadataObject]:
        objects: list[MetadataObject] = []
        for spec in self.settings.object_types:
            for folder_name in spec.folder_names:
                folder = section_path / folder_name
                if not folder.is_dir():
                    continue
                objects.extend(self._read_objects_from_folder(folder, spec, parent_full_name=None))
                break
        objects.extend(self._read_top_level_objects_from_xml(root_element, source_kind, objects))
        return objects

    def _read_top_level_objects_from_xml(
        self,
        root_element: ET.Element,
        source_kind: str,
        existing_objects: list[MetadataObject],
    ) -> list[MetadataObject]:
        child_objects = next(
            (child for child in list(root_element) if local_name(child.tag) in self.settings.xml_structure.child_objects_element_names),
            None,
        )
        if child_objects is None:
            return []
        existing_names = {obj.full_name for obj in existing_objects}
        specs_by_xml_name: dict[str, ObjectTypeSpec] = {}
        for spec in self.settings.object_types:
            for xml_name in spec.xml_element_names:
                specs_by_xml_name.setdefault(xml_name, spec)

        result: list[MetadataObject] = []
        adopted_name = translate_value("ObjectBelonging")
        adopted_value = translate_value("Adopted")
        extended_object_name = translate_value("ExtendedConfigurationObject")
        for child in list(child_objects):
            spec = specs_by_xml_name.get(local_name(child.tag))
            if spec is None:
                continue
            name = _clean_text(child.text)
            if not name:
                continue
            full_name = f"{spec.report_plural}.{name}"
            if full_name in existing_names:
                continue
            properties: list[ReportProperty] = []
            if source_kind == "extension":
                properties.append(ReportProperty(adopted_name, adopted_value, "scalar"))
                properties.append(ReportProperty(extended_object_name, "", "scalar"))
                for prop_name, prop_value in self.settings.extension_synthetic_property_defaults_by_type.get(spec.type_key, {}).items():
                    properties.append(ReportProperty(prop_name, prop_value, "scalar"))
            result.append(
                MetadataObject(
                    full_name=full_name,
                    type_key=spec.type_key,
                    name=name,
                    properties=properties,
                    children=[],
                    xml_path=None,
                )
            )
            existing_names.add(full_name)
        return result

    def _read_objects_from_folder(
        self,
        folder: Path,
        spec: ObjectTypeSpec | ChildCollectionSpec,
        *,
        parent_full_name: str | None,
    ) -> list[MetadataObject]:
        objects: list[MetadataObject] = []
        direct_stems = {path.stem.casefold() for path in folder.glob("*.xml")}
        for xml_file in sorted(folder.glob("*.xml"), key=lambda path: path.name.casefold()):
            obj = self._read_object_file(xml_file, spec, parent_full_name=parent_full_name)
            if obj is not None:
                objects.append(obj)

        for nested_xml in self._special_nested_object_xml_files(folder):
            if nested_xml.parent.parent.name.casefold() in direct_stems:
                continue
            obj = self._read_object_file(nested_xml, spec, parent_full_name=parent_full_name, name_fallback=nested_xml.parent.parent.name)
            if obj is not None:
                objects.append(obj)
        objects = _deduplicate_objects(objects)
        return objects

    def _read_object_file(
        self,
        xml_file: Path,
        spec: ObjectTypeSpec | ChildCollectionSpec,
        *,
        parent_full_name: str | None,
        name_fallback: str | None = None,
    ) -> MetadataObject | None:
        parsed_root = self._parse(xml_file)
        if parsed_root is None:
            return None
        element = payload_element(parsed_root, self.settings)

        name = extract_name(element, self.settings, fallback=name_fallback or xml_file.stem)
        if not name:
            self.diagnostics.warning("missingObjectName", "Object name not found", xml_file)
            return None

        full_name = f"{spec.report_plural}.{name}" if parent_full_name is None else f"{parent_full_name}.{spec.report_plural}.{name}"
        unsupported = isinstance(spec, ObjectTypeSpec) and spec.fallback_enabled
        if unsupported and spec.warn_on_fallback:
            self.diagnostics.warning("unsupportedType", f"Object type handled by fallback: {spec.type_key}", xml_file, typeKey=spec.type_key)

        obj = MetadataObject(
            full_name=full_name,
            type_key=spec.type_key,
            name=name,
            properties=extract_properties(
                element,
                spec.whitelist,
                self.diagnostics,
                self.settings,
                include_extra_properties=spec.include_extra_properties,
                owner_name=full_name,
                owner_type_key=spec.type_key,
                path=str(xml_file),
            ),
            children=[],
            unsupported_type=unsupported,
            xml_path=xml_file,
        )
        child_collections = spec.child_collections
        if spec.type_key == "subsystem" and not child_collections:
            child_collections = (spec,)
        obj.children.extend(self._read_child_collections(element, xml_file, obj.full_name, child_collections))
        return obj

    def _read_child_collections(
        self,
        element: ET.Element,
        xml_file: Path,
        parent_full_name: str,
        child_specs: tuple[ChildCollectionSpec, ...],
    ) -> list[MetadataObject]:
        children: list[MetadataObject] = []
        object_dir = xml_file.with_suffix("")
        for child_spec in child_specs:
            children.extend(self._read_child_collection_from_files(object_dir, child_spec, parent_full_name))
            children.extend(self._read_child_collection_from_xml(element, child_spec, parent_full_name, xml_file))
        return _sort_by_reference_order(children, _reference_order(element, child_specs, self.settings))

    def _read_child_collection_from_files(
        self,
        object_dir: Path,
        child_spec: ChildCollectionSpec,
        parent_full_name: str,
    ) -> list[MetadataObject]:
        if not object_dir.is_dir():
            return []
        children: list[MetadataObject] = []
        for folder_name in child_spec.folder_names:
            folder = object_dir / folder_name
            if not folder.is_dir():
                continue
            before_count = len(children)
            children.extend(self._read_objects_from_folder(folder, child_spec, parent_full_name=parent_full_name))
            for child in list(children):
                if child_spec.child_collections:
                    child_dir = self._object_dir_for_child(folder, child)
                    nested_children: list[MetadataObject] = []
                    for nested_spec in child_spec.child_collections:
                        nested_children.extend(self._read_child_collection_from_files(child_dir, nested_spec, child.full_name))
                    child.children.extend(_sort_by_reference_order(nested_children, _reference_order_from_file(child.xml_path, child_spec.child_collections, self.settings)))
            if len(children) > before_count:
                break
        return children

    def _read_child_collection_from_xml(
        self,
        element: ET.Element,
        child_spec: ChildCollectionSpec,
        parent_full_name: str,
        xml_file: Path,
    ) -> list[MetadataObject]:
        result: list[MetadataObject] = []
        container_names = set(child_spec.folder_names) | set(self.settings.xml_structure.child_objects_element_names)
        child_names = self._child_element_names(child_spec)
        for collection in list(element):
            collection_name = local_name(collection.tag)
            if collection_name in container_names:
                candidates = list(collection)
            elif collection_name in child_names:
                candidates = [collection]
            else:
                continue
            for child_element in candidates:
                if child_names and local_name(child_element.tag) not in child_names:
                    continue
                name = extract_name(child_element, self.settings)
                if not name:
                    continue
                full_name = f"{parent_full_name}.{child_spec.report_plural}.{name}"
                child = MetadataObject(
                    full_name=full_name,
                    type_key=child_spec.type_key,
                    name=name,
                    properties=extract_properties(
                        child_element,
                        child_spec.whitelist,
                        self.diagnostics,
                        self.settings,
                        include_extra_properties=child_spec.include_extra_properties,
                        owner_name=full_name,
                        owner_type_key=child_spec.type_key,
                        path=str(xml_file),
                    ),
                    xml_path=xml_file,
                )
                for nested_spec in child_spec.child_collections:
                    child.children.extend(self._read_child_collection_from_xml(child_element, nested_spec, child.full_name, xml_file))
                result.append(child)
        return result

    def _child_element_names(self, child_spec: ChildCollectionSpec) -> set[str]:
        return set(child_spec.xml_element_names)

    def _parse(self, xml_file: Path) -> ET.Element | None:
        try:
            return ET.parse(xml_file).getroot()
        except OSError as exc:
            self.diagnostics.warning("xmlReadError", f"Cannot read XML: {exc}", xml_file)
        except ET.ParseError as exc:
            self.diagnostics.warning("xmlParseError", f"Cannot parse XML: {exc}", xml_file)
        return None

    def _special_nested_object_xml_files(self, folder: Path) -> list[Path]:
        result: list[Path] = []
        for child_dir in sorted((path for path in folder.iterdir() if path.is_dir()), key=lambda path: path.name.casefold()):
            ext_dir = child_dir / "Ext"
            if not ext_dir.is_dir():
                continue
            for name in self.settings.xml_structure.special_nested_object_files:
                target = ext_dir / name
                if target.is_file():
                    result.append(target)
        return result

    def _object_dir_for_child(self, folder: Path, child: MetadataObject) -> Path:
        direct = folder / child.name
        if direct.is_dir():
            return direct
        xml_file = folder / f"{child.name}.xml"
        return xml_file.with_suffix("")


def _deduplicate_objects(objects: list[MetadataObject]) -> list[MetadataObject]:
    seen: set[str] = set()
    result: list[MetadataObject] = []
    for obj in objects:
        if obj.full_name in seen:
            continue
        seen.add(obj.full_name)
        result.append(obj)
    return result


def _reference_order(
    element: ET.Element,
    specs: tuple[ObjectTypeSpec, ...] | tuple[ChildCollectionSpec, ...],
    settings: GeneratorSettings,
) -> dict[tuple[str, str], int]:
    by_xml_name = _specs_by_xml_name(specs)
    result: dict[tuple[str, str], int] = {}

    def add_reference(xml_name: str, name: str | None) -> None:
        if not name:
            return
        spec = by_xml_name.get(xml_name)
        if spec is None:
            return
        key = (spec.report_plural, name)
        if key not in result:
            result[key] = len(result)

    properties = _properties_root(element)
    if properties is not None:
        for child in list(properties):
            add_reference(local_name(child.tag), _reference_name(child, settings))

    container_names = set(settings.xml_structure.child_objects_element_names)
    for child in list(element):
        if local_name(child.tag) not in container_names:
            continue
        for item in list(child):
            add_reference(local_name(item.tag), _reference_name(item, settings))

    return result


def _reference_order_from_file(
    xml_path: Path | None,
    specs: tuple[ChildCollectionSpec, ...],
    settings: GeneratorSettings,
) -> dict[tuple[str, str], int]:
    if xml_path is None or not xml_path.is_file():
        return {}
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError):
        return {}
    return _reference_order(payload_element(root, settings), specs, settings)


def _sort_by_reference_order(objects: list[MetadataObject], order: dict[tuple[str, str], int]) -> list[MetadataObject]:
    fallback_start = len(order)
    original_positions = {id(obj): index for index, obj in enumerate(objects)}
    return sorted(
        objects,
        key=lambda obj: (
            order.get((obj.full_name.rsplit(".", 2)[-2] if "." in obj.full_name else "", obj.name), fallback_start),
            original_positions[id(obj)] if (obj.full_name.rsplit(".", 2)[-2] if "." in obj.full_name else "", obj.name) in order else obj.full_name.casefold(),
        ),
    )


def _specs_by_xml_name(
    specs: tuple[ObjectTypeSpec, ...] | tuple[ChildCollectionSpec, ...],
) -> dict[str, ObjectTypeSpec | ChildCollectionSpec]:
    result: dict[str, ObjectTypeSpec | ChildCollectionSpec] = {}
    for spec in specs:
        for xml_name in spec.xml_element_names:
            result[xml_name] = spec
    return result


def _reference_name(element: ET.Element, settings: GeneratorSettings) -> str | None:
    text = (element.text or "").strip()
    if text:
        return text
    name = extract_name(element, settings)
    return name or None


def _apply_root_source_property_overrides(
    properties: list[ReportProperty],
    source_kind: str,
    settings: GeneratorSettings,
) -> None:
    overrides = settings.root_source_property_overrides.get(source_kind)
    if not overrides:
        return
    properties_by_name = {prop.name: prop for prop in properties}
    for name, value in overrides.items():
        prop = properties_by_name.get(name)
        if prop is None:
            properties.append(ReportProperty(name, value, "scalar"))
            continue
        prop.value = value
        prop.kind = "scalar"
