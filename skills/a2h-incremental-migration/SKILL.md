---
name: a2h-incremental-migration
description: "iOS→HarmonyOS 增量同步：对比 iOS 当前源码与既有 HMigBot baseline 的用户可见行为变化，保留原生语义并经 spec/plan/execute/verify 增量同步。触发语“增量迁移 / 同步 iOS 新功能 / 再检查有没有要迁移的 / 对比一下两边 / 把 XX 功能搬过来”。核心方法论是“行为同步”而非“源码差集”——比对用户可感知的行为，不比类名/id/字面量。本 skill 只负责“识别差异并交用户确认”；spec 生成 + 计划 + 实施 + 验收全流程委托给 `arkts-spec-evolver`（create+plan+execute+verify，自带 Gate 1/Gate 2 两道审批），跨源索引/spec 升级用本包 `source-refresh`/`spec-upgrade`/`import-legacy`。不要用于：初始 baseline 生成（用 a2h-spec）、排期与计划 IR（用 a2h-plan）、执行迁移代码（用 a2h-execute、arkts-spec-evolver）。适用 Swift/ObjC/SwiftUI/UIKit/Xcode 源工程。"
metadata:
  type: pipeline
  domain: migration
  tags:
  - ios
  - pipeline
  - migration
  - incremental
  layer: pipeline
---

> **派发约定**：本 skill 主会话执行，**不直接 spawn 迁移 worker**。差异识别的四类源分析由主会话按 `ios-source-analysis` 技能组织（工程=ios-project-inspector、UI=ios-ui-analyzer、功能=ios-feature-analyzer、API=ios-api-inventory）；若宿主支持 subagent，可把这四类分析按 `a2h-ios-analyzer` 角色派发，此时一律 `fork_turns:"none"`（任务书自足：写清 iOS 源锚点、比较范围、输出契约）。spec/plan/execute/verify 委托 `arkts-spec-evolver`，不在本 skill 内展开工人。
>
> **Join 协议（收口五条款）**：① 循环 wait：完成的唯一合法信号是 `agent_status=completed`，绝不是产物文件存在/条数（文件会中途落盘，读半截=事故）；② 死句柄与验收：3 次超时后 `list` 核对，completed≠验收通过，join 点跑门禁验产物，FAIL 视同未取回按断点重派；③ 收口锚点：最终报告前必须收口全部句柄；④ 放行≠遗弃（“到点即收/降级继续”只推迟收口，不豁免收口义务）；⑤ fire-and-forget 仅正文显式声明“结果丢弃/不 gate”的派发免收口。
>
> **派发纪律**：`task_name` 唯一（带 anchor-id/round-N 后缀）；派发前把预期产物清单写给 join gate 对账（契约只认派发方、不认子代理自报）；**谁派谁收**——sub-agent 内部需要再分片时禁止嵌套外派后自行退出，分片清单回报主会话代派；契约产物必须出自承担任务的子代理，重派上限后仍产不出 → 如实报缺停在未完成态，禁止派发方代写占位产物让 gate 转绿。
>
> **路径约定**：`$IOS_SRC` 读 `<target>/.migbot/config.json` 的 `ios` 字段（缺配置文件 → 先 a2h-init）；`<runtime>` = 本包 runtime（`scripts/a2h_ios.py` 所在根）。产物一律落 `<target>/spec/`（baseline/ref/reports/.a2h），**禁落会话临时目录**。本 skill 无自有 `references/`/`templates/`/`scripts/` 目录，细则跨技能引用（见 §读取时机表）。

# a2h-incremental-migration — iOS 行为增量同步

## 0. 定位与纪律

