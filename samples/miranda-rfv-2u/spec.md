# Miranda RFV — 2U Liquid-Cooled Network Server
## Техническое задание v1.2 (фиксация от 02.05.2026)

Назначение: учебно-демонстрационный стенд для роботизированной системы контроля качества (RFID HF 13,56 МГц + умные камеры). Макет полностью разборный, с намеренно сохранённой сложностью сборки (2–3 сборочные станции, прецизионное позиционирование).

## 1. Общие требования

| Параметр        | Значение                          |
|-----------------|-----------------------------------|
| Форм-фактор     | 2U rack-mount chassis             |
| Высота          | 88,9 мм                          |
| Ширина (с ушами)| 482,6 мм                         |
| Глубина         | **780 мм** (фиксация)         |
| Сборка          | полностью разборный, 2–3 станции|
| Tolerance       | ±0,05–0,1 мм на ключевых сопряжениях |
| RFID площадки   | HF 13,56 МГц (NFC-совместимые), на всех ключевых деталях |
| Alignment pins  | dowel pins H7/h7, Ст hardened   |

## 2. Состав макета

### 2.1. Шасси (Chassis)

- Материал: оцинкованная сталь, толщина листа **1,0 мм**.
- Открытая верхняя крышка.
- Монтажные уши 19".
- Направляющие (card guides) на боковых стенках.
- Отверстия M3/M4.
- Задняя панель с вырезами под bus bar и QDC.
- Внутренние бобышки и alignment pins.

### 2.2. Основная ASIC-плата

- Модульная: interconnect + 2–4 compute PCB.
- По умолчанию: **2 ASIC, footprint 80×80 мм**.
- Легко меняется на 4 через UserParameter `asic_count`.
- B2B + min 4 alignment pins на соединение.

### 2.3. Плата управления (BMC + COM Express)

- Отдельная carrier-плата справа от основной.
- BMC SoC (тип АСПИД ASPEED или Nuvoton) — placeholder.
- **COM Express Type 6 Compact** (95×95 мм, 440-pin AB+CD) наверху.
- 4 standoff M2.5 для Comex-модуля, pitch 86×86 мм.
- Независимое крепление с alignment pins к chassis base.

### 2.4. Cold plates («башни» охлаждения)

- По одной на каждый ASIC, split-type (top + bottom).
- Материал: медь **C11000** ETP.
- **Микроканалы: skived fin** geometry, fin thickness 0,3 мм, pitch 1,0 мм, depth 8,0 мм.
- U-/Г-образные медные трубки inlet/outlet.
- Flatness площадки контакта ≤ 0,05 мм (lapped).

### 2.5. Центральный manifold

- По центру сервера (X=0).
- Материал: **нержавеющая сталь AISI 304** (фиксация, совместима с PG/EG хладагентом).
- 4 × blind-mate QDC: 2 supply (верхние), 2 return (нижние).
- 2 × магистральных ввода сзади (supply / return) через QDC в rear panel.

### 2.6. Шланги / трубки

- Синие (подача), чёрные (обратка).
- Quick-disconnect коннекторы 8 мм.

### 2.7. Bus bar (54 V HVDC)

- Номинал: **54 V HVDC**, **пик 50 А** (→ P_peak = 2,7 кВт).
- Медь C11000.
- Сечение расчётное при ДT ≤3°C: 8 × 25 = 200 мм² (запас ×4 от минимума), округлённо в params.
- PA66 insulator, clearance ≥8 мм до корпуса.

### 2.8. Фронт-панель

- Алюминий 5052, 2,0 мм.
- 3 × Ethernet RJ45, USB-A, 4 индикатора.
- HF 13,56 МГц RFID-pad + camera fiducials.

## 3. Дерево сборки

```
Miranda_RFV_2U (top assembly)
├── Chassis  (Base, Side_L/R, Rear, Rack_Ear_L/R)
├── ASIC_Board (interconnect + 2×compute)
├── BMC_Carrier + COMex_Type6_Compact_Module
├── Cold_Plate × 2 (split-type, skived fin)
├── Manifold (AISI 304)
├── Hose_Set (синие + чёрные)
├── Bus_Bar_54V_50A
└── Front_Panel
```

## 4. Координатная система

- Начало: центр передней кромки базовой пластины.
- X — вправо (width), Y — вглубь (depth), Z — вверх.

## 5. Экспортные форматы

`.f3d` (source-of-truth), `.step` (interop), `.stl` (3D-печать).

## 6. Статус решений

| #   | Вопрос                              | Решение                             |
|-----|--------------------------------------|--------------------------------------|
| 1   | Пиковый ток bus bar               | 50 А                                |
| 2   | Материал manifold                   | Нерж. сталь AISI 304             |
| 3   | Геометрия микроканалов cold plate | Skived fin (0,3 мм × 1,0 pitch × 8 мм)|
| 4   | RFID                                 | HF 13,56 МГц                       |
| 5   | BMC                                  | BMC carrier + COM Express Type 6 Compact|
