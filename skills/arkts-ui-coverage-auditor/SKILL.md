---
name: arkts-ui-coverage-auditor
description: "iOS→HarmonyOS 迁移的 UI 覆盖率审计步：从 SwiftUI/UIKit 源码与 `spec/baseline` 事实出发，对“入口→页面→状态→事件→原生语义”五层逐项核对是否进入 UI spec 且每个页面/组件/导航/handler 有目标计划唯一归属，逐项记 covered/missing/unknown/not_applicable 并输出 `spec/ui-coverage-report.md`。当用户说“UI 覆盖率”“漏页”“页面齐不齐”“哪些入口没有 spec”“核对入口/页面/交互”或“对一下页面/spec 全不全”时使用；a2h-spec Phase B 完成后、a2h-plan 前必跑一次。不要用于：判断视觉一致性或运行表现（用 arkts-visual-verify / a2h-verify 的 device/visual 验证）、生成 spec 内容（用 a2h-spec 增量补规格）、生成 ArkTS 代码（用 a2h-execute）。"
metadata:
  type: domain
  domain: migration
  tags:
  - ios
  - audit
  - ui-coverage
  - spec
  - migration
---

> **派发约定**：本 skill **不派发 subagent**，全部在主会话或 a2h-spec/a2h-plan 主流程内执行，只做只读核对——不写产品代码、不改源事实、不建 spec 正文。它只读 iOS 源事实与已生成 spec，把缺口以审计报告形式交给 a2h-spec / a2h-plan 去补。
>
> 路径约定：`$IOS_SRC` 从 `<target>/.migbot/config.json` 的 `ios` 字段读取（缺配置 → 先 a2h-init）；`<target>` = 鸿蒙目标工程根；`<runtime>` = 本包 runtime（`scripts/a2h_ios.py` 所在根）。审计产物一律落 `<target>/spec/`：主报告 `spec/ui-coverage-report.md`，增量任务清单 `spec/ui-coverage-tasks.md`（禁落会话临时目录）。本 skill 无自有脚本，命令统一写成 `python <runtime>/scripts/a2h_ios.py <cmd> …`。

# arkts-ui-coverage-auditor — iOS UI 覆盖率审计

## 0. 定位与纪律

- **前置**：`<target>/.migbot/config.json` 存在且 `source_platform=ios`；a2h-spec 已产出 `spec/baseline/ui-manifest.md`、`spec/baseline/ui/page_*.md` 与 `spec/baseline/{ios-facts,ios-coverage,ios-semantics}.json`。缺 → 先跑 a2h-spec（不代跑，不可能凭空核对未生成的规格）。
- **输入**：`ios-facts.json`（身份/词法/结构事实）、`ios-coverage.json`（源覆盖记录）、`ios-semantics.json`（原生语义：SwiftUI/UIKit 记录）、`ui-manifest.md`（page 清单与归属）、`ui/page_NNNN_*.md`（分页 spec）、`feature-index.md`/`features/FNNN-*.md`（功能归属）、a2h-plan 的 `ui-plan.md`/`feature-plan.md`（若已生成，用于 owner 唯一性层）。
- **输出**：`spec/ui-coverage-report.md`（主报告）+ `spec/ui-coverage-tasks.md`（增量修复任务清单，喂给 a2h-spec 增量 / a2h-plan）。
- **唯一交互点 = 无**：全部核对由 exit code 与证据记录机械判定；只有当缺口无法机械定责（如 AC 按当前描述不可实现）时才提请人工澄清，其余禁交互追问。
- **第一条可见输出必须是一行审计计划**（读事实 → 入口层 → 页面层 → 状态层 → 事件层 → 原生语义层 → plan 归属层 → 出报告），然后才执行 §1。
- **硬约束（红线）**：静态覆盖 PASS 不能混入运行/视觉结果；不通过目录条数/文件数量推定覆盖；SwiftUI identity/Binding/modifier/task 与 UIKit lifecycle/constraint/delegate 不得被截图或扁平控件清单替代；混合框架页面必须两种框架分别检查；unknown 保持 unknown 并回流分析，绝不伪造 covered。

