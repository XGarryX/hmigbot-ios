---
name: arkts-feature-coverage-auditor
description: "iOS→HarmonyOS 迁移 Feature 覆盖率审计：对 iOS 源行为/入口/数据流/平台接缝与功能 spec/AC 做对账，逐项记 covered/missing/unknown，识别 spec Phase C 阶段漏掉或误并入的独立业务域，阻断 a2h-plan 直到通过或人工 override。当用户说“feature 覆盖率”“漏功能”“补 feature”“feature 全不全”“对一下功能”时使用。不要用于：UI 页面覆盖率（用 arkts-ui-coverage-auditor）、生成 feature spec 内容（a2h-spec 增量模式）。"
metadata:
  type: audit
  domain: migration
  tags:
  - ios
  - audit
  - coverage
  - feature
---

> **派发约定**：本 skill 主会话执行，不派发 subagent；抽查类→AC 完整性（§4.5）需要时由调用方派 sub-agent，本 skill 只产候选清单。
>
> **路径约定**：`$IOS_SRC` 从 `<target>/.migbot/config.json` 读；`<runtime>` = 本包 runtime。产出 `<target>/spec/feature-coverage-report.md` + `<target>/spec/feature-coverage-tasks.md`。本 skill 自有脚本 `scripts/compute_feature_coverage.py`（thin wrapper，转发 vendor/hmigbot helper），确有才调用；覆盖裁决以源码为真值。

# arkts-feature-coverage-auditor — iOS 功能规格覆盖审计

## 0. 定位与纪律

- **前置**：`<target>/.migbot/config.json` 存在且 `source_platform=ios`；spec Phase C 产物（`feature-index.md`、`features/F*.md`）已生成。先跑 `python <runtime>/scripts/a2h_ios.py source-check --harness --project <target>` 核对源归属与原生字段——**该门禁通过只证明结构/身份合法，不证明语义覆盖**。
- **输入**：工程地图（`spec/ref/ios-project-…`）、功能事实（`ios-feature-facts.md`）、API inventory（`api-inventory.json`）、`ui-manifest.md`、`feature-index.md`、源快照。
- **输出**：`spec/feature-coverage-report.md`（范围、版本、逐项映射、缺口、排除理由和证据）+ `spec/feature-coverage-tasks.md`（增量任务派发）。
- **唯一交互点**：连续多轮仍不通过的“人工 override”需要用户批准；其余禁交互追问。
- **第一条可见输出**必须是一行审计计划（源归属 → 四层对账 → 记账 → 缺口派发/重跑），然后执行。

## 1. 定位

Pipeline 中段的**强制审计步**：a2h-spec Phase C 之后触发，不通过则**阻断 a2h-plan**；a2h-execute/a2h-verify 阶段再跑回归。回答：**iOS 项目所有源行为/入口/数据流/平台接缝都被 `spec/baseline/features/` 覆盖了吗？**

为什么必须前置：Phase C 若只以 `ref/spec + ui-manifest + api-inventory` 为输入会漏掉**源码级独立业务域**（Swift/ObjC 子模块、app extension、后台任务、平台接缝）；本 skill 补“源码域扫描”这一输入，把缺口暴露在 spec 阶段而非 verify。

```
a2h-spec Phase C
  ├─ 生成 features/F*.md
  ├─ arkts-ui-coverage-auditor          ← UI 侧
  ├─ arkts-feature-coverage-auditor（本 skill）★
  │     [缺口] → 回 Phase C 增量补 feature → 重跑（最多 2 轮）
  │     第 3 轮仍 FAIL → warning + 人工 override（写 SESSION-HANDOFF.md）
  └─ 人工审批（HARD-GATE）→ a2h-plan
```

## 2. 记账（covered / missing / unknown，逐项）

每条候选记三态，**原文件只有名字不算覆盖**：

| 态 | 判据 |
|---|---|
| `covered` | 命中 ≥1 feature 主 spec，且行为/前置态/分支/错误有对应 AC/处置 |
| `missing` | 零命中，或仅“顺带提及”（weak_coverage）→ 进缺口清单 |
| `unknown` | 未读二进制、宏、动态分派、配置无法确认 → 保留 unknown 并给 reason/needed-evidence，**不伪造解析** |

## 3. 四层对账

1. **L1 源码域 / 入口**：每个 app/扩展/后台入口、每个独立业务域**均映射到 feature 或有具体排除证据**。**不按目录含几个文件、特定模块名或类名后缀判断是否存在功能**。
2. **L2 行为域**：每个实际业务行为的前置态、分支、计算、错误/取消、副作用均有对应 AC/处置。
3. **L3 反向对账**：UI 事件反查 feature、服务/API 候选反查 feature、**跨模块数据流各边界有责任 owner**。
4. **L4 语言语义**：Swift 值/引用、Optional、actor/task、Objective-C delegate/ownership 等行为影响**必须在 spec 或 addendum**，不能只出现于工具日志。

## 4. 核心算法

### 4.1 L1 源码域扫描
从 `spec/ref/ios-feature-facts.md` + 工程地图枚举 target/module/扩展入口；子模块行为域（≥ 独立职责）为候选。

