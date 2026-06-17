# Разработка

Проект намеренно небольшой: Python 3.11+, стандартная библиотека, `unittest`, без runtime-зависимостей.

## Локальная Подготовка

Проверить версию Python:

```powershell
python --version
```

Опционально установить проект в editable-режиме:

```powershell
python -m pip install -e .
```

После этого доступны console scripts:

```powershell
generate-config-report --help
generate-config-report-build-overrides --help
```

Без установки можно запускать напрямую:

```powershell
python generate_config_report.py --help
python -m generate_config_report --help
```

## Тесты

Полный прогон:

```powershell
python -B -m unittest discover -s tests -v
```

Часть integration tests требует локальный каталог:

```text
D:\cf_llv
D:\cf_llv\Configuration.xml
```

Эти тесты намеренно создают и заменяют:

```text
D:\cf_llv\ОтчетПоКонфигурации.txt
```

Если фикстуры нет, тест должен падать с понятным сообщением. Это сделано специально: для простого CLI проверяется реальная XML-конфигурация, а не минимальный временный пример.

## Быстрые Проверки

Синтаксис ключевых файлов:

```powershell
python -m py_compile generate_config_report\cli.py generate_config_report\generator.py generate_config_report\__main__.py tests\test_generate_config_report.py
```

Help основного CLI:

```powershell
python generate_config_report.py --help
python -m generate_config_report --help
```

Dry-run на локальной фикстуре:

```powershell
python generate_config_report.py D:\cf_llv --dry-run
python -m generate_config_report D:\cf_llv --dry-run
```

Проверка whitespace в diff:

```powershell
git diff --check
```

## Ручная Smoke-Проверка

Простой режим:

```powershell
python generate_config_report.py D:\cf_llv
```

Ожидаемый результат:

```text
D:\cf_llv\ОтчетПоКонфигурации.txt
```

Отчет должен быть непустым и содержать корневую строку вида:

```text
	- Конфигурации.
```

Расширенный режим:

```powershell
python generate_config_report.py --config .\config.example.json
```

Перед запуском замените пути в `config.example.json` на локальные.

## Добавление Поддержки Свойства

Предпочтительный порядок:

1. Найти XML-элемент в реальной выгрузке и определить, как это свойство выглядит в отчете конфигуратора.
2. Проверить, можно ли выразить поддержку настройками в `settings/defaults.json`.
3. Если XML-имя отличается от имени отчета, добавить alias в `propertyAliases`.
4. Если значение нужно перевести, добавить правило в `propertyValueTranslations`, `propertyValuePrefixTranslations`, `valueTranslations` или соседний раздел.
5. Добавить свойство в whitelist нужного `objectTypes` или `childCollections`.
6. Если свойство имеет сложную XML-структуру, добавить extractor-логику в `property_extractors.py`.
7. Добавить unit test на минимальный XML-фрагмент.
8. Прогнать tests и smoke на `D:\cf_llv`.

Если новое правило зависит от конкретной конфигурации, не добавляйте его как project-specific условие в Python-код. Используйте settings overlay или XML-derived overrides.

## Добавление Типа Объекта

Для нового типа метаданных обычно достаточно расширить `objectTypes` в `settings/defaults.json`:

```json
{
  "typeKey": "new_type",
  "folderNames": ["NewTypes", "НовыеТипы"],
  "xmlElementNames": ["NewType"],
  "reportPlural": "НовыеТипы",
  "whitelist": [
    "@common",
    "Имя",
    "Синоним"
  ],
  "childCollections": [
    "forms",
    "commands"
  ]
}
```

Правила:

- `typeKey` должен быть стабильным внутренним идентификатором;
- `folderNames` должны включать известные варианты папок XML-выгрузки;
- `xmlElementNames` нужны, если имя XML-элемента не выводится автоматически из папки;
- `reportPlural` должен совпадать с заголовком в отчете;
- `whitelist` задает порядок свойств;
- `childCollections` переиспользует уже описанные вложенные коллекции.

Если тип имеет нестандартные вложенные объекты, сначала добавьте их в `childCollections`.

## XML-Derived Overrides

Для проверки builder-а отдельно:

```powershell
python -m generate_config_report.build_xml_overrides `
  --repo-path D:\repo `
  --main-config-path src\cf `
  --output D:\repo\settings\generated\demo.xml-overrides.json
```

После генерации проверьте JSON:

```powershell
python -m json.tool D:\repo\settings\generated\demo.xml-overrides.json
```

Builder должен оставаться конфигурационно-универсальным. Новые rules допустимы, если они выводятся из XML-структуры и не завязаны на один проектный путь или одно имя базы.

## Диагностика При Доработках

Если новая поддержка уменьшает число warnings, проверьте:

- `report-diagnostics.json`;
- `report-stats.json`;
- количество `unsupportedComplexProperty`;
- количество `unsupportedType`;
- наличие новых ошибок парсинга.

При добавлении fallback-поведения лучше явно решить, нужен ли warning. Для массовых ожидаемых случаев warning может создавать шум, для неизвестного XML-формата warning полезен.

## Совместимость

При изменениях важно сохранять:

- простой CLI с одним аргументом;
- module-вариант `python -m generate_config_report`;
- JSON config mode `--config`;
- safe replace итогового отчета;
- возможность работы без diagnostics/logs;
- отсутствие внешних runtime-зависимостей;
- универсальность через settings вместо project-specific условий.

## Гигиена Git

Перед commit полезно проверить:

```powershell
git status --short
git diff --check
python -B -m unittest discover -s tests -v
```

Не коммитьте локальные временные артефакты из `work/`, если они не стали частью осознанной документации или тестовых данных.