- **前置**：已完成初始迁移——`<target>/.migbot/config.json` 存在且 `source_platform=ios`，`spec/baseline/`（ui-manifest / feature-index / feature-base / features/）就绪，`spec/baseline/ios-source-index.json` 已有旧源索引。缺旧证据时**先显式说明比较范围**（哪些入口/页面/功能有旧基线可对照、哪些只能按当前源码单边重建），不假装有对称旧快照。
- **输入**：iOS 当前源码（可给 git 信息 / 仅两份代码 / 功能锚点，三种任一）+ 既有 baseline（ui/feature/page 规格）、旧 decision 账本、旧 source-index 与目标版本。
- **输出**：本轮差异清单 + 逐条机械核查轨迹（`spec/incremental-migration-{date}/exec-log.md`）+ 运行时回归 log（`spec/incremental-migration-{date}/runtime-regression-log.md`）+ 经 evolver 落盘的增量 spec/plan/代码 + 完成摘要。派生报告 `spec/migration-report.md` 由命令单写。
- **唯一交互点 = §S2 用户对齐关卡**（差异清单确认）；其余禁交互追问，机械检查由 exit code 判定（0=PASS，1=FAIL，2=用法错）。
- **第一条可见输出必须是一行阶段计划**（固定快照 → 决策门 → 影响分析 → 用户对齐 → spec 更新 → 源索引更新 → 门禁 → 委托 evolver/a2h-plan），然后才执行 §1。
- **硬约束（黑体）**：**固定旧源快照、当前源、旧 baseline/decision、目标版本四样再下结论**；**文件 diff 只用于定位**——改名/移动不自动等于新功能，未改文件也可能受依赖变化影响；**源索引更新必须在影响分析与规格更新之后，禁止只刷新 hash 消除 stale finding**；**plan 保持只读调度，执行状态仍进原 brief/findings**；**未执行设备验证保持 not_run**。

## 1. 定位与方法论

### 1.1 核心原则：行为同步 ≠ 源码差集（务必理解）

iOS→HarmonyOS 跨越两种 UI 范式：命令式（UIViewController/UIView/constraint/outlet/action/delegate/生命周期 + Storyboard/XIB）vs 声明式 ArkTS。**同一用户感知功能，在两端产生完全不同的源码符号**。**不得**比对两端类名 / id / 字面量的集合差集作为 UI/业务层主扫描——只可用于资源层（图片/string key/endpoint 等 name-as-identity 场景）。

**正确做法**：① 从 iOS 指定分支/commit 的 **final state** 源码阅读提取“用户可感知的行为变化”（入口、UI 状态、Binding/生命周期、业务规则、API/权限、资源与持久化），commit history 仅作辅助校准证据；② 对每条行为变化在 ArkTS 代码里找**等价路径**（onClick → store → service → UI 渲染），不看类名；③ 只把“ArkTS 无等价行为路径”的条目放入差异清单。

> **已覆盖基线**：判断「ArkTS 有无等价行为路径」时，把 baseline 的 `spec/baseline/source-coverage-report.md`（多子仓另含 `module-dep-graph.json`/`cross-module-contracts.md`）作为「已认领能力」参照——已被某 baseline feature 锚定的源码行为视为「已覆盖」，不再列入差异清单，避免把上轮已迁移的行为当成新变更重复同步。

### 1.2 Final state 是行为同步的真目标（所有模式共享）

用户感知到的行为 = **当前 final state 的运行时行为**。主信源 = 用户指定分支的 final state（HEAD 或某 commit 快照），是事实底线；辅助信源 = commit history（WHY + 演进路径 + 边界 case 暗示）。两者矛盾时**一律以 final state 为准**——commit 链中被后续 commit 推翻的中间态在 final state 上不存在 = 不该同步。

### 1.3 三模块流程 + Evolver 委托

本 skill **只做差异识别和用户对齐**；spec / plan / execute / verify 全部委托 `arkts-spec-evolver`（`../arkts-spec-evolver/SKILL.md`，`create+plan+execute+verify` 模式）。三道审批分工：§S2（本 skill）=“差异清单对不对”；Gate 1（evolver）=“spec 写得对不对”；Gate 2（evolver）=“计划合理吗”。

## 2. 硬性决策门（每次启动必跑，只问三个问题）

```
问题 A：iOS 端能拿到 commit 记录吗（本地 git 或 GitHub）？
  ├─ 是 → §M1 Diff 模式（final-state 优先 + commit 辅助）
  └─ 否 → 问题 B
问题 B：用户给了具体功能锚点吗（功能名 / 类名 / id / "只迁移 XX"）？
  ├─ 是 → §M3 Targeted 模式
  └─ 否 → 问题 C
问题 C：用户只提供了两份代码，让我自己找差异？
  ├─ 是 → §M2 Source-compare 模式
  └─ 否 → 主动澄清：Diff / Source-compare / Targeted 哪种？
```

