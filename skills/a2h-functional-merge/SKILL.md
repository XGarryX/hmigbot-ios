---
name: a2h-functional-merge
description: "iOS→HarmonyOS 迁移功能事实合并：把各 target/module 的 iOS 分片功能事实与原 a2h 功能登记按行为与证据消歧合并，保持稳定 F/AC ID、源语义与决策边界，交 a2h-spec 的原 baseline，**不创建独立状态机引擎**。当用户说“合并 iOS 功能分片”“功能事实合并”“合并分片功能/登记”“把分片功能并进 baseline”时使用。不要用于：生成功能登记（a2h-functional-registry）、生成 feature spec（a2h-spec）、把功能点注入 fact-tree（Android 路径，iOS 不走）。"
metadata:
  type: domain
  domain: migration
  tags:
  - ios
  - functional
  - merge
---

> **派发约定**：本 skill 主会话执行，不派发 subagent；冲突消歧回原作者或读取源码，不委托他人代判。
>
> **路径约定**：`$IOS_SRC` 从 `<target>/.migbot/config.json` 读；`<runtime>` = 本包 runtime。合并输出落 `<target>/spec/a2h/functional_registry.json`（更新后的登记）。本 skill 自有脚本（thin wrapper）：`map_registry_to_facttree.py`/`merge_functional_into_facttree.py` 是 **Android fact-tree 注入路径，iOS 版不走**；`reconcile_behavior_chains.py`/`fold_enum_groups.py` 作用在 registry/points 层、可复用，确有才调用。

# a2h-functional-merge — iOS 功能事实合并

## 0. 定位与纪律

- **前置**：读到各 target/module 的事实、功能登记（`spec/a2h/functional_registry.json`）、已有 `feature-index.md` 与决策账本（decision ledger）。
- **输入**：iOS 分片功能事实（分 target/module）、原 a2h 功能登记、决策。
- **输出**：更新后的登记 + 具体合并说明（哪些合并/哪些保留/哪些标过期）；交 `a2h-spec` 的原 baseline。
- **唯一交互点**：冲突需要“产品决策”时提出具体选择让用户拍板；事实矛盾/配置差异回源码/原作者消歧，不无谓追问。
- **第一条可见输出**必须是一行合并计划（对齐入口/目标 → 按行为判同 → 消歧 → 保留 ID → 核对 → 交 baseline），然后执行。

## 1. 定位

只做**合并与消歧**，**不创建独立状态机引擎**；合并后的登记仍是 a2h-spec 原 baseline 的输入，不新起一套运行时。

## 2. 输入 / 输出

| | 内容 |
|---|---|
| 输入1 | 各 target/module 的 iOS 分片功能事实 |
| 输入2 | 原功能登记 `spec/a2h/functional_registry.json` |
| 输入3 | 已有 `feature-index.md` + 决策账本 |
| 输出 | 更新后 `functional_registry.json` + 合并说明 |

只合并**本次授权范围**；范围外分片不并入、不覆盖。

## 3. 合并规则（按行为与证据，不按名）

| 规则 | 含义 |
|---|---|
| 对齐入口/业务目标/状态/副作用 | 语义对齐，**按行为判断相同功能，不按类名或文件名** |
| 共享服务不自动合并 | **不把多个不同用户功能合成一项** |
| 多入口保留前置态差异 | **相同功能多入口保留不同前置态** |
| 保留语言/UI 语义与证据 | **保留 Swift/Objective-C 语言语义、SwiftUI/UIKit UI 关联和所有源证据** |
| 源版本不一致 | 先标过期，**不以较新时间戳自动覆盖** |

## 4. 冲突处置

冲突**逐条标**类型，按类型消歧：

| 类型 | 消歧 |
|---|---|
| `事实矛盾` | 回原作者或读取源码消歧 |
| `配置差异` | 回源码消歧 |
| `产品决策` | 提出具体选择让用户拍板 |

## 5. 稳定 ID 与决策引用

- **稳定 ID 不重排、不复用**；同一业务跨入口复用 F ID、保留差异。
- **AC 真值来自源或批准决策，不能采用目标实现作为裁决**。
- 删除/替代有 `decision` / `supersedes` / `addendum` 关联与范围说明。

## 6. 执行流程（骨架）

```
M0 只合并本次授权范围；源版本不一致的分片先标过期（不以较新时间戳自动覆盖）
M1 对齐入口/业务目标/状态/副作用 → 按行为判相同功能（§3）
M2 冲突消歧（§4）
M3 保留稳定 ID + 源语义 + 决策边界（§5）
M4 核对丢失/重复、源码归属、decision/supersedes/addendum 关联与范围
M5 输出更新登记 + 合并说明 → 交 a2h-spec 原 baseline
```

## 7. 铁律（防污染）

- **只合并、只更新登记**；不重排/复用稳定 ID；不改源证据。
- **不把目标实现当裁决/真值**（AC 真值只来自源或批准决策）。
- **不创建独立状态机引擎**（合并 ≠ 新运行时）。
- 源版本不一致 → 标过期，**不以较新时间戳自动覆盖**。

## 8. 自检（写 stats）

退出前核对：
- 丢失/重复：无丢失、无重复；
- 源码归属：每条回指源符号；
- decision/supersedes/addendum 关联完整；
- 合并范围 = 本次授权范围。

任一失败即 fail，不得静默落盘。

## 9. 命令表（仅真实 CLI）

| 命令 | 用途 |
|---|---|
| `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope {feature,api}` | 功能/API 事实视图 |
| `python <runtime>/scripts/a2h_ios.py validate --project <target>` | 契约校验 |
| 本 skill 自有 `reconcile_behavior_chains.py`/`fold_enum_groups.py`（thin wrapper，确有才调） | 事实对账/枚举同构收敛 |

`map_registry_to_facttree.py` / `merge_functional_into_facttree.py` 为 Android fact-tree 注入，iOS 合并层不调用。

## 10. 读取时机

| 触发时机 | 必读 |
|---|---|
| 合并前 | `../a2h-functional-registry/SKILL.md`（登记口径）、`../a2h-spec/SKILL.md`（稳定 ID/AC） |
| 语言/UI 语义 | `../ios-source-analysis/SKILL.md`（Swift/ObjC、SwiftUI/UIKit） |
| 消歧依据 | `../a2h-spec/SKILL.md` 的 decision ledger 段 |

## 11. 交接

- 前置门闸：§8 自检全过 + 合并说明落盘才交接。
- 移交产物：更新后的 `spec/a2h/functional_registry.json` + 合并说明。
- 提示进入 `a2h-spec`（在原 baseline 上做 AC 与规格收口）；同会话可直接续跑。

## 收尾：上报本阶段用量

本 skill 的最后一步（无论经 a2h-run 还是单独触发）：

```bash
python <runtime>/scripts/a2h_ios.py usage-finish --project <target> --run-id <本轮run-id>
```

写入 `<target>/spec/reports/derived/usage-budget.json`，尽力而为。token 用量由宿主生命周期采集，本步不采集。**忽略其退出码，绝不阻断流水线。**