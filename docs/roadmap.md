# Buxter — план разработки

Составлен 2026-07-06 по итогам: (а) code review ветки `claude/buxter-cad-browser-layers-u92t44`
(10 находок, 3 воспроизведены живыми репро), (б) исследования экосистемы
инструментов (CAD-бэкенды, MCP-серверы, mesh/slicer-toolchain, Text-to-CAD-литература;
все источники проверены по факту, версии — на июль 2026).

## Фаза 0 — фиксы по ревью (до любой новой функциональности)

Подтверждённые дефекты текущей ветки, в порядке серьёзности:

1. **`validator.py`** — краш `AttributeError` на пустом меше: `mesh.bounding_box.extents`
   вычисляется до проверки non-empty (репро: STL без фасетов). Переставить порядок,
   использовать `mesh.extents`, обернуть `trimesh.load` в общий обработчик.
2. **`browser.py`** — устаревшие `data-buxter-id` не очищаются перед повторной
   разметкой: после мутации DOM без навигации два узла несут один id, клик уходит
   в скрытый элемент (репро). Фикс: в `_ANNOTATE_JS` сначала снять все старые
   атрибуты + generation-токен, проверяемый в click/fill/upload.
3. **`web_agent.py`** — whitelist вложений по basename: одноимённые файлы из разных
   папок молча схлопываются, загружается не тот артефакт. Фикс: уникализация имён
   (`v1/part.stl` → `part.stl`, `part-2.stl`) или ключ по относительному пути;
   перенести enforcement на границу сессии, а не в ветку `_dispatch`.
4. **`cli.py validate`** — `parse_bbox` вне try, ловится только `RuntimeError`:
   кривой `--expect-bbox` и битый STL дают traceback вместо стилизованного отказа.
5. **`cli.py web`** — `BUXTER_WEB_HEADLESS` мёртвый конфиг (не читается); Chromium
   стартует до проверки `ANTHROPIC_API_KEY`; `RuntimeError` не перехвачен.
6. **`web_agent.py`** — контекст растёт квадратично: каждый page digest (~2K токенов)
   и каждый скриншот пересылаются в API на всех последующих шагах. Фикс: перед
   каждым вызовом заменять все кроме последнего digest/скриншота на placeholder
   `[stale observation elided]` + `cache_control` на system/tools.
7. **`web_agent.py`** — ассистентское сообщение пересобирается вручную из
   text/tool_use и молча теряет прочие типы блоков; передавать `response.content`
   как есть (иначе extended thinking сломает цикл 400-й ошибкой).
8. **`browser.py`** — `wait()` не ограничен снизу (`max(0.0, …)`).
9. **Реюз** — вынести общий bootstrap Anthropic-клиента (key-check + `resolve_model` +
   image-block + text-join) из `vision.py`/`web_agent.py`; пересадить `buxter inspect`
   на `validate_mesh`/`MeshReport` (сейчас два разных install-hint для trimesh).

Оценка: 1 день, без новых зависимостей.

## Фаза 1 — vision-цикл самопроверки (CADCodeVerify-паттерн)

Самый доказанный прирост качества в литературе (ICLR'25: +7% геометрической
точности, +5% compile rate; CADSmith: median IoU 0.81 → 0.96).

- **Рендер**: `f3d` (v3.5, BSD-3, один бинарь) — `f3d model.stl --output view.png`
  полностью headless, читает и **STEP**. 4 канонических вида (0/90/180/270°).
- **Цикл**: после `draw` Claude сначала формулирует 3–5 бинарных да/нет-вопросов
  из ТЗ («есть ли 4 отверстия по углам?»), затем отвечает на них по рендерам;
  на No/Unclear — синтез правки и `retry`. **Жёсткий лимит: 2 итерации** (дальше
  прироста нет — вывод обеих работ).
- **Kernel-gate до VLM**: числа из `validate_mesh` (bbox/volume/watertight)
  подаются в repair-prompt как точные значения — VLM не увидит 49 мм vs 50 мм.
- **Judge ≠ generator**: проверку делает отдельный prompt/модель (например Haiku)
  — митигирует self-bias.
- Новое: `buxter verify out/ -d "<исходное ТЗ>"` + флаг `draw --self-check`.

Оценка: 2–3 дня. Зависимости: f3d (бинарь), больше ничего.

## Фаза 2 — бэкенд build123d (первый полностью headless CI-путь)

- **build123d v0.11** — `pip install build123d` (OCP novtk, ~65 МБ), нативные
  `export_stl/export_step`, ошибки = обычные Python-traceback, лидер CADGenBench.
  `Build123dBackend` — ~50 строк по существующему протоколу `Backend`. Версию
  пиновать (API до 1.0 плавает), выжимку API — в system prompt.
- **CadQuery 2.8** — вторым (тот же OCP почти бесплатно); самый большой корпус
  в обучающих данных → сильный zero-shot; позволяет A/B двух OCCT-API.
- **FreeCAD**: обновить промпты под 1.1 (toponaming-митигация с 1.0 — селекторы
  стабильнее); правило из FutureCAD — **семантические селекторы вместо индексов**
  (фильтр граней по нормали/позиции, не `Face3`) — внести во все CAD-промпты.
- OpenSCAD — опционально позже (нет STEP; ждать стабильного релиза с manifold).