**输出要求**：把命中结论显式写出一行（例：`决策：用户说『再检查下还有什么要迁移』→ 无 commit 无锚点 → §M2 Source-compare 模式`）。没有这句话 = 跳过决策门 = skill 失败。

- **§M1 Diff**（有 git 历史）：探测 final state + 辅助 commit 范围 → 读 diff（辅助证据）→ 提取行为轨迹（final state 主路径，commit 校准，冲突仲裁）→ 查 ArkTS 等价路径 → 分桶 🔴/🟠/✅ → 资源层差集。**绝对原则**：commit history 不能推翻 final state 的代码事实。
- **§M2 Source-compare**（只有两份代码）：建立页面配对（iOS ViewController/SwiftUI View ↔ ArkTS 页，用架构映射）→ UI+行为层并排源码阅读（主扫描，每条差异必带证据字段）→ 数据/逻辑层对比输入/输出/副作用 → 资源层符号差集（**本模式唯一允许的符号扫描**）。**绝对原则**：UI/业务层禁止符号差集；每条 🔴 缺证据字段自动降级 `confidence: low`。
- **§M3 Targeted**（用户指定功能锚点）：grep 定位 → A_CLOSURE（iOS 端命中文件+依赖闭包）→ H_TARGETS（ArkTS 端目标改动文件清单 = scope lock）→ scope-lock 实施 → 改动审计（`git diff --name-only` 对 H_TARGETS 清单）。**A_CLOSURE 空 → 硬闸门三选一**：(a) 换关键词重试（≤3 轮）(b) iOS 无实现 → 委托 evolver 走 V2 新功能（`android_behavior_trace=null` 等价：`ios_behavior_trace=null`）(c) 取消同步。**绝对不得**凭描述脑补 iOS 实现。

## 2.5 硬性禁令（MUST NOT）

1. ❌ **不得**仅凭对话记忆判断“没有要迁移的”——只有**本轮**提取结果才是证据。
2. ❌ **不得**把“BUILD SUCCESSFUL”当作功能对齐证据。iOS 新增功能若 ArkTS 没实现，**不会触发编译错误**。
3. ❌ **不得**跳过 §2 决策门直接输出“已完成”。
4. ❌ **不得**用源码符号差集（类名/id/字面量）作为 UI/业务层主扫描——只能用于资源层。
5. ❌ **不得**在 §S2 用户对齐前直接动代码。
6. ❌ **不得**信任子代理返回的“Assumed / Estimated / likely”等估算词。
7. ❌ **不得**仅凭“用 iOS 符号名 grep ArkTS 源码返回空”作为某条功能进 🔴 的唯一证据。必须同时附带“目标页面已完整阅读”+“≥3 个同义关键词（中文文案/动词同义词/图标或资源 id）全部空命中”才可判 🔴。
8. ❌ **不得**把 override 理解为“跳过一切验证”——override 仅免对话式 yes/no，机械核查（证据字段 + 三源校验 + Pre-Edit）一项都不能省。
9. ❌ **不得**以“截图通过 + 编译通过 + grep 通过”作为回归无退化结论——feature_acs / page_acs / shared_files 须真实回归验证；缺任一类运行时证据，spec status 不许升级 done。
10. ❌ **不得**凭理由把 affected_visual_pages 中的 state_label 推给“人工验证”——先调 `arkts-scenario-runner` 写场景，反复 ≥3 次失败才升级用户裁定。
11. ❌ **不得**在 §M1 模式下用 commit history 推翻 final state 的代码事实（详见 §1.2）。
12. ❌ **不得**把 iOS 端的“死代码”作为活功能进同步清单（见 §2.6）。

## 2.6 死代码过滤（所有扫描模式共享，必跑）

直接迁移这些 = 让 evolver 在 ArkTS 端真造永不被感知的功能 = 浪费 + 污染 baseline。**绝对禁止**进 A_CLOSURE / 行为轨迹清单 / §S2 差异清单：

