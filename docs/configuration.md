# Конфигурация

Расширенный режим генератора управляется JSON-файлом. Пример находится в [config.example.json](../config.example.json).

Минимальный пример для основной конфигурации без расширения:

```json
{
  "project": "demo",
  "repoPath": "D:/repo",
  "mainConfigPath": "src/cf",
  "extensionPath": "",
  "extensionRequired": false,
  "outputPath": "D:/repo/out",
  "reportFileName": "Report.txt",
  "buildXmlOverrides": true
}
```

Запуск:

```powershell
python generate_config_report.py --config .\config.json
```

## Поля Project Config

| Поле | Обязательное | Описание |
| --- | --- | --- |
| `project` | да | имя проекта для diagnostics, logs и имени generated overrides |
| `repoPath` | да | базовый каталог проекта; относительные `mainConfigPath` и `extensionPath` считаются от него |
| `mainConfigPath` | если `mainConfigRequired=true` | путь к основной XML-конфигурации |
| `mainConfigRequired` | нет | если `true`, отсутствие основной конфигурации завершает генерацию кодом `4`; по умолчанию `true` |
| `extensionPath` | если `extensionRequired=true` | путь к XML-расширению |
| `extensionRequired` | нет | если `true`, отсутствие расширения завершает генерацию кодом `7`; по умолчанию `false` |
| `outputPath` | да | каталог итогового отчета |
| `reportFileName` | да | имя файла отчета |
| `diagnosticsPath` | нет | каталог JSON diagnostics и stats |
| `logsPath` | нет | каталог файлов логов |
| `encoding` | нет | проверяемая кодировка config-модели; допустимые значения задаются в settings |
| `warningsAsErrors` | нет | при `true` warnings приводят к коду завершения `2` |
| `buildXmlOverrides` | нет | перед генерацией построить XML-derived overrides |
| `generatorSettingsPath` | нет | путь к settings overlay или путь вывода XML-derived overrides |

Правила путей:

- `mainConfigPath` и `extensionPath` могут быть абсолютными или относительными от `repoPath`.
- `outputPath`, `diagnosticsPath`, `logsPath` и `generatorSettingsPath` используются как обычные `Path`; для повторяемости лучше задавать абсолютные пути.
- Пустая строка в `mainConfigPath` или `extensionPath` трактуется как `None`.
- Должен быть настроен хотя бы один источник метаданных: основная конфигурация или расширение.

## Diagnostics И Logs

Если задан `diagnosticsPath`, генератор пишет:

```text
report-diagnostics.json
report-stats.json
```

`report-diagnostics.json` содержит warnings и errors. Частые повторяющиеся warnings по unsupported complex properties и unsupported types агрегируются, чтобы файл оставался читаемым.

`report-stats.json` содержит:

- пути источников;
- найденность основной конфигурации и расширения;
- количество объектов основной конфигурации и расширения;
- счетчики objects by type;
- количество warnings, warning groups и errors.

Если задан `logsPath`, CLI создает файл:

```text
generate-config-report-YYYYMMDD-HHMMSS.log
```

При `--verbose` уровень логирования повышается до DEBUG.

## Настройки Генератора

Основной файл настроек:

```text
generate_config_report/settings/defaults.json
```

Он содержит:

- поддержанные input encodings: `utf-8`, `utf-8-sig`, `utf-16`, `cp1251`;
- формат отчета: UTF-16, tab-indent, CRLF;
- структуру XML-выгрузки 1C;
- aliases русских и английских имен свойств;
- переводы значений платформы в человекочитаемый отчет;
- списки подавляемых свойств и значений;
- правила форматирования списков;
- правила обработки стандартных реквизитов;
- 41 тип объектов метаданных;
- 21 коллекцию дочерних объектов.

`load_settings(path)` загружает `defaults.json`, а если передан overlay-файл, выполняет deep merge:

- словари объединяются рекурсивно;
- скаляры и массивы из overlay заменяют значения defaults.

Это позволяет добавлять поддержку новых свойств и типов без переписывания всего файла defaults.

## generatorSettingsPath

`generatorSettingsPath` используется в двух режимах.

Если `buildXmlOverrides=false`, это путь к пользовательскому settings overlay:

```json
{
  "generatorSettingsPath": "D:/repo/settings/my-overlay.json",
  "buildXmlOverrides": false
}
```

Если `buildXmlOverrides=true`, этот же путь используется как файл результата XML-derived overrides. Генератор сначала перезапишет его, затем загрузит как overlay:

```json
{
  "generatorSettingsPath": "D:/repo/settings/generated/demo.xml-overrides.json",
  "buildXmlOverrides": true
}
```

Не указывайте hand-written settings overlay в `generatorSettingsPath` одновременно с `buildXmlOverrides=true`, иначе файл будет заменен сгенерированными overrides.

Если `buildXmlOverrides=true`, но `generatorSettingsPath` не задан, файл создается в:

```text
generate_config_report/settings/generated/<project>.xml-overrides.json
```

Простой CLI не пишет этот файл в репозиторий. Он использует временный каталог и удаляет его после завершения.

## XML-Derived Overrides

XML-derived overrides нужны для случаев, где корректное поведение зависит не только от версии платформы, но и от конкретных XML-данных конфигурации.

Сейчас builder собирает:

- `standardAttributeKeepEmptyValueOwnerAttributes`;
- `standardAttributeKeepDefaultOwnerAttributeProperties`.

Основной пример: стандартные реквизиты справочников `Owner`, `Parent`, `Description`, где нужно сохранить пустое значение или default-свойство только для некоторых объектов. Такие правила нельзя надежно описать одним статическим списком для всех конфигураций.

Служебная команда:

```powershell
python -m generate_config_report.build_xml_overrides `
  --repo-path D:\repo `
  --main-config-path src\cf `
  --extension-path src\cfe `
  --output D:\repo\settings\generated\demo.xml-overrides.json
```

Параметр `--extension-path` можно опустить, если расширение не нужно.

## Простой Режим Без JSON

Команда:

```powershell
python generate_config_report.py D:\cf_llv
```

эквивалентна in-memory конфигу:

```json
{
  "project": "cf_llv",
  "repoPath": "D:/cf_llv",
  "mainConfigPath": ".",
  "mainConfigRequired": true,
  "extensionPath": null,
  "extensionRequired": false,
  "outputPath": "D:/cf_llv",
  "reportFileName": "ОтчетПоКонфигурации.txt",
  "diagnosticsPath": null,
  "logsPath": null,
  "buildXmlOverrides": true
}
```

Отличие от JSON-режима: сгенерированные XML-derived overrides пишутся во временный файл и не остаются рядом с конфигурацией.
