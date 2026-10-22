---
name: arkts-ui-coverage-auditor
description: "核对 iOS 入口、页面、状态、事件与原生语义是否进入 HMigBot UI spec，以及每个页面是否有目标计划归属；与真实设备视觉验证分开。"
---


# iOS UI 规格覆盖审计

输入工程/入口地图、ios-ui-facts、ios-semantics、ui-manifest 与分页 spec。
先执行 a2h_ios source-check，检查原生字段与源溯源，再做覆盖核对。

1. 入口→页面：应用根、导航目的地、模态、深链/通知、扩展可视入口逐项有 page ID 或具体排除理由。
2. 页面→状态：初始/加载/空/错误/内容、权限、登录、trait 条件按真实源码逐项进入 spec。
3. 状态→事件：按钮、手势、输入、选择、返回与系统回调各有前后态和处理器证据。
4. 原生语义：SwiftUI identity/Binding/modifier/task、UIKit lifecycle/constraint/delegate
   不得因截图或扁平控件清单而丢失；混合页分别检查两种框架。
5. plan 存在时页面、可复用组件、共享导航与 handler 都有唯一 owner。
6. 逐项记录 covered/missing/unknown/not_applicable 和证据；不通过目录条数推定覆盖。

输出 `spec/ui-coverage-report.md`，附检查范围、源版本、缺口和责任阶段。
只有范围内源事实全部有归属且无未决缺口才写静态覆盖 PASS；
运行/视觉结果另列 not_run 或真实结果，不能混入规格覆盖状态。
