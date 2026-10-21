---
name: ios-feature-analyzer
description: "iOS→HarmonyOS 迁移源分析第功能步：沿 Swift/ObjC 的事件、任务、委托、服务与持久化链提取状态转移、错误/取消、数据契约与独立验收真值，写功能事实与原生语义供 a2h-spec/plan 消费。当用户说“分析这个 iOS 项目的功能/业务逻辑”，或 a2h-spec/ios-source-analysis 组织功能源分析时使用；不要用于：UI 结构与导航（用 ios-ui-analyzer）、系统 API/权限/三方接缝清单（用 ios-api-inventory）、工程边界与编译单元（用 ios-project-inspector）。"
metadata:
  type: domain
  domain: migration
  tags:
  - ios
  - feature
  - source-analysis
  - source-evidence
---

> **调用关系**：本 skill 是 `ios-source-analysis` 组织的四类源分析之一（功能主责），结果由 `a2h-spec` 收口。若宿主支持 subagent，按 `ios-feature-analyzer` 角色名派发（`fork_turns:"none"`，任务书写清功能候选/入口/输出契约）；不派发时主会话顺序执行。遵守 Join 协议：完成唯一合法信号是 `agent_status=completed`；completed≠验收；谁派谁收。本 skill 只读源、写功能事实，**不派发下级 worker、不写目标代码、不决定未经授权的平台差异**。
>
> 路径约定：`$IOS_SRC` 从 `<target>/.migbot/config.json` 的 `ios` 读取；`<target>` = 目标根；`<runtime>` = 本包 runtime。产物落 `<target>/spec/ref/ios-feature-facts.md`（本 skill 单写）；原生语义由 a2h-spec 的 `spec-authoring` 落为 `spec/baseline/ios-semantics.json` feature 部分（机器校验）。本 skill 自有：`references/analysis-v2.md`、`scripts/run.py`。

# ios-feature-analyzer — iOS 功能行为与验收事实

## 0. 定位与纪律

- **前置**：上游已跑 `harness-init` + `source-index` + `facts`。先加载 `../ios-source-analysis/references/harness-v2.md`（机器产物/状态写者），外部证据按 `../ios-source-analysis/references/external-expertise.md` 执行，未连接工具保持 unknown/unavailable。
- **输入**：工程地图、页面事件、后台/扩展入口、服务调用、真实调用链与机器 feature 信号。**源不可读是阻塞**，不以旧报告补造行为。
- **输出**：`spec/ref/ios-feature-facts.md` + 每 feature 的源锚点 + 覆盖映射；随后由 a2h-spec 形成 `features/FNNN-*.md`、`ios-semantics.json` feature 部分与 `ios-coverage.json`（机器校验）。**本 skill 不直接手写 ios-semantics.json/ios-coverage.json（机器单写）**，只提供源行为事实与候选 AC。
- **唯一交互点**：无交互追问；歧义回源，不现场造分支。机械检查由 exit code 判定（0=PASS，非 0=FAIL）。
- **第一条可见输出必须是一行功能分析计划**（读信号 → 划分功能 → 读行为链 → 语言语义 → 数据/生命周期 → 形成 AC → 覆盖与交接）。
- **信号是待审线索**：先沿源码解释行为，再发行有具体期望的 AC；源测试仅作独立 oracle，不计为目标产品实现或测试通过。

## 1. 机器事实与信号读取

| # | 命令 | 产物 | exit code / 失败处置 |
|---|---|---|---|
| 1.1 | `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope feature` | `spec/ref/ios-feature-signals.json`（state/write/branch/task/persistence/service/language/ownership/lifecycle 九类信号 + obligations） | exit 0 有效；非 0 → 回上游重跑 `facts` 后重试，最多 2 轮；**禁手改信号** |
| 1.2 | （可选）`python <runtime>/scripts/a2h_ios.py mcp-query --project <target> --server <server.json> --request <query.json>` | `spec/ref/mcp-runs/MCP-ID/*` | 失败写 failure.json；真实服务缺工具保留 unavailable/unknown，**禁止换假服务** |
| 1.3 | 交付前诊断 `python <runtime>/scripts/a2h_ios.py source-check --harness --report-only --project <target>` | 只读诊断 | 非 0 → 按 §7 阶梯 | 

- 图中的 token 片段不是已绑定的跨函数调用；接收者与泛型/宏/动态派发需额外证据（协议实现、注入点、selector）。
- 每条机器 obligation 绑定真实 AC 与 source_review；一个 AC 可覆盖多个事实，但场景必须具体。

## 2. 划分功能

按用户目标与系统行为分 feature，**不按 class/file 一对一建功能**。每个 feature 记录所有 UI、深链、通知、后台、扩展入口与目标范围。共享鉴权、缓存、数据库、配置归 feature-base；领域行为仍属对应 F ID。**声明、调用、可达执行链三者分开**，发现方法名不能当成已证实功能。

## 3. 读出行为链

- 对每个入口读动作处理器及实际实现，追 protocol/conformance、delegate、closure、extension/category、默认实现、注入实例、动态 selector。**同名方法、protocol 继续追实现与注入点**。
- 记录触发条件、状态前值、输入校验、数据变换、调用顺序、副作用与可观察结果。当调用目标受运行时配置、宏或二进制影响时记录多个候选与不确定来源。
- 为源码存在的分支建状态转移表：正常/边界输入、错误、超时、取消、重复提交、并发回调、权限拒绝、无网络、会话过期、应用重启与恢复。**不能用统一模板发明分支**。
- 每个行为填 `input / precondition / processing / state transition / side effects / observable` 六段；每次写入发生的时点都要记录，不能只摘最终赋值。
- **异步取消三时点铁律**：点击后标记取消、请求停止、完成回调移除（或实际立即移除）分别记录；还要读出回调是否仍可能成功、旧回调是否仍写状态、重复取消如何处理。**不能把“cancel() 返回”当“操作完成”**。
- **清理完成边界铁律**：即时效果（UI 列表清空/内存释放）与完成事件（磁盘删除结束/失败/重启后重载）分开；公开 `clear()` 返回“已提交”还是“已完成”从实现确认。
- 业务常量、阈值、取整、单位、时区、排序、编码、精度保留原值及行号（与 `literal-ledger.json` 一致）。

