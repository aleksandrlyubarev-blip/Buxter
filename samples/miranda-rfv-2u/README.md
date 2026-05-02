# Miranda RFV — 2U Liquid-Cooled Network Server (CAD demo)

Первый сэмпл для Fusion 360-бэкенда buxter. Демо-макет 2U жидкостного сетевого сервера RFV Miranda для роботизированной системы контроля качества (RFID + умные камеры).

## Структура папки

```
miranda-rfv-2u/
  README.md          — этот файл
  spec.md            — зафиксированное ТЗ v1.1
  params.yaml        — единый source-of-truth для размеров, материалов, tolerances
  prompts/           — промпты для `buxter draw --backend fusion`
    chassis.txt
  reference/         — рабочие reference-скрипты Fusion 360, написанные вручную
    chassis.py       — параметрическое шасси, deliverable #1
```

## Как запускать

### Вариант A — руками в Fusion 360 (быстрый старт)

1. Fusion 360 → **Utilities → Add-Ins → Scripts → +**.
2. Выбрать `reference/chassis.py`, **Run**.
3. Скрипт создаёт новый документ `Miranda_RFV_Chassis` с добавленными UserParameter и генерит базовые компоненты: base plate, side panels, rear panel с вырезами, rack ears, mounting bosses, alignment pins, RFID pad.
4. Правь размеры в **Modify → Change Parameters**, design пересчитается.

Eсли в окружении заданы `BUXTER_STL`/`BUXTER_STEP`/`BUXTER_F3D`, скрипт туда экспортирует результат. Иначе экспорт пропускается, документ остаётся открытым в GUI.

### Вариант B — через buxter (AI-регенерация)

```bash
buxter draw --backend fusion \
  -d "$(cat samples/miranda-rfv-2u/prompts/chassis.txt)" \
  -o samples/miranda-rfv-2u/out/
```

Будет сгенерирован `out/_gen_fusion.py`. Сравни с `reference/chassis.py` в review-сессии. Расхождения исправляются `buxter retry`.

## Roadmap deliverable-ов

| #   | Модуль               | Статус      | Файлы                                              |
|-----|----------------------|-------------|-----------------------------------------------------|
| 1   | spec + params         | ✅ done     | `spec.md`, `params.yaml`                            |
| 2   | Chassis               | ✅ first cut | `prompts/chassis.txt`, `reference/chassis.py`       |
| 3   | Central manifold      | pending     | `prompts/manifold.txt`, `reference/manifold.py`     |
| 4   | Cold plates (split)   | pending     | `prompts/cold_plate.txt`, `reference/cold_plate.py` |
| 5   | Main ASIC board       | pending     | `prompts/asic_board.txt`, `reference/asic_board.py` |
| 6   | BMC board             | pending     | `prompts/bmc_board.txt`, `reference/bmc_board.py`   |
| 7   | Front panel           | pending     | `prompts/front_panel.txt`, `reference/front_panel.py`|
| 8   | Bus bar (54 V HVDC)   | pending     | `prompts/bus_bar.txt`, `reference/bus_bar.py`       |
| 9   | Hoses + QDC           | pending     | `prompts/hoses.txt`, `reference/hoses.py`           |
| 10  | Master assembly       | pending     | `reference/assembly.py`                             |

Каждый deliverable = пара файлов (prompt для buxter + reference-скрипт напрямую). Reference-скрипт служит ground-truth для регрессии AI-вывода.
