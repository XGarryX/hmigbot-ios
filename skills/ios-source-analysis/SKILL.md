---
name: ios-source-analysis
description: "iOS→HarmonyOS 迁移源分析的统一入口与编排器：组织工程（ios-project-inspector）、UI（ios-ui-analyzer）、功能（ios-feature-analyzer）、API（ios-api-inventory）四类分析，把 Swift/Objective-C/SwiftUI/UIKit/Interface Builder 的真实证据并入 ios-facts/ios-semantics/ios-coverage，经 source-check 门禁收口后交给 a2h-spec。当用户说“分析这个 iOS 项目”“理解这个 iOS 源码”“整理 iOS 源事实”或 a2h-spec 的源分析阶段时使用。不是 iOS 应用生成器——不要用于：生成审查 baseline 后的计划（用 a2h-plan）、写鸿蒙生产代码（用 a2h-execute）、资源转换（用 ios-resources-convert）。"
metadata:
  type: orchestrator
  domain: migration
  tags:
  - ios
  - source-analysis
  - evidence
  - orchestration
---

> **调用关系**：本 skill 是四类源分析的**统一入口 + 编排器**，自己不解析源码成业务节点——四类分析由四个 skill 承担（工程=ios-project-inspector、UI=ios-ui-analyzer、功能=ios-feature-analyzer、API=ios-api-inventory），本 skill 只做：①确定性机器事实基线 ②按类别派发(或顺序执行) ③合并证据与归属核对 ④门禁收口。若宿主支持 subagent，可把四类分析作为子代理派发；此时一律 `fork_turns:"none"`（任务书自足，写清源锚点、scope 与输出契约），并遵守 **Join 协议（收口五条款）**：
> ① **循环 wait**：完成的唯一合法信号是 `agent_status=completed`，绝不是产物文件存在（文件会中途落盘，读半截=事故）；② **死句柄与验收**：连续 3 次超时后 `list` 核对，completed≠验收通过，join 点跑本 skill 门禁验产物；③ **收口锚点**：最终报告前必须收口全部句柄；④ **放行≠遗弃**：非阻塞放行只推迟收口，不豁免；⑤ **fire-and-forget** 仅正文显式声明的派发免收口。
> **派发纪律**：`task_name` 唯一（带 scope/id 后缀）；派发前写清预期产物清单给 join 门对账；**谁派谁收**（sub-agent 不能嵌套外派后退出）；契约产物必须出自承担任务的子代理，禁止派发方代写占位产物让 gate 转绿。
>
> 路径约定：`$IOS_SRC` 从 `<target>/.migbot/config.json` 的 `ios` 字段读取（缺配置文件 → 先执行 a2h-init）；`<runtime>` = 本包 runtime（`scripts/a2h_ios.py` 所在根）。产物一律落 `<target>/spec/`（baseline/ref/reports/.a2h），**禁落会话临时目录**。机器信号与账本由随包命令单写，主会话/作者禁手改。

# ios-source-analysis — iOS 源仓理解与证据收口（统一入口）

## 0. 定位与纪律

- **前置**：`<target>/.migbot/config.json` 存在且 `source_platform=ios`；`harness-init` 已完成（缺 → 提示先由 a2h-spec 跑 §1 基线启动，不代跑）。读写机器事实、审阅外部资料都随本 skill 的命令执行。**源不可读是阻塞**，不以文件夹名或文件数量补造行为。
- **输入**：iOS 源码（Xcode 工程 / SwiftPM / 混合 Swift+ObjC + SwiftUI/UIKit/IB）+ 用户预知（既有决策、平台侧分工）+ `<target>`。源工程与目标工程必须分离。
- **输出**：机器事实 `spec/baseline/{ios-source-index,ios-facts,ios-obligations}.json`、语义 `spec/baseline/ios-semantics.json`、覆盖 `spec/baseline/ios-coverage.json`、归属 `spec/ref/ios-source-disposition.json`、四个分析 skill 的 `spec/ref/*.md` 事实（ios-project.md / ios-ui-facts.md / ios-feature-facts.md / api-inventory）。**契约定稿与计划 IR 归 a2h-plan**，本 skill 不请求审批。
- **唯一交互点**：无。机械检查由 exit code 判定（0=PASS，非 0=FAIL）；不经猜测填表。
- **第一条可见输出必须是一行阶段计划**（机器事实基线 → 工程 → UI → 功能 → API → 合并归属 → 门禁），然后才执行 §1。

### 无人值守处置阶梯（每道门禁 FAIL 一律套用）

> FAIL → 按命令 `retry_hint`/错误原文派修复并重跑同一命令，**最多 2 轮**；2 轮仍不过或确定模型修不了 → **记欠账放行**（账记全：修过几轮、每轮失败原因、判“修不了”的依据）；要拍板的模型自决并留痕；任何分支不得停机呈报人工。设备/账号类门可欠账；静态门（facts/语义/溯源）即便开了 `stage_debt` 也照修到 PASS。

## 1. 机器事实基线（确定性入口，先跑）

