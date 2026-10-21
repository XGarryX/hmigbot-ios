---
name: arkts-visual-verify
description: "iOS→HarmonyOS 迁移验证步：按页面与前置态对齐真实 iOS 截图/录像/运行证据与鸿蒙实测截图及交互结果，复用 HMigBot 的 fix 轮次与 visual-fixer/reviewer 闭环；无源证据时结论标 source_visual_unverified、无设备标 not_run，绝不伪造通过。当用户说“截图对比”“视觉验证”“检查 UI 一致性”“迁移前后效果对比”“跑一下视觉对比”时使用。不要用于：路由/导航跳转核验（用 arkts-router-verify）、UI 覆盖率审计（用 arkts-ui-coverage-auditor）、功能逻辑验证（各自 verifier 负责）；不要把 Preview/mock 图当源真值。"
metadata:
  type: verification
  domain: migration
  tags:
  - ios
  - verification
  - visual
---

> **派发约定**：本 skill **派发 subagent**——按页面/状态分片派 `visual-fixer` 修代码、派 `visual-fixer-reviewer` 反摸鱼质检（§7）。派发规则：`task_name` 唯一（带 page-id/round-N 后缀）；派发前把预期产物清单写 `<target>/spec/visual-verify/_work/expected_<join点>.json`，join 点对账用；**谁派谁收**（sub-agent 内部需“等齐 N 片再合并”时禁止嵌套外派后自行退出，把分片清单回报主会话代派）；契约产物必须出自承担任务的子代理，禁止派发方代写占位产物让 gate 转绿。
>
> **Join 协议（收口五条款）**：① 循环 wait——完成的唯一合法信号是 `agent_status=completed`，**绝不是产物文件存在**（文件会中途落盘，读半截即误判）；② 死句柄与验收——连续 3 次超时后 list 核对，completed≠验收通过，join 点跑 gate 验产物才能消费；③ 收口锚点——最终报告前必须收口全部句柄；④ 放行≠遗弃——“非阻塞放行/到点即收”只推迟收口时机，不豁免收口义务；⑤ fire-and-forget 仅正文显式声明的派发免收口。
>
> **路径约定**：`$IOS_SRC` 从 `<target>/.migbot/config.json` 的 `ios` 字段读取（缺 → 先执行 a2h-init）；`<runtime>` = 本包 runtime（`scripts/a2h_ios.py` 所在根）。产物一律落 `<target>/spec/`（`spec/fix/round-N/`、`spec/visual-verify/`），**禁落会话临时目录**。本 skill 自有脚本是 thin wrapper——`python <本skill>/scripts/<name>.py` 实际转发 `vendor/hmigbot` 内同名 helper，脚本名必须以 §4 命令表/§10 单写者分区为唯一依据，不得虚构。

# arkts-visual-verify — iOS↔鸿蒙视觉与交互对齐

## 0. 定位与纪律

- **前置**：读到 `spec/baseline/ui-manifest.md`、页面 spec（`page_NNNN_*.md`）、`ios-semantics.json`、`spec/ref/ios-ui-facts.md`（导航/身份事实）与目标构建版本；由 `arkts-scenario-runner` 承担“到态”。缺前置 → 只分析源码布局与目标画面，对应结论标 **`source_visual_unverified`**，不阻塞起步。
- **输入**：ui-manifest、页面 spec、ios-semantics、**独立源截图/运行证据**（真实 iPhone 采集或用户提供，非预览图）与目标构建版本。
- **输出**（见 §3）：
  - UI 差异 `spec/fix/round-N/ui/*.md`（`ALIGN_/URL_/CRASH_` 前缀），功能差异 `spec/fix/round-N/feat/*.md`（kind=IMPL_MISSING）；
  - 轮次汇总 `spec/fix/round-N/_index.md` / `_summary.md` / `_delta.md`；
  - 人类报告 `spec/visual-verify/report.md`；进度 `spec/visual-verify/progress.json`；
  - 双端截图各自落 `spec/visual-verify/screenshots/{ios,harmony}/<page>__<tag>.jpeg`（**iOS 与鸿蒙各自独立 evidence，不可互代**）。
