# iOS 版对齐原版 HMigBot CodeX 1.7.0 审计

> 对比对象：原版 `hmigbot-CodeX-1.7.0`（Android→鸿蒙）与 `hmigbot-ios 0.10.1`（iOS→鸿蒙）。
> 目标：五阶段流水线尽量与原版一致，同时保留 iOS 差异（尤其代码解析与规格生成），
> 并按「真实 iOS 开发 = macOS + Xcode」场景优化，接入 Apple 官方 skill / MCP。
> 本文件就是本次对齐的差异清单与实施依据。

## 0. 结论摘要

1. iOS 版**完整保留了原版五阶段主线**（init → spec → plan → execute → verify → retrospect）与
   目标侧 ArkTS 技能、角色、调度内核（`vendor/hmigbot-1.7.0`），没有结构性断裂。
2. **发生漂移的是「源解析 → 规格生成」这一段**：原版靠 `android-fact-tree / compose-fact-tree /
   android-ui-graph-builder / android-screenshot-analyzer` 的「事实树 + 三源合成」确定性流水线，
   iOS 版替换成了自编的 `ios-*` 分析技能 + Python 词法/结构抽取，**步骤更简、确定性脚本更少**。
3. **最大短板**：iOS 版把「源语义理解」降级为 Windows 上的词法静态分析，且 Apple 官方 skill / Xcode MCP
   虽已留接口（`source_mcp.py` 白名单 + `host.py` 能力协商）但从未在 mac/Xcode 真实环境接通。
4. **Python 脚本几乎无冗余**：`src/hmigbot_ios/` 的模块被 CLI/流水线/测试密集引用，无「可安全删除」的死模块；
   真正的取舍点是「旧实验 CLI（`cli.py`/ios2harmony）vs 主入口（`native_pipeline.py`/a2h_ios）」两条入口并存。

---

## 1. 仓库结构对比

| 维度 | 原版 1.7.0 | iOS 版 | 差异 |
|---|---|---|---|
| 技能目录 | `migbot/skills`（102 技能） | `skills`（96 技能） | iOS 删除 13 个技能、新增 7 个 iOS 技能（净 -6），详见下方清单 |
| 角色目录 | `migbot/agents-codex`（33 个 .toml） | `agents-codex`（29 个 .toml） | 替换 Android 分析/转换角色，见 §4 |
| 调度内核 | `migbot/skills/a2h-execute/scripts` | `vendor/hmigbot-1.7.0` | 逐字节保留，经 `ios_scheduler.py` 桥接 |
| 备用策略 | `migbot-1to1/`（一比一迁移） | 无 | iOS 版未提供 1to1 策略 |
| 架构技能 | `migbot-arch/`（a2h-arch-scaffold 等） | 无 | iOS 版未引入 arch 侧技能 |
| 安装 | `install.sh/install.ps1 --target` | `install.ps1/install.sh -Workspace` | 语义等价，路径参数名不同 |
| 版本 | 90 skill / 7 role（README 旧口径，实为 102/33） | 96 skill / 29 role | — |

### 技能差异清单（原版有、iOS 版无的 13 个）

- **Android 源专属/资源（9 个，iOS 用 7 个新技能替代）**：`android-fact-tree`、`compose-fact-tree`、
  `toolkit-fact-indexer`、`android-api-inventory`、`android-ui-graph-builder`、`android-ui-graph-query`、
  `android-screenshot-analyzer`、`android-view-to-arkui`、`android2hmos-resources-convert`。
- **目标/管线侧（4 个，iOS 用等价命令替代）**：`arkts-behavior-verify`（→ `behavior-check`）、
  `hmos-device-triage`、`a2h-stage5-fix`、`app-relationship-tree`。

> 说明：`arkts-behavior-verify` / `hmos-device-triage` / `a2h-stage5-fix` / `app-relationship-tree`
> 属目标侧或通用能力，其删除是否产生覆盖缺口需重点复核（见 §7 路线图）。

