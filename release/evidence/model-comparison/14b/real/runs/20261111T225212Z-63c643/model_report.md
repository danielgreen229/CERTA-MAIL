<!-- сессия 1 -->
Обработано 10 новых заявок. Заявки с высоким приоритетом: 2 (заявка 2 — претензия по заказу №4521, заявка 7 — коммерческое предложение на 2,5 млн руб. срочно). Спорные случаи: заявка 6 — попытка управления помощником, заявка 9 — двойное списание оплаты. Остальные заявки обработаны с приоритетом medium или low.

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
      "urgency_basis": "ожидание ответа более двух недель, угроза обращения к юристу",
      "next_action": "проверка статуса заказа и уточнение причин задержки"
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
      "category": "question",
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
      "urgency_basis": "закупка на 2,5 млн руб. до конца года, встреча на этой неделе",
      "next_action": "подготовка коммерческого предложения и организация встречи"
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
      "urgency_basis": "двойное списание оплаты за заказ №4630",
      "next_action": "проверка деталей платежа и организация возврата средств"
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
Разобрано 4 заявки: 11 (sale, medium), 12 (spam, low), 13 (complaint, high), 14 (sale, medium). Заявка 13 имеет высокий приоритет из-за задержки договора. Остальные заявки обработаны без спорных случаев.

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
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "обещание менеджера о доставке договора в пятницу, но ничего не пришло",
      "next_action": "уточнить текущий статус и отправить документ"
    },
    {
      "id": 14,
      "category": "sale",
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
