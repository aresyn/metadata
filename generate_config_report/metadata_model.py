from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


PropertyKind = Literal["scalar", "list", "marker", "object_list", "named_object_list"]
SourceKind = Literal["main", "extension"]


@dataclass(slots=True)
class ReportProperty:
    name: str
    value: str | list[str] | list[list["ReportProperty"]] | list[tuple[str, list["ReportProperty"]]]
    kind: PropertyKind = "scalar"


@dataclass(slots=True)
class MetadataObject:
    full_name: str
    type_key: str
    name: str
    properties: list[ReportProperty] = field(default_factory=list)
    children: list["MetadataObject"] = field(default_factory=list)
    unsupported_type: bool = False
    xml_path: Path | None = None


@dataclass(slots=True)
class MetadataSection:
    source_kind: SourceKind
    root: MetadataObject