---

## 2. 五阶段逐个对比

### 2.1 init（初始化）

| | 原版 | iOS 版 |
|---|---|---|
| 路径探测 | android / harmonyos / deveco / hvigorw | **ios** 源根 / harmonyos 目标 / hvigor/node/DevEco/SDK/hdc |
| 配置落盘 | `.migbot/config.json`（含 `confirmed`） | `.migbot/config.json`（`source_platform: ios`，`ios` / `harmonyos`） |
| 同意协议 | 安装期弹窗 + `a2h init-run --consent` | `telemetry_consent: denied` 默认 |

**差异**：iOS 用 `source_platform=ios` 与 `ios`/`harmonyos` 路径；功能对齐，无缺口。
**待优化**：init 应显式探测 `xcodebuild/xcrun/swift`（macOS）并写入 config，供后续阶段选择「native vs static」源解析路径——这一能力已由 `host.py:detect_host_profile()` 提供，尚未被 init 消费。

### 2.2 spec（源理解与规格）——漂移最大的一段

| 子步骤 | 原版（Android） | iOS 版 | 差异性质 |
|---|---|---|---|
| 确定性前置 | A0.0–A0.9 约 12 个脚本（sibling_facts / fact_tree_quality / resolve_theme / domain_partition / coverage_reconcile / source_inventory / infra_carve …） | `source-index` / `facts` / `literals` / `expertise-plan` / 四类 facts-view | iOS 脚本更少 |
| 源解析 | `android-fact-tree`（dispatch.py plan）+ `compose-fact-tree` + `toolkit-fact-indexer` → `toolkit-fact-tree.json` | `ios-project-inspector` + `ios-ui-analyzer` + `ios-feature-analyzer` + `ios-api-inventory` → `ios-facts.json` / `ios-obligations.json` | iOS 用 Python 词法替换了 Android 的树构建 |
| UI 抽取 | `android-ui-graph-builder` / `android-screenshot-analyzer`（三源：XML+截图+层级） | `ios-ui-analyzer`（SwiftUI/UIKit/Storyboard 静态）+ `ios-resources-convert`（Asset Catalog） | iOS 无运行时截图/层级，仅静态 |
| 规格生成 | `ui-manifest.md` / `page_*.md` / `feature-index.md` / `features/F*.md` | 同名产物 + `ios-semantics.json` + `ios-coverage.json`（新增） | iOS 保留骨架，新增 iOS 语义字段 |
| 契约 | 契约六件草案（domain-map/ownership/contracts/decisions/workflow-params + decision-ledger） | 同名 blueprint 契约 + `spec_contract_version`（profile 1/2） | iOS 强化了「规格合同」 |
| 拷问 | grill C0–C17 两轮 + `grill_autodecide.py` | `source-check --harness` + `spec-check` + coverage auditor | iOS 用**程序门禁**替代 grill 人工拷问 |

**结论**：iOS 版**没有沿用原版 A0 确定性脚本矩阵 + grill 的完整结构**，而是把「源解析」压缩成自编词法分析 +「门禁」压缩成程序检查。这是为「无 Mac 也要能跑」做的妥协，代价是语义覆盖弱、unknown 多。
**本轮不改动 spec SKILL 的既有设计**（避免把成熟的 iOS 门禁回退成 Android 事实树），但**补齐 Apple/Xcode 接入**让「源解析」在 macOS 上能升级为真实语义（见 §5）。

### 2.3 plan（责任、依赖与冻结计划）

对比无显著结构性差异：iOS 版保留 `ui-plan.md / feature-plan.md（indexed-v1）/ base-plan.md / slices / coverage-matrix.md / placeholder-registry.md`，并经 `plan-ir` 冻结成 `spec/waves/plan-*.json` + `blueprint` 契约。
**差异**：iOS 版把「P0 归属/拓扑裁决」落进 `ios_scheduler.generate()` 的**类型化计划校验**（`plan-check/plan-ir`），比原版多了 ownership/DAG/哈希钉住的程序强校验。此差异属于**强化而非漂移**，建议保留。

