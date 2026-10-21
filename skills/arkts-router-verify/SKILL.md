---
name: arkts-router-verify
description: "iOS→HarmonyOS 迁移路由核验：对照 iOS 源导航（SwiftUI NavigationPath/destination/Tab/sheet/item/dismiss/深链，UIKit push/pop/present/dismiss/segue/containment）与页面 spec，静态核验鸿蒙目标入口/目的页/触发控件/参数与返回/模态状态，按“静态存在/可达/功能正确”三账对账并修复，无设备保留 not_run。当用户说“验证路由/导航迁移对不对”“检查跳转按钮有没有/绑没绑路由”“页面跳转漏没漏”“路由对账”时使用。不要用于：纯视觉/控件属性验证（用 arkts-visual-verify）、功能逻辑验证（各自 verifier）。"
metadata:
  type: verification
  domain: migration
  tags:
  - ios
  - navigation
  - verification
---

> **派发约定**：本 skill **不派发 subagent**，静态核验与修复在主会话按 §5/§6 顺序执行；到态实测委托 `arkts-scenario-runner`（不自己驱动设备）。
>
> **路径约定**：`$IOS_SRC` 从 `<target>/.migbot/config.json` 读；`<runtime>` = 本包 runtime。产物统一落 `<target>/spec/verify/route/`（**不是 skill 目录**）。本 skill 自有脚本（`hmos_extract.py`/`hmos_reachability.py`/`thin_shell_probe.py`/`build_page_mapping.py`/`build_report.py`/`diff_routes.py`/`llm_worklist.py`/`apply_llm.py`/`build_fix_plan.py`，thin wrapper 转发 vendor/hmigbot helper）只用于**目标 ArkTS 侧**；源侧导航事实来自 `ios-ui-analyzer`，不可用 Android 抽取器代跑 Swift/ObjC。

# arkts-router-verify — iOS 导航到鸿蒙的静态核验 + 修复

## 0. 定位与纪律

- **前置**：读到 `ios-ui-analyzer` 的导航/身份事实、`spec/baseline/ui-manifest.md`、目标源码、批准决策（decision ledger）。先读 `arkts-navigation-builder` 与页面 `source_anchors`；**不根据同名类型猜源路由**。
- **输入**：源导航事实（SwiftUI/UIKit 双形态）、ui-manifest 权威映射、目标 ArkTS 源码、用户/决策批准的差异处理。
- **输出**：`spec/verify/route/` 下 源路径→目标事件/目的地→证据→状态表（`ROUTE_VERIFY_SUMMARY.md` + 各 `.json` 报告）。
- **唯一交互点**：只有“修 or 不修”的产品取舍（decision/reason）需确认；其余机械核验由脚本/静态对照判定。
- **第一条可见输出**必须是一行核验计划（源导航图 → 页面映射 → 三账对账 → 修复 → 复检），然后执行。

## 1. 定位

纯静态（读源码，零设备零编译），可进 CI、可复现。核验链 `(源页 → 触发控件 → 导航调用 → 目标页/弹窗)`，三账分开记账：**静态存在 / 可达 / 功能正确**。三者独立，任意一账 PASS 不能代替其它账。

## 2. 源导航事实（iOS 双形态，逐项枚举）

| 形态 | 核验点 | 关键语义 |
|---|---|---|
| SwiftUI | `NavigationPath` 值 | 状态型路由栈的写入/读回与类型擦除 |
| SwiftUI | `navigationDestination` 分派 | 值型 destination 分派是否与 push 配对 |
| SwiftUI | `TabView` | tab 项切换与首屏、`tabItem` 身份 |
| SwiftUI | `sheet`/`fullScreenCover`/`item` | 模态呈现形态（半屏/全屏）、item 驱动 |
| SwiftUI | `dismiss` | 模态/导航返回语义 |
| SwiftUI | 深链与恢复 | `onOpenURL`、scene/state restoration 的入口可达 |
| UIKit | `push`/`pop` | 导航栈压栈/回栈 |
| UIKit | `present`/`dismiss` | 模态呈现/关闭，`modalPresentationStyle` |
| UIKit | `segue` | storyboard segue（含 `prepare(for:)` 传参） |
| UIKit | containment | 子控制器容器（addChild/tabbar 容器） |
| UIKit | 交互式返回/取消 | `interactivePopGestureRecognizer`、`dismiss` 手势 |
| 参数/返回 | 参数类型/值域、返回传值、栈清理、重复进入、权限/登录条件、模态状态反馈 | 逐条等价 |

## 3. 目标核验点（逐项核验矩阵）

对照目标 `Navigation`/`NavPathStack` 与实际事件绑定，逐条检查：

1. 页面/弹窗/触发控件**是否存在**；
2. 参数类型/值域、返回传值、栈清理、重复进入、权限/登录条件、模态状态反馈是否等价；
3. **声明页面是否真实实例化**、入口是否 `loadContent`、**动态路由是否实际注册**（注册热点 `pageMap`/`main_pages`）；
4. 触发控件 `bound=true`（onClick/事件绑定到路由/pop/dismiss），不含空壳/恒定成功回调。

