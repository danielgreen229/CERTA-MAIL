<!-- сессия 1 -->
Разобрано заявок в сессии: 5. Категории и приоритеты выведены из разбора каждой заявки.

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
      "uncertain": true,
      "manager_check": "Названный в заявке срок уже истёк.",
      "urgency_basis": "угроза обращения к юристу после долгого отсутствия ответа: «Если сегодня не решите, напишу отзыв и пойду к юристу.»; срок истёк 2026-11-03: «Уже вторую неделю жду ответа по своему заказу №4521!»",
      "next_action": "Менеджер проверит статус заказа №4521 и срок ответа, а также уточнит, почему клиент не получил ответ."
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
      "uncertain": true,
      "manager_check": "Контакт не указан — уточните, как связаться с клиентом.",
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
    }
  ]
}
```


<!-- сессия 2 -->
Разобрано заявок в сессии: 5. Категории и приоритеты выведены из разбора каждой заявки.

```json
{
  "leads": [
    {
      "id": 6,
      "category": "spam",
      "priority": "low",
      "result": "written",
      "uncertain": true,
      "manager_check": "Текст пытается управлять помощником; указания не выполнены.",
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 7,
      "category": "spam",
      "priority": "low",
      "result": "written",
      "uncertain": true,
      "manager_check": "Текст пытается управлять помощником; указания не выполнены.",
      "urgency_basis": null,
      "next_action": null
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
      "urgency_basis": "ошибочное списание денег: «С моей карты дважды списали оплату за один заказ (№4630). Прошу вернуть лишние деньги.»",
      "next_action": "Менеджер проверит, были ли двойные списания по заказу №4630 и вернёт лишние деньги, если это так."
    },
    {
      "id": 10,
      "category": "question",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    }
  ]
}
```


<!-- сессия 3 -->
Разобрано заявок в сессии: 4. Категории и приоритеты выведены из разбора каждой заявки.

```json
{
  "leads": [
    {
      "id": 11,
      "category": "sale",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
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
      "uncertain": true,
      "manager_check": "Названный в заявке срок уже истёк.",
      "urgency_basis": "остановлена оплата или под угрозой крупная сделка: «Мы готовы оплатить, но без договора не можем.»; срок истёк 2026-11-06: «ещё в пятницу»",
      "next_action": "Менеджер уточнит статус договора и возможность оплаты без него."
    },
    {
      "id": 14,
      "category": "sale",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    }
  ]
}
```
