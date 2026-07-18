# Buxter MCP Electronics Drawing

MCP-сервер генерации технических чертежей для производства и инспекции
электроники (fixture / assembly / inspection drawings) из данных симуляции
сборки. Production-фаза: официальный MCP-протокол, шесть инструментов,
строгая валидация, песочница вывода, интеграционные stdio-тесты.

## Структура

```
mcp_server/
  drawing_generator.py   # ядро: spec → DXF (ezdxf); assembly/inspection/process
  drawing_mcp.py         # MCP-сервер (официальный SDK, stdio, 6 инструментов)
  schemas.py             # строгие JSON Schema всех инструментов (контракт)
  sandbox.py             # песочница файлов: bare names, анти-traversal/symlink
examples/
  generate_sample_assembly_drawing.py
requirements.txt
```

## Установка и запуск

```bash
pip install -r requirements.txt        # ezdxf + mcp + jsonschema
DRAWING_MCP_OUTPUT_DIR=./out python -m mcp_server.drawing_mcp
```

Конфигурация для MCP-клиента (Claude Desktop / Claude Code):

```json
{
  "mcpServers": {
    "buxter-drawing": {
      "command": "python",
      "args": ["-m", "mcp_server.drawing_mcp"],
      "cwd": "<путь>/buxter_mcp_electronics_drawing",
      "env": { "DRAWING_MCP_OUTPUT_DIR": "<путь>/out" }
    }
  }
}
```

Прямой вызов генератора без MCP:

```bash
pip install ezdxf
python examples/generate_sample_assembly_drawing.py
# → sample_electronics_assembly_inspection.dxf (FreeCAD/AutoCAD/SolidWorks/KiCad)
```

## Инструменты

| Tool | Назначение |
|---|---|
| `generate_assembly_drawing` | сборочный чертёж: геометрия, осевые, габаритные размеры, ноты, штамп |
| `generate_inspection_drawing` | + inspection-балуны на critical-отверстиях и их позиционные размеры от базового угла |
| `generate_process_sheet` | операционная карта: нумерованная таблица операций (станция, оснастка, контроль) |
| `add_gdt_and_dimensions` | донанесение GD&T-нот и aligned-размеров на существующий DXF |
| `validate_drawing_for_production` | отчёт готовности: читаемость, слои, геометрия, размеры, полнота штампа |
| `sync_with_simulation` | diff нового spec с сайдкаром `.spec.json`, bump ревизии (A→B), перегенерация |

Каждый `generate_*` пишет рядом с DXF сайдкар `<имя>.spec.json` —
каноническую форму spec. Именно по нему `sync_with_simulation` строит
детерминированный список изменений; административные поля (ревизия,
дата, автор) изменениями не считаются, «пустой» sync не двигает ревизию.

## Контракт и гарантии

- **Протокол** — официальный `mcp` SDK, stdio transport, стандартный
  lifecycle `initialize → tools/list → tools/call`.
- **Валидация** — строгие JSON Schema (`schemas.py`,
  `additionalProperties: false`, границы, enum'ы, паттерны) проверяются
  до выполнения кода; поверх — семантическая валидация spec (отверстие
  вне платы и т.п.).
- **Песочница** — все файлы живут в `DRAWING_MCP_OUTPUT_DIR` (по
  умолчанию `./out`). В аргументах — только «голые» имена файлов:
  абсолютные пути, разделители, `..` и symlink-побеги (resolve
  реального пути обязан остаться в песочнице) отклоняются.
- **Детерминированные ошибки** — стабильные префиксы, одинаковый текст
  на одинаковый вход: `SCHEMA_ERROR` / `SPEC_ERROR` / `PATH_ERROR` /
  `FILE_NOT_FOUND` / `DRAWING_ERROR` / `UNKNOWN_TOOL` /
  `INTERNAL_ERROR`. Ошибка инструмента — это `isError: true` c
  текстом, сервер не падает.
- **Результаты** — JSON с сортированными ключами и только
  sandbox-относительными именами файлов.

## Тесты

В корневом `tests/` репозитория (все скипаются, если зависимости не
установлены):

- `test_drawing_sandbox.py` — юнит: контракт песочницы, включая symlink
  escape и детерминизм сообщений;
- `test_drawing_tools.py` — юнит: assembly/inspection, process sheet,
  annotate, validate, diff, bump ревизий;
- `test_drawing_generator.py` — DXF roundtrip ядра;
- `test_drawing_mcp_stdio.py` — интеграция: реальные stdio-сессии через
  официальный MCP-клиент (полный lifecycle, таксономия ошибок, symlink
  escape через протокол, обратное чтение DXF ezdxf).

```bash
pip install -e ".[dev,drawing]"   # из корня репозитория
python -m pytest tests/test_drawing_*.py
```

## Дальше (следующие фазы)

- **B** — адаптация генератора под реальные JSON-spec симуляции
  (ждёт примера данных): PCB fixture, alignment features, допуски по
  IPC-2221/IPC-A-610, inspection views.
- **C** — Buxter skill `mcp_drawing_tools`, router, drawing handles в
  памяти агента, human-in-loop для production-ревизий.
- **D** — мосты: KiCad (kicad-mcp) для PCB, FreeCAD/build123d для 3D.
