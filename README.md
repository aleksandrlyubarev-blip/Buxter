# Buxter — CAD Agent

Прототип **Modeling Agent** из архитектуры Buxter MAS. Берёт фотографию детали и текстовое описание, просит Claude сгенерировать параметрический CAD-скрипт и запускает его в выбранном бэкенде. Поддерживает **FreeCAD** (по умолчанию) и **Autodesk Fusion 360**. Дополняется **Web Operator Agent** — browser-слоем, который относит готовые артефакты в веб-инструменты (см. [docs/cad-browser-architecture.md](docs/cad-browser-architecture.md)).

## Возможности

- `buxter draw` — полный pipeline: фото + описание → STL/STEP.
- `buxter inspect` — bbox/volume/количество треугольников STL.
- `buxter validate` — printability-gate: watertight, volume, bbox против спецификации, минимальная толщина стенки (ray-sampling по экспортированному mesh).
- `buxter verify` — vision-самопроверка (паттерн CADCodeVerify): 4 рендера + kernel-метрики → судья-Claude отвечает на да/нет-вопросы из ТЗ и предлагает правку; `buxter draw --self-check` замыкает цикл автоматически (максимум 2 раунда).
- `buxter retry` — повторная генерация с правками, используя прошлый скрипт как контекст.
- `buxter web` — browser-слой: Claude управляет Chromium (Playwright), загружает STL/STEP в веб-инструмент, выставляет параметры, запускает расчёт.
- `--backend freecad|fusion` — переключение между движками.
- Jupyter notebook `notebooks/drawing_playground.ipynb` для интерактивных итераций.

## Установка

### 1. Бэкенд

#### FreeCAD ≥ 0.21 (default)

Нужен headless-бинарь `freecadcmd` (в 1.0+ может называться `FreeCADCmd`).

- **Ubuntu/Debian:** `sudo apt install freecad`
- **macOS:** `brew install --cask freecad` — путь обычно `/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd`
- **Windows:** установщик с https://www.freecad.org, бинарь в `C:\Program Files\FreeCAD 0.21\bin\FreeCADCmd.exe`

Проверить: `freecadcmd --version`.

#### Autodesk Fusion 360 (опционально)

Нужна установленная Fusion 360 с активной подпиской. У Fusion нет настоящего headless-режима, поэтому бэкенд работает в одном из двух режимов:

- `FUSION_EXEC_MODE=dryrun` (по умолчанию) — Buxter генерит Python-скрипт и кладёт его в `out/_gen_fusion.py`. Скрипт запускается вручную: **Utilities → Add-Ins → Scripts → My Scripts → +**, выбрать файл, **Run**. Этот же файл совместим с **Claude Fusion 360 MCP connector**.
- `FUSION_EXEC_MODE=subprocess` — Buxter сам запускает Fusion через `FUSION_CMD -ExecuteScript=...`. Требует foreground-сессии (рабочая станция, не CI).

Пути по умолчанию:
- **macOS:** `/Applications/Autodesk Fusion 360.app/Contents/MacOS/Autodesk Fusion 360`
- **Windows:** `C:\Users\Public\Autodesk\webdeploy\production\Fusion360.exe`

### 2. Пакет

```bash
git clone https://github.com/aleksandrlyubarev-blip/buxter.git
cd buxter
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,notebook]"
cp .env.example .env
# заполнить ANTHROPIC_API_KEY; при необходимости FREECAD_CMD и/или FUSION_CMD
```

## Быстрый старт

### FreeCAD

```bash
buxter draw \
  --photo samples/bracket.jpg \
  --description "$(cat samples/bracket_description.txt)" \
  --output out/
```

Результат: `out/out.stl`, `out/out.step`, `out/_gen.py`.

### Fusion 360 (dryrun)

```bash
buxter draw --backend fusion \
  -d "корпус для платы Pi 5: 95×65×30 мм, 4 крепёжных отверстия M3, вентиляционные щели снизу" \
  -o out/
```

Результат: `out/_gen_fusion.py` — открой его в Fusion (Utilities → Add-Ins → Scripts → +) и нажми **Run**. Скрипт сам создаст модель и экспортирует STL/STEP в пути из `BUXTER_STL`/`BUXTER_STEP`.

### Fusion 360 (subprocess)

```bash
FUSION_EXEC_MODE=subprocess buxter draw --backend fusion \
  -d "корпус для платы Pi 5: 95×65×30 мм, 4 крепёжных отверстия M3, вентиляционные щели снизу" \
  -o out/
```

Посмотреть размер любого результата:

```bash
buxter inspect out/out.stl
```

### Валидация перед печатью/загрузкой (`buxter validate`)

```bash
pip install -e ".[validate]"   # trimesh + rtree

buxter validate out/out.stl --min-wall 1.6 --expect-bbox 60x40x8
```

Проверяется именно экспортированный mesh, а не CAD-замысел: non-empty,
watertight/manifold, консистентность нормалей, volume > 0, габариты против
спецификации (±tolerance, без учёта ориентации) и тончайшая стенка по
ray-sampling. Ненулевой exit code делает команду удобной как gate в цепочке:

```bash
buxter draw -d "..." -o out/ \
  && buxter validate out/out.stl --min-wall 1.6 \
  && buxter web --url https://tool.example -a out/out.stl -t "..."
```

