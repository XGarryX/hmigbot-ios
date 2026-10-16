# Counter migration plan
plan_format: indexed-v1

## Context
Implement synchronous CounterModel.add from Counter.swift:3,7. No persistence, async, global store or invented reset.

### SLICE:F001:3a
| 字段 | 值 |
|---|---|
| item_id | "SLICE:F001:3a" |
| ac_ids | ["F001-AC01"] |
| ownership | ["entry/src/main/ets/models/CounterModel.ets"] |
| parents | ["BASE:Base-0"] |
| page_ids | ["page_0001"] |
| scope | "product" |
| verification | "generated" |

```json
{
  "plan_items_version": 2,
  "items": [
    {
      "item_id": "SLICE:F001:3a",
      "ac_ids": [
        "F001-AC01"
      ],
      "ownership": [
        "entry/src/main/ets/models/CounterModel.ets"
      ],
      "parents": [
        "BASE:Base-0"
      ],
      "page_ids": [
        "page_0001"
      ],
      "scope": "product",
      "verification": "generated"
    }
  ]
}
```
