# Dev Spec: `generate-config-report`

## 1. Назначение

Dev spec описывает реализацию MVP генератора `Report.txt` по XML-выгрузке 1С.

Источник требований:

```text
prd-generate-config-report (1).md
```

Эталон формата:

```text
ОтчетПоКонфигурации.txt
```

Цель реализации: Python-скрипт, который читает основную конфигурацию из `src/cf`, опционально читает одно расширение из `src/cfe`, формирует `metadata/Report.txt`, диагностику и лог.

## 2. Границы MVP

Входит:

```text
- CLI: python generate_config_report.py --config <path>
- чтение JSON config;
- чтение настроек генератора из JSON (`generatorSettingsPath` или встроенный defaults);
- чтение src/cf;
- опциональное чтение src/cfe;
- отдельные корневые секции основной конфигурации и расширения;
- потоковая запись Report.txt;
- базовый отступ Report.txt в одну табуляцию, как в эталоне;
- whitelist-свойства по типам объектов;
- дополнительные простые XML-свойства после whitelist;
- fallback для неподдержанных типов;
- report-stats.json;
- report-diagnostics.json;
- файловый лог;
- exit codes из PRD.
```

Не входит:

```text
- запуск 1С/Конфигуратора;
- анализ BSL;
- вывод путей к файлам/модулям;
- merged-view расширения;
- несколько расширений;
- Docker/MCP/update pipeline.
```

## 3. Архитектура

Рекомендуемая структура:

```text
generate_config_report/
  __init__.py
  cli.py
  config.py
  diagnostics.py
  generator.py
  metadata_model.py
  object_registry.py
  property_extractors.py
  report_writer.py
  xml_reader.py

generate_config_report.py
tests/
```

Назначение модулей:

```text
generate_config_report.py
  Тонкий launcher. Импортирует generate_config_report.cli:main.

cli.py
  argparse, обработка --config/--verbose/--strict/--dry-run, настройка логирования, возврат exit code.

config.py
  Загрузка и валидация JSON config, нормализация путей через pathlib.

settings.py
  Загрузка настраиваемых правил генерации из JSON: whitelist, aliases, типы объектов, fallback, формат отступов.

generator.py
  Оркестрация: config -> чтение metadata trees -> запись Report.txt -> диагностика -> exit code.

xml_reader.py
  Обход XML-выгрузки 1С, чтение Configuration.xml и объектов метаданных.

metadata_model.py
  Внутренние dataclass-модели объекта, свойства, diagnostics events, stats.

object_registry.py
  Реестр поддержанных типов: папка выгрузки, имя в Report.txt, whitelist, вложенные коллекции.

property_extractors.py
  Извлечение простых свойств, списков, ссылок, bool/enums, safe fallback.

report_writer.py
  Потоковая запись Report.txt в штатном стиле.

diagnostics.py
  Накопление warnings/errors, JSON-сериализация, расчет warning policy.
```

## 4. Поток выполнения

Основной сценарий:

```text
1. CLI читает аргументы.
2. ConfigLoader читает config JSON.
3. ConfigLoader нормализует пути:
   repoPath
   repoPath/mainConfigPath
   repoPath/extensionPath
   outputPath
   diagnosticsPath
   logsPath
4. Generator проверяет наличие mainConfigPath.
5. Generator проверяет extensionPath:
   - найден: читает как отдельную секцию;
   - не найден и extensionRequired=false: warning;
   - не найден и extensionRequired=true: exit code 7.
6. XmlReader строит MetadataSection для основной конфигурации.
7. XmlReader строит MetadataSection для расширения, если оно есть.
8. ReportWriter потоково пишет Report.txt.
9. DiagnosticsWriter пишет report-stats.json и report-diagnostics.json.
10. CLI возвращает exit code.
```

`--dry-run`:

```text
- читает config;
- проверяет пути;
- проверяет наличие Configuration.xml;
- пробует распарсить корни основной конфигурации и расширения;
- пишет diagnostics/logs, если paths заданы;
- не пишет Report.txt.
```

## 5. Config

Dataclass:

```python
@dataclass(frozen=True)
class ProjectConfig:
    project: str
    repo_path: Path
    main_config_path: Path
    output_path: Path
    report_file_name: str
    extension_path: Path = Path("src/cfe")
    extension_required: bool = False
    diagnostics_path: Path | None = None
  logs_path: Path | None = None
  generator_settings_path: Path | None = None
  encoding: str = "utf-8"
  warnings_as_errors: bool = False
```

Правила:

