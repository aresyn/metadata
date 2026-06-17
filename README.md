# generate-config-report

`generate-config-report` формирует текстовый отчет по XML-выгрузке метаданных 1C. Цель проекта - получить отчет, близкий к штатному отчету конфигуратора `ОтчетПоКонфигурации.txt`, но без привязки к одной конкретной конфигурации или версии платформы.

Механизм работает поверх XML-структуры конфигурации: читает `Configuration.xml`, файлы объектов метаданных, применяет настройки генератора и записывает итоговый отчет в формате, удобном для сравнения и автоматической обработки.

## Быстрый Старт

Требования:

- Python 3.11 или новее.
- Каталог XML-выгрузки конфигурации 1C с файлом `Configuration.xml`.

Минимальный запуск для агентов и скриптов:

```powershell
python generate_config_report.py D:\cf_llv
```

Канонический запуск как Python-модуля:

```powershell
python -m generate_config_report D:\cf_llv
```

Оба варианта создают отчет прямо в каталоге конфигурации:

```text
D:\cf_llv\ОтчетПоКонфигурации.txt
```

Если файл уже существует, он безопасно заменяется: новый отчет сначала пишется во временный файл в том же каталоге, затем выполняется `Path.replace()`. При ошибке записи или замены временный файл удаляется, а старый отчет остается на месте.

## Установка

Проект не требует внешних Python-зависимостей. Для запуска из рабочей копии достаточно команд выше.

Чтобы получить консольные команды из `pyproject.toml`, установите проект в editable-режиме:

```powershell
python -m pip install -e .
generate-config-report D:\cf_llv
```

После установки доступны:

- `generate-config-report` - основной генератор отчета.
- `generate-config-report-build-overrides` - служебная команда построения XML-derived overrides.

## Режимы Работы

Простой режим принимает один позиционный аргумент:

```powershell
python generate_config_report.py D:\path\to\cf
```

В этом режиме:

- целевой каталог считается корнем XML-конфигурации;
- расширение `cfe` не подключается автоматически;
- diagnostics и logs не создаются;
- XML-derived overrides строятся во временном каталоге;
- итоговый файл всегда называется `ОтчетПоКонфигурации.txt`.

Расширенный режим использует JSON-конфиг:

```powershell
python generate_config_report.py --config .\config.example.json
```

Он нужен, когда требуется указать отдельный `repoPath`, `mainConfigPath`, `extensionPath`, каталог вывода, diagnostics, logs или собственный файл настроек генератора.

## Формат Отчета

По умолчанию отчет записывается в UTF-16 с BOM и CRLF-переносами. Структура представляет дерево объектов метаданных:

```text
	- Конфигурации.Демо
		Имя: "Демо"
		Синоним: "Демо"
		- Справочники.Номенклатура
			Имя: "Номенклатура"
```

Формат вывода, список поддержанных типов объектов, порядок свойств, переводы значений и подавление шумных свойств задаются в [generate_config_report/settings/defaults.json](generate_config_report/settings/defaults.json).

## Документация

- [CLI](docs/cli.md) - варианты запуска, флаги, safe replace, коды завершения.
- [Конфигурация](docs/configuration.md) - `config.json`, настройки генератора, XML-derived overrides.
- [Архитектура](docs/architecture.md) - поток данных, модули пакета, диагностический контур.
- [Разработка](docs/development.md) - тесты, локальные фикстуры, добавление поддержки новых объектов и свойств.

## Структура Проекта

```text
generate_config_report.py                 # совместимый script entry point
config.example.json                       # пример расширенного JSON-конфига
pyproject.toml                            # package metadata и console scripts
generate_config_report/
  cli.py                                  # CLI и выбор режима запуска
  config.py                               # ProjectConfig и чтение JSON-конфига
  generator.py                            # orchestration, diagnostics, exit codes
  xml_reader.py                           # чтение XML-выгрузки метаданных
  property_extractors.py                  # извлечение и форматирование свойств
  report_writer.py                        # запись текстового отчета
  build_xml_overrides.py                  # построение overrides по XML
  settings.py                             # загрузка defaults и overlay-настроек
  settings/defaults.json                  # основная настройка универсального механизма
tests/
  test_generate_config_report.py          # unit и integration tests
```

## Проверки

Быстрая проверка синтаксиса:

```powershell
python -m py_compile generate_config_report\cli.py generate_config_report\generator.py generate_config_report\__main__.py tests\test_generate_config_report.py
```

Полный тестовый прогон:

```powershell
python -B -m unittest discover -s tests -v
```

Интеграционные тесты простого CLI ожидают локальную фикстуру `D:\cf_llv` с файлом `D:\cf_llv\Configuration.xml` и намеренно создают или заменяют `D:\cf_llv\ОтчетПоКонфигурации.txt`.

## Ограничения

- Входом является XML-выгрузка конфигурации, а не бинарный `.cf`.
- Простой режим обрабатывает только указанный каталог конфигурации, без автоматического подключения расширения.
- Проект стремится к высокой близости к отчету конфигуратора, но не гарантирует побайтовое совпадение для всех версий платформы.
- Для новых XML-форматов платформы может потребоваться расширение `defaults.json` или точечная доработка extractor-логики.