- **唯一交互点**：只有需要用户补 iOS 真机证据/账号授权时提问（如“请提供 X 页登录态截图”）；其余机械检查由 exit code 判定（0=PASS，1=FAIL，2=用法错），禁交互追问。
- **第一条可见输出**必须是一行阶段计划（到态 → 采集 → 逐项核对 → 写 diff → 派 fixer → 重验 → 收口），然后才开始执行。

## 1. 定位（独立自闭环）

对齐验证器：鸿蒙目标逐页逐态核对内容、层级、间距、对齐、颜色、字体、图片裁切、safe area、键盘与命中区；核对动作后的状态与导航——**视觉相似不代表事件接线、网络或持久化行为正确**。本 skill 只做“scan + 产 diff + 派 visual-fixer + reviewer 复核”，自身不动 `.ets`。

**修复三通道按文件所有权分流**：UI/资源差异 → `visual-fixer`；涉业务功能/接线 → 对应业务 fixer。修复后必须重建当前目标并重跑原场景；reviewer 回读新证据，**不能删除问题文件来冒充关闭**。原目标 ArkTS 组件、布局、字号、安全区修复能力继续使用各自包内技能。

## 2. 100% 对齐铁律

1. **源证据真值化**：iOS 侧能采集到真实截图/录像才建立“源真值”；无源图时该页结论 = `source_visual_unverified`，**不据此判 PASS**。**不能把 Preview/mock 图当实际状态**（Preview 只是布局参考，不参与 diff 真值）。
2. **双端截图各自 evidence**：iOS 源与鸿蒙目标截图/元数据分开归档、各自带 `source_platform`、设备尺寸、系统版本、应用版本与采集时间；两端证据缺失其一 → 该对比项记 `compared=false`，不产出假 PASS。**也不能只比较两张不同场景的截图**（场景不一致 = 不可比）。
3. **同类差异不许自动判降级**：`design_difference / platform_difference / dynamic_content` 三类默认按 bug 对待，仅当 (a) 用户对话明确豁免 (b) 目标系统级 UI 无 API 干预证据 (c) 源源码证明动态随机，三选一才能改类；**所有批准差异必须引用 decision ID**。
4. **覆盖恒等**：采集集 = iOS 源覆盖集 ↔ 鸿蒙采集集双向下界对齐；鸿蒙多出组件走 `structural_diff` 的 `extra` 单兜住，不靠“多跑几页”发现。**分母是“源实际交付的页面/状态数”，不是“计划要测的数”**。
5. **视觉与功能二维覆盖**：页覆盖（页面/状态到齐）≠ 功能覆盖（行为点实测）。只对账页面不对账功能点 = 发假合格证；行为覆盖 <1.0 一律按漏测处理。

## 3. 输入与输出

### 3.1 输入路径

| 输入 | 来源 |
|---|---|
| `ui-manifest.md`（页面+page_id） | `spec/baseline/ui-manifest.md` |
| `page_NNNN_*.md`（页面 spec） | `spec/baseline/ui/` |
| `ios-semantics.json` | `spec/baseline/ios-semantics.json` |
| `ios-ui-facts.md`（导航/身份事实） | `spec/ref/ios-ui-facts.md` |
| `feature-index.md` + `features/F*.md` | `spec/baseline/`（功能对齐） |
| 源截图/录像/运行证据 | 用户采集 / Xcode 设备采集 |
| 目标构建版本 | 目标工程 build 产物戳 |

### 3.2 输出路径

| 产物 | 路径 |
|---|---|
| UI 差异 | `spec/fix/round-N/ui/{ALIGN,URL,CRASH}_*.md` |
| 功能差异 | `spec/fix/round-N/feat/*.md`（kind=IMPL_MISSING） |
| 轮次汇总 | `spec/fix/round-N/_index.md` / `_summary.md` / `_delta.md` |
| 人类报告 | `spec/visual-verify/report.md` |
| 进度状态 | `spec/visual-verify/progress.json` |
| 双端截图 | `spec/visual-verify/screenshots/{ios,harmony}/<page>__<tag>.jpeg` |

### 3.3 差异记录结构（evidence 结构，每条必填）

