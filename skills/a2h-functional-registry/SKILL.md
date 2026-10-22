---
name: a2h-functional-registry
description: "在原 a2h baseline 中维护 iOS 功能及入口/状态/事件/副作用的证据登记，用稳定 ID 防止重复或遗漏；不单独生成另一套迁移流程。"
---


# iOS 功能事实登记

读取 ios-project-inspector、ios-ui-analyzer、ios-feature-analyzer 和 ios-api-inventory。
按用户目标划分稳定 F ID，入口可以来自 UI、生命周期、扩展或后台任务。

1. 登记入口、条件、动作、状态/数据变换、副作用、源符号和行号。
2. 相同业务从多个入口调用时复用 F ID，保留各入口行为差异。
3. 枚举常量、阈值、事件、路由、错误和平台接缝逐项给出处置，不按类名数计覆盖。
4. 回指 feature-index 和 feature spec；共享基础设施回指 feature-base。
5. 未知行为保留 reason/needed-evidence；不可达或范围外项给源码证据和具体理由。
6. 增量变化保留旧 ID，新增行为新增 ID，删除/替代有 skip 或 decision 引用。

登记由唯一作者维护，不能用重复事实制造完成度；交 a2h-spec 做 AC 与规格收口。
