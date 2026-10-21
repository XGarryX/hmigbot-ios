---
name: ios-ui-analyzer
description: "iOS→HarmonyOS 迁移源分析第 UI 步：从 SwiftUI 组合/状态/Binding/身份/环境、UIKit 控制器/约束/outlet/action/委托/生命周期、以及 Interface Builder（Storyboard/XIB）三源静态一致地提取 UI 与交互事实，写页面事实与原生语义供 a2h-spec 生成 ui-manifest 与分页 spec。当用户说“分析这个 iOS 项目的界面/UI”“UI 建模”“组件关系”“页面跳转”或 a2h-spec/ios-source-analysis 组织源分析时使用；不要用于：功能行为与业务规则（用 ios-feature-analyzer）、系统 API/权限/三方接缝（用 ios-api-inventory）、生成 ArkUI 代码（用 ios-ui-to-arkui）。保持 SwiftUI/UIKit/Swift/Objective-C 语义，无运行时截图绝不伪造。"
metadata:
  type: domain
  domain: migration
  tags:
  - ios
  - ui
  - source-analysis
  - source-evidence
---

> **调用关系**：本 skill 是 `ios-source-analysis` 组织的四类源分析之一（UI 主责），结果由 `a2h-spec` 收口。若宿主支持 subagent，按 `ios-ui-analyzer` 角色名派发本技能（`fork_turns:"none"`，任务书写清 page 候选、源锚点、输出契约）；不派发时主会话顺序执行。遵守 Join 协议：完成的唯一合法信号是 `agent_status=completed`，绝不是产物文件存在；completed≠验收通过，join 点跑门禁验产物；谁派谁收。本 skill 只读源、写分析事实，**不派发下级迁移 worker、不写目标代码**。
>
> 路径约定：`$IOS_SRC` 从 `<target>/.migbot/config.json` 的 `ios` 字段读取；`<target>` = 鸿蒙目标根；`<runtime>` = 本包 runtime（`scripts/a2h_ios.py` 所在根）。产物落 `<target>/spec/ref/` 与 `<target>/spec/baseline/`，**禁落会话临时目录**。本 skill 自有文件：`references/analysis-v2.md`（逐页执行步骤与正反例）、`scripts/run.py`（runtime 定位）、`agents/openai.yaml`。

# ios-ui-analyzer — iOS 界面、状态与导航事实

## 0. 定位与纪律

- **前置**：上游（a2h-spec/ios-source-analysis）已跑 `harness-init` + `source-index` + `facts`，`spec/baseline/ios-facts.json` 与 `ios-obligations.json` 存在。缺 → 提示先跑上游（a2h-spec §1），**不代跑**。本 skill 先加载 `../ios-source-analysis/references/harness-v2.md` 确定机器产物/状态写者。
- **输入**：工程地图（`spec/ref/ios-project.md`）、target/configuration、页面候选、真实 Swift/ObjC + SwiftUI/UIKit + Storyboard/XIB 源码、机器 UI 信号。**源不可读是阻塞**，不以页面名或旧报告补造结构。
- **输出**：`spec/ref/ios-ui-facts.md`（本 skill 单写的人类可读分析）+ 每 page 的源原生语义事实；随后由 a2h-spec 的 `spec-authoring` 落为 `spec/baseline/ios-semantics.json` 的 page 部分（机器校验，见 `../ios-source-analysis/references/native-facts.md`）。**本 skill 不直接手写 `ios-semantics.json`/`ios-coverage.json`/`ios-obligations.json`（机器单写）**，只提供 page 源语义与 `ios-ui-facts.md`。
- **唯一交互点**：无交互追问；歧义回源证据，不回用户。机械检查由 exit code 判定（0=PASS，非 0=FAIL）。
- **无人值守**：机器信号缺失/过期 → 按 §1 阶梯回上游重跑，最多 2 轮；确实取不到 → 记 unknown 与补证步骤，**不伪造布局树**。
- **第一条可见输出必须是一行 UI 分析计划**（读信号 → SwiftUI 路径 → UIKit/IB 路径 → 混合 UI → 页面身份穷举 → 交互证据与收口），然后才开始 §1。

## 1. 机器事实与信号读取