| # | 命令 | 产物 | exit / 处置 |
|---|---|---|---|
| 1.1 | `python <runtime>/scripts/a2h_ios.py source-index --project <target>`（首轮或源变化后） | `spec/baseline/ios-source-index.json` | 非 0 = 源在索引期变化或索引已存在，按提示处置，禁删旧索引硬建 |
| 1.2 | `python <runtime>/scripts/a2h_ios.py facts --project <target>` | `spec/baseline/ios-facts.json` + `ios-obligations.json` | 非 0 读错误修配置重跑，最多 2 轮；缺处标 unknown 不阻塞视图 |
| 1.3 | `python <runtime>/scripts/a2h_ios.py product-literals --project <target> [--output <path>]`（按需） | 业务常量/字面量账本（缺省落点以命令返回为准） | 非 0 记 warning，不阻断；业务常量/字面量保留实际值 |
| 1.4 | `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope {project,ui,feature,api}`（四类各跑一次） | 四类机器信号（project→`spec/ref/ios-project-signals.json`，api→`spec/ref/ios-api-signals.json`，ui→`ios-ui-signals.json`，feature→`ios-feature-signals.json`） | 任一非 0 → 对应分析 skill 补事实后重跑 |
| 1.5 | `python <runtime>/scripts/a2h_ios.py expertise-plan --project <target>` | `spec/ref/ios-expertise-plan.json`（按清单定本轮必读上游资料） | 缺 vendor 快照 → 记 `apple_skills.status=not_loaded` 继续 |
| 1.6 | `python <runtime>/scripts/a2h_ios.py facts --project <target> --providers <target>/spec/ref/provider-plan.json`（按需，配置格式见 `assets/provider-plan.json`） | 指定 SwiftSyntax/Clang/构建设置/IB/资源 provider 的证据 | provider 只提升自身证据层级，不自动消除业务未知；工具失败保留 failure.json |

### 单写者分区（违者 PROCESS_VIOLATION）

| 文件 | 唯一写者 | 内容 |
|---|---|---|
| `spec/baseline/ios-source-index.json` | source-index 命令 | 文件快照/索引 |
| `spec/baseline/ios-facts.json` + `ios-obligations.json` | facts 命令 | 机器事实/义务 |
| `spec/ref/ios-*-signals.json` | facts-view 命令 | 四类机器信号 |
| `spec/baseline/ios-semantics.json` + `ios-coverage.json` | 各分析 skill 作者（唯一 owner） | 语义/覆盖 |
| `spec/.a2h/open-findings.json` | 产生该 finding 的检查 | 未关闭发现 |

- **工具与来源分级（红线）**：本包四类分析 skill 是 HMigBot-iOS 自编分析规程；Apple 官方文档用于校核语义。SwiftSyntax 是官方语法库、本包 provider 是自编适配器（不是 Apple skill）；**Clang AST 与 SourceKit-LSP 的输出不能冒充运行行为**。没有连接时走文件分析，状态记 `unavailable`，**不能伪造官方执行**。详见 `references/apple-capabilities.md`。
- **harness v2 协议**：本 skill 先加载 `references/harness-v2.md`（决定输入、机器门禁与状态写者）。事实/义务/计划/回执由随包命令检查；本正文的分析责任继续适用，v2 协议决定机器产物与状态，旧版 source-check 不能代替新版门禁。

## 2. 四类分析派发（本 skill 只编排不解析）

| 技能 | 事实主责 | 不越权决定 |
|---|---|---|
| ios-project-inspector | 编译单元、语言、依赖、目标入口与条件 | 目标架构和替代 SDK |
| ios-ui-analyzer | SwiftUI/UIKit/IB 结构、状态、布局、交互、导航 | 业务计算规则 |
| ios-feature-analyzer | 行为链、数据变换、错误、生命周期与验收依据 | 未经授权的平台差异 |
| ios-api-inventory | 外部服务、系统能力、协议、权限、三方依赖 | 仅凭同名 API 宣告等价 |

1. **工程**：识别 workspace、project、targets、schemes、SwiftPM、本地包、Pods、二进制 framework、构建条件与 app/extension 边界。没有 Xcode 时静态读文件，**不能声称已解析有效 build settings**；构建成员标 `static-inferred`，绝不改标 compiler binding。**不以 Swift 文件扩展名推定 SwiftUI，不把 Objective-C 当另一种 UI 框架**。
2. **UI**：按实际框架提取视图组合、状态/事件与导航。无可视主界面的 target 也记录入口与平台行为，不能凭没有页面宣告无需迁移。
3. **功能**：沿用户动作、生命周期与后台入口追至可观察效果，覆盖成功、错误、取消、重入、权限拒绝、持久化恢复等源码存在的分支。
4. **API**：补全服务、存储、系统框架、权限与三方接缝，与 UI/功能事实去重；平台能力无法等价时交 decision-ledger。

## 3. 源语义（iOS 语义，逐 framework 建模）

