# iOS 原生事实契约与必需维度

0.6.0 实施使用 `schema_version: 2`，结构化 known、机器 fact_ids、状态字段与义务覆盖以
[harness v2](harness-v2.md) 为准。下文 v1 的自由 value 示例只说明 0.5.0 导入格式，
不得用作新 baseline 或新版实现放行。各条件下的必需维度保持共用。

共用产物名称、稳定 page/F/AC ID 和计划布局保留；源字段使用 `source_anchors`、
`source_anchors_ref`。每个源锚点有 path、role；推荐 symbol、line、end_line。
路径相对源根，禁止越界，行号从 1 起，不能用只存在于目标仓的 .ets 作源真值。

`spec/baseline/ios-semantics.json` 是源特征的结构化伴随文件，不取代 Markdown spec。
顶层：`schema_version: 1`、`source_platform: "ios"`、`documents: []`。
每项：`id`（page_NNNN 或 FNNN）、`kind`（page/feature）、`languages`、`frameworks`、`facts`。
languages 用 swift/objc/objcxx/c/cpp；frameworks 用 swiftui/uikit/ib/other/nonvisual。

`facts` 中每个维度是对象：

```json
{
  "status": "known",
  "value": {"owner": "CounterView", "storage": "State", "initial": 0},
  "evidence": [{"path": "CounterView.swift", "line": 4}],
  "reason": ""
}
```

known 需要非空 value 和至少一处有效源证据；not_applicable 需要具体 reason；
unknown 需要 reason，保持 source finding，不用空对象伪装已完成。
各维度允许对象/数组/文字，保存真实语义而非套固定组件枚举。

| 条件 | 必须逐项交代的维度 |
|---|---|
| 任意文档 | entrypoints, data_flow, error_behavior |
| page | identity, composition, layout, state_ownership, events, navigation, accessibility |
| SwiftUI page | modifier_order, binding_flow, environment, task_lifetime |
| UIKit/IB page | controller_lifecycle, layout_constraints, event_connections, delegates |
| feature | state_transitions, concurrency, lifetime, persistence, platform_capabilities |
| Swift | optionality, value_reference_semantics, concurrency_model |
| Objective-C/Objective-C++ | nullability, ownership, dynamic_dispatch |

混合页面取各框架维度的并集。other 页面需在 composition 说明引擎/承载，不能称其已有
自动转换器。nonvisual 只用于没有 UI 的 feature；不能用它逃避页面语义校验。
文件归属与字段存在只是机械门，分析者还必须核对行为、调用目标与框架版本。

page/feature Markdown 头部增加 `source_platform: ios`、`ios_frameworks`、
`source_languages` 与 `source_anchors`；“iOS 原生语义”节引用同 ID facts。
目标映射写独立节：源概念、保留的行为、候选 ArkUI/ArkTS 表达、证据和待决策项。
不能把 SwiftUI 的状态所有权用目标装饰器名称覆盖。