| # | 命令 | 产物 | exit code / 失败处置 |
|---|---|---|---|
| 1.1 | `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope ui` | `spec/ref/ios-ui-signals.json`（state/binding/event/navigation/lifecycle/constraint/identity/composition/modifier/environment/delegate 十类信号 + obligations） | exit 0 有效；非 0（事实过期/未提取）→ 回 `ios-source-analysis` 重跑 `facts` 后重试，最多 2 轮；仍失败记欠账，**禁手改信号** |
| 1.2 | （可选符号证据）`python <runtime>/scripts/a2h_ios.py mcp-query --project <target> --server <server.json> --request <query.json>` | `spec/ref/mcp-runs/MCP-ID/{artifact,transcript,stderr}.json` + `ios-mcp-index.json` | 失败/超时写 failure.json，绝不写成功索引；真实服务缺工具保留 unavailable/unknown，**禁止换假服务凑通过** |
| 1.3 | 交付前诊断 `python <runtime>/scripts/a2h_ios.py source-check --harness --report-only --project <target>` | 不更新 findings/门禁报告的只读诊断 | 非 0 → 按 §7 阶梯补事实 |

- 信号只是待审线索，不是视图运行树；逐个点开信号指向的源代码片段与调用点，**按 §2–§5 解释语义**，不把 token_signal 写成 compiler_binding 或 runtime。
- `NA_CONTRADICTION`、`STATE_VALUE_CONTRADICTION`、`CLAIM_SIGNAL_MISSING` 三类 findings **不允许**以“页面已生成”关闭；只能由产生它的检查复跑后关闭。

## 2. SwiftUI 路径

1. 展开 `body`、`@ViewBuilder`、条件/循环、子 View、`ViewModifier`、自定义 `Layout`，保留层级、参数、条件表达式与 `ForEach` 身份键。**不把结构压成截图控件列表**。
2. 按调用顺序记录 modifier 链：`padding/background/frame/clipShape/overlay` 顺序影响布局、绘制与命中区域。记录 safe area、alignment、`layoutPriority`、`fixedSize`、`GeometryReader`、`PreferenceKey`/`AnchorPreference` 的依赖方向。
3. 为每个状态记录存储者、初值（保留源表达式文本）、生命周期、全部读写者与变化后 UI。区分 `@State`/`@StateObject`/`@ObservedObject`/`@EnvironmentObject`/`Observable`/`@Bindable`/`@Binding`/`@Environment`/`@AppStorage`/`@SceneStorage`。**不能仅按装饰器拼写判等价**。
4. `Binding` 追到 get/set 与真正源状态；值类型 copy、对象引用共享、派生值分别建模。View identity 变化导致的状态重建与 `body` 重算分开记录；`.id(...)`/列表身份/条件移除是否重置状态按实际存储者与身份证据裁定。
5. 记录 `task`/`task(id:)`、`onAppear/onDisappear`、`onChange`、Combine 订阅的启动、取消、线程/actor 与副作用去重。**不能把所有出现回调都改为只执行一次**。
6. `NavigationStack`/`NavigationPath` 的值、destination 分派、pop、深链、恢复；`sheet(item:)`/`sheet(isPresented:)`、`fullScreenCover`、`alert`/`confirmationDialog`、`popover`、`TabView` 选择均保存其状态驱动关系。

## 3. UIKit 与 Interface Builder 路径

1. `UIViewController`/自定义容器、navigation/tab/split controller、子控制器 containment 分层记录；追 `viewDidLoad`、出现/消失、trait 与 Scene 生命周期的真实副作用。**控制器生命周期 ≠ 视图创建次数**。
2. Storyboard/XIB 保存 object ID、`customClass/module`、`IBOutlet`/`IBAction`、segue、prototype/reuse identifier；继续读程序化创建与运行时 override。**IB 与程序化改动共同决定运行布局，不把 IB 文件当全貌**、也不拿程序化覆盖抹掉 IB 初值。
3. Auto Layout 记录 first/second item、relation、constant/multiplier、priority、active 条件；content hugging/compression resistance、intrinsic size、safe area **不能只压成绝对坐标**；资源尺寸来自 source/asset scale/真实布局，不靠文件像素猜点数。
4. 追 target-action、gesture recognizer、delegate/data source、Notification/KVO、collection/table diffable snapshot 与复用生命周期。记录回调顺序、cell 复用与选择状态恢复。**状态写说明被哪些 view 读取；禁止只登记 Button 和 addTarget 的存在**。
5. 导航同时保留 push/pop、present/dismiss、segue 条件、交互式返回取消、路由参数。

## 4. 混合及特殊 UI

- `UIHostingController` 与 `UIViewRepresentable`/`UIViewControllerRepresentable` 保留双边生命周期：`make/update/dismantle`、Coordinator/delegate、状态反馈与资源清理。
- `WKWebView`、Metal/SceneKit/SpriteKit、自绘 Core Graphics、地图/相机/视频叠层，按“承载”与“内容”分开记录；other 页面在 composition 中说明引擎/承载。**插件只提供分析框架，不保证任意引擎自动转写**，不声称有自动转换器。

## 5. 页面身份与二三层UI来源穷举

