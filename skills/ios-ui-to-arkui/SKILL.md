---
name: ios-ui-to-arkui
description: "iOS→HarmonyOS 迁移执行第 Stage 1 步：按冻结的 iOS 分页 spec 与源锚点把单个页面/组件实现为 ArkUI/ArkTS，保留 SwiftUI 状态/Binding/身份/任务语义或 UIKit 生命周期/委托/约束，复用包内 ArkTS 组件/状态/导航技能，并遵守 batch 收口、占位登记与单写者协议。当 a2h-execute Stage 1 派发页面 converter/worker，或用户说“把 iOS 页面转 ArkUI”“实现该页鸿蒙 UI”时使用；不要用于：源 UI 分析与页面 spec 生成（用 ios-ui-analyzer/a2h-spec）、资源/国际化/身份转换（用 ios-resources-convert）、业务 VM/数据层实现（归对应 slice worker）。"
metadata:
  type: domain
  domain: migration
  tags:
  - ios
  - arkui
  - execute
  - source-evidence
---

> **调用关系**：本 skill 是 a2h-execute Stage 1 的页面 converter/worker 角色，由 `a2h-execute` 按冻结任务书派发（`fork_turns:"none"`，任务书含 page_id/spec_refs/ac_ids/owned_files）。派发前主控写预期产物清单；本 worker **只写被分配的页/组件文件**，共享装配、结构闭包、编译与 brief 由原 batch closer 统一执行。遵守 Join 协议：完成的唯一合法信号是 `agent_status=completed`；completed≠验收（join 点跑门禁验产物）；谁派谁收。本 worker **不派发下级子代理**。
>
> 路径约定：`$IOS_SRC` = 源根；`<target>` = 目标根；`<runtime>` = 本包 runtime。任务输入（page_id、source_root、page_spec、ui_info、owning_slice、wiring_ownership_map、registered_placeholders、owned_files、原生 facts）全部来自冻结计划与回执，**计划只读**。本 skill 自有：`references/semantic-mapping-v2.md`、`references/conversion-decisions.md`、`scripts/run.py`。

# ios-ui-to-arkui — iOS 页面到 ArkUI 的实现

## 0. 定位与纪律

- **前置**：a2h-execute 已完成 Stage 0（资源/身份）与计划冻结；本 skill 由 dispatch 派发，输入为冻结任务书。先加载 `../ios-source-analysis/references/harness-v2.md`（v2 协议决定机器产物与状态；旧版 source-check 不能代替新版门禁）。
- **输入**：page_id、source_root、page_spec（含 source_anchors/ac_ids/spec_refs/contract_refs 传递闭包）、ui_info、target、owning_slice、owned_files、原生 facts（ios-semantics 同 page ID）。
- **输出**：被分配页面/组件的真实 `.ets` 文件 + 结构化回执摘要（owned_files、导入/实例化需求、source→target 决策、placeholder 登记、新增资源请求、consumed_refs/unread_refs/contract_conflicts）。
- **唯一交互点**：无交互追问；规格缺口/冲突回 a2h-spec，不现场猜、不选任意一端。
- **第一条可见输出必须是一行实现计划**（回读 spec → 列必须保留行为 → 声明式/命令式迁移 → 布局资源核对 → 交付 closer）。
- **本 worker 不直接执行编译/结构/行为门禁**——由原 batch closer 统一执行（`compile/structural` 等）；本 skill 只保证**生成不等于行为通过**。

## 1. 支持范围

适用于源页面主要由 SwiftUI（声明式状态/组合）或 UIKit/IB（控制器/约束/委托）构成、且已生成冻结分页 spec 的场景。对以下情形**不假设直接支持**，须读 `references/conversion-decisions.md` 并留显式 TODO/P-ID，而不是凭空造行为：

- 自绘/引擎 UI（Metal/SceneKit/SpriteKit/Core Graphics/游戏循环）、WKWebView 内容桥接、相机/视频/地图叠层
- 依赖 iOS 独占系统行为（后台、StoreKit、iCloud、扩展）的状态/导航
- 业务 VM/repository、后台任务、持久化迁移——**不在本 skill 范围**，归对应 slice worker

### 1.1 结构/状态逐组件映射表

| iOS 输入 | 必须保留的事实 | 目标实现方向（需核验目标 SDK 版本） |
|---|---|---|
| VStack/HStack/ZStack | 子视图顺序、对齐、间距、条件 | Column/Row/Stack 与目标布局约束 |
| List/ScrollView/ForEach | identity、选择、更新与复用、滚动行为 | List/Scroll/Repeat；显式稳定 key |
| @State / StateObject / ObservedObject | 持有者、初值、身份重置边界 | @Local/@ObservedV2/@Trace；按目标状态版本实现，非名称替换 |
| @Binding | getter/setter、回写与校验 | @Param/@Event 或受控接口；保留单一 owner |
| Environment | 注入值、覆盖子树、依赖 | Provider/Consumer 或显式参数；保持作用域 |
| task(id:)/onAppear | 启停、取消、重入、副作用 | 显式任务/生命周期适配；防旧结果覆写 |
| NavigationStack/NavigationPath/sheet(item:) | 路由值、目的地分派、dismiss | Navigation/NavPathStack 与呈现状态模型 |
| TabView/toolbar | 选中态、tab 数、子页保活 | Tabs/底部栏状态模型 |
| UIViewController | containment、出现/消失、Scene | 页面/组件/生命周期适配对象 |
| Auto Layout | 优先级、relation、intrinsic size | 布局规则与条件；不拷固定像素 |
| IB outlet/action | 连接 ID、实际 handler、参数 | 组件字段/回调与真实 VM 接线 |
| delegate/data source | 弱引用、调用顺序、复用状态 | 接口/事件适配、显式 owner 与注销 |
| Representable/HostingController | make/update/dismantle、Coordinator | 拆分双边生命周期与反馈环 |

