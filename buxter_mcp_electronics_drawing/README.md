# Buxter MCP Electronics Drawing

MCP-слой генерации технических чертежей для производства и инспекции
электроники (fixture / assembly / inspection drawings) из данных симуляции
сборки. Fable-фаза: структурированный прототип генератора + MCP-заглушка.
Codex-фаза доводит до production-grade (полный MCP-контракт, safety,
интеграция в Buxter).

## Структура

```
mcp_server/
  drawing_generator.py   # ядро: spec → DXF (ezdxf), слои/размеры/GD&T/title block
  drawing_mcp.py         # MCP-заглушка: stdio JSON-RPC, initialize/tools list+call
examples/
  generate_sample_assembly_drawing.py
```

## Быстрый старт

```bash
pip install ezdxf
python examples/generate_sample_assembly_drawing.py
# → sample_electronics_assembly_inspection.dxf (FreeCAD/AutoCAD/SolidWorks/KiCad)
```

Запуск MCP-заглушки (stdio):

```bash
DRAWING_MCP_OUTPUT_DIR=./out python -m mcp_server.drawing_mcp
```

## Что умеет Fable-фаза

- DXF R2010 со слоями `VISIBLE / HIDDEN / CENTER / DIMENSIONS /
  INSPECTION / TITLE_BLOCK`.
- Spec сборки: габариты платы, отверстия с допусками (`+0.1/-0.0`, `H7`),
  флаг `critical`, метки, `simulation_id`, общие допуски, GD&T-ноты.
- Геометрия + осевые + габаритные размеры + позиционные размеры
  critical-фич от базового угла (datum A).
- Inspection-балуны на critical-отверстиях (сквозная нумерация).
- Title block: название, тип чертежа, Sim ID, источник
  (RoboQC/RomeoFlexVision), автор, дата, ревизия, общий допуск, единицы.
- Валидация spec на границе (`AssemblySpec.from_dict`): отверстия вне
  платы и неположительные размеры отклоняются с внятной ошибкой.
- MCP-заглушка: `initialize` → `tools/list` → `tools/call
  (generate_inspection_drawing)`; вывод только в песочницу
  `DRAWING_MCP_OUTPUT_DIR` (по умолчанию `./out`), имена файлов без
  путей/traversal.

## Целевые MCP-инструменты (контракт для Codex-фазы)

| Tool | Назначение |
|---|---|
| `generate_assembly_drawing` | сборочный чертёж из spec симуляции |
| `generate_inspection_drawing` | инспекционный чертёж с балунами и critical dims *(есть в заглушке)* |
| `generate_process_sheet` | операционная карта процесса сборки |
| `add_gdt_and_dimensions` | донанесение GD&T/размеров на существующий DXF |
| `validate_drawing_for_production` | проверка чертежа: слои, title block, полнота размеров |
| `sync_with_simulation` | обновление чертежа из свежего JSON симуляции по `simulation_id` |

## Roadmap Codex-фазы

1. Полноценный MCP-сервер: официальный SDK, полный контракт, сессии,
   таксономия ошибок, structured logging.
2. Все инструменты из таблицы выше.
3. Safety-слой: sandbox вывода (уже в заглушке), human-in-loop для
   production-ревизий, аудит операций.
4. Интеграция в Buxter: skill `mcp_drawing_tools`, router, drawing
   handles в памяти агента; переиспользование `buxter validate` как gate.
5. Расширение генератора под реальные spec симуляции: PCB fixture,
   alignment features, допуски по IPC (IPC-A-610, IPC-2221),
   inspection views.
6. Мосты: KiCad (kicad-mcp) для PCB-чертежей, FreeCAD/build123d для 3D.
7. Качество: полная типизация, тесты, документация.

## Интеграция с Buxter

Подпроект намеренно изолирован (как browser-слой на старте): у него нет
зависимостей от `src/buxter`, контракт — JSON spec на входе, путь DXF на
выходе. Точки стыковки, когда Codex-фаза начнёт интеграцию:

- `buxter draw` → генерация 3D → `generate_inspection_drawing` для
  2D-документации той же детали;
- `simulation_id` — ключ связи с pipeline RoboQC/RomeoFlexVision;
- артефакты BIM-слоя (`objects-database.md`) как источник допусков и
  количеств для ведомостей на чертеже.