## 1. 何时必跑（Pipeline 集成位）

```
a2h-spec Phase B ──► 本 skill（必跑，出 ui-coverage-report.md）
                          │ 缺口
                          ▼
                 a2h-spec 增量补 spec ──► 重跑本 skill 直到无未决缺口
                          │ 通过
                          ▼
                     a2h-plan 前放行
```

- **必跑时机**：a2h-spec Phase B 完成后、a2h-plan 前；a2h-plan 变更页面归属后；用户主动说「漏页 / UI 覆盖率 / 页面齐不齐」时立即跑增量审计（不依赖 pipeline 状态）；a2h-retrospect 阶段再跑一次最终回归，作为本轮迁移的 UI 覆盖 KPI 写入回顾。
- **为什么必须前置**：原版实证（Fitness 迁移）：大量非一层入口（子页/Step/内嵌对话框）在 spec 阶段被漏，靠后续多条「补齐」手工救火。本 skill 在 spec 阶段就把「入口—页面—状态—事件—原生语义」逐项缺口暴露出来，避免一路漏到 verify。

## 2. 输入与数据来源（不重新解析 iOS 项目）

| 来源 | 用途 |
|---|---|
| `spec/baseline/ios-facts.json` | 页面/组件/导航/入口的结构事实（身份、词法、结构） |
| `spec/baseline/ios-coverage.json` | 已记录来源与覆盖的状态（源侧覆盖底账） |
| `spec/baseline/ios-semantics.json` | SwiftUI（identity/state/binding/modifier/task/导航）与 UIKit（controller/view/constraint/outlet/action/delegate/生命周期）原生语义记录 |
| `spec/baseline/ui-manifest.md` | 已发 page ID 与 page_id/framework/目标页/归属/证据置信度 |
| `spec/baseline/ui/page_NNNN_*.md` | 分页 spec（组件层级、布局约束、状态接口、交互、导航、资源、AC、目标接线责任段） |
| `spec/baseline/feature-index.md` + `features/FNNN-*.md` | 功能归属与入口/交互的 AC 映射 |
| `spec/baseline/plans/{ui-plan,feature-plan}.md` | （若已是 indexed 计划）页面/组件/共享导航/handler 的 owner 唯一性 |

> **重要**：本 skill **不重新解析 iOS 项目**。所有入口/页面/状态/事件/原生语义来自 a2h-spec 的 `ios-source-analysis` 事实产物（`facts` / `facts-view` 与 `ios-facts.json`）。若发现源事实本身缺失（缺入口、缺语义记录），报告标注 `SOURCE_FACTS_INCOMPLETE` + 建议回 a2h-spec 补事实，而非在本 skill 内重解析（避免双源不一致）。

## 3. 核对：五层逐项 + plan 归属（审计维度表）

按下面五层顺序逐项核对，每项给出 covered/missing/unknown/not_applicable 与证据（真实文件/符号/行号）；**不通过目录条数或文件数量推定覆盖**。

| 层 | 核对内容 | 判定口径 |
|---|---|---|
| ① 入口→页面 | 应用根、导航目的地、模态、深链/通知、扩展可视入口（widget/today 等） | 每项有 page ID 或**具体排除理由** |
| ② 页面→状态 | 初始/加载/空/错误/内容状态，权限、登录、trait 条件（横竖屏/深色/Dynamic Type） | 按真实源码逐项进入 spec |
| ③ 状态→事件 | 按钮、手势、输入、选择、返回与系统回调 | 各有前后态 + 处理器证据 |
| ④ 原生语义 | SwiftUI identity/Binding/modifier/task；UIKit lifecycle/constraint/delegate | 不得因截图或扁平控件清单而丢失；混合页两种框架分别检查 |
| ⑤ plan 归属 | 页面、可复用组件、共享导航与 handler | 唯一 owner（plan 存在时） |