### 2.4 execute（实现与编译收口）

Stage 划分一致：Stage 0 资源 / Stage 1 UI 批次 / Stage 2 Base / Stage 3 功能切片 + 结构收敛。
派发协议一致：`next_batch → dispatch → receipt → land_results` 四拍，经 `ios_scheduler.step()` 桥接原版内核 `_wavelib.py`。
**差异**：iOS 版用 `ios-ui-to-arkui` / `ios-resources-convert` 替换 Stage 0/1 的源侧角色（`android2hmos-resources-convert`）。
**结论**：目标侧执行框架对齐良好，无需改动。

### 2.5 verify（独立预期与真实验证）——存在一处明确缺口

| 检查 | 原版 | iOS 版 |
|---|---|---|
| CHECK-1 静态 / CHECK-2 身份 | 固定 | 固定（`arkts-app-identity`） |
| CHECK-3 UT / CHECK-4 UI/视觉 | 可选 | 可选（`arkts-ut-verifier` / `arkts-ui-verifier` / `arkts-visual-verify`） |
| CHECK-5 行为验证 | **有**（视觉+UT+行为+设备） | **SKILL 层面未单列 CHECK-5**，但等价能力由 `behavior-check` CLI + `ios-feature-analyzer` 源 oracle 提供 |

**结论**：iOS 版把「行为验证」从 verify SKILL 的 CHECK 清单里拆开、下沉为独立 `behavior-check` 命令；能力在、术语漂移。属**低风险可对齐项**：在 `a2h-verify` SKILL 补回 CHECK-5 行为验证条目并指向 `behavior-check`，与本轮一致。

### 2.6 retrospect（复盘与经验反馈）

对比无显著差异：均产出 `docs/retrospect-report-*.md` + findings 队列 + 经验沉淀 + 用量上报（`a2h mark-stage`）。
**差异**：iOS 版把「重复门禁是否继承旧 PASS」收紧为「不继承旧 PASS，重核许可/摘要」，属强化而非漂移。

---

## 3. 「代码解析 & 规格生成」专项（iOS 差异核心）

| 源平台事实 | 原版 Android 手段 | iOS 版当前手段 | 宏观区别 |
|---|---|---|---|
| 工程结构 | `AndroidManifest.xml` + `build.gradle` | `.xcodeproj/.pbxproj`（`xcode.py` 自解析）| pbxproj 是自编解析，注释自认「not complete Xcode compatibility」 |
| 组件/页面 | Activity/Fragment + Compose（`android-ui-graph-builder`） | SwiftUI View / UIKit 控制器 / Storyboard/XIB（`ios-ui-analyzer` + `swiftui.py` 词法） | iOS 用词法代替语义绑定 |
| 状态/事件 | ViewModel/LiveData/Compose state | SwiftUI `@State/@Binding/@Environment` + UIKit delegate（`ios_facts.py` identity_usage 词法规则） | iOS 以「词法证据」标注，多次声明「不声称编译器绑定」 |
| 语义真值 | 三源（XML+UIAutomator+截图）运行采集 | source anchor + 独立 oracle（`behavior-check`），无运行时 UI 采集 | iOS 无模拟器运行，行为放 UNVERIFIED |

**根本差异**：原版 Android 侧能拿到 Android SDK/设备做**运行时/编译器**真实证据；iOS 版在 Windows 上**拿不到 Xcode/Swift 编译语义**，只能用词法兜底。
**正确补法**（本轮方向）：在 macOS 上接 `xcrun agent skills export`（Apple 官方 skill）+ `xcrun mcpbridge`（Xcode MCP）+ SwiftSyntax/Clang provider，把 `ios-facts` 从「词法」升级为「真实符号/类型/引用」；Windows 上静态降级、macOS 上原生。

---