```
1. 枚举 app / extension / 后台入口 / 独立业务子模块
2. 黑名单排除纯基础设施：utils/common/base/config/infra
3. 业务层强弱信号：
   - 强：Manager/Service/Coordinator/Delegate/ViewModel
   - 中：ViewController/SwiftUI View（UI 层但有独立 feature 可能）
   - 弱：Util/Constants（大概率不构成 feature）
4. 候选在 features/F*.md 搜域名/类名：
   - 命中 ≥1 → covered
   - 命中 0 → missing
   - 命中 1~2 次仅顺带 → weak_coverage
```

### 4.2 L2 行为域扫描
读 `features/F*.md` 的“验收标准”，对照源行为清单（前置态/分支/计算/错误/取消/副作用），缺一即 missing。**不通过扩写泛化 AC 凑数**——缺失项回 spec 增量补，保持稳定 F-AC ID。

### 4.3 L3 API 候选
读 `api-inventory.json` 的 `coverage.feature_candidates[]`，每个候选搜 `suggested_id` 或 API 章节引用；零命中 → missing。缺失则软降级（warning 不阻断）。

### 4.4 L4 page/入口 → feature 反向
读 `ui-manifest.md` 全 page_id，逐页在 feature-index/features 搜归属：0 命中 → 孤页；≥3 命中 → 警告“共享过细”。

### 4.5 L5 类→AC 完整性（optional）
对 `source_anchors` 类清单抽样方法名 vs AC：方法名/语义对应 → covered，否则 LLM 判定；complex 全量、simple 抽 30%；只产质量提示，不阻断 HARD-GATE。

## 5. 输出与 PASS 条件

### 5.1 报告模板
`spec/feature-coverage-report.md`：扫描时间、目标范围、版本、逐项映射、缺口清单、排除理由与证据。四层总览表（全量/已覆盖/缺失/覆盖率/阈值/状态）+ L1/L2/L3/L4 各自缺失明细 + 增量任务派发。

### 5.2 阈值（按体量分档）

| 层 | ≤30 features | >30 features |
|---|---|---|
| L1 源码域 | ≥95% | ≥85% |
| L2 契约层 | 100% | 100% |
| L3 API 候选 | 100% | 100% |
| L4 反向 | ≥95% | ≥90% |

- **静态覆盖 PASS 与功能验证 PASS 分开记**：设备/运行项未执行明确 `not_run`，不得当 covered。
- 失败处置：首次失败 → 生成 `feature-coverage-tasks.md` 派增量补 + 重跑（最多 2 轮）；**第 3 轮仍 FAIL → warning + 人工 override（写 SESSION-HANDOFF.md）**，阻断 a2h-plan 直到通过或 override。

## 6. 命令表（仅真实 CLI）

| 命令 | 用途 |
|---|---|
| `python <runtime>/scripts/a2h_ios.py source-check --harness --project <target>` | 源归属/原生字段门禁（不证语义覆盖） |
| `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope {feature,api}` | 功能/API 事实视图 |
| `python <本skill>/scripts/compute_feature_coverage.py …`（thin wrapper） | 确定性覆盖计算（候选清单，裁决回源码） |

## 7. Failure Modes

| 现象 | 处理 |
|---|---|
| `features/` 不存在 | PHASE_C_INCOMPLETE → 先跑 a2h-spec Phase C |
| ref/spec 不存在 | L2 软降级（warning 不阻断） |
| api-inventory 不存在 / `_mode` 不符 | L3 软降级 |
| SwiftPM/Xcode 工程结构无法识别 | 用工程地图 fallback，不猜目录 |
| 连续 3 轮 HARD-GATE 失败 | warning + 人工 override + SESSION-HANDOFF.md 留痕 |
| 体量分档误判 | 默认按 features 数 ≤30/>30，可 `--tier strict/lenient` 覆盖 |

## 8. 与 ui-coverage-auditor 的关系

| | ui-coverage-auditor | feature-coverage-auditor |
|---|---|---|
| 审计对象 | page 覆盖 | feature-index / features |
| 数据源 | ui-manifest / 页面 | 源码域 + ref/spec + api + ui-manifest |
| 触发词 | “漏页/UI 覆盖率” | “漏 feature/漏功能” |
| HARD-GATE | 阻断 a2h-plan | 阻断 a2h-plan |

两者独立，**都 PASS 才进 a2h-plan**。

## 9. 读取时机

| 触发时机 | 必读 |
|---|---|
| 执行前 | `../ios-feature-analyzer/SKILL.md`、`../ios-api-inventory/SKILL.md`、`../ios-source-analysis/SKILL.md` |
| 与 UI 审计关系 | `../arkts-ui-coverage-auditor/SKILL.md` |
| 增量/恢复 | `../a2h-spec/SKILL.md`（稳定 F/AC ID 保留） |

## 10. 交接

- 前置门闸：`feature-coverage-report.md` 落盘且通过阈值（或人工 override 留痕）才交接。
- 移交产物：`spec/feature-coverage-report.md` + `spec/feature-coverage-tasks.md`。
- 提示进入 `a2h-plan`（重算依赖图/拓扑）或回 `a2h-spec` 增量补 feature；同会话可直接续跑。

## 收尾：上报本阶段用量

本 skill 的最后一步（无论经 a2h-run 还是单独触发）：

```bash
python <runtime>/scripts/a2h_ios.py usage-finish --project <target> --run-id <本轮run-id>
```

写入 `<target>/spec/reports/derived/usage-budget.json`，尽力而为。token 用量由宿主生命周期采集，本步不采集。**忽略其退出码，绝不阻断流水线。**