三账判定：

| 账 | 判据 | 无证据时 |
|---|---|---|
| 静态存在 | 目标 struct 存在、控件存在 | 记 `missing` |
| 可达 | 页面已注册 + push/绑定在渲染可达路径上（非死 Builder/孤儿页） | 记 `unreachable` |
| 功能正确 | 参数/返回/栈/模态行为等价；`arkts-scenario-runner` 实测返回与可达 | **无设备保留 `not_run`，不声称完成点击** |

## 4. 命令表（仅真实 CLI + 自有脚本）

| 命令 | 用途 |
|---|---|
| `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope ui` | 读 UI 事实（页面/导航维度） |
| `python <本skill>/scripts/hmos_extract.py` / `hmos_reachability.py` / `thin_shell_probe.py` | 目标 ArkTS 控件级抽取/可达/薄壳对账（thin wrapper） |
| `python <本skill>/scripts/build_page_mapping.py` / `build_report.py` / `diff_routes.py` | 页面映射与对账报告 |
| `python <runtime>/scripts/a2h_ios.py doctor --project <target>` | 读 host_profile 判断有无设备（决定 not_run 或实测） |

源侧**禁止**用 Android `extract_nav_graph.py` 抽 Swift/ObjC——源导航事实只能来自 `ios-ui-analyzer` 的既有事实。

## 5. 修复（改目标源码）

- 缺页/缺 handler 在**原文件按 `owning_slice` 修复**；**不能以空壳或恒定成功回调替代**。
- 弹窗与页面同为一等路由目的地，禁止以“弹窗属功能层”划出修复范围；确实修不了（依赖未迁移外部能力）逐条定性进遗留项，不按类划走。

修法速查：

| 维度 | 现象 | 修法 |
|---|---|---|
| A1-REG 注册缺失 | pushed_but_unregistered（运行时必崩） | `pageMap`/`main_pages` 补注册 |
| A1 页面不存在 | 缺 struct / 孤儿目标 | 建 `pages/X.ets` + 注册 + 来源页绑定 |
| A2 弹窗不存在 | 弹窗目的地缺 | 建弹窗组件 + 宿主 controller + 触发 `.open()` + 回调 |
| B 触发控件缺失 | 该页无对应控件/菜单项 | build()/菜单数组加项 |
| C 触发存在未绑定 | `bound=false`/空壳 | onClick/事件回调补 push 或 `openCustomDialog`/`dismiss` |
| C-back 返回键死/缺 | 返回无 `pop`/`dismiss` 绑定；模态无反馈 | 补 `pop`/`dismiss`；模态状态补反馈事件 |

## 6. 复检出报告

修完重跑 §4 目标侧脚本全链；断言：缺页/缺注册项转 wired；触发控件 `bound=true`；`not_run` 项在有设备时用 `arkts-scenario-runner` 实测可达性与返回状态补 `run` 账。最终报告 `spec/verify/route/ROUTE_VERIFY_SUMMARY.md`：verified / reopened / wontfix（带 verdict_basis）三级，缺一不可。

## 7. 产物清单（`spec/verify/route/`）

```
page_mapping.json               iOS↔鸿蒙 页面映射 + 偏差
expected_nav.json               源导航图（来自 ios-ui-analyzer 事实）
actual_nav.json                 目标控件级 + 绑定链
reachability_robust.json        三账「可达」口径
thin_shell_report.json          薄壳占位口径（字段集对账）
migration_nav_report.json       per-page 报告（静态存在口径）
diff_routes_report.json/.md     目的地覆盖 + 边级对账
fix_plan.json                   修复清单（审计轨迹）
ROUTE_VERIFY_SUMMARY.md         最终报告（模型写入）
```

## 8. 读取时机

| 触发时机 | 必读 |
|---|---|
| 执行前 | `../ios-ui-analyzer/SKILL.md`（导航/身份事实）；`../arkts-navigation-builder/SKILL.md` |
| 源路由形态/参数 | 本 skill §2 矩阵 |
| 目标注册/薄壳对账 | `references/config.md`、`references/fix-guide.md`（已有则读） |
| 弹出/模态修法 | `references/fix-guide.md` |

## 9. 交接

- 前置门闸：`ROUTE_VERIFY_SUMMARY.md` 落盘、修复项三账闭环（verified/reopened/wontfix 收口）才交接。
- 移交产物：`spec/verify/route/*`（映射/报告/summary）。
- 提示进入 `arkts-visual-verify`（视觉/行为层）或 `a2h-verify`；同会话直接续跑。

## 收尾：上报本阶段用量

本 skill 的最后一步（无论经 a2h-run 还是单独触发）：

```bash
python <runtime>/scripts/a2h_ios.py usage-finish --project <target> --run-id <本轮run-id>
```

写入 `<target>/spec/reports/derived/usage-budget.json`，尽力而为。token 用量由宿主生命周期采集，本步不采集。**忽略其退出码，绝不阻断流水线。**