从应用根、路由目的地、presented controller、sheet/popover、扩展入口找页面候选。小型可复用 View 不自动算独立页面；page ID 按入口与功能稳定分配。同一页面的 loading/empty/error/content、登录态/权限态是状态，不随意拆成重复页。

按以下信号穷举二/三层 UI（下游 `arkts-ui-coverage-auditor` 依赖完整识别；漏识别 → 其启动校验 `BUILDER_INCOMPLETE`）：

| # | 信号（SwiftUI） | 层级 | # | 信号（UIKit/IB） | 层级 |
|---|---|---|---|---|---|
| 1 | `sheet`/`fullScreenCover`/`popover` | 二层 | 6 | `present(_:animated:)`/`UIAlertController` | 二/三层 |
| 2 | `alert`/`confirmationDialog` | 三层 | 7 | `pushViewController`/`show`/segue | 一/二层 |
| 3 | `NavigationStack` destination 分派 | 一/二层 | 8 | 自定义容器/child containment | 二层 |
| 4 | `TabView` 每项 | 二层 | 9 | `UIWindowScene` 多窗口/扩展入口 | 根/扩展 |
| 5 | 页内 `when(状态)` 全屏分支 | 二/三层 | 10 | App Clip/Widget/分享等独立 target | 扩展 |

命中 → 必须产生对应 page 节点（带正确 framework 归属与 page ID）；`when(uiState){Loading/Success/Error}` 等加载/错误态不是页（不拆）。记录 iPhone/iPad、横竖屏、多窗口、语言/动态字体条件；无源码证据的条件保留 unknown。

## 6. 交互证据与收口

- 为用户可触发事件记录：前置态 → 动作 → 状态变更 → 可观察 UI/导航/副作用。跨页/异步动作引用 `../a2h-spec/references/action-contracts.md` 的动作 ID，**禁止在页面重写另一套取消/完成语义**。
- 源码初值优先于 Preview；预览专用假数据、mock Environment、截图仅用于标注。**没有 iPhone 录制不生成运行观察结论（runtime=not_run）；没有运行时截图不伪造（screenshot=null，runtime=not_run 合法）**。
- 有设备证据时须含版本、设备、入口、动作、时间与文件引用；运行截图只能补充该场景观察，不能取代约束/状态分析。
- 输出每页：framework/language、入口、source_anchors（path/role/symbol/line）、组合、有序 modifier、状态所有权、事件链、导航/返回、布局、variants/accessibility、unknown。事实不完整写 unknown 与补证步骤，**不生成假布局文件**。
- 动态字符串、无障碍名称、RTL、键盘/focus、手势冲突、深色模式逐项交代。

## 7. 硬约束

- **禁止**手改 `facts-view`/`facts` 产出的机器信号、`ios-facts.json`、`ios-obligations.json` 及任何状态账本（PROCESS_VIOLATION）。
- **不得**把 IB 文件当布局全貌，也**不得**用程序化覆盖抹掉 IB 初值——两者合成运行布局。
- **不得**伪造截图、布局树或运行观察；无运行证据时 `screenshot=null`、`runtime=not_run` 是合法值。
- **不得**仅按装饰器拼写判定状态等价；**不得**把 `body` 重算等同于重新创建所有状态。
- **不得**用“已处理/页面已生成/N/A”清空 unknown 维度；unknown 必须带原因与补证步骤。
- **不越权**：业务计算规则归 ios-feature-analyzer；系统 API/权限归 ios-api-inventory；本 skill 不写 ArkUI。

## 8. 读取时机（references）

| 触发时机 | 必读文件 |
|---|---|
| 执行任何步骤前；机器产物/状态写者存疑 | `../ios-source-analysis/references/harness-v2.md` |
| 源事实字段、identity/state/evidence 规则 | `../ios-source-analysis/references/native-facts.md` + `source-semantics.md` |
| 外部资料/MCP 证据 | `../ios-source-analysis/references/external-expertise.md` |
| 逐页填录与正反例 | `references/analysis-v2.md` |
| 转页面行为与状态接口 | `../a2h-spec/references/spec-delivery-contract.md` + `../a2h-spec/templates/page-spec-template.md` |

## 9. 交接

- 前置门闸：本 skill 产出的 page 语义经 `source-check --harness`（由 a2h-spec 正式执行）无新增 finding 后交接。
- 移交：`spec/ref/ios-ui-facts.md`、每 page 的源语义事实（composition/layout/state_ownership/events/navigation/accessibility 及 SwiftUI/UIKit 附加维度）、未被解释的 unknown 与现象清单。
- 下一步提示：交 `a2h-spec`（Phase B 生成 `ui-manifest.md` 与分页 `page_NNNN_*.md`）；功能/API 事实分别归 ios-feature-analyzer/ios-api-inventory。