逐动作用下表留痕（分析工作记录，不是新增控制账本；每行能回证据）：

| 时点 | 触发/回调 | 内存与 UI 变化 | 服务/磁盘变化 | 对外可观察结果 | 源证据 |
|---|---|---|---|---|---|
| 例：点击 | 按钮 handler | 置 busy/禁用 | 发起请求 | — | 源文件:行 |

- 输入、状态、线程/actor、句柄所有权必须能回到证据；没有实际运行时，"可观察结果"描述源规则并标 `runtime=not_run`。
- 对同步返回、异步完成、错误/取消、再次触发分别填表；**只展开源码存在的分支**，无法确定的顺序写 unknown、原因与补证位置。

## 4. 保留语言语义

- Swift：Optional 与 nil、enum associated values、struct 值语义、class identity、copy-on-write、throws/Result、defer、escaping closure、weak/unowned、actor/MainActor、Sendable、structured/unstructured Task、Task cancellation、AsyncSequence。记录语义对行为的影响，再由目标接口选择表示；**不能把 enum 直接压成任意字符串**。
- Objective-C：nullability、nil messaging、selector/category、protocol optional method、block capture、ARC/retain cycle、weak delegate、KVC/KVO、NSError、dispatch queue。
- Objective-C++/C++：ABI、指针/句柄、资源所有权、回调线程；**不能承诺直接语法转写**。

## 5. 数据与生命周期

- 追 URLSession/Combine/async await 等执行上下文：**取消后是否仍回调、旧请求是否覆盖新状态、重试是否幂等、缓存是否先发、错误映射是否吞掉**，均用真实实现作证。
- Core Data/SwiftData/SQLite/文件/UserDefaults/Keychain：记录 key/schema/事务/迁移/序列化/写入/重读/业务读取/恢复失败与敏感数据边界。**不要只给存储 API 名**；状态区分值复制与对象共享，不能把普通 var 直接翻成全局 store。
- 网络记录服务参数、鉴权、编码、响应和错误到用户反馈。

## 6. 形成 AC 输入

- 每个可断言行为给稳定 F ID 的候选 AC、源符号、可观察结果与独立真值。`判:unit/contract/route/ui/visual/device/static` 根据行为选择；**静态函数存在不能证明副作用**。
- 期望值来自 iOS 源码、源测试、真实 trace/device 或已批准 decision，**不来自生成的 .ets**。
- 纯逻辑、平台能力、视觉行为分别选择验证方法，不强制所有行为都是单元测试。独立真值：unit 用源规则与边界样本、contract 用真实协议样本、ui/device 用真实动作与观察。
- 目标平台差异先列原行为、不可等价原因、候选替代、用户影响，交 decision-ledger。**未经批准的替代不能写成 source fact**。复杂功能把状态机/协议细节放 addendum，稳定 AC 留主 feature spec 并给 `impl:` 指针。

## 7. 硬约束

- **禁止**手改 `facts-view`/`facts` 产出的机器信号、`ios-facts.json`、`ios-obligations.json`（PROCESS_VIOLATION）。
- **禁止**用统一模板发明分支；状态转移、错误/取消、持久化恢复只展开源码存在的分支。
- **禁止**把生成的目标实现结果反推为期望；expected 不来自 .ets。
- **不得**以 AC 数量、文件数量或扫描数量宣称完备；逐项列未解释调用、不可读二进制、缺配置、未运行场景。
- **不得**用“已处理/N/A”清空 unknown 维度；unknown 必须带原因与补证步骤。
- **不越权**：UI 结构归 ios-ui-analyzer；协议/SDK 清单归 ios-api-inventory；本 skill 只解释完整可观察行为与验收依据。

## 8. 读取时机（references）

| 触发时机 | 必读文件 |
|---|---|
| 执行前；机器产物/状态写者存疑 | `../ios-source-analysis/references/harness-v2.md` |
| 源事实字段、语言/框架语义 | `../ios-source-analysis/references/native-facts.md` + `source-semantics.md` |
| 外部资料/MCP 证据 | `../ios-source-analysis/references/external-expertise.md` |
| 逐动作执行与取消/清理正反例 | `references/analysis-v2.md` |
| 共享/异步/取消动作合同 | `../a2h-spec/references/action-contracts.md` |
| 转 baseline 与 AC 交付 | `../a2h-spec/references/spec-delivery-contract.md` |

## 9. 交接

- 前置门闸：每 feature 的 `state_transitions/concurrency/lifetime/persistence/platform_capabilities` 及语言维度经 `source-check --harness`（a2h-spec 执行）无新增 finding。
- 移交：数据流、源行为表（含状态转移表）、错误/取消模型、目标接缝约束、候选 AC 与独立真值、unknown 清单、待决策项、source-notes（保留语言语义，避免 worker 再从零猜业务）。
- 下一步提示：交 `a2h-spec`（Phase C 生成 `features/FNNN-*.md` 与决策账本）；平台差异交 decision-ledger；对应页面事件与 UI 分析去重引用同一动作 ID。