---
name: ios-source-analysis
description: "原生 iOS 仓理解的统一入口：组织工程、UI、功能、API 四类分析，把 Swift、Objective-C、SwiftUI、UIKit、Interface Builder 的真实证据交给 a2h-spec。不是 iOS 应用生成器。"
---

## 0.7.0 外部专业资料与工具证据

先读 [外部 skill/MCP 接入规程](references/external-expertise.md)。facts 后运行 expertise-plan，按本轮主题清单读取实际上游资料，再用 expertise-review 提交源观察。需要符号证据时用 mcp-query；未连接工具保持 unknown/unavailable。结果继续进入现有 semantics/coverage/AC，不采用上游重构建议改写源行为。

## 0.6.0 可执行协议

本技能先加载 [Harness v2 协议](references/harness-v2.md)。事实、义务、计划和回执由随包脚本检查；本正文的分析责任继续适用，v2 协议决定机器产物和状态，旧版 source-check 不能代替新版门禁。



# iOS 源仓理解与证据收口

## 边界与输入

本技能只读源工程并写迁移事实。`a2h-spec` 负责形成可审查 baseline，
`a2h-plan` 负责目标任务，`a2h-execute` 才写鸿蒙生产代码。输入是源根、
目标根、范围及已有决策；以 `.migbot/config.json` 的 `ios` 和 `harmonyos` 为准。
源工程与目标工程必须分离。不能把工程目录名、文件数量或某个编译成功视为功能理解。

先读 [源语义规程](references/source-semantics.md) 与
[事实记录契约](references/native-facts.md)。本轮涉及哪些框架，就读取对应分析技能，
不以 Swift 文件扩展名推定 SwiftUI，也不把 Objective-C 当成另一种 UI 框架。

## 执行顺序

1. 检查已有 `spec/ref/ios-project.md`、源索引、未关闭 findings 和源版本。
   首轮用随包 `scripts/a2h_ios.py source-index --project <目标根>` 建立文件快照。
   索引只是范围与线索；对每个业务结论继续读实际函数、调用点、配置与资源。
2. 调用 `ios-project-inspector`，识别 workspace、project、targets、schemes、
   SwiftPM、本地包、Pods、二进制 framework、构建条件和 app/extension 边界。
   在没有 Xcode 的机器上静态读文件；不能声称已解析有效 build settings。
   遇 `Package.swift` 未求值或需区分产品与测试成员时，按
   [清单求值与产品成员证据](references/source-input-evidence.md) 采集/推导后重做 facts。
3. 调用 `ios-ui-analyzer`，按实际框架分别提取视图组合、状态/事件与导航。
   无可视主界面的 target 也要记录入口与平台行为，不能凭没有页面宣告无需迁移。
4. 调用 `ios-feature-analyzer`，沿用户动作、生命周期和后台入口追至可观察效果，
   覆盖成功、错误、取消、重入、权限拒绝、持久化恢复等源码存在的分支。
5. 调用 `ios-api-inventory`，补全服务、存储、系统框架、权限和三方接缝，
   与 UI/功能事实去重；平台能力无法等价时交 decision-ledger。
6. 合并四类证据，核对每个业务源文件归属 page/feature；不在迁移范围内的文件
   写 `ios-source-disposition.json`，逐文件说明依赖、测试或不适用理由。
   不用目录白名单把未理解业务一笔略过。
7. 将结果交 `a2h-spec`。`ios-semantics.json` 中每个声明都要回指文件和行，
   `unknown` 继续保留；已有截图只能证明该场景下的显示，不能推导全部导航/状态。

## 分析分工

| 技能 | 事实主责 | 不越权决定 |
|---|---|---|
| ios-project-inspector | 编译单元、语言、依赖、目标入口与条件 | 目标架构和替代 SDK |
| ios-ui-analyzer | SwiftUI/UIKit/IB 结构、状态、布局、交互、导航 | 业务计算规则 |
| ios-feature-analyzer | 行为链、数据变换、错误、生命周期与验收依据 | 未经授权的平台差异 |
| ios-api-inventory | 外部服务、系统能力、协议、权限、三方依赖 | 仅凭同名 API 宣告等价 |

## 工具与来源分级

本包上述技能是 HMigBot-iOS 自编分析规程。Apple 官方文档用于校核语义；
SwiftSyntax 是 Swift 官方语法库，本包 provider 是自编适配器，不是 Apple skill。
Clang AST 与 SourceKit-LSP 的输出也不能冒充运行行为。

如环境提供 Xcode MCP，先确认实际可调用工具与打开的工程，再请求符号/构建诊断。
如用户已从 Xcode 导出官方 skills，先核对导出来源、版本、适用框架，并读取其原文；
只有实际加载才在 `spec/ref/ios-analysis-provenance.json` 标记 used。
没有连接时走文件分析，状态记 unavailable，不能伪造官方执行。
详见 [官方能力接入](references/apple-capabilities.md)。

## 收口与恢复

每个 page/feature 有一个事实作者。可按 target/module 分工，但派发前写清文件所有权；
宿主不支持分工时按同规程顺序执行。结束前回读交付文件、核对证据和范围，
文件存在不代表分析已完成；不得用占位 Markdown 填平缺项。

新生成产物先按 [Spec产物目录](../a2h-spec/references/artifact-contracts.md) 确认profile、格式、作者与消费者。UI/功能/API作者分别加载自己的analysis-v2执行步骤和正反例；异步/取消/分层清理的即时、完成与最终效果由唯一作者定义，各方精确引用。提交前按 [独立跨文档复核](../a2h-spec/references/spec-content-review.md) 完成finding→原owner返修→独立复查，结构PASS不能代替该源语义审阅。

源码变化时按快照差异重读受影响调用链，再更新相关事实；保留旧版本和变更原因。
只刷新 hash 不能关闭过期 source finding。路径歧义必须回到真实目录消歧。
最终返回已分析范围、语言/框架、证据来源、未知项和待决策项。

已审Spec变更与旧在途形成死锁时，先停止worker、固定review v1，仅用[可执行协议](references/harness-v2.md)的`recover-blocked`显式失败终止，再正常replan；不得回退Spec、手写三账本或把blocked伪装PASS。普通冻结检查保持。