```jsonc
{
  "id": "ALIGN_P0001_...",
  "page": "P0001",                    // 归属页面
  "f_ac": "F001-AC02",                // 归属 F/AC
  "expected": "…",                    // 期望（源侧）
  "actual": "…",                      // 实际（目标侧）
  "source_evidence": "spec/visual-verify/screenshots/ios/…",   // 源证据
  "target_evidence": "spec/visual-verify/screenshots/harmony/…", // 目标证据
  "repro_steps": ["…"],                // 复现步骤
  "scope": {"layer": "ui|feat|resource", "owning_slice": "…"}, // 责任范围
  "acceptance": "…"                    // 验收方式
}
```

缺任一字段 → 该单退回重写，不进入修复分发。

## 4. 执行流程（骨架 + 分场景）

1. **建到态**：按 page_id 与前置态调 `arkts-scenario-runner` 实际到态；采集操作前后画面并保留日志/版本。
2. **分场景枚举**（§5 分表，逐项核对，缺一不可）。
3. **逐项核对**（§6 核对清单 + 动作后状态/导航）。
4. **写 diff**：UI 差异落 `spec/fix/round-N/ui/`，功能差异落同轮 `feat/`；按 §3.3 结构写全。
5. **修复**：按文件所有权交 `visual-fixer` 或对应业务 fixer；修复后重建当前目标并重跑原场景。
6. **复验**：reviewer 回读新证据核闭环；**不能删除问题文件冒充关闭**。

### 4.1 命令表（仅真实 CLI，短表）

| 命令 | 用途 | exit 语义 |
|---|---|---|
| `python <runtime>/scripts/a2h_ios.py source-check --harness --project <target>` | 源事实/门禁 | 0=PASS, 1=FAIL |
| `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope {ui,feature}` | 页面/功能维度事实 | 同上 |
| `python <runtime>/scripts/a2h_ios.py doctor --project <target>` | 读 host_profile：hdc 路径、设备可用性 | 同上 |
| `python <本skill>/scripts/round_budget.py …` | 轮次机械路由 | 见 §7 |
| `python <本skill>/scripts/assert_round_complete.py <target> <N> …` | 整轮硬闸 | 0/10/11/20/21/22 |
| `python <本skill>/scripts/assert_run_success.py <N>` | 单 run 成功断言 | 0/1/2 |
| `python <本skill>/scripts/check_scratch_pollution.py <target> …` | 工程卫生检查 | 0/其它 |

上述自有脚本仅在与 vendor/hmigbot helper 同名存在时调用；FAIL 一律按 §8 E266 处置阶梯。

## 5. 场景枚举分表（逐维成对比项）

按 page ID 与前置态分场景，**每页每态按以下七维展开**，各自成独立对比项：

| 维度 | 枚举值 |
|---|---|
| 设备尺寸 | iPhone 尺寸档 × 鸿蒙设备档 |
| 横竖屏 | portrait / landscape |
| 语言 | 显式语言（非默认） |
| 字体 | 系统字号缩放 / Dynamic Type 档 |
| 深色 | light / dark |
| 账号 | 未登录 / 已登录 / VIP 等前置账号态 |
| 权限 | 相机/相册/通知/定位等被拒/被允 |

各维记录来源：源侧设备/系统/应用版本 + 截图来源；无源图 → 该维 `source_visual_unverified`，仅做“源码布局 vs 目标画面”的结构核对。

## 6. 核对清单

**静态/布局**：内容、层级、间距、对齐、颜色、字体、图片裁切、safe area、键盘、命中区。
**动态/功能**：动作后的状态与导航；视觉相似 ≠ 事件接线/网络/持久化行为正确。

## 7. fix 轮次纪律

- 每轮 `round_budget.py begin [--budget N]`（默认 3 轮）→ 修 → 重建 → 重验 → `round_budget.py next` 机械路由，不自行判断“再来一轮”。`next` 退出码：0=继续下一轮 / 10=预算用尽收尾 / 11=显式 `--early-exit-on-clean` 才可能收敛 / 2=状态异常升级。
- **fix 后必须顺利出包/落在设备才算过**；构建失败按门禁阶梯修到出包（每构建点最多一次）。
- reviewer 回读**新证据**判 `fixed`；disposition 仅 verifier（下轮/复验）能写，fixer 不写；未收口 finding 原名结转，结转轮次记 frontmatter `carried_rounds`。
- “尝试过的修复方案”追加式，下轮 fixer 必读历史、假设根因+改动摘要不得与历史雷同。
- 顽固 finding（≥3 attempts 未 fixed / 跨轮 ≥3 仍 open / 连续 2 轮 `blocked_by_*`）→ 集中 mini-round 冲刺或标 `manual_review`，报告点名阻断源。