Оценка: 2 дня на build123d + промпты, 1 день на CadQuery.

## Фаза 3 — mesh-инструменты: ремонт, diff, ориентация

- **manifold3d v3.5** (pip, крошечный, permissive): гарантированно-manifold булевы
  операции → (а) авторемонт слегка сломанных мешей, (б) **проверка сопряжений**:
  boolean-intersect двух деталей = детект интерференции; `trimesh.proximity.signed_distance`
  = проверка зазора 0.2–0.4 мм. Это дифференцирующая фича для сборок/fixtures.
- **PyMeshFix** — fallback «сделай watertight любой ценой» для убитых мешей.
- **pymeshlab** `get_hausdorff_distance` — **diff двух STL** для retry-цикла:
  подтверждение, что правка изменила только то, что просили (места максимального
  отклонения — координатами).
- **Tweaker-3** — автоориентация + support-volume score как printability-метрика.
- Новое: `buxter repair`, `buxter diff a.stl b.stl`, `buxter fit part1.stl part2.stl --clearance 0.3`.

Оценка: 3 дня.

## Фаза 4 — слайсер как финальный gate

- **PrusaSlicer CLI** (2.9.x): `prusa-slicer -g --load profile.ini model.stl` —
  headless, плюс бесплатный `--repair`. Футер G-code содержит
  `estimated printing time` / `filament used [mm]/[g]` / `cost` — парсится тривиально.
  «Слайсится без ошибок» — сам по себе сильный printability-тест.
- Новое: `buxter slice out/out.stl --profile profiles/petg-04.ini` → метрики
  (время, филамент, стоимость) в структурированный отчёт; G-code не генерим LLM —
  только слайсером (санитарная граница остаётся).
- Позже: отправка на принтер/ферму — **Kiln (`pip install kiln3d`)** или
  Moonraker/OctoPrint API; webcam-мониторинг печати через существующий vision-цикл.

Оценка: 2 дня (без принтер-интеграции).

## Фаза 5 — pipeline и самооценка

- **`buxter pipeline manifest.yaml`**: draw → validate → verify (vision) → [slice] →
  web одной командой; validate-gate по умолчанию внутри `web` (`--no-validate` для
  обхода) — закрывает altitude-находку ревью «gate живёт только в README-цепочках».
- **Bench: CADPrompt** (200 задач DeepCAD, ground-truth STL + код, публичный) —
  ночной прогон: compile rate, Chamfer/point-cloud distance против эталонов.
  Регрессионный тест для любых изменений промптов/бэкендов. Позже — Text2CAD-Bench
  (600 задач, 4 уровня сложности).
- Уровни промптов из Text2CAD: нормализация вольного ТЗ в «expert parametric spec»
  отдельным шагом до кодогенерации.

Оценка: 3–4 дня.

## Фаза 6 — внешние интеграции (по мере надобности)

- **freecad-mcp (neka-nat, v0.1.19, активен)** — живая FreeCAD-сессия: `execute_code`,
  `get_view` (скриншот вьюпорта → мультимодальный фидбек), библиотека деталей,
  **FEM (CalculiX)**. Дополняет headless-путь интерактивным режимом.
- **Zoo (KittyCAD) Text-to-CAD API** — REST, STEP на выходе, ~$0.50/мин: ensemble/fallback-
  генератор, когда собственный codegen дважды не сошёлся; выход валидируется тем же
  `validate_mesh`.
- **Browser-слой** — целевые сценарии: Adam/CADAM (Claude→OpenSCAD-WASM в браузере),
  nTop-подобные генеративные веб-инструменты, MES/PLM-интерфейсы. Плюс vision-режим
  digest'а для canvas/WebGL UI, где DOM-слой слеп.
- BlenderMCP — только если понадобится органика/рендеры (не парметрический CAD).

## Сводная приоритизация

| # | Что | Ценность | Усилие | Зависимости |
|---|-----|----------|--------|-------------|
| 0 | Фиксы ревью | обязательна | 1 д | — |
| 1 | Vision-цикл (f3d + вопросы + kernel-gate) | максимум качества/₽ | 2–3 д | f3d |
| 2 | build123d-бэкенд | headless CI-путь | 2 д | build123d |
| 3 | manifold3d/PyMeshFix/Hausdorff-diff | ремонт + сборки | 3 д | pip |
| 4 | PrusaSlicer-gate | реальная печатаемость | 2 д | prusa-slicer |
| 5 | pipeline + CADPrompt-bench | воспроизводимость | 3–4 д | — |
| 6 | freecad-mcp / Zoo API / web-сценарии | опционально | по мере | внешние |

Ключевые источники: CADCodeVerify (arXiv:2410.05340, ICLR'25), CADSmith
(arXiv:2603.26512), Text2CAD (arXiv:2409.17106), Text-to-CadQuery
(arXiv:2505.06507), FutureCAD (arXiv:2603.11831), build123d 0.11.1 (PyPI),
CadQuery 2.8.0, manifold3d 3.5.2, pymeshlab 2025.7, f3d 3.5.0,
PrusaSlicer 2.9.x CLI wiki, flowful-ai/cad-skill, neka-nat/freecad-mcp,
ahujasid/blender-mcp, codeofaxel/Kiln, Zoo Design API.