| 类型 | iOS 识别特征 |
|------|-------------|
| 注释代码 | `//` 或 `/* */` 包裹 |
| 已废弃 | `@available(*, deprecated)` / `@available(*, unavailable)` / `@available(swift, obsoleted:)` |
| 死分支 | `#if false` / `#if DEBUG && 恒 false` 不进入分支；`if false {}` |
| 编译期消除 | `#if` 配置恒 false / `FOUNDATION_EXPORT` 未链接的死符号 |
| 占位 | `fatalError("TODO")` / `// TODO:` / 空函数 + `#warning("not implemented")` |

- §M3：grep 命中后**必须**剥离注释再判；只命中注释 → A_CLOSURE 等价于空 → 走硬闸门。
- §M1：diff 中纯注释 `+/-` 行不计入新增/下线行为。
- §M2：源码阅读提示词必须显式声明忽略上述死代码。

## 3. 分步命令表（顺序执行；每步带产物与 exit 语义）

| 步 | 命令 | 产物 | exit 语义 | 失败处置 |
|---|---|---|---|---|
| ① 固定快照与源复核 | `python <runtime>/scripts/a2h_ios.py source-index --project <target>`（已有索引时只比较源 sha256，变化走 ⑤ 的 `source-refresh`）；`python <runtime>/scripts/a2h_ios.py source-check --harness --report-only --project <target>`（只读诊断，不更新 findings/门禁报告） | 旧 `spec/baseline/ios-source-index.json` + 诊断 | 0=PASS；1=FAIL；2=用法错 | 缺旧索引 → 说明比较范围后继续；FAIL 按 §0 阶梯修到肯收口 |
| ② 四类影响分析 | 按 `ios-source-analysis` 组织四类重读受影响调用链 + `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope {project,ui,feature,api}` + `python <runtime>/scripts/a2h_ios.py resolve --source <source> --anchor <anchor>` 定符号锚点 | 事实视图 + 符号锚点 | 0=PASS；1=FAIL | 记录新增/修改/删除/无行为变化 + 证据 |
| ③ 用户对齐 | 主会话呈报 §S2 差异清单，用户裁决 | 确认后的差异清单（含 override 声明） | — | 唯一交互点，见 §S2 |
| ④ spec 更新 | 委托 `arkts-spec-evolver` create；存量规格升级 `python <runtime>/scripts/a2h_ios.py spec-upgrade --project <target> [--output <p> --apply <id> --patch <file> | --all-candidates]` / `python <runtime>/scripts/a2h_ios.py import-legacy --project <target>` | 增量 spec / 升级后的候选 | 0=成功；非0=FAIL | 按 evolver Gate 1 审批；升级候选由用户选 apply |
| ⑤ 源索引更新（规格更新后） | `python <runtime>/scripts/a2h_ios.py source-refresh --project <target> --review <review.json>` | 更新后的 `ios-source-index.json` | 0=更新；非0=FAIL | **必须在 ④ 之后**；禁止只刷新 hash 消 stale |
| ⑥ 门禁 | `python <runtime>/scripts/a2h_ios.py spec-check --project <target>`；`python <runtime>/scripts/a2h_ios.py source-check --harness --project <target>` | 门禁报告 | 0=PASS；非0=FAIL | 按 §0 阶梯修，最多 2 轮，禁停机呈报人工 |
| ⑦ plan/execute/verify | 委托 `arkts-spec-evolver`（plan+execute+verify）或回 `a2h-plan` 走 `replan`/`plan-ir`（命令与 flags 见 `../a2h-plan/SKILL.md`） | spec/features/F-*.md + 计划 + 代码 + 验证 | 按 evolver/plan | 守 evolver Gate 2 + verify 三层，不重复其内容 |
| ⑧ 报告 | `python <runtime>/scripts/a2h_ios.py migration-report --project <target> --output <target>/spec/migration-report.md [--build-evidence <build-report.json>]` | `spec/migration-report.md` | 0=生成；非0=FAIL | 命令单写，禁止手填状态消差异 |

