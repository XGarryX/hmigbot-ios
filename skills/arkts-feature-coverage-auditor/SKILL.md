---
name: arkts-feature-coverage-auditor
description: "核对 iOS 源行为、入口、数据流和平台接缝在 HMigBot 功能 spec/AC 中的覆盖；使用真实目标与模块范围，不靠目录结构或文件数量推定业务覆盖。"
---


# iOS 功能规格覆盖

输入工程地图、功能事实、API inventory、ui-manifest、feature-index 和源快照。
先运行 native source-check 核对源归属与原生字段；它不证明语义覆盖。

1. 每个应用/扩展/后台入口均映射到 feature 或有具体排除证据。
2. 每个实际业务行为的前置态、分支、计算、错误/取消与副作用均有对应 AC/处置。
3. UI 事件反查 feature，服务/API 候选反查 feature，跨模块数据流各边界有责任 owner。
4. Swift 值/引用、Optional、actor/task、Objective-C delegate/ownership 等行为影响
   必须在 spec 或 addendum，不能只出现于工具日志。
5. 未读二进制、宏、动态分派与配置保留 unknown；原文件只有名字不算覆盖。
6. 用稳定 F-AC 与原 traceability index 对账；缺失项回 spec，不通过扩写泛化 AC 凑数。

输出 source-coverage-report.md：范围、版本、逐项映射、缺口、排除理由和证据。
不按目录含几个文件、特定模块名或类名后缀判断是否存在功能。
静态覆盖 PASS 与功能验证 PASS 分开，设备项未执行明确 not_run。
