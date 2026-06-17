from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from generate_config_report.build_xml_overrides import (
    collect_standard_attribute_keep_default_overrides,
    collect_standard_attribute_keep_empty_overrides,
)
from generate_config_report.cli import SIMPLE_REPORT_FILE_NAME, main
from generate_config_report.config import ConfigError, load_config
from generate_config_report.diagnostics import Diagnostics
from generate_config_report.generator import EXIT_REPORT_WRITE_ERROR
from generate_config_report.metadata_model import MetadataObject, MetadataSection, ReportProperty
from generate_config_report.property_extractors import (
    configure_extractor,
    extract_property,
    extract_property_with_used_names,
    extract_properties,
    format_value,
    translate_value,
)
from generate_config_report.report_writer import ReportWriter
from generate_config_report.settings import load_settings


TEMP_ROOT = Path("C:/tmp")
CF_LLV_FIXTURE = Path("D:/cf_llv")
SETTINGS = load_settings()


def read_report(path: Path) -> str:
    return path.read_text(encoding=SETTINGS.report_format.encoding)


def require_cf_llv_fixture(testcase: unittest.TestCase) -> Path:
    testcase.assertTrue(CF_LLV_FIXTURE.is_dir(), f"Required fixture directory is missing: {CF_LLV_FIXTURE}")
    configuration_xml = CF_LLV_FIXTURE / "Configuration.xml"
    testcase.assertTrue(configuration_xml.is_file(), f"Required fixture file is missing: {configuration_xml}")
    return CF_LLV_FIXTURE