## 4. 角色映射（agents-codex）

原版有而 iOS 版删除（Android 源专属）：`a2h-android-analyzer`、`a2h-activity-converter`、
`a2h-factchain-runner`、`a2h-domain-worker`、`compose-fact-analyzer`、`arkts-android-analysis`、
`ad-profile-builder`（启动画像）等。
iOS 版新增：`a2h-ios-analyzer`（组织 iOS 源四分析器）、`a2h-ios-converter`（iOS 页面→ArkUI）。
目标侧通用角色（`arkts-*`、`a2h-closer/fixer`、`hmos-builder`、`scenario-builder`）原样保留。

---

## 5. Apple 官方 Skill / Xcode MCP 接入（本轮实施重点）

现状（来自 `docs/PROVIDERS.md` 与 `src/hmigbot_ios/source_mcp.py`）：

- **Xcode MCP**：`source_mcp.py` 已实现 stdio 客户端与工具白名单 `{XcodeRead, XcodeGrep, XcodeGlob, XcodeListWindows, DocumentationSearch}`；官方接入命令 `xcrun mcpbridge`（`codex mcp add xcode -- xcrun mcpbridge`）。
- **Apple agent skills**：Xcode 27 提供 `xcrun agent skills export` 导出官方 Markdown；本包未导出/加载，`apple_skills.status=not_loaded`。
- **SwiftSyntax / Clang provider**：`providers/swift-syntax`、`providers/clang` 自编适配，需真实编译上下文。
- **宿主能力协商**：`src/hmigbot_ios/host.py:detect_host_profile()` 已能按 macOS+`xcodebuild`+`xcrun` 选择 `macos_xcode/native` 源 provider，Windows 回退 `windows_static`。此文件为**未提交的 WIP**，本轮正式纳入。

本轮动作：
1. 提交 `host.py` + `doctor.py` 宿主能力协商改动，并补 `tests/test_host_profile.py` 覆盖 provider 选择与 profile 校验。
2. 新增 `skills/ios-source-analysis/references/apple-xcode-integration.md`，固化「在 macOS 上导出 Apple skill / 连接 Xcode MCP / 写 provenance」的完整接入规程与降级路径。

---

## 6. Python 脚本取舍评估

`src/hmigbot_ios/` 现约 80 个模块，经 import 引用扫描**未见可安全删除的死模块**——`native_static_runtime`、
`computed_properties`、`harmony_diagnostics`、`host`、`cloud`、`iphone`、`capture`、`generate`、`environment`、
`behavior`、`evidence`、`build` 等均被 CLI/流水线/测试直接引用。
两条入口并存：`native_pipeline.main()`（主线 `a2h_ios.py`）与 `cli.main()`（旧适配器 `ios2harmony`）。
**建议（不本轮强删）**：旧适配器命令（`hmigbot-bind`/`migration-contract`/`cloud-*`/`ipa-inspect`/`scan/generate/scaffold`）
标记 deprecated，但其所依赖模块与主线共享（如 `analyze.py` 被 `index_source` 复用），物理删除需先解耦，风险高于收益。

---

## 7. 后续路线图（本审计未完成项）

- [ ] 在真实 macOS+Xcode 跑通 `xcrun agent skills export` → 导入官方 skill → 写 provenance。
- [ ] 在 macOS 跑通 `xcrun mcpbridge` Xcode MCP → 让 `source_mcp.py` 走真实 XcodeRead/Grep 采集符号/引用。
- [ ] `a2h-verify` SKILL 补回 CHECK-5 行为验证条目（对齐原版术语，指向 `behavior-check`）。
- [ ] `a2h-init` 消费 `host_profile`：macOS 写 native 路径、Windows 写 static 路径到 config。
- [ ] 评估引入 `migbot-1to1`/`migbot-arch` 侧技能的必要性（iOS 是否需要「一比一」策略）。
- [ ] 旧 `cli.py` 适配器命令的 deprecated 与解耦。