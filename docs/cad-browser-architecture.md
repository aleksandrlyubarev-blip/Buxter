# Buxter: связка CAD-слоя и browser-слоя

Архитектурная записка. Фиксирует фактическое состояние обоих слоёв и то, как
они работают в паре — по мотивам сценария «Codex + Comet» (генерация сложной
геометрии + browser automation в веб-инструменте типа Spherene ADMS).

## Ответы на четыре вопроса (по факту, из кода)

### 1. На чём работает CAD-слой

Не CadQuery и не PythonOCC. Схема — **Claude как кодогенератор + внешние CAD-движки
как исполнители**:

- `vision.py` отправляет фото + описание в Claude (multimodal) и получает
  один самодостаточный Python-скрипт.
- Скрипт исполняется одним из двух бэкендов (`backends.py`):
  - **FreeCAD** — headless через `freecadcmd` (`runner.py`), API `Part`/`Mesh`/`Sketcher`;
  - **Fusion 360** — `fusion_runner.py`, режимы `dryrun` (эмиссия скрипта для
    ручного запуска или Fusion MCP-коннектора) и `subprocess` (`-ExecuteScript`).
- Экспорт STL + STEP (+ опционально `.f3d`), валидация артефактов в
  `exporter.py`, инспекция меша через `trimesh` (`buxter inspect`:
  bbox / volume / watertight).
- Итерации: `buxter retry` — прошлый скрипт + stderr идут обратно в Claude
  как контекст.

### 2. На чём работает browser-слой

До этой ветки browser-слоя в репозитории **не было** (ни строчки). Теперь он
есть, стек такой:

- **Playwright (sync) + Chromium** — `browser.py`, класс `PlaywrightSession`.
- Наблюдение страницы — не пиксельный computer-use, а **DOM-дайджест**:
  видимый текст + список интерактивных элементов, проиндексированных
  атрибутом `data-buxter-id`. Дешевле и стабильнее координатных кликов;
  скриншот остаётся fallback-инструментом (уходит в Claude как картинка).
- **Claude tool-use loop** — `web_agent.py`, функция `run_web_task()`.
  Инструменты: `goto`, `read_page`, `click`, `fill`, `select_option`,
  `upload_file`, `screenshot`, `wait`, `finish`.
- CLI: `buxter web -t "…" --url … -a out/out.stl`.

### 3. Оркестрация

Сознательно **не** MAS с shared memory — на этом этапе:

- Один процесс, последовательный pipeline. Слои соединяются **файловыми
  артефактами**: CAD-слой пишет STL/STEP в `out/`, browser-слой получает их
  как явный whitelist вложений.
- Каждый слой возвращает структурированный результат:
  `BackendArtifacts` (CAD) и `WebTaskReport` (web) — `success`, `summary`,
  список шагов. Никакой передачи состояния «через контекст модели».
- Специализация через system prompts: Modeling Agent (FreeCAD/Fusion) и
  Web Operator Agent — разные роли, разные жёсткие правила, один и тот же
  вызов Anthropic API.

Это соответствует духу поста: два узких агента, каждый силён в своём слое,
координация — тонкая и детерминированная.

### 4. Первый сценарий

Ровно в духе Codex + Comet, но на своих артефактах:

```bash
# 1. CAD-слой: геометрия
buxter draw -d "inspection fixture для детали X: базовая плита 120×80×12 мм, \
  3 упора, 2 отверстия M4 под прижим" -o out/

# 2. Browser-слой: веб-инструмент
buxter web \
  --url https://tool.example/upload \
  -a out/out.stl \
  -t "Загрузи out.stl, выставь min wall thickness 1.6 мм, запусти расчёт \
      и дождись результата. Процитируй job id и итоговые метрики."
```

Для задач RoboQC/manufacturing тот же паттерн покрывает: подготовку данных
для simulation-сервисов, загрузку fixtures в MES/PLM-веб-интерфейсы, запуск
проверок в облачных CAM/nesting-инструментах.

## Схема

```
requirements ─▶ Modeling Agent (Claude) ─▶ freecad | fusion ─▶ STL/STEP
                                                                  │
                                                   attachments whitelist
                                                                  ▼
              Web Operator Agent (Claude tool-use) ─▶ PlaywrightSession
                goto / read_page / click / fill /        │
                upload_file / screenshot / wait          ▼
                                                    Chromium → веб-инструмент
                                                                  │
                                                                  ▼
                                          WebTaskReport {success, summary, steps}
```

## Как минимизированы ошибки на стыке слоёв

1. **Whitelist вложений.** `upload_file` принимает только имена файлов,
   явно переданных в `run_web_task(attachments=…)`. Произвольный путь —
   отказ, который возвращается модели как error tool_result.
2. **Контракт завершения.** Агент обязан закончить вызовом `finish(success,
   summary)`; `success=true` — только если цель реально достигнута, а summary
   обязан цитировать наблюдаемые значения (job id, метрики). Выход без
   `finish` трактуется как неуспех.
3. **Свежесть наблюдений.** Element id действительны только до следующей
   навигации; prompt требует `read_page` после каждого перехода. Ошибки
   браузера (timeout, отсутствующий селектор) не роняют цикл, а идут модели
   как error tool_result — она восстанавливается сама.
4. **Бюджет шагов.** `BUXTER_WEB_MAX_STEPS` (по умолчанию 40) — защита от
   зацикливания; при исчерпании возвращается `success=false` с диагнозом.
5. **Безопасность по умолчанию.** Правила в `WEB_SYSTEM_PROMPT`: никаких
   кредов/платежей без явных значений в задаче, никаких регистраций и
   деструктивных действий, не уходить с целевого сайта.

## Что дальше (кандидаты)

- `buxter pipeline manifest.yaml` — draw → validate → web одной командой.
- Валидатор на `trimesh` между слоями (watertight / min wall) как gate перед
  загрузкой в веб-инструмент.
- Доменные пресеты задач для web-агента (загрузка в конкретные инструменты)
  как параметризованные prompt-шаблоны.
- Замер: скриншот-fallback → полноценный vision-режим для canvas/WebGL UI,
  где DOM-дайджест слеп.