**逐项证据要求**：`covered` 必须有源码证据（文件/符号/行号）；`not_applicable` 给具体理由（如某入口仅适用 iPad 或特定 target）；`unknown` 保持 unknown 并写清“确认所需额外证据”，回流 a2h-spec 源分析，不降级为 covered、不凭命名猜测。

**④原生语义重点（iOS 特有）**：

- SwiftUI 的 `body`/`@State`/`@Binding`/`@Environment`/`task`/`onAppear`/`NavigationStack`，UIKit 的 controller/view hierarchy、Auto Layout constraint、outlet/action、delegate 回调与生命周期——每类都必须在对应 page spec 的「iOS 源语义段」保留，**不能用目标 ArkUI 装饰器反向改写源事实**。
- 程序化 UI + IB（Storyboard/XIB）共同决定运行布局：两者缺一都要标注 unknown（IB 未解析 → 记录所需额外证据，不伪造布局树）。
- Preview/mock 数据与实际入口分开；**没有 iPhone 录制就不生成运行观察结论**（runtime=not_run、screenshot=null 合法）。

## 4. 审计命令表（真实 CLI，逐条可复制）

| # | 命令 | 产物/作用 | exit code 语义 | 失败处置 |
|---|---|---|---|---|
| 1 | `python <runtime>/scripts/a2h_ios.py source-check --harness --project <target>` | 原生字段/源溯源 harness 门禁 | 0=PASS，1=FAIL，2=用法错 | FAIL 读错误回 a2h-spec 修 spec/事实后重跑，≤2 轮（§0 阶梯） |
| 2 | `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope project` | 工程事实视图 | 同上 | FAIL → a2h-spec 补工程事实后重跑 |
| 3 | `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope ui` | UI 事实视图（页面/组件/入口） | 同上 | FAIL → 对应 UI 分析补事实后重跑 |
| 4 | `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope feature` | 功能事实视图 | 同上 | FAIL → 功能分析补事实后重跑 |
| 5 | （核对动作，无脚本）读 `ios-facts/ios-coverage/ios-semantics.json` + `ui-manifest.md` + 全部分页 spec，逐项打 covered/missing/unknown/not_applicable | 主会话逐项核对 | — | 核对动作本身不“通过”，只有结论进报告 |

- **无人值守处置阶梯（E266，每个 FAIL 门禁都套用）**：FAIL → 按错误修 spec/事实并重跑同一命令，最多 2 轮；2 轮仍不过或确定模型修不了 → **记欠账放行**（记全：修过几轮、每轮失败原因、判“修不了”的依据）；要拍板的模型自决并留痕；任何分支不得停机呈报人工（`gates.stage_debt=true` 时仅设备/账号类门允许欠账，静态门即便开 stage_debt 也照常修到 PASS）。
- 命令不可手改、产物（`ios-facts.json` 等事实 JSON）不可手写；脚本单写文件主会话禁改。

## 5. 判定、记录与报告

- 逐项记录 `covered/missing/unknown/not_applicable` 及其证据（文件/符号/行号或排除理由）；`unknown` 必须同时写清“确认所需额外证据”，回流分析，不降级为 covered。
- **主报告 `spec/ui-coverage-report.md`** 结构：
  - 检查范围（本轮核对的入口/页面/源版本 `ios-facts.json` 的 source_sha256）；
  - 五层核对总表（层 × 入口/状态/事件/语义/归属 × 状态列）；
  - 缺口清单（按优先级：被多入口引用 → 单入口 → 工具/调试页），每条带“责任阶段”（回 spec / 回 plan / 回源分析）；
  - 静态覆盖结论（见下）。
