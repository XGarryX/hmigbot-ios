# Counter migration plan
plan_format: indexed-v1

## Context
Preserve VStack/Text/Button order and page lifetime; Button calls add, model result refreshes @State count.

## Batch 1
| item_id | 目标文件 | ac_ids | owning_slice |
|---|---|---|---|
| PAGE-0001 | entry/src/main/ets/pages/CounterPage.ets | ["F001-AC02"] | F001 |

### UI:PAGE-0001
| 字段 | 值 |
|---|---|
| item_id | "UI:PAGE-0001" |
| ac_ids | ["F001-AC02"] |
| ownership | ["entry/src/main/ets/pages/CounterPage.ets"] |
| parents | ["BASE:Base-0"] |
| page_ids | ["page_0001"] |
| scope | "product" |
| verification | "generated" |

```json
{
  "plan_items_version": 2,
  "items": [
    {
      "item_id": "UI:PAGE-0001",
      "ac_ids": [
        "F001-AC02"
      ],
      "ownership": [
        "entry/src/main/ets/pages/CounterPage.ets"
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
