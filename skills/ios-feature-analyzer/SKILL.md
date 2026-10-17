---
name: ios-feature-analyzer
description: "读取 iOS 功能行为与业务规则：沿 Swift/Objective-C 的事件、任务、委托、服务和持久化链提取状态转移、错误/取消、数据契约及独立验收真值，供原 a2h spec/plan 消费。"
---

## 执行前加载

按 [Harness v2](../ios-source-analysis/references/harness-v2.md) 确定机器产物/状态写者；按 [外部资料规程](../ios-source-analysis/references/external-expertise.md) 执行expertise-plan/review，未连接工具保持unknown/unavailable。

执行 `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope feature`，读取真实 `spec/ref/ios-feature-signals.json` 后继续读完整调用链。加载 [逐动作步骤与取消/清理正反例](references/analysis-v2.md)；不得手改机器信号，也不采用上游重构建议改写源行为。

# iOS 功能行为与验收事实

输出规格时按 [交付合同](../a2h-spec/references/spec-delivery-contract.md) 形成前态/事件/处理/后态/副作用/失败恢复、目标公开接口和对接点。信号是待审线索；先沿源码解释行为，再发行有具体期望的 AC。源测试仅作为独立 oracle，不计为目标产品实现或测试通过。

## 范围

输入工程地图、页面事件、后台/扩展入口与服务调用；输出 `spec/ref/ios-feature-facts.md`、
feature 源锚点和 `ios-semantics.json` 的 feature 部分。
使用 `ios-source-analysis/references/source-semantics.md` 和 `native-facts.md`。
页面结构归 UI 分析；协议和 SDK 清单归 API inventory；本技能解释完整可观察行为。

## 1. 划分功能

按用户目标与系统行为分 feature，不按 class/file 一对一建功能。
每个 feature 记录所有 UI、深链、通知、后台、扩展入口与目标范围。
共享鉴权、缓存、数据库、配置放 feature-base；领域行为仍属于对应 F ID。
声明、调用、可达执行链三者分开；发现方法名不能当成已证实功能。

## 2. 读出行为链

对每个入口读动作处理器及实际实现，追 protocol/conformance、delegate、closure、
extension/category、默认实现、注入实例和动态 selector。
记录触发条件、状态前值、输入校验、数据变换、调用顺序、副作用与可观察结果。
当调用目标受运行时配置、宏或二进制影响时记录多个候选与不确定来源。

为源码存在的分支建状态转移表：正常/边界输入、错误、超时、取消、重复提交、
并发回调、权限拒绝、无网络、会话过期、应用重启与恢复。不能用统一模板发明分支。
业务常量、阈值、取整、单位、时区、排序、编码和精度保留原值及行号。

## 3. 保留语言语义

Swift：Optional 与 nil、enum associated values、struct 值语义、class identity、
copy-on-write、throws/Result、defer、escaping closure、weak/unowned、actor/MainActor、
Sendable、structured/unstructured Task、Task cancellation 与 AsyncSequence。
记录语义对行为的影响，再由目标接口选择表示；不能把 enum 直接压成任意字符串。

Objective-C：nullability、nil messaging、selector/category、protocol optional method、
block capture、ARC/retain cycle、weak delegate、KVC/KVO、NSError、dispatch queue。
Objective-C++/C++ 记录 ABI、指针/句柄、资源所有权和回调线程；不能承诺直接语法转写。

## 4. 数据与生命周期

追 URLSession/Combine/async await 等执行上下文；取消后是否仍回调、旧请求是否覆盖新状态、
重试是否幂等、缓存是否先发、错误映射是否吞掉，均用真实实现作证。
Core Data/SwiftData/SQLite/文件/UserDefaults/Keychain 记录 schema、事务、迁移、
序列化、重启恢复和敏感数据边界。不要只给出存储 API 名。

## 5. 形成 AC 输入

每个可断言行为给稳定 F ID 的候选 AC、源符号、可观察结果与独立真值。
`判:unit/contract/route/ui/visual/device/static` 根据行为选择；静态函数存在不能证明副作用。
期望值来自 iOS 源码、源测试、真实 trace/device 或批准的 decision，不来自生成的 .ets。
纯逻辑、平台能力、视觉行为分别选择验证方法，不强制所有行为都是单元测试。

目标平台差异先列原行为、不可等价原因、候选替代、用户影响；交 decision-ledger。
未经批准的替代不能写成 source fact。复杂功能把状态机/协议细节放 addendum，
稳定 AC 留在主 feature spec，并给 `impl:` 指针。

## 6. 覆盖与交接

建立入口/分支/副作用 → source evidence → F-AC 映射。
逐个列未解释调用、不可读二进制、缺配置与未运行场景，不能靠 AC 数量宣布完备。
给 a2h-spec：数据流、源行为表、错误/取消模型、目标接缝约束、验收事实及未知项。
给 a2h-execute 的 source-notes 保留语言语义，避免 worker 再从零猜业务。