- **只有范围内源事实全部有归属、无未决缺口，才写「静态覆盖 PASS」**。运行/视觉结果**另列** `not_run` 或真实 device/visual 结果，**不能混入规格覆盖状态**——「静态覆盖 PASS」不证明任何行为等价或视觉一致。
- 报告中「已读源码 / 已生成规格 / 已编译源 / 已运行观察」四轴分列，任意一种不能代替其他项。

## 6. 通过/失败信号与修复回环

```text
通过：范围内源事实全部有归属、无未决缺口（静态覆盖 PASS，运行另列）
失败：存在 missing 或未决 unknown / 未决缺口 → 阻断 a2h-plan
```

```
本 skill 不通过
  ↓
生成 spec/ui-coverage-tasks.md（缺口清单 + 责任阶段 + 增量任务）
  ↓
派回 a2h-spec（增量补 page/语义/AC）/ a2h-plan（补 owner/归属）
  ↓
重跑本 skill 直到无未决缺口
```

## 7. 边界（做 / 不做）

**做**：五层覆盖率核对 + 缺口清单 + 增量任务派发 + 静态覆盖结论（与运行/视觉分离）。

**不做**：不生成 spec 内容（a2h-spec 增量的事）；不写 ArkTS 代码（a2h-execute 的事）；不判断 UI 视觉一致性或运行表现（arkts-visual-verify / a2h-verify 的事）——本 skill 只看“入口/状态/事件/语义是否进入 spec 且有无归属”，不看“好不好看、对不对”。

## 8. 失败模式

| 现象 | 处理 |
|---|---|
| `ios-facts.json`/`ios-coverage.json` 缺失 | 回 a2h-spec 跑 `source-index` + `facts` 后再审；报告标 `SOURCE_FACTS_INCOMPLETE` |
| 混合 SwiftUI+UIKit 页面 | 第④层两框架分别核对，任一缺失都记 missing，不合并判 covered |
| SwiftUI 命名/路由非约定（如自定义 View 名） | 按 `ios-facts.json` 符号做归一化 + 模糊匹配，警告但不误判 missing |
| IB/Storyboard 未解析 | 记 `unknown` + 所需额外证据，不伪造布局树 |
| 一个组件被多个入口复用 | 每个入口都标 hit，不重复计数也不因复用漏归属 |
| 无设备/无录制 | 运行/视觉列 `not_run`，**不得与静态覆盖状态混写** |

## 9. 读取时机表（references）

| 触发时机 | 必读文件 |
|---|---|
| 第④层原生语义字段/identity/state 规则 | `../ios-source-analysis/references/native-facts.md` + `source-semantics.md` |
| 页面 spec 应含哪些公共段落（页面结构/视觉/状态接口/交互/导航/资源/AC/目标接线责任） | `../a2h-spec/templates/page-spec-template.md` |
| 源覆盖记录的口径（哪些算 covered/未知） | `../a2h-spec/templates/source-coverage-report-template.md` |
| a2h-spec 的门禁与 UI baseline 产出约定 | `../a2h-spec/SKILL.md`（Phase B） |

## 10. 交接

- **前置门闸**：§4 命令第 1 步 `source-check --harness` exit 0；主报告 `spec/ui-coverage-report.md` 已写且静态覆盖 PASS（或缺口已在 `spec/ui-coverage-tasks.md` 列全、责任阶段明确）。
- **移交产物清单**：`spec/ui-coverage-report.md`、`spec/ui-coverage-tasks.md`。
- **下一步**：无缺口 → 提示进入 `a2h-plan`（同会话可直接续跑）；有缺口 → 交回 `a2h-spec` 增量补规格后重跑本 skill。

---

## 收尾：上报本阶段用量

本 skill 为域步骤（a2h-spec / a2h-plan 内嵌调用），不独立上报阶段用量；token 用量由宿主生命周期按调用阶段（a2h-spec）的 `usage-*` 账本采集，本步不采集。**若有可用 usage 账本则尽力上报，忽略其退出码，绝不阻断流水线。**