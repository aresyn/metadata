# generate-config-report

Генератор `Report.txt` по XML-выгрузке конфигурации 1С для последующей индексации и анализа.

Инструмент читает основную конфигурацию из `src/cf`, опционально читает расширение из `src/cfe` и формирует отчет в формате, максимально близком к штатному отчету Конфигуратора `Отчет по конфигурации`.

## Что умеет

- CLI на Python.
- Чтение project config из JSON.
- Чтение основной конфигурации и расширения.
- Генерация `Report.txt`.
- Диагностика, статистика, логирование.
- Настройки генерации через JSON.
- Overlay-настройки поверх defaults.
- XML-derived overrides через отдельный builder.
- Unit tests.

## Структура

```text
generate_config_report.py
generate_config_report/
  cli.py
  config.py
  diagnostics.py
  generator.py
  metadata_model.py
  object_registry.py
  property_extractors.py
  report_writer.py
  settings.py
  xml_reader.py
  build_xml_overrides.py
  settings/
    defaults.json
    generated/
tests/
  test_generate_config_report.py
```

## Быстрый запуск

Пример project config:

```json
{
  "project": "orders",
  "repoPath": "C:/im/Devops/Codemetadata/orders",
  "mainConfigPath": "src/cf",
  "mainConfigRequired": true,
  "extensionPath": "src/cfe",
  "extensionRequired": false,
  "outputPath": "C:/tmp/generate-config-report-orders/metadata",
  "reportFileName": "Report.txt",
  "diagnosticsPath": "C:/tmp/generate-config-report-orders/diagnostics",
  "logsPath": "C:/tmp/generate-config-report-orders/logs",
  "encoding": "utf-8",
  "warningsAsErrors": false,
  "buildXmlOverrides": true,
  "generatorSettingsPath": "C:/im/Devops/Codemetadata/generate_config_report/settings/generated/orders.xml-overrides.json"
}
```

Запуск:

```powershell
python -B generate_config_report.py --config C:\tmp\orders-generate-config-report.json
```

Результат:

```text
C:\tmp\generate-config-report-orders\metadata\Report.txt
C:\tmp\generate-config-report-orders\diagnostics\report-stats.json
C:\tmp\generate-config-report-orders\diagnostics\report-diagnostics.json
C:\tmp\generate-config-report-orders\logs\generate-config-report-<timestamp>.log
```

## CLI

```text
--config <path>       путь к project config JSON
--verbose             подробный лог
--strict              считать warnings ошибками
--dry-run             проверить входные данные без записи Report.txt
```

## Project config

Обязательные поля:

```text
project
repoPath
outputPath
reportFileName
```

Необязательные поля:

```text
mainConfigPath
mainConfigRequired
extensionPath
extensionRequired
diagnosticsPath
logsPath
encoding
warningsAsErrors
buildXmlOverrides
generatorSettingsPath
```

Правила источников:

- `mainConfigPath` и `extensionPath` можно отключить, передав пустую строку.
- `mainConfigRequired=true` требует существующий каталог основной конфигурации.
- `extensionRequired=true` требует существующий каталог расширения.
- Хотя бы один источник должен быть сконфигурирован.
- На этапе запуска должен быть найден хотя бы один каталог источника, иначе генератор завершится ошибкой.

`generatorSettingsPath` работает как overlay поверх встроенных defaults, а не как полная замена файла настроек.

`buildXmlOverrides=true` включает автоматическое построение XML-derived override JSON в основном скрипте перед генерацией `Report.txt`.

Поведение:

- если `generatorSettingsPath` указан, overrides будут сгенерированы в этот файл;
- если `generatorSettingsPath` не указан, файл будет создан автоматически в:
  `generate_config_report/settings/generated/<project>.xml-overrides.json`;
- после этого основной скрипт сразу использует полученный JSON как overlay settings.

## Настройки генератора

Базовые настройки лежат в файле:

```text
generate_config_report/settings/defaults.json
```

В JSON-настройки вынесены:

- aliases XML-свойств к именам из `Report.txt`;
- whitelist свойств по типам объектов;
- default values для свойств, которые штатный отчет печатает даже без явного XML-узла;
- переводы значений, типов, префиксов и enum;
- marker properties;
- joined-list / multiline formatting rules;
- synthetic defaults для adopted объектов расширения;
- suppression rules для шумных стандартных реквизитов;
- value/prefix translations;
- корневые overrides;
- XML-derived override sections.

