from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChildCollectionSpec:
    folder_names: tuple[str, ...]
    report_plural: str
    type_key: str
    whitelist: tuple[str, ...]
    child_collections: tuple["ChildCollectionSpec", ...] = ()
    xml_element_names: tuple[str, ...] = ()
    include_extra_properties: bool = True


@dataclass(frozen=True, slots=True)
class ObjectTypeSpec:
    type_key: str
    folder_names: tuple[str, ...]
    report_plural: str
    whitelist: tuple[str, ...]
    child_collections: tuple[ChildCollectionSpec, ...] = ()
    xml_element_names: tuple[str, ...] = ()
    include_extra_properties: bool = True
    fallback_enabled: bool = False
    warn_on_fallback: bool = False
