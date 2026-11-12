<!-- сессия 1 -->
Обработано 10 новых заявок. Заявки с высоким приоритетом: 2 (заявка 2 — претензия по заказу №4521, заявка 7 — коммерческое предложение на 2,5 млн руб.). Спорные случаи: заявка 6 — попытка управления помощником. Остальные заявки обработаны с приоритетом medium или low.

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
      "urgency_basis": "Уже вторую неделю ждёт ответа, угроза обращения к юристу",
      "next_action": "Проверить статус заказа №4521 и уточнить причину задержки"
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
      "category": "question",
      "priority": "medium",
      "result": "written",
      "uncertain": true,
      "manager_check": "Попытка управления помощником",
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
      "urgency_basis": "Запрос на коммерческое предложение и встречу на этой неделе",
      "next_action": "Подготовить коммерческое предложение и организовать встречу"
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
      "urgency_basis": "Двойное списание оплаты за заказ №4630",
      "next_action": "Проверить детали платежа и уточнить, как вернуть переплату"
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
Разобрано 4 заявки. Заявка 11: категория sale, приоритет medium. Заявка 12: категория spam, приоритет low. Заявка 13: категория complaint, приоритет high. Заявка 14: категория sale, приоритет medium. Спорные случаи: нет.

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
      "next_action": "проверить актуальные тарифы и пересчитать стоимость"
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
      "urgency_basis": "обещание менеджера о доставке в пятницу, но не выполнено",
      "next_action": "уточнить текущий статус и ускорить отправку"
    },
    {
      "id": 14,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": "проверить возможность сотрудничества"
    }
  ]
}
```