```text
- обязательные параметры: project, repoPath, mainConfigPath, outputPath, reportFileName;
- encoding: только utf-8, utf-8-sig, cp1251;
- extensionRequired default false;
- warningsAsErrors default false;
- generatorSettingsPath optional; если не задан, используется `generate_config_report/settings/defaults.json`;
- --strict принудительно включает warningsAsErrors=true на время запуска;
- относительные mainConfigPath/extensionPath считаются относительно repoPath;
- outputPath/diagnosticsPath/logsPath могут быть абсолютными или относительными от текущей рабочей директории запуска.
```

## 6. Модель данных

Минимальная внутренняя модель:

```python
@dataclass
class MetadataSection:
    source_kind: Literal["main", "extension"]
    root: MetadataObject

@dataclass
class MetadataObject:
    full_name: str
    type_key: str
    name: str
    properties: list[ReportProperty]
    children: list[MetadataObject]
    unsupported_type: bool = False
    xml_path: Path | None = None

@dataclass
class ReportProperty:
    name: str
    value: str | list[str]
    kind: Literal["scalar", "list"]
```

`xml_path` используется только для diagnostics/logs. В `Report.txt` не выводится.

## 7. Настройки генератора

Все правила, которые меняются от проекта к проекту или уточняются по мере изучения XML-выгрузок, должны лежать в JSON-настройках, а не в Python-коде.

Default-файл:

```text
generate_config_report/settings/defaults.json
```

Project config может переопределить его:

```json
{
  "generatorSettingsPath": "E:/mcp-1c/projects/orders-generator-settings.json"
}
```

В настройках должны находиться:

```text
- supportedEncodings;
- reportFormat: baseIndent, indent, lineEnding, blankLineBetweenRootSections;
- commonProperties;
- propertyAliases;
- propertyDefaults;
- blockedPropertyNames;
- blockedPropertyFragments;
- listPropertyNames;
- valueTranslations, valuePrefixTranslations и valueSegmentTranslations;
- standardAttributeNameTranslations;
- standardAttributePropertyDefaults;
- standardAttributeSuppressedValues;
- standardAttributeSuppressedValueSuffixes;
- standardAttributeSuppressedNames;
- standardAttributeNoisyProperties;
- standardAttributeKeepEmptyValueNames;
- childCollections;
- configurationWhitelist;
- objectTypes;
- fallbackEnabled и warnOnFallback для типов.
```

Python-код должен содержать только механизм чтения и применения настроек. Добавление нового типа метаданных, alias или whitelist-свойства не должно требовать изменения Python-кода, если не нужна новая логика парсинга сложного XML-узла.

## 8. Реестр типов

Реестр типов описывается в JSON-настройках. `object_registry.py` содержит только dataclass-структуры.

Реестр является источником:

```text
- соответствия папок выгрузки 1С типам Report.txt;
- whitelist-порядка свойств;
- поддержанных вложенных коллекций;
- правил формирования full_name.
```

Пример структуры:

```python
@dataclass(frozen=True)
class ObjectTypeSpec:
    type_key: str
    folder_names: tuple[str, ...]
    report_plural: str
    whitelist: tuple[str, ...]
    child_collections: tuple[ChildCollectionSpec, ...] = ()
    xml_element_names: tuple[str, ...] = ()
    fallback_enabled: bool = False
    warn_on_fallback: bool = False
```

`xml_element_names` задает имена XML-ссылок родителя (`Document`, `Catalog`, `Form`, `Template` и т.д.) и используется для восстановления порядка как в эталоне. Если поле не задано, допускается безопасный fallback из английского имени папки, но для неоднозначных типов значение должно быть явно вынесено в JSON-настройки.

Минимальная карта для MVP:

```text
Configuration.xml       -> Конфигурации.<Имя>
Subsystems              -> Подсистемы.<Имя>
CommonModules           -> ОбщиеМодули.<Имя>
Catalogs                -> Справочники.<Имя>
Documents               -> Документы.<Имя>
InformationRegisters    -> РегистрыСведений.<Имя>
AccumulationRegisters   -> РегистрыНакопления.<Имя>
AccountingRegisters     -> РегистрыБухгалтерии.<Имя>
CalculationRegisters    -> РегистрыРасчета.<Имя>
Reports                 -> Отчеты.<Имя>
DataProcessors          -> Обработки.<Имя>
Enumerations            -> Перечисления.<Имя>
Roles                   -> Роли.<Имя>
```