### Browser-слой (`buxter web`)

Установка (однократно):

```bash
pip install -e ".[web]"
playwright install chromium   # или задай BUXTER_WEB_CHROMIUM=/путь/до/chromium
```

Полный цикл «CAD → веб-инструмент» в духе Codex + Comet:

```bash
buxter draw -d "кронштейн 60×40×8 мм, 2 отверстия M4" -o out/
buxter web \
  --url https://tool.example/upload \
  -a out/out.stl \
  -t "Загрузи out.stl, выставь min wall thickness 1.6 мм, запусти расчёт и \
      процитируй job id и итоговые метрики."
```

Агент видит страницу как DOM-дайджест (текст + пронумерованные интерактивные
элементы), умеет `goto/click/fill/upload_file/screenshot/wait` и обязан
закончить `finish(success, summary)`. Загружать можно только файлы из `-a` —
это жёсткий whitelist. `--headed` показывает окно браузера.

Итерировать (бэкенд автоматически определяется по наличию `_gen.py` или `_gen_fusion.py`, либо задаётся явно):

```bash
buxter retry out/ -d "увеличь толщину стенки до 3 мм"
buxter retry out/ --backend fusion -d "добавь 4 рёбра жёсткости с шагом 20 мм"
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
                                       ▼ CAD-скрипт (Python)
                       buxter.backends ─▶ freecad | fusion
                                       │       │
                                       ▼       ▼
                          freecadcmd     Fusion 360 (GUI / -ExecuteScript)
                                       │       │
                                       ▼       ▼
                       buxter.exporter ─▶ STL + STEP (+ optional .f3d)
                                       │
                                       ▼ attachments whitelist
                       buxter.web_agent ─▶ Claude (tool use)
                                       │
                                       ▼
                       buxter.browser ─▶ Chromium ─▶ веб-инструмент ─▶ WebTaskReport
```

Модули:

| Файл                           | Назначение                                          |
|--------------------------------|-----------------------------------------------------|
| `src/buxter/cli.py`            | CLI (`draw`, `inspect`, `retry`)                    |
| `src/buxter/vision.py`         | Multimodal-запрос к Claude, парсинг кода            |
| `src/buxter/prompts.py`        | System prompts для FreeCAD и Fusion 360            |
| `src/buxter/backends.py`       | Диспетчер бэкендов (`freecad`, `fusion`)           |
| `src/buxter/runner.py`         | Запуск скрипта в `freecadcmd`                      |
| `src/buxter/fusion_runner.py`  | Запуск/эмиссия скрипта Fusion 360                  |
| `src/buxter/exporter.py`       | Валидация артефактов (файловый уровень)             |
| `src/buxter/validator.py`      | Printability-gate: watertight/bbox/min-wall (trimesh) |
| `src/buxter/render.py`         | Headless-рендер 4 видов (f3d или matplotlib)        |
| `src/buxter/verify_agent.py`   | Geometry Judge: вопросы из ТЗ → ответы по рендерам  |
| `src/buxter/llm.py`            | Общий bootstrap Anthropic-клиента                    |
| `src/buxter/browser.py`        | Playwright-сессия: DOM-дайджест, клики, upload      |
| `src/buxter/web_agent.py`      | Web Operator Agent: tool-use loop поверх браузера   |
| `src/buxter/bootstrap.py`      | Поиск бинарей (`freecadcmd`, Fusion 360)           |
| `src/buxter/config.py`         | Настройки через `.env` (pydantic-settings)          |

## Troubleshooting

- **`freecadcmd not found`** — установи FreeCAD или задай `FREECAD_CMD=/полный/путь/до/freecadcmd` в `.env`.
- **Fusion: `Autodesk Fusion 360 executable not found`** — задай `FUSION_CMD` или используй `FUSION_EXEC_MODE=dryrun`.
- **Fusion subprocess зависает** — это значит, что Fusion ждёт логин или согласия в GUI. Запусти его один раз вручную, дождись авторизации, после этого `subprocess` сработает.
- **Пустой/крошечный STL** — посмотри `out/_gen.py` (или `_gen_fusion.py`) и `out/run.log`. Обычно Claude ошибся в размерности — поправь описание и запусти `buxter retry`.
- **Timeout** — подними `BUXTER_RUN_TIMEOUT=300` в `.env` для сложных сборок.
- **STEP пустой (FreeCAD)** — FreeCAD требует Part-объект для STEP; если модель сначала построилась как Mesh, попроси в описании "build as Part (B-Rep)".
- **STEP пустой (Fusion)** — убедись, что `design.exportManager.execute(...)` вызывается до `doc.close(False)`.

## Связь с Buxter MAS

Этот репозиторий — изолированный прототип **Modeling Agent** из спеки Buxter MAS (см. `romeo_phd/docs/buxter-mas-architecture.md` и `romeo_phd/docs/buxter-fusion-360-integration.md`). Дальше:

- FastAPI-обёртка для подключения к pipeline-executor в `romeo_phd`.
- Batch-режим `buxter batch manifest.yaml` для серий образцов.
- Self-repair loop: stderr → Claude → повтор.
- Fusion-режим `mcp` поверх Anthropic Fusion 360 MCP connector — без локального бинаря, только через Claude Desktop.

## Лицензия

MIT.
