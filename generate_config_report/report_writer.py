from __future__ import annotations

from pathlib import Path
from typing import Sequence, TextIO

from .metadata_model import MetadataObject, MetadataSection, ReportProperty
from .settings import ReportFormatSettings


class ReportWriter:
    def __init__(
        self,
        format_settings: ReportFormatSettings,
        joined_list_property_names: Sequence[str] = (),
        marker_property_names_with_colon: Sequence[str] = (),
    ) -> None:
        self.format_settings = format_settings
        self.joined_list_property_names = frozenset(joined_list_property_names)
        self.marker_property_names_with_colon = frozenset(marker_property_names_with_colon)

    def write(self, sections: Sequence[MetadataSection], output_file: Path, encoding: str) -> None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding=encoding, newline="") as stream:
            for index, section in enumerate(sections):
                if index and self.format_settings.blank_line_between_root_sections:
                    stream.write(self.format_settings.line_ending)
                self._write_object(stream, section.root, depth=0)

    def _write_object(self, stream: TextIO, obj: MetadataObject, *, depth: int) -> None:
        indent = self.format_settings.indent * (self.format_settings.base_indent + depth)
        stream.write(f"{indent}- {obj.full_name}{self.format_settings.line_ending}")
        for prop in obj.properties:
            self._write_property(stream, prop, depth=depth + 1)
        for child in obj.children:
            self._write_object(stream, child, depth=depth + 1)

    def _write_property(self, stream: TextIO, prop: ReportProperty, *, depth: int) -> None:
        indent = self.format_settings.indent * (self.format_settings.base_indent + depth)
        if prop.kind == "marker":
            suffix = ":" if prop.name in self.marker_property_names_with_colon else ""
            stream.write(f"{indent}{prop.name}{suffix}{self.format_settings.line_ending}")
            return
        if prop.kind == "object_list":
            stream.write(f"{indent}{prop.name}{self.format_settings.line_ending}")
            groups = prop.value if isinstance(prop.value, list) else []
            for index, group in enumerate(groups):
                group_indent = indent + self.format_settings.indent
                stream.write(f"{group_indent} - {index}{self.format_settings.line_ending}")
                if isinstance(group, list):
                    for item in group:
                        self._write_property(stream, item, depth=depth + 2)
            return
        if prop.kind == "named_object_list":
            stream.write(f"{indent}{prop.name}{self.format_settings.line_ending}")
            groups = prop.value if isinstance(prop.value, list) else []
            for group in groups:
                if not isinstance(group, tuple) or len(group) != 2:
                    continue
                group_name, items = group
                group_indent = indent + self.format_settings.indent
                stream.write(f"{group_indent}- {group_name}{self.format_settings.line_ending}")
                for item in items:
                    self._write_property(stream, item, depth=depth + 2)
            return
        if prop.kind == "list" or isinstance(prop.value, list):
            stream.write(f"{indent}{prop.name}:{self.format_settings.line_ending}")
            item_indent = indent + self.format_settings.indent
            values = prop.value if isinstance(prop.value, list) else [prop.value]
            if prop.name in self.joined_list_property_names and len(values) > 1:
                self._write_joined_list(stream, values, item_indent)
                return
            for value in values:
                self._write_quoted_value(stream, item_indent, str(value))
            return
        self._write_named_scalar_value(stream, indent, prop.name, str(prop.value))

    def _write_joined_list(self, stream: TextIO, values: Sequence[object], item_indent: str) -> None:
        rendered = [str(value) for value in values]
        if not rendered:
            return
        if len(rendered) == 1:
            self._write_quoted_value(stream, item_indent, rendered[0])
            return
        continuation_indent = item_indent + " "
        stream.write(f'{item_indent}"{rendered[0]},{self.format_settings.line_ending}')
        for value in rendered[1:-1]:
            stream.write(f"{continuation_indent}{value},{self.format_settings.line_ending}")
        stream.write(f'{continuation_indent}{rendered[-1]}"{self.format_settings.line_ending}')

    def _write_named_scalar_value(self, stream: TextIO, indent: str, name: str, value: str) -> None:
        prefix = f'{indent}{name}: "'
        if "\n" not in value:
            stream.write(f'{prefix}{value}"{self.format_settings.line_ending}')
            return
        continuation_padding = " " * (len(name) + 3)
        first, *rest = value.split("\n")
        stream.write(f"{prefix}{first}{self.format_settings.line_ending}")
        for index, line in enumerate(rest):
            suffix = '"' if index == len(rest) - 1 else ""
            continuation = line if line[:1].isspace() else continuation_padding + line
            stream.write(f"{indent}{continuation}{suffix}{self.format_settings.line_ending}")

    def _write_quoted_value(self, stream: TextIO, indent: str, value: str) -> None:
        if "\n" not in value:
            stream.write(f'{indent}"{value}"{self.format_settings.line_ending}')
            return
        first, *rest = value.split("\n")
        stream.write(f'{indent}"{first}{self.format_settings.line_ending}')
        for index, line in enumerate(rest):
            suffix = '"' if index == len(rest) - 1 else ""
            stream.write(f"{indent}{line}{suffix}{self.format_settings.line_ending}")