Дополнительные типы из FR-020, подтвержденные по эталону `orders`, регистрируются как поддержанные типы с явными `xmlElementNames`, `reportPlural`, whitelist и дочерними коллекциями:

```text
BusinessProcesses, Tasks, ChartsOfCharacteristicTypes, CommandGroups,
CommonAttributes, CommonTemplates, DocumentJournals, EventSubscriptions,
FilterCriteria, FunctionalOptionsParameters, HTTPServices, IntegrationServices,
SessionParameters, SettingsStorages, StyleItems, WebServices, XDTOPackages.
```

Fallback остается только для типов, где пока достаточно базовых свойств и дополнительных простых XML-свойств.

Имена в `Report.txt` должны быть русскими штатными именами из PRD/эталона. Если точное русское имя для fallback-типа не подтверждено, добавить явную запись diagnostics `unknownReportTypeName` и использовать безопасное имя из registry, а не имя папки Git.

## 9. Извлечение XML

### 8.1. Общие правила

Использовать только стандартную библиотеку Python:

```text
xml.etree.ElementTree
pathlib
json
logging
argparse
dataclasses
```

Правила XML:

```text
- поддерживать namespace-agnostic чтение: local_name(tag);
- не зависеть от порядка атрибутов XML;
- не исполнять код и внешние команды;
- не читать BSL как код;
- не выводить физические пути в Report.txt;
- поврежденный XML фиксировать в diagnostics и продолжать, если это не Configuration.xml основной конфигурации.
```

### 8.2. Поиск объектов

Для каждого `ObjectTypeSpec`:

```text
1. Найти каталог <section_path>/<folder>.
2. Если каталога нет, пропустить без warning, кроме обязательного корня Configuration.xml.
3. Для каждого *.xml в каталоге и подкаталогах прочитать XML.
4. Исключить XML, относящиеся к BSL-модулям, формам/макетам как физическим файлам, если они уже обрабатываются через родительский объект.
5. Построить MetadataObject.
```

Важно: физический путь используется только для чтения и diagnostics. Он не должен попадать в `Report.txt`.

### 8.3. Имя объекта

Извлечение имени:

```text
1. искать элемент/атрибут Name или Имя;
2. если объект хранит имя в корневом XML-элементе или filename, сначала предпочитать XML;
3. filename использовать только как fallback для восстановления объекта;
4. если имя не найдено, diagnostics `missingObjectName`, объект пропускается или выводится частично только если full_name можно безопасно восстановить.
```

Для `Configuration.xml` имя берется из XML. Если не найдено, это критично для основной конфигурации.

### 8.4. Простые свойства

Простым scalar считается XML-узел:

```text
- имеет текстовое значение;
- не имеет значимых дочерних XML-узлов;
- не является служебным идентификатором/UUID/GUID;
- не является файловым путем;
- не содержит BSL-код или бинарное тело.
```

Простым list считается XML-узел:

```text
- содержит однотипные дочерние элементы;
- каждый дочерний элемент преобразуется в строку;
- список не является сложной структурой формы/макета/прав/таблицы.
```

Сложные дополнительные узлы:

```text
- не выводить автоматически;
- фиксировать diagnostics `unsupportedComplexProperty`.
```

### 8.5. Значения

Форматирование значений:

```text
None/пустая строка -> ""
true/True/Истина   -> "Истина"
false/False/Ложь   -> "Ложь"
строка             -> "<строка>"
список             -> блок:
                      ИмяСвойства:
                          "Значение1"
                          "Значение2"
```

Кавычки внутри значений не экранировать обратным слешем. Эталон выводит вложенные кавычки как есть:

```text
Синоним: "Система заказов "Братья Караваевы""
```

Многострочные значения сохранять внутри одной quoted property, если значение пришло из XML как простой текст и не является BSL.

## 10. Вложенные элементы

Поддержанные вложенные коллекции MVP:

```text
Реквизиты
ТабличныеЧасти
Реквизиты табличных частей
Измерения
Ресурсы
Формы
Команды
Макеты
Значения перечислений
Вложенные подсистемы
```

Full name строится от родителя:

```text
Документы.Заказ.Реквизиты.Шаблон
Документы.Заказ.ТабличныеЧасти.Товары
Документы.Заказ.ТабличныеЧасти.Товары.Реквизиты.Номенклатура
РегистрыСведений.Фасовки.Измерения.Номенклатура
Отчеты.Продажи.Формы.ФормаОтчета
Перечисления.Статусы.Значения.Новый
```

Порядок вывода:

```text
- основной источник порядка: ссылки родительского XML;
- для корня: Configuration.xml / ChildObjects;
- для дочерних объектов: ChildObjects родительского объекта;
- для файловых дочерних объектов, например Forms/Templates: текстовые ссылки <Form>, <Template>, <Command>;
- fallback для объектов без ссылки: сортировка по full_name.
```

Writer не сортирует дерево повторно. `XmlReader` готовит `MetadataObject.children` в эталонном порядке, а `ReportWriter` только сохраняет этот порядок в `Report.txt`.

## 11. Свойства и whitelist

Для каждого поддержанного типа whitelist задается в JSON-настройках в фиксированном порядке.

Общее начало большинства объектов:

```text
Имя
Синоним
Комментарий
ПринадлежностьОбъекта
ОбъектРасширяемойКонфигурации
```

Правило вывода:

```text
1. Собрать whitelist-свойства в порядке registry/settings.
2. Если свойства нет в XML, проверить `propertyDefaults`; такие значения используются для строк, которые Конфигуратор печатает даже когда XML-узел пустой или отсутствует.
3. Собрать дополнительные простые свойства.
4. Исключить свойства, которые уже выведены через whitelist.
5. Исключить запрещенные технические поля.
6. Отсортировать дополнительные простые свойства по имени.
7. Вывести whitelist + дополнительные.
8. Сложные дополнительные свойства записать в diagnostics, если для них нет явного extractor.
```

Поддержанные сложные блоки:

```text
Тип
Подсказка
СвязиПараметровВыбора
ПараметрыВыбора
Характеристики
СтандартныеРеквизиты
XDTO-типы Web-сервисов
Состав / ссылки на объекты метаданных
```

Запрещенные поля/фрагменты для `Report.txt`:

```text
Модуль менеджера
Модуль объекта
Модуль формы
Модуль
МодульОбщегоМодуля
МодульФормы
ПутьКФайлу
ФайлBSL
code/main
code/extensions
src/cf
src/cfe
GitCommit
ПоисковыеТеги
Источник: Основная конфигурация
Источник: Расширение
```

## 12. ReportWriter

Главное правило форматирования:

```text
baseIndent = settings.reportFormat.baseIndent
```

Отступы:

```text
object logical depth 0 -> "\t- Конфигурации..."
property of depth 0   -> "\t\tИмя: ..."
child object depth 1  -> "\t\t- Документы..."
child property        -> "\t\t\tИмя: ..."
list item             -> property_indent + "\t" + "\"...\""
```

API:

```python
class ReportWriter:
    def write(self, sections: Sequence[MetadataSection], output_file: Path, encoding: str) -> None: ...
```

Потоковая запись:

```text
- открыть файл один раз;
- писать строки последовательно;
- не собирать весь Report.txt в память;
- между main и extension секциями писать ровно одну пустую строку;
- если extension нет, не добавлять лишнюю пустую строку в конце.
```

## 13. Диагностика

`report-diagnostics.json`:

```json
{
  "project": "orders",
  "warnings": [
    {
      "code": "extensionMissing",
      "message": "Extension path not found and extensionRequired=false",
      "path": "E:/mcp-1c/repos/orders/src/cfe"
    }
  ],
  "errors": []
}
```

Типовые codes:

```text
configReadError
invalidConfig
mainConfigPathMissing
configurationXmlMissing
configurationNameMissing
extensionMissing
extensionRequiredMissing
xmlReadError
xmlParseError
missingObjectName
unsupportedType
unsupportedComplexProperty
unsafePropertySkipped
reportWriteError
diagnosticsWriteError
```

`report-stats.json`:

```json
{
  "project": "orders",
  "mainConfigPath": "src/cf",
  "extensionPath": "src/cfe",
  "extensionFound": false,
  "extensionRequired": false,
  "generatedAt": "2026-05-06T12:00:00",
  "mainConfigurationObjects": 0,
  "extensionObjects": 0,
  "objectsByType": {},
  "warnings": 0,
  "errors": 0
}
```

`generatedAt` допустим только в diagnostics/stats, не в `Report.txt`.

## 14. Exit codes

Использовать коды из PRD:

```text
0 — Report.txt успешно сформирован, warnings нет.
1 — Report.txt сформирован, есть warnings.
2 — Report.txt сформирован или частично сформирован, но warningsAsErrors=true или передан --strict.
3 — неверные параметры запуска.
4 — не найден путь основной конфигурации src/cf.
5 — не найдено ни одного объекта метаданных.
6 — ошибка записи Report.txt.
7 — extensionRequired=true, но src/cfe не найден.
8 — ошибка чтения config-файла.
```