- **E266 无人值守处置阶梯**（适用于 ①⑤⑥⑦ 每个门禁 FAIL）：FAIL → 按脚本 `retry_hint`/错误原文定位缺陷，派修复并重跑同一命令；**最多 2 轮**；2 轮仍不过或确定模型修不了 → **记欠账放行**（账记全：修过几轮、每轮失败原因、判“修不了”的依据）；要拍板的模型自决并留痕；**任何分支不得停机呈报人工**（`gates.stage_debt=true` 时例外：仅设备/账号类门允许欠账；静态门即便开了 stage_debt 也照常修到 PASS）。
- **单写者分区**：`source-index/source-refresh/spec-upgrade/import-legacy/migration-report` 单写的文件（索引/report）主会话禁手改；`exec-log.md`/`runtime-regression-log.md` 由本 skill 主会话 append；evolver 写其 spec/计划/代码目录。主会话或 worker 手改脚本单写文件 → PROCESS_VIOLATION。

## 4. §S2 用户对齐关卡（实施前必跑）

三模式产出的差异清单都必须经此关卡。清单格式：🔴 HMOS/ArkTS 未覆盖需新建、🟠 部分覆盖需补步骤、✅ 已覆盖（透明度）。每条 🔴/🟠 带：`HMOS Spec:` ❌/✅/⚠、`hmos_reverse_scan:`（≥3 同义关键词命中）、预计改动文件、iOS 源锚点（path+行号）。

- **用户回复前不得开工**。四种回复："全做"→ §3 委托；"只做 X"→ 剔除其余；"漏了 Y"→ 回对应模式补提取；"其实有 Z"→ 验证后剔除。**禁止**自行推断“用户应该选全部”。
- **告知后续流程**：本关卡确认“我找到的差异对不对”；确认后每条差异委托 evolver 走 create→plan→execute→verify，Gate 1/Gate 2 两处还会再暂停。
- **未授权产品替代才请求明确选择**：已授权决策直接复用 decision 账本；只有新的产品取舍才提出具体选项。

### S2.override 模式（用户显式授权“跳过确认”时）

| 可以跳过 | **不能跳过** |
|---|---|
| yes/no 对话式确认 | 证据字段完整性（缺字段仍不能进 🔴）|
| evolver Gate 1/Gate 2 审批 | §3 三源校验 + 代码反向扫描 |
| 多条差异的分组/合并对话 | §S2.5 Pre-Edit 机械核查 + 改后 `git diff` 自审 |

**硬性要求**：override 下主代理须在清单末尾显式声明“已收到 override 授权，跳过对话式确认；证据字段 + 三源校验 + Pre-Edit 机械核查仍逐条跑”。缺此声明 = 视角跳过机械核查 = skill 失败。

## 5. §S2.5 Pre-Edit 机械核查 + §SR 回归范围

**(1) Pre-Edit 四步**（§S2 确认后、任何 Edit/Write 前，每条差异必跑；任一步失败 → 该条降级“待人工复核”回清单末尾）：① 目标文件完整 Read（禁 grep 代替）；② Spec 反查（`existing_spec_refs` 非空时读对应 spec 判断不破坏已签收条目）；③ 同义词扫描（复跑 `hmos_synonyms` 关键词，全 0 命中才继续）；④ 改后 `git diff` 自审（实际改动必须是 `expected_files` 子集）。

**(2) §SR 回归范围派生**（改前清单 A → 改后清单 B → 取并集 R）：7 维 grep 派生（文件/struct/共享方法/AC ID/事件/状态/路由）+ LLM 语义补全（读 baseline AC 全集 + 改动 diff + 漏报模式知识库）→ R = A∪B 写入 spec `## 回归范围`，作为 evolver Step 11 + 运行时回归依据。`only_in_B_count > 0` = 改前预测有遗漏，取并集兜住并把漏报模式追加进知识库。

- **执行期日志**：每条差异完成后写一行到 `spec/incremental-migration-{date}/exec-log.md`（含 target_files_read / existing_spec_refs / reverse_scan_hits / scope_audit / result）。
- **运行时回归**（evolver verify 后必跑，不可绕过）：A. feature_acs 主链路烟雾、B. page_acs UI 交互回归、C. shared_files 被改函数 happy path；证据落 `spec/incremental-migration-{date}/runtime-regression-log.md`。升级 done 的 HARD-GATE：编译 PASS + 静态 AC 全命中 + 三类回归全 PASS 或 user_waived；任一缺失维持 `verifying(*-pending)`。**未执行设备验证保持 not_run**。

