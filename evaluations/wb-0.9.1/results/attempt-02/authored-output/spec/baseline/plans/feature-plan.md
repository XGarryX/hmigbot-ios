# Counter migration plan
plan_format: indexed-v1

## Context
Check imports/registration/wiring first, then run actual hvigor assembleHap. Device UI is unavailable.

## Base
detail: plans/base-plan.md

## F001
detail: plans/slices/slice-01-F001.md

### FV:FV-1
| 字段 | 值 |
|---|---|
| item_id | "FV:FV-1" |
| ac_ids | ["F001-AC01", "F001-AC02"] |
| ownership | [] |
| parents | ["UI:PAGE-0001", "SLICE:F001:3a"] |
| page_ids | [] |
| scope | "product" |
| verification | "compile" |

### FV:FV-2
| 字段 | 值 |
|---|---|
| item_id | "FV:FV-2" |
| ac_ids | ["F001-AC01", "F001-AC02"] |
| ownership | [] |
| parents | ["FV:FV-1"] |
| page_ids | [] |
| scope | "product" |
| verification | "compile" |

```json
{
  "plan_items_version": 2,
  "items": [
    {
      "item_id": "FV:FV-1",
      "ac_ids": [
        "F001-AC01",
        "F001-AC02"
      ],
      "ownership": [],
      "parents": [
        "UI:PAGE-0001",
        "SLICE:F001:3a"
      ],
      "page_ids": [],
      "scope": "product",
      "verification": "compile"
    },
    {
      "item_id": "FV:FV-2",
      "ac_ids": [
        "F001-AC01",
        "F001-AC02"
      ],
      "ownership": [],
      "parents": [
        "FV:FV-1"
      ],
      "page_ids": [],
      "scope": "product",
      "verification": "compile"
    }
  ]
}
```