### 1.2 基础控件逐组件映射表

| iOS 控件（SwiftUI / UIKit） | 必须保留的事实 | 目标实现方向 |
|---|---|---|
| Text / UILabel | 文案、字体/字号/字重、截断/换行、对齐、动态字级 | Text + 目标文本属性；截断与换行逐项核对 |
| Image / UIImageView | 源资源名、contentMode、tint/渲染、圆角/裁剪 | Image + `$r('app.media.xxx')`；contentMode→objectFit 逐项映射 |
| Button / UIButton | 标题、触发动作、禁用态、命中区 | Button + onClick；禁用态与命中区不丢 |
| TextField / UITextField | 初值、占位、键盘类型、校验、onSubmit | TextInput + onChange；键盘/输入法类型映射 |
| Toggle / UISwitch | 绑定值、初始化、开启文案 | Toggle/Switch + 状态绑定；保留初始极性 |
| Slider / UISlider | 范围、步长、值绑定、onEditingChanged | Slider + onChange；步长与首尾取值 |
| Picker / UIPickerView | 选项、选中值、联动 data source | Select/自定义选择器；选中与联动分别处理 |
| Alert / UIAlertController | 标题/消息/按钮/取消、触发条件 | 对话框组件；取消与 destructive 顺序保留 |
| NavigationLink / push segue | 目的地、参数、返回 | Navigation 跳转；参数与返回语义保留 |
| Gesture（tap/swipe/longPress） | 触发源、手势冲突、命中节点 | gesture 绑定；命中区与冲突优先级核对 |

> 完整逐项验收见 `references/semantic-mapping-v2.md`；决策顺序见 `references/conversion-decisions.md`。上面是概要，不是空壳说明——每个接缝要形成 fact→decision→task→AC→observation。

### 1.3 布局与约束参数表（不按字面平移）

| iOS 参数 | 处理 |
|---|---|
| point 坐标/尺寸 | 与目标 vp 不作无条件等比承诺；结合 safe area、系统字体、动态字级、缩放核对 |
| 水平 margin + `width('100%')` | 目标 margin 计入组件自身尺寸——把水平 margin 下沉为父级 `padding`（或 `calc(100% - Nvp)`），垂直 margin 保持 |
| safe area / safeAreaInsets | 目标安全区（刘海/挖孔/手势条）逐场景适配，不照拷 inset 数值 |
| intrinsic size / hugging / compression | 记录优先级与 relation，转成目标布局规则，不拷固定像素 |
| 隐显（hidden/alpha/removed） | 三种不同态；默认极性照抄 iOS 侧初值；隐藏、透明、移除布局不能互相替代 |

### 1.4 不可映射兜底

自绘/引擎 UI、WKWebView 内容桥接、相机/视频/地图叠层、iOS 独占系统行为等——**无可行方案时不得声称通用自动转换成功**；给具体边界与候选替代，登记 TODO/P-ID，回 `references/conversion-decisions.md` 走 decision 而非 fix。

## 2. 读必需参考（写代码前）

1. `references/semantic-mapping-v2.md`（语义接缝与独立验收）
2. `references/conversion-decisions.md`（决策顺序：视觉不等价走 fix、平台行为不等价走 decision、未知源行为回源）
3. `../arkts-component-builder/SKILL.md` 的 iOS 参照模式与 V2 参考；需状态/导航时读 `../arkts-state-manager/SKILL.md`、`../arkts-navigation-builder/SKILL.md`
4. `../a2h-execute/references/agent-prompts/_common.md`（占位 6 类 kind、P-ID 发号、HANDOFF、单写者、consumed_refs 契约）

**不要只引用技能名而不读其实际约束。**

## 3. 输入、所有权与消费纪律

- 源只读；本 worker 只写被分配的页/组件。共享导航、注册、资源账本交 batch closer；功能 VM/repository 交所属 slice，**不能抢写**或用独立样例替代应用接线。
- 按 `_common.md` 消费冻结输入：只读索引或页摘要不算消费；每次返回 `consumed_refs`/`unread_refs`/`contract_conflicts`。读取预算超出时分批读或拆任务，**未消费输入不能被 deferred 描述掩盖成完成**。
- page 与共享动作合同冲突时，提供两端路径/动作 ID、冲突点、source_anchor/fact ID，**回 a2h-spec 裁定，不自行选一端**。

