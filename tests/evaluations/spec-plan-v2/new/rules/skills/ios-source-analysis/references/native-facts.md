# iOS 原生事实契约与必需维度

新生成与0.6.0以后实施使用 `schema_version: 2`，结构化known、机器fact_ids、状态字段与义务覆盖以
[harness v2](harness-v2.md) 为准。项目spec_contract_version只决定内容profile，不修改本载荷版本。
v1自由value只可作为0.5.0历史导入输入，不能用于新baseline或新版门禁。

共用产物名称、稳定 page/F/AC ID 和计划布局保留；源字段使用 `source_anchors`、
`source_anchors_ref`。每个源锚点有 path、role；推荐 symbol、line、end_line。
路径相对源根，禁止越界，行号从 1 起，不能用只存在于目标仓的 .ets 作源真值。

`spec/baseline/ios-semantics.json` 是源特征的结构化伴随文件，不取代 Markdown spec。
顶层：`schema_version: 2`、`source_platform: "ios"`、`documents: []`。
每项：`id`（page_NNNN 或 FNNN）、`kind`（page/feature）、`languages`、`frameworks`、`facts`。
languages 用 swift/objc/objcxx/c/cpp；frameworks 用 swiftui/uikit/ib/other/nonvisual。

`facts` 中每个维度是对象：

```json
{
  "status": "known",
  "value": {"input": "真实输入", "processing": "从当前源片段解释实际处理", "observable": "该源行为的具体结果"},
  "fact_ids": ["从当前ios-facts复制的真实ID"],
  "evidence": [{"path": "CounterView.swift", "line": 4}],
  "reason": ""
}
```

示例只说明字段形态，必须替换真实内容/机器ID/源行，不可原样发行。known需要非空对象value、当前机器fact_ids和至少一处有效源证据；not_applicable需要具体reason；
unknown 需要 reason，保持 source finding，不用空对象伪装已完成。
v2中value固定为对象，数组/源表达式放对象内部；保存真实语义而非套固定组件枚举。

`state_ownership.value`有更严格结构：`{"states":[{"fact_id":"实际状态fact ID","owner":"实际owner","storage":"State","type":"Int","initializer":"0"}]}`。owner/storage/type/initializer逐字匹配当前机器状态事实；initializer保留源表达式文本，不能把false/nil/0互换。其它维度的value对象按语义展开，不借状态示例捏造所有页面都含计数器。

历史导入的schema_version 1可含自由value；import-legacy将旧声明归档并转unknown，重新关联当前fact_ids和源复核后才成为v2 known。只改schema_version或摘要不能继承旧PASS。

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
