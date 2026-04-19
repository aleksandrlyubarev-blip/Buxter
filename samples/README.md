# Samples

Справочные входы для `buxter draw`.

- `bracket_description.txt` — текстовое описание L-кронштейна под M4. Используется в quickstart в главном README.
- `bracket.jpg` — фотография референсной детали. **Не закоммичено**: положи сюда свой снимок (jpg/png, ≤ 5 МБ). Минимальное требование — видны общая форма и расположение отверстий.

Пример запуска из корня репо:

```bash
buxter draw \
  --photo samples/bracket.jpg \
  --description "$(cat samples/bracket_description.txt)" \
  --output out/
```
