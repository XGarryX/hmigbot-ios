---
name: a2h-functional-registry
description: "iOS→HarmonyOS 迁移功能证据登记：在原 a2h baseline 中维护 iOS 功能及其入口/条件/动作/状态/数据变换/副作用的证据登记，用稳定 F ID 防止重复或遗漏，交 a2h-spec 做 AC 与规格收口，**不单独生成另一套迁移流程**。当用户说“登记 iOS 功能”“功能证据/事实登记”“稳定功能 ID”“把功能点登记进 baseline”时使用。不要用于：生成 feature spec 内容（a2h-spec）、把功能注入 fact-tree（a2h-functional-merge，iOS 走登记层）、跑设备测试。"
metadata:
  type: domain
  domain: migration
  tags:
  - ios
  - functional
  - registry
---

> **派发约定**：本 skill 主会话执行，登记由**唯一作者**维护；本 skill 被当 sub-agent 调起时禁止再嵌套外派后台分域 agent 后自行退出（收口会随 sub-agent 停止而丢失）——分域抽取要么同步自做，要么把分片清单回报主会话代派。
>
> **路径约定**：`$IOS_SRC` 从 `<target>/.migbot/config.json` 读；`<runtime>` = 本包 runtime。登记落 `<target>/spec/a2h/`（契约路径固定），`_work/` 留审计。本 skill 自有脚本（thin wrapper）：面向 Android XML layout 的 `source_index/strings_catalog/arrays_catalog/control_census/deterministic_floor` **iOS 版不适用**；可复用投影/校验类 `project_registry/build_intents/validate_contract/spec_oracle/spec_crosscheck/reconcile` 确有才调用。

# a2h-functional-registry — iOS 功能事实登记

## 0. 定位与纪律

- **前置**：读到 `../ios-project-inspector`、`../ios-ui-analyzer`、`../ios-feature-analyzer`、`../ios-api-inventory` 四类事实；已有 `feature-index.md` 与 feature spec。
- **输入**：iOS 源事实（工程/UI/功能/API 四类）、既有 baseline 登记（若在）。
- **输出**：`<target>/spec/a2h/functional_registry.json`（功能点枚举 + 源锚点）与（可选）`test_intents.json`；中间产物 `spec/a2h/_work/` 留审计。
- **唯一交互点**：登记口径冲突需回源码裁决时由本 skill **以源码为真值**，仅在 LLM 明确拿不准时升级用户在回路的决策；其余禁交互追问。
- **第一条可见输出**必须是一行登记计划（划分稳定 F ID → 逐项登记 → 举证 → 校验 → 交 a2h-spec），然后执行。

## 1. 定位（登记侧，不另起迁移流程）

本 skill 是**证据登记器**，不是“第二套迁移流程”：它把 iOS 功能的入口/条件/动作/状态/数据变换/副作用登记进原 a2h baseline，交 `a2h-spec` 做 AC 与规格收口。

| ✅ 做 | ❌ 不做 |
|---|---|
| 按稳定 ID 登记 + 逐项举证 | 生成 feature spec 正文 |
| 复用多入口 F ID、保留差异 | 跑设备测试 |
| 未知标 reason/needed-evidence | 改 fact-tree / 产 UI 清单 |

## 2. 稳定 F ID 划分规则

- 按**用户目标**划分稳定 F ID；入口可来自 UI、生命周期、扩展或后台任务。
- **相同业务从多个入口调用时复用 F ID，保留各入口行为差异**（同一功能多入口 ≠ 拆成多个 F）。
- 共享基础设施回指 `feature-base`；具体业务回指对应 `feature-index` 与 feature spec。

## 3. 证据登记完整性规则（逐项必填）

每项登记字段：

```jsonc
{
  "f_id": "F018",
  "entry": ["主页>设置>售后服务"],       // 入口（UI/生命周期/扩展/后台任务）
  "precondition": "已登录",               // 条件（前置态）
  "action": "展示售后服务入口",           // 动作
  "state_change": "进入售后中心页",       // 状态/数据变换
  "side_effect": ["弹客服 H5"],           // 副作用
  "source_symbol": "MineView.showService", // 源符号
  "source_file": "…/MineView.swift",       // 源文件
  "line": 123                              // 行号
}
```

- 枚举常量、阈值、事件、路由、错误、平台接缝**逐项给出处置**，**不按类名数计覆盖**。
- **未知行为保留 `reason`/`needed-evidence`**；不可达或范围外项给**源码证据与具体理由**。
- 登记由**唯一作者**维护，**不能用重复事实制造完成度**。

