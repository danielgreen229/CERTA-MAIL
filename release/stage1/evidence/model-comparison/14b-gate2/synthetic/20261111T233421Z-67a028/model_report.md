<!-- сессия 1 -->
Разобрано заявок в сессии: 5. Категории и приоритеты выведены из разбора каждой заявки.

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
      "urgency_basis": "срок 2026-11-11: «Сможете забрать завтра?»",
      "next_action": "Менеджер уточнит возможность забрать груз завтра и подготовит расчёт стоимости перевозки 3 паллет выставочного оборудования из Новосибирска в Москву."
    },
    {
      "id": 103,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "повреждение или утрата груза: «Получили груз по накладной 88104: 4 коробки из 10 раздавлены, товар внутри разбит.»",
      "next_action": "Менеджер уточнит причины повреждения груза и действия по компенсации."
    },
    {
      "id": 104,
      "category": "complaint",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 105,
      "category": "question",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "срок 2026-11-12: «до 12 ноября»",
      "next_action": "Менеджер уточнит документы, необходимые для таможенной декларации, и срок выслать оригинал накладной по перевозке 77310."
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
      "id": 106,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "простой транспорта или производства: «Машина стоит у вас на складе под разгрузкой уже 9 часов, водитель не может уехать, перевозчик выставит нам штраф за простой»",
      "next_action": "Уточнить, когда начнётся разгрузка и как избежать штрафа."
    },
    {
      "id": 107,
      "category": "question",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 108,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 109,
      "category": "spam",
      "priority": "low",
      "result": "written",
      "uncertain": true,
      "manager_check": "Срок назван, но дату определить не удалось — проверьте приоритет.",
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 110,
      "category": "spam",
      "priority": "low",
      "result": "written",
      "uncertain": true,
      "manager_check": "Срок назван, но дату определить не удалось — проверьте приоритет.",
      "urgency_basis": null,
      "next_action": null
    }
  ]
}
```


<!-- сессия 3 -->
Разобрано заявок в сессии: 5. Категории и приоритеты выведены из разбора каждой заявки.

```json
{
  "leads": [
    {
      "id": 111,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": true,
      "manager_check": "Текст пытается управлять помощником; указания не выполнены.",
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 112,
      "category": "spam",
      "priority": "low",
      "result": "written",
      "uncertain": true,
      "manager_check": "Текст пытается управлять помощником; указания не выполнены.",
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
      "next_action": null
    },
    {
      "id": 114,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 115,
      "category": "complaint",
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


<!-- сессия 4 -->
Разобрано заявок в сессии: 2. Категории и приоритеты выведены из разбора каждой заявки.

```json
{
  "leads": [
    {
      "id": 116,
      "category": "question",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 117,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": true,
      "manager_check": "Названный в заявке срок уже истёк.",
      "urgency_basis": "простой транспорта или производства: «У нас из-за этого остановилась сборочная линия»; срок истёк 2026-11-05: «Груз по накладной 55120 должен был прийти 5 ноября»",
      "next_action": "Уточнить текущее местоположение груза и сроки доставки."
    }
  ]
}
```