## 6. §S3 委托 arkts-spec-evolver + 多差异调度

逐条差异独立委托一次 evolver（不要把多差异打包成一个任务，Gate 审批以 spec 为单位）。委托 payload 字段：`title` / `ios_behavior_trace` / `hmos_current_state` / `expected_files` / `resources` / `acceptance_criteria` / `ios_source_refs` / `hmos_source_refs` / `hmos_spec_status` / `existing_spec_refs` / `regression_scope`。首次委托 `regression_scope` 只含清单 A（`derivation_provenance: {A_count:N, B_count:0}`）；**evolver execute 完成后回到本 skill 跑 §SR 改后审查产出 B**，更新 spec `## 回归范围` 为 R，再让 evolver 继续 Step 11——委托时显式约定该 callback 点，不能让 evolver 在 execute 后直接进 Step 11（那只回归 A，漏掉 only_in_B）。

- **多差异调度**：默认顺序执行（一条走完 create→plan→execute→verify 再起下一条）；两条差异共享基础类时可合并为一条 spec（由本 skill 在汇总 payload 时提议，用户决定）。**禁止**把所有差异打包一次性委托。
- **资源/权限特殊处理**：纯资源层变更（图片 / string key / 权限）独立存在且无业务逻辑时，本 skill 直接处理后仅在 evolver spec 里作“前置资源”声明（图片落 `resources/base/media/`、string key 落 `resources/base/element/string.json`、权限按映射写 `module.json5`）；若资源是某业务功能的一部分，**并入**对应业务差异的 evolver 调用。
- **复用证据**：未受影响且输入未变的页面/功能复用既有证据；**变化范围重新验证**——只有本轮重读结论才是“无行为变化”的凭据。

## 7. §S4 完成摘要

所有差异条目走完 evolver 流程后汇总：模式、范围、§S2 确认条目数；逐条 spec 路径 + Gate 1/Gate 2 审批结果 + verify 结果；独立处理的资源变更；整体状态（编译 / 运行时回归 log 路径 / feature_acs·page_acs·shared_files 的 pass/fail/pending 计数 / 未完成条目）。**任一 fail/pending 非 0 → 摘要顶部放显眼警告块**，列每条阻塞点 + 下一步，禁止用“整体已完成，仅 X 条待补”掩盖未通过项。

## 8. 读取时机（跨技能 references）

| 触发时机 | 必读文件 |
|---|---|
| 执行前；机器门禁与状态写者 | ../ios-source-analysis/references/harness-v2.md |
| 四类源分析组织与源事实字段/identity/state 规则 | ../ios-source-analysis/references/native-facts.md + source-semantics.md |
| spec 更新 / baseline 冻结 / 稳定 ID | ../a2h-spec/references/spec-delivery-contract.md + migration-decision-categories.md |
| plan/replan 与计划 IR 衔接 | ../a2h-plan/references/plan-delivery-contract.md + ../a2h-plan/SKILL.md |
| iOS spec → 原双计划衔接 | ../a2h-plan/references/ios-source-protocol.md |
| spec→code→verify 闭环与 Gate 1/2 | ../arkts-spec-evolver/SKILL.md + references/workflow.md + references/spec-format-and-structure.md |

## 9. 交接

- **闸门**：§3 ①–⑥ 步门禁 exit 0、§S2 差异清单已确认、委托 evolver 的句柄全部收口（join gate exit 0）后，才算完成本轮增量同步。
- **移交产物**：`spec/incremental-migration-{date}/exec-log.md`、`spec/incremental-migration-{date}/runtime-regression-log.md`、evolver 落盘的增量 spec/计划/代码、`spec/migration-report.md`。
- **下一步**：按摘要的未完成项继续，或进入 `a2h-retrospect` 复盘（同会话可直接续跑）。

---

## 收尾：上报本阶段用量

本 skill 的最后一步（无论经 a2h-run 还是单独触发；若本轮启动了 `usage-start` 账本）：

```bash
python <runtime>/scripts/a2h_ios.py usage-finish --project <target> --run-id <本轮run-id>
```

标记本轮增量同步的用量水位（写本地 usage 账本，尽力而为）。token 用量由宿主生命周期采集，本步不采集。**忽略其退出码，绝不阻断流水线。**