<!-- сессия 1 -->
Обработано 10 заявок. Высокий приоритет: 3 заявки (ID 2, 7, 9) — претензия по заказу, срочный запрос на коммерческое предложение и двойное списание. Остальные 7 — вопросы, запросы и спам. Нет спорных случаев. Все обработаны успешно.

```json
{
  "leads": [
    {
      "id": 1,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 2,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "Угроза обращения к юристу",
      "next_action": "Уточнить вопросы по заказу №4521"
    },
    {
      "id": 3,
      "category": "spam",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 4,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 5,
      "category": "question",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 6,
      "category": "spam",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 7,
      "category": "sale",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "Срочно",
      "next_action": "Подготовить коммерческое предложение и уточнить время встречи"
    },
    {
      "id": 8,
      "category": "question",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 9,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "Двойное списание",
      "next_action": "Уточнить детали платежа"
    },
    {
      "id": 10,
      "category": "question",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    }
  ]
}
```


<!-- сессия 2 -->
Разобрано 4 заявки:
- 11: Запрос о стоимости для 20 сотрудников (sale, medium). Менеджер проверит тарифы.
- 12: Реклама криптовалютных сигналов (spam, low). Черновика нет.
- 13: Претензия по отсутствию договора (complaint, high). Срок истёк (обещано 2026-11-05). Менеджер проверит статус.
- 14: Запрос о сотрудничестве с Казахстаном (sale, medium). Менеджер проверит возможность услуг.
Спорных случаев нет.

```json
{
  "leads": [
    {
      "id": 11,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": "проверит актуальные тарифы и подготовит коммерческое предложение"
    },
    {
      "id": 12,
      "category": "spam",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 13,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "срок истёк (обещано в пятницу, 2026-11-05)",
      "next_action": "проверит статус вашего запроса и свяжется с вами"
    },
    {
      "id": 14,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": "проверит возможность предоставления услуг"
    }
  ]
}
```