- 先读 `references/source-semantics.md` 与 `references/native-facts.md`。语言与 UI 框架分开建模：Swift/ObjC/ObjC++/C/C++ 是语言；SwiftUI/UIKit/IB/引擎承载是界面形态。首次快照（Index）只是范围与线索。
- 逐 page/feature 维护 `spec/baseline/ios-semantics.json` v2：`known` 必须是对象 value + 当前机器 `fact_ids` + 落于事实片段内的证据；`unknown` 必须带原因并阻断受影响实现；`not_applicable` 只有完整调用链审阅后才可记录具体理由。**不用“已处理”“无特殊情况”覆盖全部维度**。
- SwiftUI 的 body/modifier/state/binding/identity/environment/task/导航、UIKit 的 controller/view/constraint/outlet/action/delegate/生命周期分别保留；**IB 与程序化改动共同决定运行布局**。宏/二进制/动态配置无法确认时说明所需额外证据，不伪造解析结果。
- Preview/mock 数据与实际入口分开；**没有 iPhone 录制不生成运行观察结论**（runtime=not_run 合法）。已有截图只能证明该场景下的显示，不能推导全部导航/状态。

## 4. 外部资料与 MCP 证据（可选项）

1. 按 §1.5 清单实际读取上游资料，沿源实现形成观察：`python <runtime>/scripts/a2h_ios.py expertise-review --project <target> --input <review.json>`。resources 摘要必须与清单一致；空壳“已处理”不代替分析。
2. 需要符号证据时 `python <runtime>/scripts/a2h_ios.py mcp-query --project <target> --server <server.json> --request <query.json>`（示例见 `assets/mcp-server.example.json` / `assets/mcp-query.example.json`）。只有固定源读工具白名单可调用；失败/超时写 failure.json，绝不写成功索引。返回标 `resolution=tool_response`、`build_context=unverified`，不自动升级为 compiler_binding/runtime。
3. 记录证据工具来源、版本、实际是否执行：`spec/ref/ios-analysis-provenance.json`。源码、Apple 文档、运行 trace 三源分列；只有实际加载才标 `used`，未接入标 `unavailable`/`not_loaded`，**不把自编规程冠为官方**。

## 5. 合并、归属与恢复

1. 合并四类证据，核对每个业务源文件归属 page/feature；不在迁移范围内的文件写 `spec/ref/ios-source-disposition.json`，逐文件说明依赖、测试或不适用理由。**不用目录白名单把未理解业务一笔略过**。
2. 每个 page/feature 有一个事实作者；可按 target/module 分工，但派发前写清文件所有权。身份信号（`.id`/ForEach）判据候选为 unit/contract/ui，缺失/歧义保守处理，**不根据目录或 import 猜语义**。
3. 源码变化时按快照差异重读受影响调用链，再更新相关事实；保留旧版本与变更原因。**只刷新 hash 不能关闭过期 source finding**；路径歧义必须回真实目录消歧。复跑产生该 finding 的检查才能关闭。
4. 已审 Spec 变更与旧在途死锁时：先停止 worker，固定 review v1，仅用 harness-v2 的 `recover-blocked` 显式失败终止，再正常 replan；不得回退 Spec、手写三账本或把 blocked 伪装 PASS。

## 6. 门禁与交接

- 门禁：`python <runtime>/scripts/a2h_ios.py source-check --harness --project <target>` exit 0 才交接（含 external-expertise 门禁与溯源检查；`--report-only` 只诊断不更新 findings）。FAIL 按 §0 处置阶梯最多修 2 轮；结构 PASS 不能代替源语义审阅。
- 独立复核：提交前按 `../a2h-spec/references/spec-content-review.md` 完成 finding→原 owner 返修→独立复查。共享事实单一 owner，用 ID 引用，避免重复登记。
- 移交产物：`spec/baseline/{ios-source-index,ios-facts,ios-obligations,ios-semantics,ios-coverage}.json`、`spec/ref/{ios-project,ios-ui-facts,ios-feature-facts,ios-api-facts,ios-source-disposition}` 相关文件、未关闭 findings。随后交 a2h-spec（同会话可直接续跑 Phase B/Phase C）。
- 本 skill 无独立 stage 水位（无 mark-stage）；`source-check --harness` 绿即源分析阶段收口。

## 7. 读取时机（references）

| 触发时机 | 必读文件 |
|---|---|
| 执行前；机器产物/状态写者存疑 | references/harness-v2.md |
| 源事实字段、identity/state/维度规则 | references/native-facts.md |
| SwiftUI/UIKit/ObjC/桥接语义读法 | references/source-semantics.md |
| expertise-plan/review、MCP 查询边界 | references/external-expertise.md + assets/mcp-{server,query}.example.json |
| Apple skill/MCP/宿主能力三态与 provenance | references/apple-capabilities.md |
| 运行指定 provider（SwiftSyntax/Clang/IB/资源） | assets/provider-plan.json |
| Package.swift 未求值 / 产品成员证据 | references/source-input-evidence.md |
| 产物 profile/格式/作者/消费者 | ../a2h-spec/references/artifact-contracts.md |
| 独立跨文档复核 | ../a2h-spec/references/spec-content-review.md |
| 异步/取消动作契约 | ../a2h-spec/references/action-contracts.md |