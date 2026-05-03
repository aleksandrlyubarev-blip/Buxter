# Miranda RFV — 2U Liquid-Cooled Network Server (CAD demo)

Первый сэмпл для Fusion 360-бэкенда buxter. Демо-макет 2U жидкостного сетевого сервера RFV Miranda для роботизированной системы контроля качества (RFID HF 13,56 МГц + умные камеры).

## Структура папки

```
miranda-rfv-2u/
  README.md          — этот файл
  spec.md            — зафиксированное ТЗ v1.2
  params.yaml        — единый source-of-truth
  prompts/           — промпты для `buxter draw --backend fusion`
    chassis.txt
    manifold.txt
    cold_plate.txt
  reference/         — рабочие reference-скрипты Fusion 360 (написаны вручную)
    chassis.py
    manifold.py
    cold_plate.py
```

## Как запускать

### Вариант A — руками в Fusion 360

1. Fusion 360 → **Utilities → Add-Ins → Scripts → +**.
2. Выбрать reference-скрипт (`chassis.py` / `manifold.py` / `cold_plate.py`), **Run**.
3. Скрипт создаёт отдельный документ с UserParameter; правь в **Modify → Change Parameters**.
4. Master assembly (сведённая модель) — deliverable #10.

Eсли заданы `BUXTER_STL`/`BUXTER_STEP`/`BUXTER_F3D`, скрипт туда экспортирует результат.

### Вариант B — через buxter (AI-регенерация)

```bash
buxter draw --backend fusion \
  -d "$(cat samples/miranda-rfv-2u/prompts/cold_plate.txt)" \
  -o samples/miranda-rfv-2u/out/cold_plate/
```

## Roadmap deliverable-ов

| #   | Модуль               | Статус      | Файлы                                              |
|-----|----------------------|-------------|-----------------------------------------------------|
| 1   | spec + params         | ✅ done v1.2 | `spec.md`, `params.yaml`                            |
| 2   | Chassis               | ✅ done v1   | `prompts/chassis.txt`, `reference/chassis.py`       |
| 3   | Central manifold      | ✅ done v1   | `prompts/manifold.txt`, `reference/manifold.py`     |
| 4   | Cold plate (split, skived, U-tube) | ✅ done v1 | `prompts/cold_plate.txt`, `reference/cold_plate.py` |
| 5   | Main ASIC board       | pending     | `prompts/asic_board.txt`, `reference/asic_board.py` |
| 6   | BMC + COMex carrier   | pending     | `prompts/bmc_board.txt`, `reference/bmc_board.py`   |
| 7   | Front panel           | pending     | `prompts/front_panel.txt`, `reference/front_panel.py`|
| 8   | Bus bar (54 V / 50 A) | pending     | `prompts/bus_bar.txt`, `reference/bus_bar.py`       |
| 9   | Hoses + QDC           | pending     | `prompts/hoses.txt`, `reference/hoses.py`           |
| 10  | Master assembly       | pending     | `reference/assembly.py`                             |