## 4. 迁移一批（Stage 1 执行）

1. 回读分页 spec、source_anchors 与 ios-semantics 同 page ID。读取真实源文件、子视图和事件实现；核对源 hash，缺失/歧义回 a2h-spec。联读组件树、条件分支、布局约束、资源与具体 ArkUI 映射；只有概述或未解决 unknown 时返回规格缺口，**不能现场猜尺寸和状态**。
2. 列出必须保留的行为：初态、状态所有权、条件显示、输入/输出、导航、副作用时机、取消、布局/命中、资源与无障碍。原生机制和目标方案分开记录。
3. SwiftUI 先迁移声明式层级与状态数据流，再迁移 modifier 有序效果（`padding().background()` 与反序效果不同，保存原链）、身份键、Binding 回写与 Environment 范围；task/id 改变和取消在显式生命周期适配层实现。
4. UIKit 先把 controller/view containment、约束与事件图转成页面组件和布局关系，再明确 delegate/data source、复用状态、生命周期和导航的目标责任对象。
5. 复用 ArkTS 组件/状态/路由/资源技能写真实 `.ets`。目标 API 与状态版本以目标工程锁定配置为准，**不因 SwiftUI 有 @State 就直接使用同名目标装饰器**。
6. 业务暂未实现时登记 P-ID/FWD-REF，写清触发条件、唯一 owning_slice 与到期点；**不能把空 handler、恒定假数据或跳过导航写成已实现**。
7. 页面函数与 ViewModel 接口使用 plan 的结构化对；调用、实例化与反馈均要接通。**仅文件存在或结构扫描通过不能证明按钮行为**。

## 5. 布局与资源核对

- 保持源码声明的布局意图。iOS point 与目标 vp 不作无条件等比承诺；结合 safe area、系统字体、动态字级、缩放、屏幕配置校验目标结果（见 §1.3 参数表）。
- 颜色/图片/字体走 ios-resources-convert 的映射；SF Symbols 无同名目标资源保证（只记录符号含义与许可/版本约束）。
- **不凭截图抹掉源码中的隐藏态、返回语义、VoiceOver 标签或键盘/focus 行为**；隐藏、透明、移除布局是三种不同状态，默认极性照抄 iOS 侧初值。
- 显隐绑定三条硬规矩照 `_common.md`「显隐绑定铁律」执行：默认极性=iOS 默认、声明即接线、逐条核销。

## 6. 交付到原 closer

返回实际 owned_files、组件导入/实例化需求、source→target 决策、placeholder、新增资源请求、未解决事实、需验证场景。原 batch closer 负责共享装配、结构闭包、编译与 brief；主控按 apply_writeback 原协议落盘，**不在 plan 回填状态**。回执分列 `generated/compile/structural/behavior/visual`；无设备时 `generated/compiled` 为真实状态，`visual/device=not_run`，**不得把结构/编译通过标成行为/视觉 PASS**。

## 7. 硬约束

- **禁止**写 owned_files 之外的任何文件；共享文件只有 `spec/placeholder-registry.md` 的 P-ID 登记行与共享资源 JSON append 两项例外（`_common.md` 单写者纪律）。
- **禁止**跳过 batch closer 的编译门；本 worker 结束时不保证已编译，**不得在本批文件中留 syntax/build 错误宣称完成**。
- **不得**用空 handler、静态假列表、目标硬编码预期冒充行为实现；**不得**用结构扫描通过证明按钮行为。
- **不得**把未执行检查记为 PASS；未消费输入、contract_conflicts、unknown 必须回 spec/计划。
- **不得**在无可行方案时声称通用自动转换成功；复杂引擎/自绘/闭源 UI 须给具体边界与候选替代。

## 8. 读取时机（references）

| 触发时机 | 必读文件 |
|---|---|
| 执行前；机器产物/状态写者存疑 | `../ios-source-analysis/references/harness-v2.md` |
| 每个接缝的验收判据 | `references/semantic-mapping-v2.md` |
| 视觉/平台差异决策顺序 | `references/conversion-decisions.md` |
| 占位/P-ID/HANDOFF/单写者/consumed_refs | `../a2h-execute/references/agent-prompts/_common.md` |
| 组件/状态/导航目标实现参照 | `../arkts-component-builder/SKILL.md`、`../arkts-state-manager/SKILL.md`、`../arkts-navigation-builder/SKILL.md` |
| 目标 SDK/API 版本核实 | `../arkts-knowledge-verifier/SKILL.md`、`../hmos-sdk-docs/SKILL.md` |

## 9. 交接

- 前置门闸：本批 `.ets` 由 batch closer 结构/编译通过，残留项全部登记占位或回 spec。
- 移交：owned_files 清单、导入/实例化需求、source→target 决策、placeholder(P-ID)、新增资源请求、consumed_refs/unread_refs/contract_conflicts、需验证场景。
- 下一步提示：交原 batch closer（共享装配/结构闭包/编译/brief）；业务 VM/数据层交所属 slice；视觉/行为验证在 a2h-verify 阶段。