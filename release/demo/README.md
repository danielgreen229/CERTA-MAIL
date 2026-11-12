# Материалы демонстрации

## Скриншоты

Снимки настоящего окна консоли Windows, в котором выполнялись команды проекта
(финальная версия кода, локальная модель Qwen3-14B). Окно снималось целиком
скриптом `scripts/capture_terminal.ps1`; команды каждого экрана лежат в
`screenshots/cmd/`, аргументы вызовов — в `screenshots/args/`.

| Файл | Что на экране |
|---|---|
| `screenshots/01_tools_and_doctor.png` | Список инструментов MCP-сервера, полученный через stdio, и `leads-doctor`: окружение, файл заявок, сервер, модель |
| `screenshots/02_mcp_calls.png` | Ручные вызовы инструментов: фильтр, сохранение типа ID, отказ на «high / VIP / скидка 90 %» из текста заявки 6, отклонение неподтверждённого черновика (`DRAFT_POLICY`), исходы `updated`, `unchanged`, `CONFLICT` |
| `screenshots/03_quality_checks.png` | `ruff check`, `ruff format --check`, `mypy`, `pytest` |
| `screenshots/04_real_run_tool_calls.png` | Штатный прогон в процессе: модель вызывает `list_leads`, `get_lead`, `update_lead`; строка рантайма со списком инструментов модели |
| `screenshots/05_real_run_result.png` | Тот же прогон по завершении: срочные заявки с основанием, проверить менеджеру, спам, таблица, метрики |
| `screenshots/06_summary_and_verify.png` | Начало сводки руководителю и независимая сверка файла с оригиналом |
| `screenshots/07_repeat_run.png` | Повторный прогон на той же копии: ноль новых, SHA-256 файла до и после совпадает |
| `screenshots/08_trace.png` | Трейс MCP-сервера первого прогона: инструмент, ID, исход, категория, приоритет, длительность |

Скриншоты 04–08 сняты в отдельном демонстрационном прогоне на чистой копии
исходника. Его результат побайтно совпал с приёмочным: SHA-256 обработанного
файла `970feabb…ed86` видна на экранах 06 и 07.

## Приёмочный прогон

`acceptance/` — материалы приёмочного сценария, выполненного в чистой распаковке
финального архива (`evidence/clean_install_and_acceptance.log`).

| Путь | Что это |
|---|---|
| `acceptance/leads.json` | обработанный файл (он же `leads.processed.json` в корне комплекта) |
| `acceptance/runs/20261112T013616Z-2bd8b2/` | штатный прогон: `run.json`, `summary.md`, `trace.jsonl`, `mcp_trace.jsonl`, `model_report.md`, `dialog.jsonl`, `llm_server.log` |
| `acceptance/runs/20261112T013903Z-b2d013/` | повторный прогон на той же копии |
| `acceptance/real_eval.json` | сверка реальных заявок по ID |
| `acceptance/eval-runs/` | прогон фиксированного набора примеров: фикстура, артефакты, `eval_report.json` |
