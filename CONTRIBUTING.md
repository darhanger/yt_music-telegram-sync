# Участие в разработке

Спасибо за интерес к проекту. Перед началом работы создайте issue с описанием ошибки или предлагаемого изменения.

## Локальная проверка

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Сохраняйте изменения небольшими и целевыми. Новое поведение должно быть покрыто тестами. Не добавляйте в issue, коммиты или логи Telegram-сессии, API key, API hash, номера телефонов и другие персональные данные.
