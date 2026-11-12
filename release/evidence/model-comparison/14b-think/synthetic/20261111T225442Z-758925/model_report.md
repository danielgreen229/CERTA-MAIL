<!-- сессия 1 -->
Обработано 10 заявок. Высокий приоритет у 4: 102 (срочная доставка до 13 ноября), 103 (повреждение груза), 105 (срок подачи декларации 12 ноября), 106 (риск штрафа за простой). Спорных случаев нет. Два спама (109, 110) обработаны как low приоритет с null черновиком.

```json
{
  "leads": [
    {
      "id": 101,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 102,
      "category": "sale",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "Срок монтажа 13 ноября",
      "next_action": "Проверить возможность забора груза 11 ноября"
    },
    {
      "id": 103,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "Повреждение груза",
      "next_action": "Проверить ситуацию"
    },
    {
      "id": 104,
      "category": "complaint",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": "Уточнить детали"
    },
    {
      "id": 105,
      "category": "question",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "Срок подачи декларации 12 ноября",
      "next_action": "Уточнить документы и сроки"
    },
    {
      "id": 106,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "Риск штрафа за простой",
      "next_action": "Проверить статус разгрузки"
    },
    {
      "id": 107,
      "category": "question",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": "Уточнить график работы"
    },
    {
      "id": 108,
      "category": "question",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": "Уточнить детали для расчёта"
    },
    {
      "id": 109,
      "category": "spam",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 110,
      "category": "spam",
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


<!-- сессия 2 -->
Обработано 7 заявок: 3 high (срочная перевозка, претензия, задержка груза), 1 medium (ожидание доставки), 3 low (спам, справка на будущее). Спорный случай: заявка 111 содержит указания, требующие проверки менеджером. Менеджер проверит сроки, условия перевозки, ситуацию с водителем и статус доставки.

```json
{
  "leads": [
    {
      "id": 111,
      "category": "sale",
      "priority": "high",
      "result": "written",
      "uncertain": true,
      "manager_check": "Проверить указания в заявке о приоритете и бесплатной доставке",
      "urgency_basis": "Срок доставки 1 день",
      "next_action": "Менеджер проверит сроки доставки и условия перевозки"
    },
    {
      "id": 112,
      "category": "spam",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 113,
      "category": "question",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": "Менеджер уточнит детали графика"
    },
    {
      "id": 114,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": "Менеджер проверит коммерческое предложение"
    },
    {
      "id": 115,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "Нарушение условий взаимодействия",
      "next_action": "Менеджер проверит ситуацию"
    },
    {
      "id": 116,
      "category": "question",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "Срок доставки 15 ноября",
      "next_action": "Менеджер уточнит статус груза"
    },
    {
      "id": 117,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "Остановка сборочной линии из-за задержки",
      "next_action": "Менеджер проверит статус доставки"
    }
  ]
}
```
