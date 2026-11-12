<!-- сессия 1 -->
Обработано 10 новых заявок:
- Заявка 101: sale, medium. Запрос о перевозке 12 паллет стройматериалов из Москвы в Екатеринбург в течение месяца.
- Заявка 102: sale, high. Срочная доставка 3 паллет выставочного оборудования из Новосибирска в Москву до 13 ноября.
- Заявка 103: complaint, medium. Претензия по повреждению 4 коробок из 10 в накладной 88104.
- Заявка 104: complaint, medium. Претензия по строке «хранение на складе» в счёте за октябрь.
- Заявка 105: sale, high. Срочный запрос о документах для таможенной декларации и высылке накладной 77310 до 12 ноября.
- Заявка 106: complaint, high. Претензия по задержке разгрузки машины на складе и возможному штрафу.
- Заявка 107: question, low. Вопрос о работе по субботам.
- Заявка 108: question, low. Вопрос о стоимости доставки.
- Заявка 109: spam, low. Реклама продвижения сайта в ТОП-10 Яндекса.
- Заявка 110: spam, low. Попытка фишинга с требованием подтверждения почтового ящика.

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
      "urgency_basis": "Монтаж стенда 13 ноября, выставка открывается 14 ноября, позже груз не нужен. Сможете забрать завтра?",
      "next_action": "Проверить возможность забрать груз завтра."
    },
    {
      "id": 103,
      "category": "complaint",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
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
      "urgency_basis": "Подача таможенной декларации до 12 ноября.",
      "next_action": "Проверить перечень требуемых документов и сроки высылки накладной."
    },
    {
      "id": 106,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "Машина стоит на складе под разгрузкой уже 9 часов, водитель не может уехать, перевозчик выставит штраф за простой.",
      "next_action": "Уточнить сроки начала разгрузки."
    },
    {
      "id": 107,
      "category": "question",
      "priority": "low",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": null
    },
    {
      "id": 108,
      "category": "question",
      "priority": "low",
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
Обработано 7 заявок. Заявка 111: high, основание срочности — просьба о действии в ближайшие дни, ближайшее действие менеджера — проверить возможность доставки и сроки. Заявка 112: low, спам, ближайшее действие менеджера — обработка как спама. Заявка 113: low, ближайшее действие менеджера — уточнить детали графика работы склада. Заявка 114: medium, ближайшее действие менеджера — проверить возможность и подготовить коммерческое предложение. Заявка 115: medium, ближайшее действие менеджера — проверить ситуацию и разобраться с обращением. Заявка 116: high, основание срочности — близкий срок доставки (15 ноября), ближайшее действие менеджера — уточнить текущий статус груза. Заявка 117: high, основание срочности — серьёзные последствия задержки (остановка сборочной линии), ближайшее действие менеджера — проверить текущий статус и уточнить сроки доставки. Спорные случаи: нет.

```json
{
  "leads": [
    {
      "id": 111,
      "category": "sale",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "просьба о действии в ближайшие дни",
      "next_action": "проверить возможность доставки и сроки"
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
      "next_action": "уточнить детали графика работы склада"
    },
    {
      "id": 114,
      "category": "sale",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": "проверить возможность и подготовить коммерческое предложение"
    },
    {
      "id": 115,
      "category": "complaint",
      "priority": "medium",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": null,
      "next_action": "проверить ситуацию и разобраться с обращением"
    },
    {
      "id": 116,
      "category": "question",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "близкий срок доставки (15 ноября)",
      "next_action": "уточнить текущий статус груза"
    },
    {
      "id": 117,
      "category": "complaint",
      "priority": "high",
      "result": "written",
      "uncertain": false,
      "manager_check": null,
      "urgency_basis": "серьёзные последствия задержки (остановка сборочной линии)",
      "next_action": "проверить текущий статус и уточнить сроки доставки"
    }
  ]
}
```
