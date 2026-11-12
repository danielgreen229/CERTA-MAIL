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
      "urgency_basis": "срок 2026-11-10: «Монтаж стенда 13 ноября, выставка открывается 14 ноября, позже груз не нужен. Сможете забрать завтра?»",
      "next_action": "Менеджер уточнит возможность забора груза завтра и сроки доставки."
    },
    {
      "id": 103,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "повреждение или утрата груза: «4 коробки из 10 раздавлены, товар внутри разбит»",
      "next_action": "Менеджер проверит состояние груза по накладной 88104 и сообщит о дальнейших действиях."
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
      "category": "sale",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "срок 2026-11-12: «до 12 ноября»",
      "next_action": "Менеджер уточнит, какие документы требуются для таможенной декларации и срок выдачи оригинала накладной по перевозке 77310."
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
      "next_action": "Менеджер проверит, когда начнётся разгрузка и как избежать штрафа за простой."
    },
    {
      "id": 107,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": true,
      "manager_check": "Срок назван, но дату определить не удалось — проверьте приоритет.",
      "urgency_basis": "простой транспорта или производства: «СРОЧНО!!! Мне очень нужно знать, работаете ли вы по субботам!!! Ответьте немедленно!!!»",
      "next_action": "Менеджер проверит, работает ли компания по субботам и как быстро можно получить ответ."
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
      "manager_check": "Проверить, является ли сообщение рекламой или мошенничеством.",
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 110,
      "category": "spam",
      "priority": "low",
      "result": "written",
      "uncertain": true,
      "manager_check": "Проверить, является ли сообщение фишингом или мошенничеством.",
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
      "priority": "low",
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
      "urgency_basis": "простой транспорта или производства: «У нас из-за этого остановилась сборочная линия»; срок истёк 2026-11-05: «должен был прийти 5 ноября»",
      "next_action": "Менеджер проверит срок доставки и сообщит клиенту о дате поступления груза."
    }
  ]
}
```