Приоритет:

```text
3/8 config/CLI errors
4 main path missing
7 required extension missing
6 report write error
5 no metadata objects
2 warningsAsErrors with warnings or recoverable errors
1 warnings
0 success
```

Критические ошибки не должны оставлять старый `Report.txt` как новый успешный результат. Рекомендуется писать во временный файл и атомарно заменять целевой файл после успешной генерации:

```text
Report.txt.tmp -> Report.txt
```

## 15. Логирование

Лог в файл:

```text
logs/generate-config-report-<timestamp>.log
```

Правила:

```text
- INFO: старт, config summary без секретов, найденные пути, counts;
- WARNING: все diagnostics warnings;
- ERROR: критические ошибки;
- DEBUG включать при --verbose;
- stdout/stderr не являются единственным источником диагностики.
```

## 16. Тестирование

Минимальный набор unit tests:

```text
test_config_required_fields
test_config_defaults
test_config_strict_overrides_warnings_as_errors
test_config_uses_custom_generator_settings_path
test_path_normalization_windows_style
test_path_normalization_posix_style
test_report_writer_root_has_base_tab
test_report_writer_no_trailing_blank_line_without_extension
test_report_writer_blank_line_between_main_and_extension
test_scalar_format_empty_string
test_scalar_format_bool
test_scalar_format_quotes_not_escaped
test_list_format
test_order_objects_by_parent_xml_references
test_order_children_by_parent_xml_references
test_order_fallback_objects_by_full_name
test_whitelist_then_extra_properties
test_complex_extra_property_goes_to_diagnostics
test_unsupported_type_fallback
test_extension_missing_not_required_exit_1
test_extension_missing_required_exit_7
test_no_technical_fields_in_report
```

Integration fixtures:

```text
tests/fixtures/minimal_cf/
  Configuration.xml
  Documents/Заказ.xml
  Catalogs/Номенклатура.xml

tests/fixtures/cf_with_extension/
  cf/...
  cfe/...

tests/fixtures/broken_xml/
```

Acceptance checks:

```text
- Report.txt содержит "\t- Конфигурации.<Имя>";
- Report.txt не содержит запрещенные технические строки;
- два запуска на одной fixture дают одинаковый Report.txt;
- extension выводится отдельной корневой секцией;
- diagnostics лежит отдельно от metadata/Report.txt;
- dry-run не создает Report.txt.
```

Качество относительно эталона:

```text
- сравнение не бинарным diff;
- проверять стиль отступов, кавычки, списки, порядок и отсутствие технических полей;
- использовать ОтчетПоКонфигурации.txt как reference для ручной сверки и snapshot-фрагментов.
```

## 17. План реализации

Этап 1. Каркас:

```text
- package structure;
- CLI;
- config loader;
- generator settings loader;
- diagnostics/logging;
- exit code plumbing.
```

Этап 2. Report writer:

```text
- MetadataObject model;
- базовый отступ в одну табуляцию;
- scalar/list formatting;
- секции main/extension;
- детерминированный порядок вывода: XML reference order + fallback-сортировка.
```

Этап 3. XML reader MVP:

```text
- Configuration.xml;
- поддержанные top-level folders;
- name extraction;
- whitelist properties;
- extra simple properties;
- fallback unsupported types.
```

Этап 4. Вложенные элементы:

```text
- реквизиты;
- табличные части и реквизиты ТЧ;
- измерения/ресурсы;
- формы/команды/макеты;
- значения перечислений;
- вложенные подсистемы.
```

Этап 5. Интеграция и hardening:

```text
- dry-run;
- temp file + atomic replace;
- stats/diagnostics JSON;
- tests;
- smoke run на fixture;
- проверка запретных строк.
```

## 18. Риски реализации

Основной риск: разные версии XML-выгрузки 1С могут иметь отличающуюся структуру.

Митигировать так:

```text
- parser namespace-agnostic;
- registry-driven extraction;
- fallback для простых свойств;
- diagnostics для сложных пропусков;
- не блокировать генерацию из-за одного битого объекта;
- расширять whitelist итерационно по реальным XML.
```

## 19. Готовность к следующей версии

Оставить для следующей версии:

```text
- Linux deployment;
- расширение registry новыми типами метаданных через JSON-настройки;
- более точное сопоставление XML со штатными свойствами;
- опциональные snapshot-тесты фрагментов по эталону.
```

## 20. Открытые вопросы

Открытых вопросов по PRD на момент подготовки dev spec нет.