## 4. 输出契约（路径固定）

| 产物 | 路径 |
|---|---|
| 功能点枚举 | `<target>/spec/a2h/functional_registry.json` |
| 测试意图（可选） | `<target>/spec/a2h/test_intents.json` |
| 中间产物 | `<target>/spec/a2h/_work/`（留审计） |

三条 join 命门：`registry.name` == `intent.feature_path` 叶名；`intent.steps` 含“预期结果：”；iOS 锚点 = 源符号 + `source_file:line`（非 XML resource-id——那是对 Android 的等价物，iOS 用符号锚）。

## 5. 执行流程（骨架 + 主体切换）

```
S0 🤖 确认输入（$IOS_SRC / <target> / 四类事实源基线）
S1 ⚙️ 读四类事实：ios-project-inspector / ios-ui-analyzer / ios-feature-analyzer / ios-api-inventory
S2 🤖 划分稳定 F ID（§2），逐项登记（§3）——唯一手写主体
S3 ⚙️ project_registry → validate_contract（thin wrapper，可复用者）
S4 ⚙️ spec_oracle + spec_crosscheck → 候选分歧
S5 🤖 逐条裁决（回源码为真值）→ 真漏补/真多删/spec 漏记
S6 🤖 确认 ok=true 且候选已处理 → 交 a2h-spec（AC 收口）
```

**回路只有一条**：任何修改都落在登记主体，再经 S3 重投影；registry/intents 永不手改。

## 6. 增量与决策引用

- **增量变化保留旧 ID**，新增行为**新增 ID**，删除/替代有 `skip` 或 `decision` 引用。
- AC 真值来自源或批准决策，**不能采用目标实现作为裁决**。
- 冲突一律**以源码为真值**：spec / 派生指数与实际源码冲突时回源码确认。

## 7. 命令表（仅真实 CLI）

| 命令 | 用途 |
|---|---|
| `python <runtime>/scripts/a2h_ios.py facts --project <target>` | 源事实 |
| `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope {feature,api}` | 功能/API 事实视图 |
| `python <runtime>/scripts/a2h_ios.py source-analysis --project <target>` | 源码分析（源锚点/符号） |
| `python <runtime>/scripts/a2h_ios.py validate --project <target>` | 契约校验 |
| 本 skill 自有 `project_registry.py`/`validate_contract.py`/`spec_oracle.py`/`spec_crosscheck.py`（thin wrapper，确有才调） | 投影/校验/交叉核对 |

## 8. 单写者分区

| 文件 | 唯一写者 |
|---|---|
| 登记主体（功能点手写体） | 本 skill 运行的 agent（唯一作者） |
| `functional_registry.json` / `test_intents.json` | S3 投影脚本（禁止手改） |
| `_work/` 中间产物 | 各脚本 + S2 手写体 |

## 9. 读取时机

| 触发时机 | 必读 |
|---|---|
| 划分 F ID 前 | `../ios-feature-analyzer/SKILL.md`、`../ios-api-inventory/SKILL.md` |
| 入口/导航事实 | `../ios-ui-analyzer/SKILL.md` |
| 工程边界 | `../ios-project-inspector/SKILL.md` |
| 交 AC 收口 | `../a2h-spec/SKILL.md`（Phase C / 稳定 AC） |
| 注入事实给下游 | `../a2h-functional-merge/SKILL.md`（本 skill 是其上游生产者） |

## 10. 兜底

- 源事实缺失 → 该条标 `unknown` + needed-evidence，不跳过入口/扩展/后台任务。
- 源码 handler 找不到 → expected 标“inferred”备注，不丢控件/入口。

## 11. 交接

- 前置门闸：`validate_contract` 报告 `ok=true`（或等价校验 PASS）且候选分歧已逐条处理才交接。
- 移交产物：`spec/a2h/functional_registry.json` +（可选）`test_intents.json` + `_work/` 审计。
- 提示进入 `a2h-functional-merge`（合并 into baseline）或 `a2h-spec`（AC 收口）；同会话可直接续跑。

## 收尾：上报本阶段用量

本 skill 的最后一步（无论经 a2h-run 还是单独触发）：

```bash
python <runtime>/scripts/a2h_ios.py usage-finish --project <target> --run-id <本轮run-id>
```

写入 `<target>/spec/reports/derived/usage-budget.json`，尽力而为。token 用量由宿主生命周期采集，本步不采集。**忽略其退出码，绝不阻断流水线。**