class ReportWriterTests(unittest.TestCase):
    def test_root_has_base_tab_and_no_trailing_blank_line(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            root = MetadataObject(
                full_name="Конфигурации.Тест",
                type_key="configuration",
                name="Тест",
                properties=[ReportProperty("Имя", "Тест")],
            )
            ReportWriter(SETTINGS.report_format).write([MetadataSection("main", root)], target, "utf-8")

            text = target.read_text(encoding="utf-8")
            self.assertTrue(text.startswith('\t- Конфигурации.Тест\n\t\tИмя: "Тест"\n'))
            self.assertFalse(text.endswith("\n\n"))

    def test_utf16_report_uses_bom_and_crlf(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            root = MetadataObject(
                full_name="Конфигурации.Тест",
                type_key="configuration",
                name="Тест",
                properties=[ReportProperty("Имя", "Тест")],
            )

            ReportWriter(SETTINGS.report_format).write([MetadataSection("main", root)], target, "utf-16")

            data = target.read_bytes()
            self.assertTrue(data.startswith(b"\xff\xfe"))
            self.assertIn("\r\n".encode("utf-16le"), data)
            self.assertNotIn("\r\r\n".encode("utf-16le"), data)
            self.assertEqual(target.read_text(encoding="utf-16").splitlines()[0], "\t- Конфигурации.Тест")

    def test_blank_line_between_main_and_extension(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            main_root = MetadataObject("Конфигурации.Основная", "configuration", "Основная")
            extension_root = MetadataObject("Конфигурации.Расширение", "configuration", "Расширение")

            ReportWriter(SETTINGS.report_format).write(
                [MetadataSection("main", main_root), MetadataSection("extension", extension_root)],
                target,
                "utf-8",
            )

            self.assertIn("\t- Конфигурации.Основная\n\n\t- Конфигурации.Расширение\n", target.read_text(encoding="utf-8"))

    def test_list_and_quotes_format(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            root = MetadataObject(
                "Конфигурации.Тест",
                "configuration",
                "Тест",
                [
                    ReportProperty("Синоним", 'Тест "Кавычки"'),
                    ReportProperty("ОсновныеРоли", ["Роль.Администратор", "Роль.Пользователь"], "list"),
                ],
            )
            ReportWriter(SETTINGS.report_format).write([MetadataSection("main", root)], target, "utf-8")

            text = target.read_text(encoding="utf-8")
            self.assertIn('\t\tСиноним: "Тест "Кавычки""\n', text)
            self.assertIn('\t\tОсновныеРоли:\n\t\t\t"Роль.Администратор"\n', text)

    def test_joined_list_format(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            root = MetadataObject(
                "Конфигурации.Тест",
                "configuration",
                "Тест",
                [
                    ReportProperty("ВводПоСтроке", ["Наименование", "Код"], "list"),
                    ReportProperty(
                        "Тип",
                        ["СправочникСсылка.Пользователи", "СправочникСсылка.ВнешниеПользователи"],
                        "list",
                    ),
                ],
            )
            ReportWriter(SETTINGS.report_format, SETTINGS.joined_list_property_names).write(
                [MetadataSection("main", root)],
                target,
                "utf-8",
            )

            text = target.read_text(encoding="utf-8")
            self.assertIn('\t\tВводПоСтроке:\n\t\t\t"Наименование,\n\t\t\t Код"\n', text)
            self.assertIn(
                '\t\tТип:\n\t\t\t"СправочникСсылка.Пользователи,\n\t\t\t СправочникСсылка.ВнешниеПользователи"\n',
                text,
            )

    def test_choice_parameter_lists_use_joined_list_format(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            root = MetadataObject(
                "Конфигурации.Тест",
                "configuration",
                "Тест",
                [
                    ReportProperty("ПараметрыВыбора", ["Отбор.А(Булево:Истина)", "Отбор.Б(Булево:Ложь)"], "list"),
                    ReportProperty("СвязиПараметровВыбора", ["Отбор.Владелец(Свойство)", "Отбор.Тип(Тип)"], "list"),
                ],
            )
            ReportWriter(SETTINGS.report_format, SETTINGS.joined_list_property_names).write(
                [MetadataSection("main", root)],
                target,
                "utf-8",
            )

            text = target.read_text(encoding="utf-8")
            self.assertIn('\t\tПараметрыВыбора:\n\t\t\t"Отбор.А(Булево:Истина),\n\t\t\t Отбор.Б(Булево:Ложь)"\n', text)
            self.assertIn('\t\tСвязиПараметровВыбора:\n\t\t\t"Отбор.Владелец(Свойство),\n\t\t\t Отбор.Тип(Тип)"\n', text)

    def test_multiline_scalar_value_keeps_reference_indentation(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            root = MetadataObject(
                "Конфигурации.Тест",
                "configuration",
                "Тест",
                [ReportProperty("Подсказка", "Первая строка\n            Вторая строка")],
            )

            ReportWriter(SETTINGS.report_format).write([MetadataSection("main", root)], target, "utf-8")

            text = target.read_text(encoding="utf-8")
            self.assertIn('\t\tПодсказка: "Первая строка\n\t\t            Вторая строка"\n', text)

    def test_multiline_scalar_value_aligns_unindented_continuation(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            root = MetadataObject(
                "Конфигурации.Тест",
                "configuration",
                "Тест",
                [ReportProperty("Подсказка", "Первая строка\nВторая строка")],
            )

            ReportWriter(SETTINGS.report_format).write([MetadataSection("main", root)], target, "utf-8")

            text = target.read_text(encoding="utf-8")
            self.assertIn('\t\tПодсказка: "Первая строка\n\t\t            Вторая строка"\n', text)

    def test_multiline_scalar_value_keeps_blank_continuation_line_empty(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            root = MetadataObject(
                "Конфигурации.Тест",
                "configuration",
                "Тест",
                [ReportProperty("Подсказка", "Первая строка\n\n            Третья строка")],
            )

            ReportWriter(SETTINGS.report_format).write([MetadataSection("main", root)], target, "utf-8")

            text = target.read_text(encoding="utf-8")
            self.assertIn('\t\tПодсказка: "Первая строка\n\n\t\t            Третья строка"\n', text)

    def test_writer_preserves_prepared_reference_order(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            root = MetadataObject("Конфигурации.Тест", "configuration", "Тест")
            root.children.extend(
                [
                    MetadataObject("Документы.Заказ.Реквизиты.Шаблон", "attribute", "Шаблон"),
                    MetadataObject("Документы.Заказ.Формы.ФормаДокумента", "form", "ФормаДокумента"),
                    MetadataObject("Документы.Заказ.ТабличныеЧасти.ТЧ", "tabular_section", "ТЧ"),
                ]
            )

            ReportWriter(SETTINGS.report_format).write([MetadataSection("main", root)], target, "utf-8")

            text = target.read_text(encoding="utf-8")
            self.assertLess(text.index("Реквизиты.Шаблон"), text.index("Формы.ФормаДокумента"))
            self.assertLess(text.index("Формы.ФормаДокумента"), text.index("ТабличныеЧасти.ТЧ"))

    def test_marker_and_object_list_format(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            root = MetadataObject(
                "Конфигурации.Тест",
                "configuration",
                "Тест",
                [
                    ReportProperty("СтандартныеРеквизиты", "", "marker"),
                    ReportProperty("Характеристики", [[ReportProperty("ПолеКлюча", "Свойство")]], "object_list"),
                ],
            )

            ReportWriter(SETTINGS.report_format).write([MetadataSection("main", root)], target, "utf-8")

            text = target.read_text(encoding="utf-8")
            self.assertIn("\t\tСтандартныеРеквизиты\n", text)
            self.assertIn('\t\tХарактеристики\n\t\t\t - 0\n\t\t\t\tПолеКлюча: "Свойство"\n', text)

    def test_marker_with_colon_format(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            target = Path(tmp) / "Report.txt"
            root = MetadataObject(
                "Конфигурации.Тест",
                "configuration",
                "Тест",
                [
                    ReportProperty("Ссылки", "", "marker"),
                    ReportProperty("СтандартныеРеквизиты", "", "marker"),
                ],
            )

            ReportWriter(SETTINGS.report_format, marker_property_names_with_colon=("Ссылки",)).write(
                [MetadataSection("main", root)],
                target,
                "utf-8",
            )

            text = target.read_text(encoding="utf-8")
            self.assertIn("\t\tСсылки:\n", text)
            self.assertIn("\t\tСтандартныеРеквизиты\n", text)


class GeneratorIntegrationTests(unittest.TestCase):
    def test_simple_cli_writes_report_to_target_configuration_dir(self) -> None:
        cf = require_cf_llv_fixture(self)
        report_path = cf / SIMPLE_REPORT_FILE_NAME

        logging.shutdown()
        logging.getLogger().handlers.clear()
        exit_code = main([str(cf)])

        self.assertEqual(exit_code, 0)
        self.assertTrue(report_path.is_file())
        report = read_report(report_path)
        self.assertGreater(len(report), 0)
        self.assertIn("\t- Конфигурации.", report)

    def test_simple_cli_replaces_existing_report_in_target_dir(self) -> None:
        cf = require_cf_llv_fixture(self)
        report_path = cf / SIMPLE_REPORT_FILE_NAME
        sentinel = "old report sentinel"
        report_path.write_text(sentinel, encoding=SETTINGS.report_format.encoding)

        logging.shutdown()
        logging.getLogger().handlers.clear()
        exit_code = main([str(cf)])

        self.assertEqual(exit_code, 0)
        report = read_report(report_path)
        self.assertNotEqual(report, sentinel)
        self.assertIn("\t- Конфигурации.", report)

    def test_simple_cli_dry_run_does_not_touch_report(self) -> None:
        cf = require_cf_llv_fixture(self)
        report_path = cf / SIMPLE_REPORT_FILE_NAME
        if not report_path.exists():
            report_path.write_text("dry-run sentinel", encoding=SETTINGS.report_format.encoding)
        before = report_path.read_bytes()
        before_mtime = report_path.stat().st_mtime_ns

        logging.shutdown()
        logging.getLogger().handlers.clear()
        exit_code = main([str(cf), "--dry-run"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(report_path.read_bytes(), before)
        self.assertEqual(report_path.stat().st_mtime_ns, before_mtime)

    def test_simple_cli_safe_replace_keeps_existing_report_when_write_fails(self) -> None:
        cf = require_cf_llv_fixture(self)
        report_path = cf / SIMPLE_REPORT_FILE_NAME
        temp_report_path = report_path.with_name(f"{report_path.name}.tmp")
        original = report_path.read_bytes() if report_path.exists() else None
        sentinel = "protected report sentinel"
        report_path.write_text(sentinel, encoding=SETTINGS.report_format.encoding)

        def fail_after_partial_write(_writer, _sections, output_file, _encoding) -> None:
            Path(output_file).write_text("partial report", encoding="utf-8")
            raise OSError("simulated write failure")

        try:
            logging.shutdown()
            logging.getLogger().handlers.clear()
            with patch("generate_config_report.generator.ReportWriter.write", fail_after_partial_write):
                exit_code = main([str(cf)])

            self.assertEqual(exit_code, EXIT_REPORT_WRITE_ERROR)
            self.assertEqual(read_report(report_path), sentinel)
            self.assertFalse(temp_report_path.exists())
        finally:
            if original is None:
                report_path.unlink(missing_ok=True)
            else:
                report_path.write_bytes(original)
            temp_report_path.unlink(missing_ok=True)

    def test_simple_cli_rejects_config_and_target_dir_together(self) -> None:
        with self.assertRaises(SystemExit) as exc:
            main([str(CF_LLV_FIXTURE), "--config", "config.json"])

        self.assertEqual(exc.exception.code, 2)

    def test_main_only_configuration_succeeds_when_extension_is_disabled(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            root = Path(tmp)
            repo = root / "repo"
            cf = repo / "src" / "cf"
            docs = cf / "Documents"
            docs.mkdir(parents=True)
            forms = docs / "Р—Р°РєР°Р·" / "Forms"
            forms.mkdir(parents=True)
            (cf / "Configuration.xml").write_text(CONFIGURATION_XML, encoding="utf-8")
            (docs / "Р—Р°РєР°Р·.xml").write_text(DOCUMENT_XML, encoding="utf-8")
            (forms / "Р¤РѕСЂРјР°Р’С‹Р±РѕСЂР°.xml").write_text(FORM_XML.format(name="Р¤РѕСЂРјР°Р’С‹Р±РѕСЂР°"), encoding="utf-8")
            (forms / "Р¤РѕСЂРјР°Р”РѕРєСѓРјРµРЅС‚Р°.xml").write_text(FORM_XML.format(name="Р¤РѕСЂРјР°Р”РѕРєСѓРјРµРЅС‚Р°"), encoding="utf-8")

            output = root / "metadata"
            diagnostics = root / "diagnostics"
            logs = root / "logs"
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "project": "test",
                        "repoPath": str(repo),
                        "mainConfigPath": "src/cf",
                        "extensionPath": "",
                        "extensionRequired": False,
                        "outputPath": str(output),
                        "reportFileName": "Report.txt",
                        "diagnosticsPath": str(diagnostics),
                        "logsPath": str(logs),
                        "encoding": "utf-8",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            logging.shutdown()
            logging.getLogger().handlers.clear()
            exit_code = main(["--config", str(config)])

            self.assertEqual(exit_code, 0)
            report_path = output / "Report.txt"
            data = report_path.read_bytes()
            self.assertTrue(data.startswith(b"\xff\xfe"))
            self.assertIn("\r\n".encode("utf-16le"), data)
            self.assertNotIn("\r\r\n".encode("utf-16le"), data)
            report = read_report(report_path)
            self.assertTrue(report.startswith("\t- "))
            self.assertNotIn("\n\n\t- ", report)
            stats = json.loads((diagnostics / "report-stats.json").read_text(encoding="utf-8"))
            self.assertTrue(stats["mainConfigFound"])
            self.assertFalse(stats["extensionFound"])

    def test_extension_only_configuration_succeeds_when_main_is_disabled(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            root = Path(tmp)
            repo = root / "repo"
            cfe = repo / "src" / "cfe"
            cfe.mkdir(parents=True)
            (cfe / "Configuration.xml").write_text(EXTENSION_CONFIGURATION_WITH_ADOPTED_DOCUMENT_XML, encoding="utf-8")

            output = root / "metadata"
            diagnostics = root / "diagnostics"
            logs = root / "logs"
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "project": "test",
                        "repoPath": str(repo),
                        "mainConfigPath": "",
                        "mainConfigRequired": False,
                        "extensionPath": "src/cfe",
                        "extensionRequired": False,
                        "outputPath": str(output),
                        "reportFileName": "Report.txt",
                        "diagnosticsPath": str(diagnostics),
                        "logsPath": str(logs),
                        "encoding": "utf-8",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            logging.shutdown()
            logging.getLogger().handlers.clear()
            exit_code = main(["--config", str(config)])

            self.assertEqual(exit_code, 0)
            report = read_report(output / "Report.txt")
            self.assertTrue(report.startswith("\t- "))
            self.assertNotIn("\n\n\t- ", report)
            stats = json.loads((diagnostics / "report-stats.json").read_text(encoding="utf-8"))
            self.assertFalse(stats["mainConfigFound"])
            self.assertTrue(stats["extensionFound"])

    def test_extension_root_block_uses_native_compatible_order_and_defaults(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            root = Path(tmp)
            repo = root / "repo"
            cfe = repo / "src" / "cfe"
            cfe.mkdir(parents=True)
            languages = cfe / "Languages"
            languages.mkdir()
            (cfe / "Configuration.xml").write_text(EXTENSION_CONFIGURATION_NATIVE_COMPAT_XML, encoding="utf-8")
            (languages / "Русский.xml").write_text(LANGUAGE_RUSSIAN_WITHOUT_CODE_XML, encoding="utf-8")

            output = root / "metadata"
            diagnostics = root / "diagnostics"
            logs = root / "logs"
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "project": "test",
                        "repoPath": str(repo),
                        "mainConfigPath": "",
                        "mainConfigRequired": False,
                        "extensionPath": "src/cfe",
                        "extensionRequired": True,
                        "outputPath": str(output),
                        "reportFileName": "Report.txt",
                        "diagnosticsPath": str(diagnostics),
                        "logsPath": str(logs),
                        "encoding": "utf-8",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            logging.shutdown()
            logging.getLogger().handlers.clear()
            exit_code = main(["--config", str(config)])

            self.assertEqual(exit_code, 0)
            report_lines = read_report(output / "Report.txt").splitlines()
            expected_root = [
                "\t- Конфигурации.Расширение",
                '\t\tИмя: "Расширение"',
                '\t\tСиноним: "Расширение"',
                '\t\tКомментарий: ""',
                '\t\tНазначениеРасширенияКонфигурации: "Дополнение"',
                '\t\tПринадлежностьОбъекта: "Заимствованный"',
                '\t\tОбъектРасширяемойКонфигурации: ""',
                '\t\tПоддерживатьСоответствиеОбъектамРасширяемойКонфигурацииПоВнутреннимИдентификаторам: "Истина"',
                '\t\tПрефиксИмен: "шн_"',
                '\t\tРежимСовместимостиРасширенияКонфигурации: "Версия8_3_23"',
                '\t\tОсновнойРежимЗапуска: "УправляемоеПриложение"',
                '\t\tНазначенияИспользования: "ПриложениеПлатформы"',
                '\t\tВариантВстроенногоЯзыка: "Русский"',
                "\t\tОсновныеРоли:",
                '\t\t\t"Роль.шн_ОбменСШиной"',
                '\t\tПоставщик: "НМ"',
                '\t\tВерсия: "1.0.058"',
                '\t\tОсновнаяФормаОтчета: ""',
                '\t\tОсновнаяФормаВариантаОтчета: ""',
                '\t\tОсновнаяФормаНастроекОтчета: ""',
                '\t\tОсновнаяФормаНастроекДинамическогоСписка: ""',
                '\t\tОсновнаяФормаПоиска: ""',
                '\t\tОсновнаяФормаИсторииИзмененийИсторииДанных: ""',
                '\t\tОсновнаяФормаДанныхВерсииИсторииДанных: ""',
                '\t\tОсновнаяФормаРазличийВерсийИсторииДанных: ""',
                '\t\tОсновнаяФормаВыбораПользователейСистемыВзаимодействия: ""',
                '\t\tОсновнойСтиль: ""',
                '\t\tОсновнойЯзык: "Язык.Русский"',
                '\t\tКраткаяИнформация: ""',
                '\t\tПодробнаяИнформация: ""',
                '\t\tАвторскиеПрава: ""',
                '\t\tАдресИнформацииОПоставщике: ""',
                '\t\tАдресИнформацииОКонфигурации: ""',
                '\t\tРежимИспользованияМодальности: "НеИспользовать"',
                '\t\tРежимИспользованияСинхронныхВызововРасширенийПлатформыИВнешнихКомпонент: "НеИспользовать"',
                '\t\tРежимСовместимостиИнтерфейса: "ТаксиРазрешитьВерсия8_2"',
                '\t\tРежимИспользованияТабличныхПространствБазыДанных: "НеИспользовать"',
                '\t\tРежимСовместимости: "Версия8_3_24"',
            ]
            self.assertEqual(report_lines[: len(expected_root)], expected_root)
            self.assertEqual(report_lines[len(expected_root)], "\t\t- Языки.Русский")
            self.assertEqual(report_lines[len(expected_root) + 6], '\t\t\tКодЯзыка: "ru"')

    def test_minimal_configuration_generates_report(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            root = Path(tmp)
            repo = root / "repo"
            cf = repo / "src" / "cf"
            docs = cf / "Documents"
            docs.mkdir(parents=True)
            forms = docs / "Заказ" / "Forms"
            forms.mkdir(parents=True)
            (cf / "Configuration.xml").write_text(CONFIGURATION_XML, encoding="utf-8")
            (docs / "Заказ.xml").write_text(DOCUMENT_XML, encoding="utf-8")
            (forms / "ФормаВыбора.xml").write_text(FORM_XML.format(name="ФормаВыбора"), encoding="utf-8")
            (forms / "ФормаДокумента.xml").write_text(FORM_XML.format(name="ФормаДокумента"), encoding="utf-8")

            output = root / "metadata"
            diagnostics = root / "diagnostics"
            logs = root / "logs"
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "project": "test",
                        "repoPath": str(repo),
                        "mainConfigPath": "src/cf",
                        "extensionPath": "src/cfe",
                        "extensionRequired": False,
                        "outputPath": str(output),
                        "reportFileName": "Report.txt",
                        "diagnosticsPath": str(diagnostics),
                        "logsPath": str(logs),
                        "encoding": "utf-8",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            logging.shutdown()
            logging.getLogger().handlers.clear()
            exit_code = main(["--config", str(config)])

            self.assertEqual(exit_code, 1)
            report = read_report(output / "Report.txt")
            self.assertIn("\t- Конфигурации.Тестовая\n", report)
            self.assertIn('\t\tСиноним: "Тестовая конфигурация"\n', report)
            self.assertIn('\t\tРежимСовместимостиРасширенияКонфигурации: "НеИспользовать"\n', report)
            self.assertIn("\t\t- Документы.Заказ\n", report)
            self.assertIn("\t\t\t- Документы.Заказ.Реквизиты.НомерВнешний\n", report)
            self.assertLess(report.index("Реквизиты.НомерВнешний"), report.index("Формы.ФормаДокумента"))
            self.assertLess(report.index("Формы.ФормаДокумента"), report.index("Формы.ФормаВыбора"))
            self.assertNotIn("src/cf", report)
            self.assertTrue((diagnostics / "report-diagnostics.json").exists())
            self.assertTrue((diagnostics / "report-stats.json").exists())
            stats = json.loads((diagnostics / "report-stats.json").read_text(encoding="utf-8"))
            self.assertIn("warningEvents", stats)
            self.assertIn("warningGroups", stats)

    def test_extension_adopted_top_level_object_is_created_from_configuration_xml(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            root = Path(tmp)
            repo = root / "repo"
            cf = repo / "src" / "cf"
            cfe = repo / "src" / "cfe"
            docs = cf / "Documents"
            docs.mkdir(parents=True)
            cfe.mkdir(parents=True)
            (cf / "Configuration.xml").write_text(CONFIGURATION_XML, encoding="utf-8")
            (docs / "Заказ.xml").write_text(DOCUMENT_XML, encoding="utf-8")
            (cfe / "Configuration.xml").write_text(EXTENSION_CONFIGURATION_WITH_ADOPTED_DOCUMENT_XML, encoding="utf-8")

            output = root / "metadata"
            diagnostics = root / "diagnostics"
            logs = root / "logs"
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "project": "test",
                        "repoPath": str(repo),
                        "mainConfigPath": "src/cf",
                        "extensionPath": "src/cfe",
                        "extensionRequired": False,
                        "outputPath": str(output),
                        "reportFileName": "Report.txt",
                        "diagnosticsPath": str(diagnostics),
                        "logsPath": str(logs),
                        "encoding": "utf-8",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            logging.shutdown()
            logging.getLogger().handlers.clear()
            exit_code = main(["--config", str(config)])

            self.assertEqual(exit_code, 0)
            report = read_report(output / "Report.txt")
            self.assertEqual(report.count("\t\t- Документы.Заказ\n"), 2)
            self.assertIn('\t\t\tТипНомера: "Строка"\n', report)
            self.assertIn('\t\t\tДлинаНомера: "9"\n', report)
            self.assertIn('\t\tПринадлежностьОбъекта: "Заимствованный"\n', report)


    def test_extension_adopted_catalog_uses_synthetic_defaults_instead_of_main_values(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            root = Path(tmp)
            repo = root / "repo"
            cf = repo / "src" / "cf"
            cfe = repo / "src" / "cfe"
            catalogs = cf / "Catalogs"
            catalogs.mkdir(parents=True)
            cfe.mkdir(parents=True)
            (cf / "Configuration.xml").write_text(CONFIGURATION_WITH_CATALOG_XML, encoding="utf-8")
            (catalogs / "TestCatalog.xml").write_text(CATALOG_XML, encoding="utf-8")
            (cfe / "Configuration.xml").write_text(EXTENSION_CONFIGURATION_WITH_ADOPTED_CATALOG_XML, encoding="utf-8")

            output = root / "metadata"
            diagnostics = root / "diagnostics"
            logs = root / "logs"
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "project": "test",
                        "repoPath": str(repo),
                        "mainConfigPath": "src/cf",
                        "extensionPath": "src/cfe",
                        "extensionRequired": False,
                        "outputPath": str(output),
                        "reportFileName": "Report.txt",
                        "diagnosticsPath": str(diagnostics),
                        "logsPath": str(logs),
                        "encoding": "utf-8",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            logging.shutdown()
            logging.getLogger().handlers.clear()
            exit_code = main(["--config", str(config)])

            self.assertEqual(exit_code, 0)
            report = read_report(output / "Report.txt")
            catalog_line = "\t\t- \u0421\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0438.TestCatalog\n"
            code6_line = '\t\t\t\u0414\u043b\u0438\u043d\u0430\u041a\u043e\u0434\u0430: "6"\n'
            code9_line = '\t\t\t\u0414\u043b\u0438\u043d\u0430\u041a\u043e\u0434\u0430: "9"\n'
            desc100_line = '\t\t\t\u0414\u043b\u0438\u043d\u0430\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u044f: "100"\n'
            desc25_line = '\t\t\t\u0414\u043b\u0438\u043d\u0430\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u044f: "25"\n'
            type_number_line = '\t\t\t\u0422\u0438\u043f\u041a\u043e\u0434\u0430: "\u0427\u0438\u0441\u043b\u043e"\n'
            type_string_line = '\t\t\t\u0422\u0438\u043f\u041a\u043e\u0434\u0430: "\u0421\u0442\u0440\u043e\u043a\u0430"\n'
            adopted_line = '\t\t\t\u041f\u0440\u0438\u043d\u0430\u0434\u043b\u0435\u0436\u043d\u043e\u0441\u0442\u044c\u041e\u0431\u044a\u0435\u043a\u0442\u0430: "\u0417\u0430\u0438\u043c\u0441\u0442\u0432\u043e\u0432\u0430\u043d\u043d\u044b\u0439"\n'
            hierarchical_false_line = '\t\t\t\u0418\u0435\u0440\u0430\u0440\u0445\u0438\u0447\u0435\u0441\u043a\u0438\u0439: "\u041b\u043e\u0436\u044c"\n'

            self.assertEqual(report.count(catalog_line), 2)
            self.assertEqual(report.count(code6_line), 1)
            self.assertEqual(report.count(code9_line), 1)
            self.assertEqual(report.count(desc100_line), 1)
            self.assertEqual(report.count(desc25_line), 1)
            self.assertEqual(report.count(type_number_line), 1)
            self.assertEqual(report.count(type_string_line), 1)
            self.assertIn(hierarchical_false_line, report)
            self.assertIn(adopted_line, report)

    def test_generator_fails_when_no_source_directories_are_available(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir(parents=True)

            output = root / "metadata"
            diagnostics = root / "diagnostics"
            logs = root / "logs"
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "project": "test",
                        "repoPath": str(repo),
                        "mainConfigPath": "src/cf",
                        "mainConfigRequired": False,
                        "extensionPath": "src/cfe",
                        "extensionRequired": False,
                        "outputPath": str(output),
                        "reportFileName": "Report.txt",
                        "diagnosticsPath": str(diagnostics),
                        "logsPath": str(logs),
                        "encoding": "utf-8",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            logging.shutdown()
            logging.getLogger().handlers.clear()
            exit_code = main(["--config", str(config)])

            self.assertEqual(exit_code, 9)
            diagnostics_data = json.loads((diagnostics / "report-diagnostics.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["code"] == "noMetadataSources" for item in diagnostics_data["errors"]))


class ConfigTests(unittest.TestCase):
    def test_load_config_requires_at_least_one_metadata_source_path(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            root = Path(tmp)
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "project": "test",
                        "repoPath": str(root / "repo"),
                        "mainConfigPath": "",
                        "mainConfigRequired": False,
                        "extensionPath": "",
                        "extensionRequired": False,
                        "outputPath": str(root / "metadata"),
                        "reportFileName": "Report.txt",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "At least one metadata source path must be configured"):
                load_config(config)


class SettingsAndOverridesTests(unittest.TestCase):
    def test_load_settings_merges_overlay_with_defaults(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            overlay = Path(tmp) / "overlay.json"
            overlay.write_text(
                json.dumps(
                    {
                        "standardAttributeKeepEmptyValueOwnerAttributes": ["Справочники.Тест|Владелец"],
                        "standardAttributeKeepDefaultOwnerAttributeProperties": ["Справочники.Тест|Наименование|ПроверкаЗаполнения"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            settings = load_settings(overlay)

            self.assertIn("utf-8", settings.supported_encodings)
            self.assertEqual(settings.standard_attribute_keep_empty_value_owner_attributes, ("Справочники.Тест|Владелец",))
            self.assertEqual(
                settings.standard_attribute_keep_default_owner_attribute_properties,
                ("Справочники.Тест|Наименование|ПроверкаЗаполнения",),
            )

    def test_collect_standard_attribute_keep_empty_overrides_from_xml(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            repo = Path(tmp) / "repo"
            catalogs = repo / "src" / "cf" / "Catalogs"
            extension = repo / "src" / "cfe"
            catalogs.mkdir(parents=True)
            extension.mkdir(parents=True)
            (catalogs / "Файлы.xml").write_text(CATALOG_OWNER_XML, encoding="utf-8")
            (catalogs / "ПредопределенныеВариантыОтчетовРасширений.xml").write_text(CATALOG_PARENT_XML, encoding="utf-8")
            (catalogs / "Обычный.xml").write_text(CATALOG_NONE_XML, encoding="utf-8")

            pairs = collect_standard_attribute_keep_empty_overrides(repo / "src" / "cf", extension, SETTINGS)

            self.assertEqual(
                pairs,
                [
                    "Справочники.ПредопределенныеВариантыОтчетовРасширений|Родитель",
                    "Справочники.Файлы|Владелец",
                ],
            )

    def test_collect_standard_attribute_keep_empty_overrides_from_zero_guid_design_time_ref(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            repo = Path(tmp) / "repo"
            catalogs = repo / "src" / "cf" / "Catalogs"
            catalogs.mkdir(parents=True)
            zero_guid_xml = CATALOG_OWNER_XML.replace(
                '<xr:FillValue xsi:nil="true"/>',
                '<xr:FillValue xsi:type="xr:DesignTimeRef">357cf802-45da-4084-adb7-a07496253859.00000000-0000-0000-0000-000000000000</xr:FillValue>',
                1,
            )
            (catalogs / "Файлы.xml").write_text(zero_guid_xml, encoding="utf-8")

            pairs = collect_standard_attribute_keep_empty_overrides(repo / "src" / "cf", None, SETTINGS)

            self.assertEqual(pairs, ["Справочники.Файлы|Владелец"])

    def test_collect_standard_attribute_keep_empty_overrides_for_attached_file_catalogs(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            repo = Path(tmp) / "repo"
            catalogs = repo / "src" / "cf" / "Catalogs"
            catalogs.mkdir(parents=True)
            attached_file_xml = CATALOG_OWNER_XML.replace("<Name>Файлы</Name>", "<Name>ДокументПрисоединенныеФайлы</Name>").replace(
                "<CreateOnInput>DontUse</CreateOnInput>",
                "<CreateOnInput>Use</CreateOnInput>\n      <Comment>Подчиненный справочник файлов</Comment>\n      <InputByString><xr:Field>Catalog.ДокументПрисоединенныеФайлы.StandardAttribute.Description</xr:Field></InputByString>",
            )
            (catalogs / "ДокументПрисоединенныеФайлы.xml").write_text(attached_file_xml, encoding="utf-8")

            pairs = collect_standard_attribute_keep_empty_overrides(repo / "src" / "cf", None, SETTINGS)

            self.assertEqual(pairs, ["Справочники.ДокументПрисоединенныеФайлы|Владелец"])


    def test_collect_standard_attribute_keep_default_overrides_from_xml(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            repo = Path(tmp) / "repo"
            catalogs = repo / "src" / "cf" / "Catalogs"
            extension = repo / "src" / "cfe"
            catalogs.mkdir(parents=True)
            extension.mkdir(parents=True)
            (catalogs / "Файлы.xml").write_text(CATALOG_DESCRIPTION_DONT_CHECK_XML, encoding="utf-8")
            (catalogs / "Обычный.xml").write_text(CATALOG_NONE_XML, encoding="utf-8")

            pairs = collect_standard_attribute_keep_default_overrides(repo / "src" / "cf", extension, SETTINGS)

            self.assertEqual(
                pairs,
                ["Справочники.Файлы|Наименование|ПроверкаЗаполнения"],
            )


class PropertyExtractorTests(unittest.TestCase):
    def test_configuration_default_keep_mapping_is_emitted_when_xml_node_is_absent(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(
            """<Configuration>
  <Properties>
    <Name>Тест</Name>
  </Properties>
</Configuration>"""
        )

        props = extract_properties(root, SETTINGS.configuration_whitelist, Diagnostics("test"), SETTINGS, include_extra_properties=False)

        self.assertIn(
            ReportProperty(
                "ПоддерживатьСоответствиеОбъектамРасширяемойКонфигурацииПоВнутреннимИдентификаторам",
                "Истина",
            ),
            props,
        )

    def test_standard_attribute_suppresses_noisy_properties_by_name(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(STANDARD_ATTRIBUTE_SUPPRESSION_XML)
        standard_attributes_name = next(
            key for key, aliases in SETTINGS.property_aliases.items() if "StandardAttributes" in aliases
        )

        prop = extract_properties(
            root,
            (standard_attributes_name,),
            Diagnostics("test"),
            SETTINGS,
            include_extra_properties=False,
            owner_name="\u0421\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0438.\u0424\u0430\u0439\u043b\u044b",
            owner_type_key="catalog",
        )[0]

        self.assertEqual(
            prop,
            ReportProperty(
                standard_attributes_name,
                [
                    (
                        "\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435",
                        [ReportProperty("\u041f\u043e\u0434\u0441\u043a\u0430\u0437\u043a\u0430", "\u0418\u043c\u044f \u0444\u0430\u0439\u043b\u0430", "scalar")],
                    ),
                ],
                "named_object_list",
            ),
        )

    def test_standard_attribute_keeps_name_and_parent_fill_check_when_not_globally_suppressed(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(STANDARD_ATTRIBUTE_NAME_AND_PARENT_XML)
        standard_attributes_name = next(
            key for key, aliases in SETTINGS.property_aliases.items() if "StandardAttributes" in aliases
        )

        prop = extract_properties(
            root,
            (standard_attributes_name,),
            Diagnostics("test"),
            SETTINGS,
            include_extra_properties=False,
            owner_name="\u0421\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0438.\u0422\u0435\u0441\u0442",
            owner_type_key="catalog",
        )[0]

        self.assertEqual(
            prop,
            ReportProperty(
                standard_attributes_name,
                [
                    ("\u0420\u043e\u0434\u0438\u0442\u0435\u043b\u044c", [ReportProperty("\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f", "\u0412\u044b\u0434\u0430\u0432\u0430\u0442\u044c\u041e\u0448\u0438\u0431\u043a\u0443", "scalar")]),
                ],
                "named_object_list",
            ),
        )

    def test_standard_attribute_keeps_default_property_for_owner_attribute_triplet(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            overlay = Path(tmp) / "overlay.json"
            overlay.write_text(
                json.dumps(
                    {
                        "standardAttributeKeepDefaultOwnerAttributeProperties": [
                            "Справочники.Тест|Наименование|ПроверкаЗаполнения"
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = load_settings(overlay)
            configure_extractor(settings)
            root = ET.fromstring(STANDARD_ATTRIBUTE_NAME_AND_PARENT_XML)
            standard_attributes_name = next(
                key for key, aliases in settings.property_aliases.items() if "StandardAttributes" in aliases
            )

            prop = extract_properties(
                root,
                (standard_attributes_name,),
                Diagnostics("test"),
                settings,
                include_extra_properties=False,
                owner_name="Справочники.Тест",
                owner_type_key="catalog",
            )[0]

            self.assertEqual(
                prop,
                ReportProperty(
                    standard_attributes_name,
                    [
                        ("Наименование", [ReportProperty("ПроверкаЗаполнения", "НеПроверять", "scalar")]),
                        ("Родитель", [ReportProperty("ПроверкаЗаполнения", "ВыдаватьОшибку", "scalar")]),
                    ],
                    "named_object_list",
                ),
            )

    def test_standard_attribute_keeps_period_fill_checking_by_default(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(STANDARD_ATTRIBUTE_PERIOD_XML)
        standard_attributes_name = next(
            key for key, aliases in SETTINGS.property_aliases.items() if "StandardAttributes" in aliases
        )

        prop = extract_properties(
            root,
            (standard_attributes_name,),
            Diagnostics("test"),
            SETTINGS,
            include_extra_properties=False,
            owner_name="РегистрыСведений.шн_РесурсыЗаданийОбработкиДокументов",
            owner_type_key="information_register",
        )[0]

        self.assertEqual(
            prop,
            ReportProperty(
                standard_attributes_name,
                [("Период", [ReportProperty("ПроверкаЗаполнения", "НеПроверять", "scalar")])],
                "named_object_list",
            ),
        )

    def test_standard_attribute_suppresses_properties_by_owner_type_and_name(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(STANDARD_ATTRIBUTE_TYPE_SPECIFIC_SUPPRESSION_XML)
        standard_attributes_name = next(
            key for key, aliases in SETTINGS.property_aliases.items() if "StandardAttributes" in aliases
        )

        document_prop = extract_properties(
            root,
            (standard_attributes_name,),
            Diagnostics("test"),
            SETTINGS,
            include_extra_properties=False,
            owner_name="\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u044b.\u0422\u0435\u0441\u0442",
            owner_type_key="document",
        )[0]
        exchange_plan_prop = extract_properties(
            root,
            (standard_attributes_name,),
            Diagnostics("test"),
            SETTINGS,
            include_extra_properties=False,
            owner_name="\u041f\u043b\u0430\u043d\u044b\u041e\u0431\u043c\u0435\u043d\u0430.\u0422\u0435\u0441\u0442",
            owner_type_key="exchange_plan",
        )[0]
        catalog_prop = extract_properties(
            root,
            (standard_attributes_name,),
            Diagnostics("test"),
            SETTINGS,
            include_extra_properties=False,
            owner_name="\u0421\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0438.\u0422\u0435\u0441\u0442",
            owner_type_key="catalog",
        )[0]

        self.assertEqual(
            document_prop,
            ReportProperty(
                standard_attributes_name,
                [
                    (
                        "\u041a\u043e\u0434",
                        [
                            ReportProperty("\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f", "\u0412\u044b\u0434\u0430\u0432\u0430\u0442\u044c\u041e\u0448\u0438\u0431\u043a\u0443", "scalar"),
                            ReportProperty("\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f", "\u0421\u0442\u0440\u043e\u043a\u0430:123", "scalar"),
                        ],
                    ),
                    ("\u041d\u043e\u043c\u0435\u0440", [ReportProperty("\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f", "\u0412\u044b\u0434\u0430\u0432\u0430\u0442\u044c\u041e\u0448\u0438\u0431\u043a\u0443", "scalar")]),
                ],
                "named_object_list",
            ),
        )
        self.assertEqual(
            exchange_plan_prop,
            ReportProperty(
                standard_attributes_name,
                [
                    ("\u041a\u043e\u0434", [ReportProperty("\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f", "\u0421\u0442\u0440\u043e\u043a\u0430:123", "scalar")]),
                    (
                        "\u041d\u043e\u043c\u0435\u0440",
                        [
                            ReportProperty("\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f", "\u0412\u044b\u0434\u0430\u0432\u0430\u0442\u044c\u041e\u0448\u0438\u0431\u043a\u0443", "scalar"),
                            ReportProperty("\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f", "\u0421\u0442\u0440\u043e\u043a\u0430:123", "scalar"),
                        ],
                    ),
                ],
                "named_object_list",
            ),
        )
        self.assertEqual(
            catalog_prop,
            ReportProperty(
                standard_attributes_name,
                [
                    (
                        "\u041a\u043e\u0434",
                        [
                            ReportProperty("\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f", "\u0412\u044b\u0434\u0430\u0432\u0430\u0442\u044c\u041e\u0448\u0438\u0431\u043a\u0443", "scalar"),
                            ReportProperty("\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f", "\u0421\u0442\u0440\u043e\u043a\u0430:123", "scalar"),
                        ],
                    ),
                    (
                        "\u041d\u043e\u043c\u0435\u0440",
                        [
                            ReportProperty("\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f", "\u0412\u044b\u0434\u0430\u0432\u0430\u0442\u044c\u041e\u0448\u0438\u0431\u043a\u0443", "scalar"),
                            ReportProperty("\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435\u0417\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f", "\u0421\u0442\u0440\u043e\u043a\u0430:123", "scalar"),
                        ],
                    ),
                ],
                "named_object_list",
            ),
        )

    def test_type_and_choice_links_match_reference_format(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(TYPE_AND_CHOICE_XML)

        type_prop = extract_property(root, "Тип", SETTINGS)
        links_prop = extract_property(root, "СвязиПараметровВыбора", SETTINGS)

        self.assertEqual(type_prop, ReportProperty("Тип", ["Характеристика.ДополнительныеРеквизитыИСведения"], "list"))
        self.assertEqual(links_prop, ReportProperty("СвязиПараметровВыбора", ["Отбор.Владелец(ДополнительныеРеквизиты.Свойство)"], "list"))

    def test_reference_specific_values_are_formatted(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(REFERENCE_VALUE_XML)

        use_purposes = extract_property(root, "НазначенияИспользования", SETTINGS)
        value_type = extract_property(root, "Тип", SETTINGS)
        fill_value = extract_property(root, "ЗначениеЗаполнения", SETTINGS)
        form_type = extract_property(root, "ТипФормы", SETTINGS)
        lock_mode = extract_property(root, "РежимУправленияБлокировкойДанных", SETTINGS)
        write_mode = extract_property(root, "РежимЗаписи", SETTINGS)

        self.assertEqual(use_purposes, ReportProperty("НазначенияИспользования", "ПриложениеПлатформы, ПриложениеМобильнойПлатформы"))
        self.assertEqual(value_type, ReportProperty("Тип", ["Дата(ДатаВремя)", "ХранилищеЗначения"], "list"))
        self.assertIsNone(fill_value)
        self.assertEqual(form_type, ReportProperty("ТипФормы", "Управляемая"))
        self.assertEqual(lock_mode, ReportProperty("РежимУправленияБлокировкойДанных", "Управляемый"))
        self.assertEqual(write_mode, ReportProperty("РежимЗаписи", "Независимый"))

    def test_zero_guid_design_time_ref_fill_value_is_empty(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(
            """<Attribute xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <FillValue xsi:type="xr:DesignTimeRef">357cf802-45da-4084-adb7-a07496253859.00000000-0000-0000-0000-000000000000</FillValue>
  </Properties>
</Attribute>"""
        )

        fill_value = extract_property(root, "ЗначениеЗаполнения", SETTINGS)

        self.assertEqual(fill_value, ReportProperty("ЗначениеЗаполнения", ""))

    def test_standard_tabular_sections_are_extracted_from_standard_tabular_sections_node(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(
            """<ChartOfCalculationTypes xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <StandardTabularSections>
      <xr:StandardTabularSection name="LeadingCalculationTypes"/>
      <xr:StandardTabularSection name="DisplacingCalculationTypes"/>
      <xr:StandardTabularSection name="BaseCalculationTypes"/>
    </StandardTabularSections>
  </Properties>
</ChartOfCalculationTypes>"""
        )

        prop = extract_property(root, "СтандартныеТабличныеЧасти", SETTINGS)

        self.assertEqual(
            prop,
            ReportProperty(
                "СтандартныеТабличныеЧасти",
                [
                    ("ВедущиеВидыРасчета", []),
                    ("ВытесняющиеВидыРасчета", []),
                    ("БазовыеВидыРасчета", []),
                ],
                "named_object_list",
            ),
        )

    def test_empty_full_text_search_dictionaries_are_written_as_empty_list(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(
            """<Configuration>
  <Properties>
    <AdditionalFullTextSearchDictionaries/>
  </Properties>
</Configuration>"""
        )

        prop = extract_property(root, "ДополнительныеСловариПолнотекстовогоПоиска", SETTINGS)

        self.assertEqual(prop, ReportProperty("ДополнительныеСловариПолнотекстовогоПоиска", [], "list"))

    def test_comment_preserves_trailing_spaces(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(
            """<Attribute>
  <Properties>
    <Comment>АПК:58 </Comment>
  </Properties>
</Attribute>"""
        )

        prop = extract_property(root, "Комментарий", SETTINGS)

        self.assertEqual(prop, ReportProperty("Комментарий", "АПК:58 "))

    def test_mobile_application_functionalities_use_reference_multiline_format(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(
            """<Configuration xmlns:app="http://v8.1c.ru/8.2/managed-application/core">
  <Properties>
    <UsedMobileApplicationFunctionalities>
      <app:functionality>
        <app:functionality>Biometrics</app:functionality>
        <app:use>true</app:use>
      </app:functionality>
      <app:functionality>
        <app:functionality>Location</app:functionality>
        <app:use>false</app:use>
      </app:functionality>
    </UsedMobileApplicationFunctionalities>
  </Properties>
</Configuration>"""
        )

        prop = extract_property(root, "ИспользуемаяФункциональностьМобильногоПриложения", SETTINGS)

        self.assertEqual(
            prop,
            ReportProperty(
                "ИспользуемаяФункциональностьМобильногоПриложения",
                "Функциональность:\nБиометрия = Истина\nГеопозиционирование = Ложь",
            ),
        )

    def test_recent_reference_value_translations_are_applied(self) -> None:
        configure_extractor(SETTINGS)

        self.assertEqual(format_value("AutoDelete"), "УдалятьАвтоматически")
        self.assertEqual(format_value("FromForm"), "ИзФормы")
        self.assertEqual(format_value("DocumentNumerator.ПерсонифицированныйУчет"), "НумераторДокументов.ПерсонифицированныйУчет")

    def test_task_number_auto_prefix_uses_reference_property_name(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(
            """<Task>
  <Properties>
    <TaskNumberAutoPrefix>BusinessProcessNumber</TaskNumberAutoPrefix>
  </Properties>
</Task>"""
        )

        prop = extract_property(root, "АвтоПрефиксНомераЗадачи", SETTINGS)

        self.assertEqual(prop, ReportProperty("АвтоПрефиксНомераЗадачи", "НомерБизнесПроцесса"))

    def test_business_process_head_task_keeps_empty_fill_value_as_leading_task(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(
            """<BusinessProcess xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Properties>
    <StandardAttributes>
      <xr:StandardAttribute name="HeadTask">
        <xr:FillValue xsi:type="xr:DesignTimeRef">Task.ЗадачаИсполнителя.EmptyRef</xr:FillValue>
      </xr:StandardAttribute>
    </StandardAttributes>
  </Properties>
</BusinessProcess>"""
        )

        prop = extract_property(root, "СтандартныеРеквизиты", SETTINGS)

        self.assertEqual(
            prop,
            ReportProperty("СтандартныеРеквизиты", [("ВедущаяЗадача", [ReportProperty("ЗначениеЗаполнения", "")])], "named_object_list"),
        )

    def test_calculation_register_properties_use_report_names_and_suppress_standard_attribute_noise(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(
            """<CalculationRegister xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <Periodicity>Month</Periodicity>
    <ActionPeriod>true</ActionPeriod>
    <BasePeriod>true</BasePeriod>
    <Schedule>InformationRegister.Графики</Schedule>
    <ScheduleValue>InformationRegister.Графики.Resource.Значение</ScheduleValue>
    <ScheduleDate>InformationRegister.Графики.Dimension.Дата</ScheduleDate>
    <ScheduleLink/>
    <ChartOfCalculationTypes>ChartOfCalculationTypes.Начисления</ChartOfCalculationTypes>
    <StandardAttributes>
      <xr:StandardAttribute name="RegistrationPeriod">
        <xr:FillChecking>ShowError</xr:FillChecking>
      </xr:StandardAttribute>
      <xr:StandardAttribute name="CalculationType">
        <xr:FillChecking>ShowError</xr:FillChecking>
      </xr:StandardAttribute>
    </StandardAttributes>
  </Properties>
</CalculationRegister>"""
        )

        props = extract_properties(
            root,
            (
                "Периодичность",
                "ПериодДействия",
                "БазовыйПериод",
                "График",
                "ЗначениеГрафика",
                "ДатаГрафика",
                "СвязьСГрафиком",
                "ПланВидовРасчета",
                "СтандартныеРеквизиты",
            ),
            Diagnostics("test"),
            SETTINGS,
            include_extra_properties=False,
            owner_type_key="calculation_register",
        )

        self.assertEqual(
            props,
            [
                ReportProperty("Периодичность", "Месяц"),
                ReportProperty("ПериодДействия", "Истина"),
                ReportProperty("БазовыйПериод", "Истина"),
                ReportProperty("График", "РегистрСведений.Графики"),
                ReportProperty("ЗначениеГрафика", "РегистрСведений.Графики.Ресурс.Значение"),
                ReportProperty("ДатаГрафика", "РегистрСведений.Графики.Измерение.Дата"),
                ReportProperty("СвязьСГрафиком", ""),
                ReportProperty("ПланВидовРасчета", "ПланВидовРасчета.Начисления"),
                ReportProperty("СтандартныеРеквизиты", "", "marker"),
            ],
        )

    def test_fixed_string_whitespace_fill_value_is_empty(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(FIXED_STRING_WHITESPACE_FILL_VALUE_XML)

        fill_value = extract_property(root, "ЗначениеЗаполнения", SETTINGS)

        self.assertEqual(fill_value, ReportProperty("ЗначениеЗаполнения", ""))

    def test_variable_string_whitespace_fill_value_is_preserved(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(VARIABLE_STRING_WHITESPACE_FILL_VALUE_XML)

        fill_value = extract_property(root, "ЗначениеЗаполнения", SETTINGS)

        self.assertEqual(fill_value, ReportProperty("ЗначениеЗаполнения", "Строка:" + " " * 36))

    def test_localized_tooltip_preserves_significant_spaces(self) -> None:
        configure_extractor(SETTINGS)

        tooltip_prop = extract_property(ET.fromstring(TOOLTIP_SINGLE_SPACE_XML), "Подсказка", SETTINGS)
        self.assertEqual(tooltip_prop, ReportProperty("Подсказка", " "))

        tooltip_prop = extract_property(ET.fromstring(TOOLTIP_TRAILING_SPACE_XML), "Подсказка", SETTINGS)
        self.assertEqual(tooltip_prop, ReportProperty("Подсказка", "Глобальный уникальный идентификатор объекта "))

    def test_key_guid_is_not_filtered_as_unsafe_value(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(SCHEDULED_JOB_KEY_XML)

        key_prop = extract_property(root, "Ключ", SETTINGS)

        self.assertEqual(key_prop, ReportProperty("Ключ", "9fa79867-46b8-4060-9694-eb85d6ecf1ea"))

    def test_xdto_packages_are_scalar_and_mdobjectref_is_unknown_object(self) -> None:
        configure_extractor(SETTINGS)

        packages_prop = extract_property(ET.fromstring(XDTO_PACKAGES_XML), "ПакетыXDTO", SETTINGS)
        self.assertEqual(packages_prop, ReportProperty("ПакетыXDTO", "НеизвестныйОбъект"))

        packages_prop = extract_property(ET.fromstring(XDTO_PACKAGES_URI_XML), "ПакетыXDTO", SETTINGS)
        self.assertEqual(packages_prop, ReportProperty("ПакетыXDTO", "http://v8.1c.ru/8.1/data/core"))

    def test_source_typeset_is_extracted_as_metadata_reference(self) -> None:
        configure_extractor(SETTINGS)

        source_prop = extract_property(ET.fromstring(EVENT_SUBSCRIPTION_SOURCE_XML), "Источник", SETTINGS)
        self.assertEqual(source_prop, ReportProperty("Источник", ["ПланОбменаОбъект"], "list"))

    def test_input_by_string_uses_standard_attribute_name_translation(self) -> None:
        configure_extractor(SETTINGS)

        input_prop = extract_property(ET.fromstring(INPUT_BY_STRING_STANDARD_ATTRIBUTE_XML), "ВводПоСтроке", SETTINGS)
        self.assertEqual(input_prop, ReportProperty("ВводПоСтроке", ["Номер"], "list"))

    def test_marker_properties_by_type_are_emitted_without_values(self) -> None:
        configure_extractor(SETTINGS)

        use_prop = extract_property_with_used_names(
            ET.fromstring(FUNCTIONAL_OPTION_PARAMETER_USE_XML),
            "Использование",
            SETTINGS,
            owner_type_key="functional_option_parameter",
        )[0]
        self.assertEqual(use_prop, ReportProperty("Использование", "", "marker"))

        references_prop = extract_property_with_used_names(
            ET.fromstring(DOCUMENT_JOURNAL_COLUMN_REFERENCES_XML),
            "Ссылки",
            SETTINGS,
            owner_type_key="document_journal_column",
        )[0]
        self.assertEqual(references_prop, ReportProperty("Ссылки", "", "marker"))

    def test_empty_quoted_list_property_is_emitted_for_used_empty_node(self) -> None:
        configure_extractor(SETTINGS)

        shortcut_name = "СочетаниеКлавиш"
        shortcut_prop = extract_property(ET.fromstring(EMPTY_SHORTCUT_XML), shortcut_name, SETTINGS)

        self.assertEqual(shortcut_prop, ReportProperty(shortcut_name, [""], "list"))

    def test_characteristic_data_path_field_uses_types_filter_field_by_strategy(self) -> None:
        configure_extractor(SETTINGS)
        prop = extract_property(ET.fromstring(CHARACTERISTICS_NEGATIVE_DATA_PATH_XML), "Характеристики", SETTINGS)
        self.assertIsNotNone(prop)
        self.assertEqual(prop.kind, "object_list")
        first_group = prop.value[0]
        self.assertEqual(first_group[4], ReportProperty("ПолеПутиКДанным", "ИмяПредопределенногоНабора"))

    def test_characteristic_zero_fields_are_blank_by_settings(self) -> None:
        configure_extractor(SETTINGS)
        property_name = next(key for key, aliases in SETTINGS.property_aliases.items() if "Characteristics" in aliases)
        prop = extract_property(ET.fromstring(CHARACTERISTICS_ZERO_FIELDS_XML), property_name, SETTINGS)
        self.assertIsNotNone(prop)
        self.assertEqual(prop.kind, "object_list")
        first_group = prop.value[0]
        by_name = {item.name: item for item in first_group}
        data_path_name = translate_value("DataPathField")
        types_filter_name = translate_value("TypesFilterField")
        self.assertEqual(by_name[data_path_name], ReportProperty(data_path_name, by_name[types_filter_name].value))
        multiple_key_name = translate_value("MultipleValuesKeyField")
        self.assertEqual(by_name[multiple_key_name], ReportProperty(multiple_key_name, ""))
        multiple_order_name = translate_value("MultipleValuesOrderField")
        self.assertEqual(by_name[multiple_order_name], ReportProperty(multiple_order_name, ""))

    def test_characteristic_data_path_uses_types_filter_prefix_for_attribute_paths(self) -> None:
        configure_extractor(SETTINGS)
        property_name = next(key for key, aliases in SETTINGS.property_aliases.items() if "Characteristics" in aliases)
        prop = extract_property(ET.fromstring(CHARACTERISTICS_COMPOSED_DATA_PATH_XML), property_name, SETTINGS)
        self.assertIsNotNone(prop)
        self.assertEqual(prop.kind, "object_list")
        first_group = prop.value[0]
        by_name = {item.name: item for item in first_group}
        data_path_name = translate_value("DataPathField")
        types_filter_name = translate_value("TypesFilterField")
        key_field_name = translate_value("KeyField")
        self.assertEqual(
            by_name[data_path_name],
            ReportProperty(data_path_name, f"{by_name[types_filter_name].value}.{by_name[key_field_name].value}"),
        )

    def test_type_values_follow_priority_prefixes_from_settings(self) -> None:
        configure_extractor(SETTINGS)
        prop = extract_property(ET.fromstring(MIXED_TYPE_ORDER_XML), "Тип", SETTINGS)
        self.assertEqual(
            prop,
            ReportProperty(
                "Тип",
                ["ЛюбаяСсылка", "Булево", "Строка(128, Переменная)", "Дата(ДатаВремя)", "Число(16, 2)"],
                "list",
            ),
        )

    def test_type_values_keep_specific_refs_before_primitives_and_generic_refs_last(self) -> None:
        configure_extractor(SETTINGS)
        property_name = next(key for key, aliases in SETTINGS.property_aliases.items() if "Type" in aliases)
        prop = extract_property(ET.fromstring(MIXED_TYPE_SPECIFIC_AND_GENERIC_REFS_XML), property_name, SETTINGS)
        self.assertIsNotNone(prop)
        self.assertEqual(prop.kind, "list")
        values = prop.value
        self.assertEqual(values[0], format_value("cfg:EnumRef.???????"))
        self.assertEqual(values[-1], format_value("cfg:CatalogRef"))
        self.assertLess(values.index(format_value("cfg:EnumRef.???????")), values.index(format_value("xs:boolean")))
        self.assertLess(values.index(format_value("xs:boolean")), values.index(format_value("cfg:CatalogRef")))


    def test_data_lock_fields_use_compact_metadata_reference_values(self) -> None:
        configure_extractor(SETTINGS)
        property_name = next(key for key, aliases in SETTINGS.property_aliases.items() if "DataLockFields" in aliases)
        prop = extract_property(ET.fromstring(DATA_LOCK_FIELDS_XML), property_name, SETTINGS)
        self.assertEqual(prop, ReportProperty(property_name, ["?????????????"], "list"))

    def test_choice_parameter_links_standard_attribute_uses_translated_last_part(self) -> None:
        configure_extractor(SETTINGS)
        property_name = next(key for key, aliases in SETTINGS.property_aliases.items() if "ChoiceParameterLinks" in aliases)
        prop = extract_property(ET.fromstring(CHOICE_PARAMETER_LINK_STANDARD_ATTRIBUTE_XML), property_name, SETTINGS)
        self.assertIsNotNone(prop)
        self.assertEqual(prop.kind, "list")
        self.assertEqual(len(prop.value), 1)
        self.assertNotIn("StandardAttribute", prop.value[0])
        self.assertTrue(prop.value[0].endswith(f"({SETTINGS.standard_attribute_name_translations["Owner"]})"))

    def test_choice_parameters_design_time_ref_matches_reference_format(self) -> None:
        configure_extractor(SETTINGS)
        property_name = next(key for key, aliases in SETTINGS.property_aliases.items() if "ChoiceParameters" in aliases)
        prop = extract_property(ET.fromstring(CHOICE_PARAMETERS_DESIGN_TIME_REF_XML), property_name, SETTINGS)
        self.assertIsNotNone(prop)
        self.assertEqual(prop.kind, "list")
        self.assertEqual(len(prop.value), 1)
        self.assertNotIn("xr:DesignTimeRef", prop.value[0])
        self.assertNotIn(".EmptyRef", prop.value[0])
        self.assertTrue(prop.value[0].endswith(":)"))

    def test_choice_parameters_fixed_array_keeps_type_marker(self) -> None:
        configure_extractor(SETTINGS)
        property_name = next(key for key, aliases in SETTINGS.property_aliases.items() if "ChoiceParameters" in aliases)
        prop = extract_property(ET.fromstring(CHOICE_PARAMETERS_FIXED_ARRAY_XML), property_name, SETTINGS)
        self.assertIsNotNone(prop)
        self.assertEqual(prop.kind, "list")
        self.assertEqual(len(prop.value), 1)
        fixed_array = format_value("v8:FixedArray")
        self.assertTrue(prop.value[0].endswith(f"({fixed_array}:{fixed_array})"))

    def test_dcs_settings_composer_uses_reference_translation(self) -> None:
        configure_extractor(SETTINGS)
        property_name = next(key for key, aliases in SETTINGS.property_aliases.items() if "Type" in aliases)
        prop = extract_property(ET.fromstring(DCS_SETTINGS_COMPOSER_XML), property_name, SETTINGS)
        self.assertEqual(prop, ReportProperty(property_name, [format_value("dcsset:SettingsComposer")], "list"))

    def test_property_specific_prefix_translation_is_applied(self) -> None:
        configure_extractor(SETTINGS)
        prop = extract_property(ET.fromstring(HANDLER_WITH_COMMON_MODULE_XML), "Обработчик", SETTINGS)
        self.assertEqual(prop, ReportProperty("Обработчик", "РаботаСФайламиКлиентСервер.ОпределитьФормуПрисоединенногоФайла"))

    def test_method_name_prefix_translation_is_applied(self) -> None:
        configure_extractor(SETTINGS)
        prop = extract_property(ET.fromstring(METHOD_NAME_WITH_COMMON_MODULE_XML), "ИмяМетода", SETTINGS)
        self.assertEqual(prop, ReportProperty("ИмяМетода", "шн_ОбменСШинойСервер.ВыполнитьОбработкуСервисовИнтеграции"))

    def test_extended_type_and_return_values_reuse_are_translated(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(EXTENDED_TYPE_XML)

        type_name = next(key for key, aliases in SETTINGS.property_aliases.items() if "Type" in aliases)
        reuse_name = next(key for key, aliases in SETTINGS.property_aliases.items() if "ReturnValuesReuse" in aliases)

        type_prop = extract_property(root, type_name, SETTINGS)
        reuse_prop = extract_property(root, reuse_name, SETTINGS)

        self.assertIsNotNone(type_prop)
        self.assertEqual(type_prop.name, type_name)
        self.assertEqual(type_prop.kind, "list")
        self.assertEqual(len(type_prop.value), 2)
        self.assertNotIn("cfg:", type_prop.value[0])
        self.assertNotIn("cfg:", type_prop.value[1])
        self.assertIn(".", type_prop.value[0])
        self.assertIn(".", type_prop.value[1])
        self.assertIsNotNone(reuse_prop)
        self.assertEqual(reuse_prop.name, reuse_name)
        self.assertNotEqual(reuse_prop.value, "DuringRequest")
        self.assertTrue(reuse_prop.value)

    def test_empty_type_node_is_suppressed(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(EMPTY_TYPE_XML)

        type_name = "\u0422\u0438\u043f"
        type_prop = extract_property(root, type_name, SETTINGS)

        self.assertEqual(type_prop, ReportProperty(type_name, [""], "list"))

    def test_style_item_type_is_scalar(self) -> None:
        configure_extractor(SETTINGS)
        root = ET.fromstring(STYLE_ITEM_XML)
        payload = next(iter(root))

        style_type = extract_property(payload, "Вид", SETTINGS)
        properties = extract_properties(payload, ("Вид",), Diagnostics("test"), SETTINGS, include_extra_properties=False)

        self.assertEqual(style_type, ReportProperty("Вид", "Цвет"))
        self.assertEqual(properties, [ReportProperty("Вид", "Цвет")])


CONFIGURATION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Configuration>
    <Properties>
        <Name>Тестовая</Name>
        <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Тестовая конфигурация</v8:content></v8:item></Synonym>
        <Comment/>
        <ConfigurationExtensionCompatibilityMode>Version8_3_27</ConfigurationExtensionCompatibilityMode>
        <DefaultRunMode>ManagedApplication</DefaultRunMode>
      </Properties>
    <ChildObjects>
      <Document>Заказ</Document>
    </ChildObjects>
  </Configuration>
</MetaDataObject>
"""


DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Document>
    <Properties>
      <Name>Заказ</Name>
      <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Заказ</v8:content></v8:item></Synonym>
      <Comment/>
      <UseStandardCommands>true</UseStandardCommands>
    </Properties>
    <ChildObjects>
      <Attribute>
        <Properties>
          <Name>НомерВнешний</Name>
          <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Номер внешний</v8:content></v8:item></Synonym>
          <Comment/>
        </Properties>
      </Attribute>
      <Form>ФормаДокумента</Form>
      <Form>ФормаВыбора</Form>
    </ChildObjects>
  </Document>
</MetaDataObject>
"""


FORM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Form>
    <Properties>
      <Name>{name}</Name>
      <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>{name}</v8:content></v8:item></Synonym>
      <Comment/>
    </Properties>
  </Form>
</MetaDataObject>
"""


EXTENSION_CONFIGURATION_WITH_ADOPTED_DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Configuration>
    <Properties>
      <ObjectBelonging>Adopted</ObjectBelonging>
      <Name>Расширение</Name>
      <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Расширение</v8:content></v8:item></Synonym>
      <Comment/>
    </Properties>
    <ChildObjects>
      <Document>Заказ</Document>
    </ChildObjects>
  </Configuration>
</MetaDataObject>
"""


EXTENSION_CONFIGURATION_NATIVE_COMPAT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Configuration>
    <Properties>
      <ObjectBelonging>Adopted</ObjectBelonging>
      <Name>Расширение</Name>
      <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Расширение</v8:content></v8:item></Synonym>
      <Comment/>
      <ConfigurationExtensionPurpose>AddOn</ConfigurationExtensionPurpose>
      <KeepMappingToExtendedConfigurationObjectsByIDs>true</KeepMappingToExtendedConfigurationObjectsByIDs>
      <NamePrefix>шн_</NamePrefix>
      <ConfigurationExtensionCompatibilityMode>Version8_3_23</ConfigurationExtensionCompatibilityMode>
      <ScriptVariant>Russian</ScriptVariant>
      <DefaultRoles>
        <xr:Item xsi:type="xr:MDObjectRef">Role.шн_ОбменСШиной</xr:Item>
      </DefaultRoles>
      <Vendor>НМ</Vendor>
      <Version>1.0.058</Version>
      <BriefInformation/>
      <DetailedInformation/>
      <Copyright/>
      <VendorInformationAddress/>
      <ConfigurationInformationAddress/>
    </Properties>
    <ChildObjects>
      <Language>Русский</Language>
    </ChildObjects>
  </Configuration>
</MetaDataObject>
"""


LANGUAGE_RUSSIAN_WITHOUT_CODE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses">
  <Language>
    <Properties>
      <ObjectBelonging>Adopted</ObjectBelonging>
      <Name>Русский</Name>
      <Comment/>
    </Properties>
  </Language>
</MetaDataObject>
"""


CONFIGURATION_WITH_CATALOG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Configuration>
    <Properties>
      <Name>TestConfiguration</Name>
      <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Test configuration</v8:content></v8:item></Synonym>
      <Comment/>
    </Properties>
    <ChildObjects>
      <Catalog>TestCatalog</Catalog>
    </ChildObjects>
  </Configuration>
</MetaDataObject>
"""


CATALOG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Catalog>
    <Properties>
      <Name>TestCatalog</Name>
      <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Test catalog</v8:content></v8:item></Synonym>
      <Comment/>
      <Hierarchical>true</Hierarchical>
      <HierarchyType>HierarchyOfFoldersAndItems</HierarchyType>
      <Owners/>
      <CodeLength>6</CodeLength>
      <DescriptionLength>100</DescriptionLength>
      <CodeType>Number</CodeType>
      <CodeAllowedLength>Variable</CodeAllowedLength>
    </Properties>
  </Catalog>
</MetaDataObject>
"""


EXTENSION_CONFIGURATION_WITH_ADOPTED_CATALOG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Configuration>
    <Properties>
      <ObjectBelonging>Adopted</ObjectBelonging>
      <Name>Extension</Name>
      <Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Extension</v8:content></v8:item></Synonym>
      <Comment/>
    </Properties>
    <ChildObjects>
      <Catalog>TestCatalog</Catalog>
    </ChildObjects>
  </Configuration>
</MetaDataObject>
"""


TYPE_AND_CHOICE_XML = """<Attribute xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <Type>
      <v8:TypeSet>cfg:Characteristic.ДополнительныеРеквизитыИСведения</v8:TypeSet>
    </Type>
    <ChoiceParameterLinks>
      <xr:Link>
        <xr:Name>Отбор.Владелец</xr:Name>
        <xr:DataPath>Document.Заказ.TabularSection.ДополнительныеРеквизиты.Attribute.Свойство</xr:DataPath>
        <xr:ValueChange>Clear</xr:ValueChange>
      </xr:Link>
    </ChoiceParameterLinks>
  </Properties>
</Attribute>"""


REFERENCE_VALUE_XML = """<Form xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Properties>
    <UsePurposes>
      <v8:Value>PlatformApplication</v8:Value>
      <v8:Value>MobilePlatformApplication</v8:Value>
    </UsePurposes>
    <Type>
      <v8:Type>xs:dateTime</v8:Type>
      <v8:Type>v8:ValueStorage</v8:Type>
      <v8:DateQualifiers>
        <v8:DateFractions>DateTime</v8:DateFractions>
      </v8:DateQualifiers>
    </Type>
    <FillValue xsi:nil="true"/>
    <FormType>Managed</FormType>
    <DataLockControlMode>Managed</DataLockControlMode>
    <WriteMode>Independent</WriteMode>
  </Properties>
</Form>"""


FIXED_STRING_WHITESPACE_FILL_VALUE_XML = """<Attribute xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Properties>
    <Type>
      <v8:Type>xs:string</v8:Type>
      <v8:StringQualifiers>
        <v8:Length>36</v8:Length>
        <v8:AllowedLength>Fixed</v8:AllowedLength>
      </v8:StringQualifiers>
    </Type>
    <FillValue xsi:type="xs:string">                                    </FillValue>
  </Properties>
</Attribute>"""


VARIABLE_STRING_WHITESPACE_FILL_VALUE_XML = """<Attribute xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Properties>
    <Type>
      <v8:Type>xs:string</v8:Type>
      <v8:StringQualifiers>
        <v8:Length>36</v8:Length>
        <v8:AllowedLength>Variable</v8:AllowedLength>
      </v8:StringQualifiers>
    </Type>
    <FillValue xsi:type="xs:string">                                    </FillValue>
  </Properties>
</Attribute>"""


TOOLTIP_SINGLE_SPACE_XML = """<Attribute xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Properties>
    <ToolTip>
      <v8:item>
        <v8:lang>ru</v8:lang>
        <v8:content> </v8:content>
      </v8:item>
    </ToolTip>
  </Properties>
</Attribute>"""


TOOLTIP_TRAILING_SPACE_XML = """<Attribute xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Properties>
    <ToolTip>
      <v8:item>
        <v8:lang>ru</v8:lang>
        <v8:content>Глобальный уникальный идентификатор объекта </v8:content>
      </v8:item>
    </ToolTip>
  </Properties>
</Attribute>"""


EXTENDED_TYPE_XML = """<DefinedType xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Properties>
    <Type xsi:type="xr:ExtendedProperty">
      <xr:ExtendValue xsi:type="v8:TypeDescription">
        <v8:Type>cfg:CatalogRef.Номенклатура</v8:Type>
        <v8:Type>cfg:DocumentRef.Заказ</v8:Type>
      </xr:ExtendValue>
    </Type>
    <ReturnValuesReuse>DuringRequest</ReturnValuesReuse>
  </Properties>
</DefinedType>"""


EMPTY_TYPE_XML = """<Attribute xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Properties>
    <Type/>
  </Properties>
</Attribute>"""


CATALOG_OWNER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Catalog>
    <Properties>
      <Name>Файлы</Name>
      <Hierarchical>false</Hierarchical>
      <SubordinationUse>ToItems</SubordinationUse>
      <UseStandardCommands>false</UseStandardCommands>
      <CodeLength>0</CodeLength>
      <DescriptionLength>150</DescriptionLength>
      <CreateOnInput>DontUse</CreateOnInput>
      <StandardAttributes>
        <xr:StandardAttribute name="Owner">
          <xr:FillValue xsi:nil="true"/>
        </xr:StandardAttribute>
        <xr:StandardAttribute name="Parent">
          <xr:FillValue xsi:nil="true"/>
        </xr:StandardAttribute>
      </StandardAttributes>
    </Properties>
  </Catalog>
</MetaDataObject>
"""


CATALOG_PARENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Catalog>
    <Properties>
      <Name>ПредопределенныеВариантыОтчетовРасширений</Name>
      <Hierarchical>true</Hierarchical>
      <SubordinationUse>ToItems</SubordinationUse>
      <UseStandardCommands>true</UseStandardCommands>
      <CodeLength>0</CodeLength>
      <DescriptionLength>150</DescriptionLength>
      <Comment>Предопределенные варианты отчетов расширения</Comment>
      <StandardAttributes>
        <xr:StandardAttribute name="Owner">
          <xr:FillValue xsi:nil="true"/>
        </xr:StandardAttribute>
        <xr:StandardAttribute name="Parent">
          <xr:FillValue xsi:nil="true"/>
        </xr:StandardAttribute>
      </StandardAttributes>
    </Properties>
  </Catalog>
</MetaDataObject>
"""


CATALOG_NONE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Catalog>
    <Properties>
      <Name>Обычный</Name>
      <Hierarchical>false</Hierarchical>
      <SubordinationUse>NotUse</SubordinationUse>
      <StandardAttributes>
        <xr:StandardAttribute name="Owner">
          <xr:FillValue xsi:nil="true"/>
        </xr:StandardAttribute>
        <xr:StandardAttribute name="Parent">
          <xr:FillValue xsi:nil="true"/>
        </xr:StandardAttribute>
      </StandardAttributes>
    </Properties>
  </Catalog>
</MetaDataObject>
"""


CATALOG_DESCRIPTION_DONT_CHECK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Catalog>
    <Properties>
      <Name>Файлы</Name>
      <StandardAttributes>
        <xr:StandardAttribute name="Description">
          <xr:FillChecking>DontCheck</xr:FillChecking>
        </xr:StandardAttribute>
      </StandardAttributes>
    </Properties>
  </Catalog>
</MetaDataObject>
"""


STANDARD_ATTRIBUTE_SUPPRESSION_XML = """<Catalog xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Properties>
    <StandardAttributes>
      <xr:StandardAttribute name="Owner">
        <xr:FillChecking>ShowError</xr:FillChecking>
        <xr:FillFromFillingValue>true</xr:FillFromFillingValue>
        <xr:TypeReductionMode>Deny</xr:TypeReductionMode>
        <xr:FillValue xsi:nil="true"/>
      </xr:StandardAttribute>
      <xr:StandardAttribute name="Description">
        <xr:FillChecking>ShowError</xr:FillChecking>
        <xr:FillFromFillingValue>false</xr:FillFromFillingValue>
        <xr:TypeReductionMode>TransformValues</xr:TypeReductionMode>
        <xr:ToolTip>
          <v8:item>
            <v8:lang>ru</v8:lang>
            <v8:content>Имя файла</v8:content>
          </v8:item>
        </xr:ToolTip>
      </xr:StandardAttribute>
    </StandardAttributes>
  </Properties>
</Catalog>
"""


STANDARD_ATTRIBUTE_NAME_AND_PARENT_XML = """<Catalog xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <StandardAttributes>
      <xr:StandardAttribute name="Description">
        <xr:FillChecking>DontCheck</xr:FillChecking>
      </xr:StandardAttribute>
      <xr:StandardAttribute name="Parent">
        <xr:FillChecking>ShowError</xr:FillChecking>
      </xr:StandardAttribute>
    </StandardAttributes>
  </Properties>
</Catalog>
"""


STANDARD_ATTRIBUTE_PERIOD_XML = """<InformationRegister xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <StandardAttributes>
      <xr:StandardAttribute name="Period">
        <xr:FillChecking>DontCheck</xr:FillChecking>
      </xr:StandardAttribute>
    </StandardAttributes>
  </Properties>
</InformationRegister>"""


STANDARD_ATTRIBUTE_TYPE_SPECIFIC_SUPPRESSION_XML = """<Catalog xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Properties>
    <StandardAttributes>
      <xr:StandardAttribute name="Code">
        <xr:FillChecking>ShowError</xr:FillChecking>
        <xr:FillValue xsi:type="xs:string">123</xr:FillValue>
      </xr:StandardAttribute>
      <xr:StandardAttribute name="Number">
        <xr:FillChecking>ShowError</xr:FillChecking>
        <xr:FillValue xsi:type="xs:string">123</xr:FillValue>
      </xr:StandardAttribute>
    </StandardAttributes>
  </Properties>
</Catalog>
"""


STYLE_ITEM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <StyleItem>
    <Properties>
      <Name>ТестовыйЭлементСтиля</Name>
      <Type>Color</Type>
      <Value xsi:type="v8ui:Color">web:Red</Value>
    </Properties>
  </StyleItem>
</MetaDataObject>
"""


SCHEDULED_JOB_KEY_XML = """<ScheduledJob>
  <Properties>
    <Key>9fa79867-46b8-4060-9694-eb85d6ecf1ea</Key>
  </Properties>
</ScheduledJob>"""


XDTO_PACKAGES_XML = """<WebService xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Properties>
    <XDTOPackages>
      <xr:Item>
        <xr:Value xsi:type="xr:MDObjectRef">XDTOPackage.EnterpriseDataExchange_1_0_1_1</xr:Value>
      </xr:Item>
    </XDTOPackages>
  </Properties>
</WebService>"""


XDTO_PACKAGES_URI_XML = """<WebService xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Properties>
    <XDTOPackages>
      <xr:Item>
        <xr:Value xsi:type="xs:string" xmlns:xs="http://www.w3.org/2001/XMLSchema">http://v8.1c.ru/8.1/data/core</xr:Value>
      </xr:Item>
    </XDTOPackages>
  </Properties>
</WebService>"""


EVENT_SUBSCRIPTION_SOURCE_XML = """<EventSubscription xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Properties>
    <Source>
      <v8:TypeSet>cfg:ExchangePlanObject</v8:TypeSet>
    </Source>
  </Properties>
</EventSubscription>"""


INPUT_BY_STRING_STANDARD_ATTRIBUTE_XML = """<Document>
  <Properties>
    <InputByString>
      <v8:Field xmlns:v8="http://v8.1c.ru/8.1/data/core">Document.Заказ.StandardAttribute.Number</v8:Field>
    </InputByString>
  </Properties>
</Document>"""


FUNCTIONAL_OPTION_PARAMETER_USE_XML = """<FunctionalOptionsParameter xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <Use>
      <xr:Metadata>InformationRegister.НастройкиВерсионированияОбъектов.Dimension.ТипОбъекта</xr:Metadata>
    </Use>
  </Properties>
</FunctionalOptionsParameter>"""


DOCUMENT_JOURNAL_COLUMN_REFERENCES_XML = """<Column xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <References>
      <xr:Metadata>Document.Заказ.Attribute.Шаблон</xr:Metadata>
    </References>
  </Properties>
</Column>"""


EMPTY_SHORTCUT_XML = """<Command>
  <Properties>
    <Shortcut/>
  </Properties>
</Command>"""


EMPTY_DATA_LOCK_FIELDS_XML = """<Catalog>
  <Properties>
    <DataLockFields/>
  </Properties>
</Catalog>"""


EMPTY_TYPE_XML = """<Attribute>
  <Properties>
    <Type/>
  </Properties>
</Attribute>"""


CHARACTERISTICS_NEGATIVE_DATA_PATH_XML = """<Catalog xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <Characteristics>
      <Characteristic>
        <CharacteristicTypes from="ChartOfCharacteristicTypes.ДополнительныеРеквизитыИСведения">
          <KeyField>Свойство</KeyField>
          <TypesFilterField>ИмяПредопределенногоНабора</TypesFilterField>
          <TypesFilterValue>Справочник_Пользователи</TypesFilterValue>
          <DataPathField>-1</DataPathField>
        </CharacteristicTypes>
      </Characteristic>
    </Characteristics>
  </Properties>
</Catalog>"""


CHARACTERISTICS_ZERO_FIELDS_XML = """<Catalog xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <Characteristics>
      <Characteristic>
        <CharacteristicTypes from="ChartOfCharacteristicTypes.ДополнительныеРеквизитыИСведения">
          <KeyField>Свойство</KeyField>
          <TypesFilterField>ИмяПредопределенногоНабора</TypesFilterField>
          <TypesFilterValue>Справочник_Пользователи</TypesFilterValue>
          <DataPathField>0</DataPathField>
        </CharacteristicTypes>
        <CharacteristicValues from="InformationRegister.ДополнительныеСведения">
          <ObjectField>Объект</ObjectField>
          <TypeField>Свойство</TypeField>
          <ValueField>Значение</ValueField>
          <MultipleValuesUseField>0</MultipleValuesUseField>
          <MultipleValuesKeyField>0</MultipleValuesKeyField>
          <MultipleValuesOrderField>0</MultipleValuesOrderField>
        </CharacteristicValues>
      </Characteristic>
    </Characteristics>
  </Properties>
</Catalog>"""


MIXED_TYPE_SPECIFIC_AND_GENERIC_REFS_XML = """<Attribute xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Properties>
    <Type>
      <v8:Type>xs:boolean</v8:Type>
      <v8:Type>xs:string</v8:Type>
      <v8:Type>xs:decimal</v8:Type>
      <v8:Type>cfg:EnumRef.???????</v8:Type>
      <v8:Type>cfg:CatalogRef</v8:Type>
      <v8:NumberQualifiers>
        <v8:Digits>10</v8:Digits>
        <v8:FractionDigits>0</v8:FractionDigits>
      </v8:NumberQualifiers>
      <v8:StringQualifiers>
        <v8:Length>10</v8:Length>
        <v8:AllowedLength>Variable</v8:AllowedLength>
      </v8:StringQualifiers>
    </Type>
  </Properties>
</Attribute>"""

MIXED_TYPE_ORDER_XML = """<Attribute xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Properties>
    <Type>
      <v8:Type>xs:boolean</v8:Type>
      <v8:Type>xs:string</v8:Type>
      <v8:Type>xs:dateTime</v8:Type>
      <v8:Type>xs:decimal</v8:Type>
      <v8:TypeSet>cfg:AnyIBRef</v8:TypeSet>
      <v8:NumberQualifiers>
        <v8:Digits>16</v8:Digits>
        <v8:FractionDigits>2</v8:FractionDigits>
        <v8:AllowedSign>Any</v8:AllowedSign>
      </v8:NumberQualifiers>
      <v8:StringQualifiers>
        <v8:Length>128</v8:Length>
        <v8:AllowedLength>Variable</v8:AllowedLength>
      </v8:StringQualifiers>
      <v8:DateQualifiers>
        <v8:DateFractions>DateTime</v8:DateFractions>
      </v8:DateQualifiers>
    </Type>
  </Properties>
</Attribute>"""


CHARACTERISTICS_COMPOSED_DATA_PATH_XML = """<Catalog xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <Characteristics>
      <Characteristic>
        <CharacteristicTypes from="ChartOfCharacteristicTypes.ДополнительныеРеквизитыИСведения">
          <KeyField>Свойство</KeyField>
          <TypesFilterField>Catalog.Номенклатура.Attribute.ИмяПредопределенногоНабора</TypesFilterField>
          <TypesFilterValue>Справочник_Номенклатура</TypesFilterValue>
          <DataPathField>Catalog.Номенклатура.Attribute.Свойство</DataPathField>
        </CharacteristicTypes>
      </Characteristic>
    </Characteristics>
  </Properties>
</Catalog>"""


DATA_LOCK_FIELDS_XML = """<Attribute xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <DataLockFields>
      <xr:Field>Catalog.??????????????????????????.Attribute.?????????????</xr:Field>
    </DataLockFields>
  </Properties>
</Attribute>"""

CHOICE_PARAMETER_LINK_STANDARD_ATTRIBUTE_XML = """<Attribute xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <ChoiceParameterLinks>
      <xr:Link>
        <xr:Name>?????.????????</xr:Name>
        <xr:DataPath>Catalog.??????????????????????.StandardAttribute.Owner</xr:DataPath>
        <xr:ValueChange>Clear</xr:ValueChange>
      </xr:Link>
    </ChoiceParameterLinks>
  </Properties>
</Attribute>"""

CHOICE_PARAMETERS_DESIGN_TIME_REF_XML = """<Attribute xmlns:app="http://schemas.xmlsoap.org/2003/05/soap-envelope" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Properties>
    <ChoiceParameters>
      <app:item name="Отбор.ТипЭлементовНабора">
        <app:value xsi:type="xr:DesignTimeRef">Catalog.ГруппыДоступа.EmptyRef</app:value>
      </app:item>
    </ChoiceParameters>
  </Properties>
</Attribute>"""


CHOICE_PARAMETERS_FIXED_ARRAY_XML = """<Attribute xmlns:app="http://schemas.xmlsoap.org/2003/05/soap-envelope" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable">
  <Properties>
    <ChoiceParameters>
      <app:item name="Отбор.ТипЭлементовНабора">
        <app:value xsi:type="v8:FixedArray">
          <v8:Value xsi:type="xr:DesignTimeRef">Catalog.ГруппыПользователей.EmptyRef</v8:Value>
          <v8:Value xsi:type="xr:DesignTimeRef">Catalog.ГруппыВнешнихПользователей.EmptyRef</v8:Value>
        </app:value>
      </app:item>
    </ChoiceParameters>
  </Properties>
</Attribute>"""


DCS_SETTINGS_COMPOSER_XML = """<Attribute xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Properties>
    <Type>
      <v8:Type>dcsset:SettingsComposer</v8:Type>
    </Type>
  </Properties>
</Attribute>"""


HANDLER_WITH_COMMON_MODULE_XML = """<EventSubscription>
  <Properties>
    <Handler>ОбщийМодуль.РаботаСФайламиКлиентСервер.ОпределитьФормуПрисоединенногоФайла</Handler>
  </Properties>
</EventSubscription>"""


METHOD_NAME_WITH_COMMON_MODULE_XML = """<ScheduledJob>
  <Properties>
    <MethodName>ОбщийМодуль.шн_ОбменСШинойСервер.ВыполнитьОбработкуСервисовИнтеграции</MethodName>
  </Properties>
</ScheduledJob>"""


if __name__ == "__main__":
    unittest.main()
