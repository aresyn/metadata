# CLI

Основной CLI рассчитан на два сценария:

- простой запуск с одним путем к XML-конфигурации;
- расширенный запуск через JSON-конфиг проекта.

Оба сценария используют один и тот же конвейер генерации отчета.

## Простой Режим

Минимальный вызов:

```powershell
python generate_config_report.py D:\cf_llv
```

Эквивалентный module-вариант:

```powershell
python -m generate_config_report D:\cf_llv
```

Если проект установлен через `pip install -e .`, можно вызвать console script:

```powershell
generate-config-report D:\cf_llv
```

Результат:

```text
D:\cf_llv\ОтчетПоКонфигурации.txt
```

В простом режиме CLI создает `ProjectConfig` в памяти со следующими значениями:

| Поле | Значение |
| --- | --- |
| `repo_path` | переданный каталог конфигурации |
| `main_config_path` | `.` |
| `main_config_required` | `true` |
| `extension_path` | `None` |
| `extension_required` | `false` |
| `output_path` | переданный каталог конфигурации |
| `report_file_name` | `ОтчетПоКонфигурации.txt` |
| `diagnostics_path` | `None` |
| `logs_path` | `None` |
| `build_xml_overrides` | `true` |

XML-derived overrides строятся во временном каталоге через `tempfile.TemporaryDirectory`. После завершения простого запуска в каталоге конфигурации должен остаться только итоговый отчет.

## Расширенный Режим

Запуск через JSON-конфиг:

```powershell
python generate_config_report.py --config .\config.example.json
```

Module-вариант:

```powershell
python -m generate_config_report --config .\config.example.json
```

Console script:

```powershell
generate-config-report --config .\config.example.json
```

Этот режим нужен, если требуется:

- писать отчет не в каталог XML-конфигурации;
- использовать другое имя отчета;
- подключить расширение `cfe`;
- включить diagnostics и logs;
- управлять `buildXmlOverrides`;
- использовать overlay-настройки генератора.

Позиционный аргумент и `--config` взаимоисключающие. Вызов без обоих аргументов также считается usage error.

## Флаги

Текущий `--help`:

```text
usage: generate_config_report.py [-h] [--config CONFIG] [--verbose] [--strict]
                                 [--dry-run]
                                 [target_config_dir]
```

| Аргумент | Назначение |
| --- | --- |
| `target_config_dir` | путь к XML-каталогу конфигурации для простого режима |
| `--config CONFIG` | путь к JSON-конфигу для расширенного режима |
| `--verbose` | включает debug logging |
| `--strict` | трактует warnings как ошибочный результат генерации |
| `--dry-run` | проверяет входы и строит модель без записи итогового отчета |

Особенность `--dry-run`:

- отчет не записывается;
- в простом режиме каталог конфигурации не меняется;
- в расширенном режиме diagnostics, logs и XML-derived overrides могут быть записаны, если они включены в config.

## Safe Replace

Запись отчета выполняется атомарной заменой в том же каталоге:

1. Генератор пишет новый отчет во временный файл рядом с целевым отчетом.
2. Имя временного файла формируется как `<имя отчета>.tmp`.
3. После успешной записи выполняется `Path.replace(target)`.
4. Если запись или замена завершается `OSError`, временный файл удаляется.
5. Старый отчет не удаляется заранее.

Для простого режима временный файл будет:

```text
D:\cf_llv\ОтчетПоКонфигурации.txt.tmp
```

Если итоговый файл заблокирован, каталог недоступен для записи или не хватает прав, CLI возвращает `EXIT_REPORT_WRITE_ERROR`.

## Коды Завершения

Коды генератора объявлены в `generate_config_report.generator`.

| Код | Имя | Значение |
| --- | --- | --- |
| `0` | `EXIT_SUCCESS` | отчет успешно сформирован, ошибок и warnings нет |
| `1` | `EXIT_WARNINGS` | отчет сформирован, но есть warnings |
| `2` | `EXIT_WARNINGS_AS_ERRORS` | есть errors или warnings при `--strict` / `warningsAsErrors=true` |
| `3` | `EXIT_BAD_ARGS` | JSON-конфиг прочитан, но содержит некорректные значения |
| `4` | `EXIT_MAIN_PATH_MISSING` | обязательный каталог основной конфигурации не найден |
| `5` | `EXIT_NO_OBJECTS` | источники найдены, но объекты метаданных не прочитаны |
| `6` | `EXIT_REPORT_WRITE_ERROR` | отчет не удалось записать или заменить |
| `7` | `EXIT_EXTENSION_REQUIRED_MISSING` | обязательный каталог расширения не найден |
| `8` | `EXIT_CONFIG_READ_ERROR` | JSON-конфиг не удалось прочитать или распарсить |
| `9` | `EXIT_NO_SOURCES` | не найден ни один каталог-источник метаданных |

Отдельно: ошибки разбора CLI-аргументов обрабатываются `argparse` и завершают процесс с кодом `2`. При прямом вызове `main([...])` такие ошибки выбрасывают `SystemExit(2)`.

## Служебный CLI Для Overrides

Команда:

```powershell
generate-config-report-build-overrides --repo-path D:\repo --main-config-path src\cf --output .\work\project.xml-overrides.json
```

Module-вариант:

```powershell
python -m generate_config_report.build_xml_overrides --repo-path D:\repo --main-config-path src\cf --output .\work\project.xml-overrides.json
```

Аргументы:

| Аргумент | Назначение |
| --- | --- |
| `--repo-path` | корень репозитория или проекта |
| `--main-config-path` | путь к основной конфигурации, по умолчанию `src/cf` |
| `--extension-path` | путь к расширению, по умолчанию `src/cfe` |
| `--output` | файл JSON overrides |
| `--generator-settings` | опциональный базовый файл настроек для анализа XML |

Этот CLI не формирует отчет. Он только строит JSON overlay, который можно передать генератору через `generatorSettingsPath`.