Правило проекта: все настраиваемое хранится в JSON.  
Python-код должен содержать только общую логику разбора и вывода, без таблиц проектных переводов и без конфигурационно-специфичного хардкода.

Важно: даже если в текущем эталонном `orders` нет некоторых типов метаданных, генератор должен их поддерживать. В частности, `ПланыСчетов` и `РегистрыБухгалтерии` нельзя считать неактуальными только потому, что их нет в текущем примере.

## XML-derived overrides

Для project-specific правил, которые должны вычисляться по XML, есть два режима.

Основной рекомендуемый режим: через project config и `buildXmlOverrides=true`.

Отдельный ручной builder остается доступен:

```powershell
python -B -m generate_config_report.build_xml_overrides `
  --repo-path C:\im\Devops\Codemetadata\orders `
  --main-config-path src/cf `
  --extension-path src/cfe `
  --output C:\im\Devops\Codemetadata\generate_config_report\settings\generated\orders.xml-overrides.json
```

Этот файл затем подключается через `generatorSettingsPath`.

Builder нужен для случаев, где:

- нельзя захардкодить список объектов в defaults;
- правило должно работать для любых конфигураций;
- критерий можно вычислить из XML-структуры.

Примеры таких правил:

- keep empty/default для части стандартных реквизитов;
- owner-specific suppression/keep rules;
- узкие override-списки для `Owner/Parent` и похожих случаев.

## Формат `Report.txt`

Ключевые правила:

- корневая секция начинается с одной табуляции перед `-`;
- вложенность задается табуляцией;
- scalar-свойства печатаются как `Имя: "Значение"`;
- списки печатаются блоком;
- часть списков печатается в joined multiline quoted-формате;
- основная конфигурация и расширение идут отдельными корневыми секциями;
- между корневыми секциями одна пустая строка;
- технические пути, BSL-модули и Git-сведения не выводятся.

## Порядок вывода

`Report.txt` строится в порядке, близком к Конфигуратору:

- сначала основная конфигурация, потом расширение;
- объекты внутри секции идут по ссылкам из `Configuration.xml` и `ChildObjects`;
- дочерние объекты идут по порядку из XML родителя;
- fallback применяется только там, где нет явной ссылки в XML.

`ReportWriter` не сортирует дерево повторно. Порядок должен быть подготовлен до него.

## Проверки

Unit tests:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TMP='C:\tmp'
$env:TEMP='C:\tmp'
python -B -m unittest discover -s tests -v
```

Smoke run:

```powershell
python -B generate_config_report.py --config C:\tmp\orders-generate-config-report.json
```

JSON validation:

```powershell
python -m json.tool generate_config_report\settings\defaults.json > $null
```

## Текущий статус

На выгрузке `orders` механизм уже закрывает основную часть функционала и большую часть расхождений с эталонным `ОтчетПоКонфигурации.txt`.

По последнему прогону:

- unit tests: `42/42 OK`
- полная генерация `orders`: успешно
- генератор без проектного хардкода в Python для переводов и override-таблиц
- XML-derived overrides вынесены в отдельный generated JSON
- текущее расхождение с эталоном: `197631` строк против `197782`

Детальный прогресс и остаток работ вынесены в отдельный файл:

```text
progress-generate-config-report.md
```

## Ограничения

- полное совпадение с Конфигуратором еще не достигнуто;
- остаток расхождений сейчас в основном сидит в exact-line diff, а не в крупных архитектурных пробелах;
- часть правил по сложным mixed-list значениям и пустым quoted-строкам еще требует уточнения;
- `ПланыСчетов` и `РегистрыБухгалтерии` нужно отдельно проверить и при необходимости добавить как полноценные metadata-type, даже если в текущем `orders` они отсутствуют;
- defaults и generated overrides нужно поддерживать как конфигурацию, а не переносить такие правила в Python.

## Документы

```text
prd-generate-config-report.md
prd-generate-config-report (1).md
dev-spec-generate-config-report.md
ОтчетПоКонфигурации.txt
progress-generate-config-report.md
```
