# Buxter — CAD Agent

Прототип **FreeCAD Modeling Agent** из архитектуры Buxter MAS. Берёт фотографию детали и текстовое описание, просит Claude сгенерировать параметрический FreeCAD-скрипт, запускает его в `freecadcmd` и выдаёт STL/STEP, готовые для FDM-печати.

## Возможности

- `buxter draw` — полный pipeline: фото + описание → STL/STEP.
- `buxter inspect` — bbox/volume/количество треугольников STL.
- `buxter retry` — повторная генерация с правками, используя прошлый скрипт как контекст.
- Jupyter notebook `notebooks/drawing_playground.ipynb` для интерактивных итераций.

## Установка

### 1. FreeCAD ≥ 0.21

Нужен headless-бинарь `freecadcmd` (в 1.0+ может называться `FreeCADCmd`).

- **Ubuntu/Debian:** `sudo apt install freecad`
- **macOS:** `brew install --cask freecad` — путь обычно `/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd`
- **Windows:** установщик с https://www.freecad.org, бинарь в `C:\Program Files\FreeCAD 0.21\bin\FreeCADCmd.exe`

Проверить: `freecadcmd --version`.

### 2. Пакет

```bash
git clone https://github.com/aleksandrlyubarev-blip/buxter.git
cd buxter
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,notebook]"
cp .env.example .env
# заполнить ANTHROPIC_API_KEY; при необходимости FREECAD_CMD
```

## Быстрый старт

```bash
buxter draw \
  --photo samples/bracket.jpg \
  --description "$(cat samples/bracket_description.txt)" \
  --output out/
```

Результат: `out/out.stl`, `out/out.step`, `out/_gen.py` (сам сгенерированный скрипт — его полезно коммитить рядом с образцом).

Посмотреть размер:

```bash
buxter inspect out/out.stl
```

Итерировать:

```bash
buxter retry out/ --description "увеличь толщину стенки до 3 мм"
```

## Jupyter

```bash
jupyter lab notebooks/drawing_playground.ipynb
```

В ноутбуке: загрузка фото, правка описания, preview STL через `trimesh`, кнопка повторного прогона.

## Архитектура

```
photo + description ─▶ buxter.vision ─▶ Claude (multimodal)
                                       │
                                       ▼ FreeCAD-скрипт (Python)
                         buxter.runner ─▶ freecadcmd (subprocess)
                                       │
                                       ▼
                       buxter.exporter ─▶ STL + STEP
```

Модули:

| Файл                           | Назначение                                          |
|--------------------------------|-----------------------------------------------------|
| `src/buxter/cli.py`            | CLI (`draw`, `inspect`, `retry`)                    |
| `src/buxter/vision.py`         | Multimodal-запрос к Claude, парсинг кода            |
| `src/buxter/prompts.py`        | System prompt с правилами генерации скрипта        |
| `src/buxter/runner.py`         | Запуск скрипта в `freecadcmd` с таймаутом          |
| `src/buxter/exporter.py`       | Валидация артефактов                                |
| `src/buxter/bootstrap.py`      | Поиск `freecadcmd`                                  |
| `src/buxter/config.py`         | Настройки через `.env` (pydantic-settings)          |

## Troubleshooting

- **`freecadcmd not found`** — установи FreeCAD или задай `FREECAD_CMD=/полный/путь/до/freecadcmd` в `.env`.
- **Пустой/крошечный STL** — посмотри `out/_gen.py` и stderr (`out/run.log`). Обычно Claude ошибся в размерности — поправь описание и запусти `buxter retry`.
- **Timeout** — подними `BUXTER_RUN_TIMEOUT=300` в `.env` для сложных сборок.
- **STEP пустой** — FreeCAD требует Part-объект для STEP; если модель сначала построилась как Mesh, попроси в описании "build as Part (B-Rep)".

## Связь с Buxter MAS

Этот репозиторий — изолированный прототип **одной роли** из спеки Buxter MAS (см. `romeo_phd/docs/buxter-mas-architecture.md`). Дальше:

- `validator.py` на `trimesh` для watertight/min-wall-thickness.
- FastAPI-обёртка для подключения к pipeline-executor в `romeo_phd`.
- Batch-режим `buxter batch manifest.yaml` для серий образцов.
- Self-repair loop: stderr → Claude → повтор.

## Лицензия

MIT.
