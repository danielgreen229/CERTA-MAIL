# Комплект сдачи — AI-помощник менеджера по заявкам (Certa), версия 2.1.0

| Что просили в задании | Где лежит |
|---|---|
| Ссылка на репозиторий / архив с кодом и README | этот репозиторий; архив — `lead-assistant-2.1.0.tar.gz` (+ `.sha256`); [README](../README.md) |
| Обработанный `leads.json` | [`leads.processed.json`](leads.processed.json) — 15 заявок, все `processed` |
| Скриншоты, где видно, как агент работает | [`screenshots/`](screenshots/) — 17 штук (список ниже) |
| Диалоги с ИИ во время работы | [`dialogs/`](dialogs/) |
| Отчёт проверки | [`REVIEW.md`](REVIEW.md) |
| Трейсы и сверки | [`evidence/`](evidence/) |

## Скриншоты

| Файл | Что видно |
|---|---|
| `16_agent_one_command_mcp.png` | **Агент одной командой**: вызовы `list_leads` → `get_lead` → `update_lead` и сводка руководителю |
| `17_claude_code_mcp_tools.png` | **Claude Code**: модель сама нашла три MCP-инструмента и вызвала их, итоговая сводка |
| `01_login.png` | Вход |
| `02_mail_important_first.png` | Почта: папки по ящикам и срочности, сводка, вкладки, «Сначала важные» |
| `03_letter_popup.png` | Окно письма: письмо, что понял помощник, оценка с цитатой, «Проверьте сами», статус груза |
| `04_reply_sent_telegram.png` | Ответ клиенту отправлен в Telegram от бота, источники из базы знаний |
| `05_assign_from_staff.png` | Назначение ответственного из сотрудников или отдела |
| `06_export_menu.png` | Выгрузка: Excel, PDF, Word, JSON |
| `07_onboarding_offer.png`, `08_onboarding_step.png` | Обучение: предложение и шаг тура |
| `09_mailboxes_and_bots.png` | Почтовые ящики, Telegram-боты, сервисы компании |
| `10_agent_runs.png` | Разбор писем: автопроверка почты, история со срочными |
| `11_knowledge_base.png` | База знаний: 10 документов |
| `12_settings_admin.png` | Настройки администратора |
| `13_dark_theme_collapsed_panel.png` | Тёмная тема, свёрнутая панель |
| `14_mobile_mail.png`, `15_mobile_menu.png` | Телефон: список и меню |

Личные данные на скриншотах заменены: имя и логин Telegram тестового клиента показаны как
«Даниил Клиентов», `@client_demo`.

## Как воспроизвести

```bash
cd lead-assistant && bash scripts/install.sh
.venv/bin/process-leads --leads-file <копия data/leads.original.json>
python -m lead_assistant.verify data/leads.original.json <обработанный файл> --expect-all-processed
```