## 8. 门禁处置阶梯（E266，每个 FAIL 套用）

FAIL → 按脚本 `retry_hint`/门禁提示派修复并重跑同一命令；**最多 2 轮**；2 轮仍不过或确定模型修不了 → **记欠账放行**（账记全：修过几轮、每轮失败原因、判“修不了”的依据）；要拍板的模型自决并留痕；**任何分支不得停机呈报人工**（`gates.stage_debt=true` 时例外：仅设备/账号类门允许欠账；静态门即便开了 stage_debt 也照常修到 PASS）。

## 9. 覆盖与收口

每页每态统计，**不按截图张数算通过率**：

| 态 | 含义 |
|---|---|
| `visited` | 已到达 |
| `observed` | 已观察（采集到证据） |
| `compared` | 已与源证据比对 |
| `fixed` | 已修复 |
| `reverified` | 复验通过 |
| `not_run` | 未执行（无设备/无授权/平台不可等价，逐项记原因） |

- **无设备 / 无授权操作 / 平台不可等价的场景分别记录原因**；批准差异引用 decision ID。
- 批次结束回收所有任务与真实证据，汇总未完成项；**不能以“页面已生成”代替视觉验收**。

## 10. 单写者分区（多文件账本唯一写者）

| 文件 | 唯一写者 |
|---|---|
| `spec/fix/round-N/{ui,feat}/*.md` | batch sub-agent（visual-fixer 只能改 .ets，不写 diff） |
| `spec/fix/round-N/_*.md` | 主会话（`render_round_summary.py` 机械渲染） |
| `spec/visual-verify/progress.json` | 主会话调度脚本 |
| `spec/fix/_state.yaml`（last_verifier_results.visual-verify 段） | 本 skill 脚本 |

主会话/worker 越区手改 → 契约违规（PROCESS_VIOLATION）。

## 11. 终态契约（standalone 就是完整答案）

本 skill 给出机械终态，不依赖外部裁决：`VERDICT: BUDGET_EXHAUSTED | CLEAN_AT_EXIT | OPEN_REMAIN` + `_summary.md` + `report.md`。`CLEAN_AT_EXIT` 需三条同时成立：open==0 且 debt==0 且整轮闸 == `ALIGNMENT_CLEAN`。**`open=0` 不代表 PASS**——漏检同样呈现为 0，结论必须结合 `_summary.md` 实际比对页数。本 skill 不出业务层 PASS/FAIL/PARTIAL——是否可交付是调用方（a2h-verify/spec-evolver）基于终态的再解释。

## 12. 读取时机

| 触发时机 | 必读 |
|---|---|
| 写第一条 diff 前 | 本 skill §3.3 差异结构（禁凭记忆猜） |
| 源事实/门禁存疑 | `../ios-source-analysis/SKILL.md`、`../a2h-spec/SKILL.md` 相关段 |
| 到态/造态 | `../arkts-scenario-runner/SKILL.md` |
| 修复/复验 | `../a2h-execute/SKILL.md` 修复权属段；本 skill §7 |

## 13. 交接

- 前置门闸：`assert_run_success.py` 对应门禁 PASS + `check_scratch_pollution.py` 卫生 clean 才交接。
- 移交产物：`spec/fix/round-N/{ui,feat}/*.md`、`_index.md/_summary.md/_delta.md`、`spec/visual-verify/{screenshots,report.md,progress.json}`。
- 提示进入 `a2h-verify`（CHECK-7 读 VERDICT）或 `a2h-retrospect`；同会话可直接续跑。

## 收尾：上报本阶段用量

本 skill 的最后一步（无论经 a2h-run 还是单独触发）：

```bash
python <runtime>/scripts/a2h_ios.py usage-finish --project <target> --run-id <本轮run-id>
```

写入 `<target>/spec/reports/derived/usage-budget.json`，尽力而为。token 用量由宿主生命周期采集，本步不采集。**忽略其退出码，绝不阻断流水线。**