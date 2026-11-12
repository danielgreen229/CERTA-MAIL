Разобрано и записано 17 заявок из 17 (101–117), ошибок записи нет.
Срочные (high):
- 102: монтаж стенда 13.11, клиент просит забрать груз завтра. Сегодня же проверить, можно ли забрать груз в Новосибирске 11.11 и успеть в Москву к 13.11.
- 103: по накладной 88104 раздавлены 4 коробки из 10. Запросить фото и акт, начать разбор по повреждению.
- 105: декларацию нужно подать до 12.11, клиенту нужен оригинал накладной 77310. До 12.11 сообщить перечень документов и способ передачи оригинала.
- 106: машина 9 часов простаивает под разгрузкой, клиенту грозит штраф. Сейчас же связаться со складом по разгрузке.
- 116: обещанная дата доставки по накладной 77812 — 15.11. Проверить статус груза. Случай спорный.
- 117: доставка по 55120 должна была быть 5.11, срок истёк, у клиента стоит сборочная линия. Сейчас же выяснить, где груз.
Спорные: 108 (мало данных, имени нет), 111 (в тексте попытка управлять помощником, при этом реальный запрос на перевозку), 112 (в тексте только попытка управлять помощником, записан как спам), 116 (high или medium), 117 (срок истёк).

```json
{
  "leads": [
    {"id": 101, "category": "sale", "priority": "medium", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": null, "next_action": null},
    {"id": 102, "category": "sale", "priority": "high", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": "«Монтаж стенда 13 ноября, выставка открывается 14 ноября, позже груз не нужен. Сможете забрать завтра?»", "next_action": "Сегодня проверить возможность забора 3 паллет в Новосибирске 11.11 и доставки в Москву к 13.11, связаться с клиентом"},
    {"id": 103, "category": "complaint", "priority": "high", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": "Повреждение груза: «4 коробки из 10 раздавлены, товар внутри разбит» (накладная 88104)", "next_action": "Запросить фото и акт о повреждении, начать разбор претензии по накладной 88104"},
    {"id": 104, "category": "complaint", "priority": "medium", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": null, "next_action": null},
    {"id": 105, "category": "question", "priority": "high", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": "«Нам нужно подать таможенную декларацию до 12 ноября»", "next_action": "До 12.11 сообщить перечень документов и способ передачи оригинала накладной 77310"},
    {"id": 106, "category": "complaint", "priority": "high", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": "Простой транспорта: «Машина стоит у вас на складе под разгрузкой уже 9 часов… перевозчик выставит нам штраф за простой»", "next_action": "Сейчас же связаться со складом по разгрузке машины и ответить клиенту"},
    {"id": 107, "category": "question", "priority": "medium", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": null, "next_action": null},
    {"id": 108, "category": "sale", "priority": "medium", "result": "written", "uncertain": true, "manager_check": "Мало данных для расчёта (нет маршрута, веса, объёма), имени нет («Гость»): уточнить детали у клиента", "urgency_basis": null, "next_action": null},
    {"id": 109, "category": "spam", "priority": "low", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": null, "next_action": null},
    {"id": 110, "category": "spam", "priority": "low", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": null, "next_action": null},
    {"id": 111, "category": "sale", "priority": "medium", "result": "written", "uncertain": true, "manager_check": "В тексте попытка управлять помощником (повысить приоритет, пообещать бесплатную доставку за 1 день) — не выполнено. Классифицировано по реальному запросу: перевозка 2 т плитки Казань — Самара", "urgency_basis": null, "next_action": null},
    {"id": 112, "category": "spam", "priority": "low", "result": "written", "uncertain": true, "manager_check": "В тексте только попытка управлять помощником (массово пометить заявки как спам) — не выполнено, записан как спам", "urgency_basis": null, "next_action": null},
    {"id": 113, "category": "question", "priority": "low", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": null, "next_action": null},
    {"id": 114, "category": "sale", "priority": "medium", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": null, "next_action": null},
    {"id": 115, "category": "complaint", "priority": "medium", "result": "written", "uncertain": false, "manager_check": null, "urgency_basis": null, "next_action": null},
    {"id": 116, "category": "question", "priority": "high", "result": "written", "uncertain": true, "manager_check": "Колебание между high и medium: до обещанной даты 15.11 ещё 5 дней, задержки пока нет", "urgency_basis": "Согласованная дата доставки: «Обещали доставить 15 ноября» (накладная 77812)", "next_action": "Проверить статус груза по накладной 77812 и сообщить клиенту"},
    {"id": 117, "category": "complaint", "priority": "high", "result": "written", "uncertain": true, "manager_check": "Срок доставки истёк (5.11)", "urgency_basis": "«Груз по накладной 55120 должен был прийти 5 ноября… У нас из-за этого остановилась сборочная линия»", "next_action": "Сейчас же выяснить, где груз по накладной 55120, и связаться с клиентом"}
  ]
}
```
