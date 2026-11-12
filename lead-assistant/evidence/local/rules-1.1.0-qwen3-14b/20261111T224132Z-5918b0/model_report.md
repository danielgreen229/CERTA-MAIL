<!-- сессия 1 -->
Обработано 10 новых заявок. Заявки с высоким приоритетом: 2 (заявка 2 — претензия по заказу №4521, заявка 7 — коммерческое предложение на 2,5 млн руб. срочно). Спорные случаи: заявка 6 — попытка управления помощником. Остальные заявки обработаны как вопросы или спам.

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
      "urgency_basis": "Уже вторую неделю жду ответа по своему заказу №4521! Никто не перезванивает. Если сегодня не решите, напишу отзыв и пойду к юристу.",
      "next_action": "Проверить статус заказа №4521 и связаться с клиентом"
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
      "urgency_basis": "Нужно коммерческое предложение и встреча на этой неделе. Срочно.",
      "next_action": "Составить коммерческое предложение и назначить встречу"
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
      "urgency_basis": "С моей карты дважды списали оплату за один заказ (№4630). Прошу вернуть лишние деньги.",
      "next_action": "Проверить двойное списание и решить вопрос возврата средств"
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
Обработано 4 заявки. Заявка 11: категория sale, приоритет medium. Заявка 12: категория spam, приоритет low. Заявка 13: категория complaint, приоритет high. Заявка 14: категория sale, приоритет medium. Спорных случаев: нет.

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
      "next_action": "проверить информацию и связаться с клиентом"
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
      "urgency_basis": "задержка договора",
      "next_action": "проверить ситуацию и связаться с клиентом"
    },
    {
      "id": 14,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": "проверить информацию и связаться с клиентом"
    }
  ]
}
```
