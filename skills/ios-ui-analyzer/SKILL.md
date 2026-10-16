---
name: ios-ui-analyzer
description: "按 SwiftUI、UIKit、Interface Builder 和桥接场景提取 iOS UI 与交互事实；保留状态所有权、Binding、视图身份、modifier 顺序、控制器生命周期、约束、事件和导航，供 a2h-spec 使用。"
---

## 执行前加载

按 [Harness v2](../ios-source-analysis/references/harness-v2.md) 确定机器产物/状态写者；按 [外部资料规程](../ios-source-analysis/references/external-expertise.md) 执行expertise-plan/review，未连接工具保持unknown/unavailable。

执行 `python <runtime>/scripts/a2h_ios.py facts-view --project <target> --scope ui`，读取真实 `spec/ref/ios-ui-signals.json` 后继续读源码。加载 [逐页执行步骤与正反例](references/analysis-v2.md)，按页面模板填写核心表、状态与交互；不得手改机器信号，也不采用上游重构建议改写源行为。

# iOS 界面、状态与导航事实

事实进入 baseline 前按 [规格交付合同](../a2h-spec/references/spec-delivery-contract.md) 转为页面行为与目标状态接口。保持生产/Preview/平台条件边界，明确状态身份和持有/借用、事件回写、资源/生命周期，不把每个语法信号都变成 AC。

## 输入与产物

输入工程地图、具体 target/configuration、页面候选与真实源码。
写 `spec/ref/ios-ui-facts.md` 及 `ios-semantics.json` 的 page 部分，
由 a2h-spec 形成 `ui-manifest.md`、分页 spec 和 snapshot/meta。
必读 `ios-source-analysis/references/native-facts.md`、
`ios-ui-to-arkui/references/conversion-decisions.md`，后者只用于记录迁移约束。

## 1. 确定页面身份

从应用根、路由目的地、presented controller、sheet/popover 和扩展入口找候选。
小型可复用 View 不自动算独立页面；page ID 根据入口与功能稳定分配。
同一页面的 loading/empty/error/content、登录态与权限态是状态，不随意拆成重复页。
记录 iPhone/iPad、横竖屏、多窗口、语言/动态字体条件；无源码证据的条件保留未知。

## 2. SwiftUI 路径

1. 展开 `body`、ViewBuilder、条件/循环、子 View、ViewModifier、自定义 Layout，
   保留层级、参数、条件表达式及 `ForEach` 的身份键，不把结构压成截图控件列表。
2. 按调用顺序记录 modifier 链；`padding/background/frame/clipShape/overlay` 顺序
   会影响布局、绘制和命中区域。记录 safe area、alignment、layoutPriority、
   fixedSize、GeometryReader、PreferenceKey/AnchorPreference 的依赖方向。
3. 为每个状态记存储者、初值、生命周期、所有读写者与变化后 UI。
   区分 State、StateObject、ObservedObject、EnvironmentObject、Observable/Bindable、
   Binding、Environment、AppStorage、SceneStorage。不能仅按装饰器拼写判等价。
4. Binding 追到 get/set 与真正源状态；值类型 copy、对象引用共享及派生值分别建模。
   View 身份变化导致状态重建，与 `body` 重算分开记录。
5. 记录 task/task(id:)、onAppear/onDisappear、onChange、Combine 订阅的启动、
   取消、线程/actor 与副作用去重。不能把所有出现回调都改为只执行一次。
6. NavigationStack/NavigationPath 的值、destination 分派、pop、深链、恢复，
   sheet(item:)/sheet(isPresented:)、fullScreenCover、Tab 选择均保存其状态驱动关系。

## 3. UIKit 与 Interface Builder 路径

1. UIViewController/自定义容器、navigation/tab/split controller、子控制器 containment
   分层记录；追 viewDidLoad、出现/消失、trait 与 Scene 生命周期的真实副作用。
2. Storyboard/XIB 保存 object ID、customClass/module、IBOutlet/IBAction、segue、
   prototype/reuse identifier；继续读程序化创建和运行时 override，不把 IB 文件当全貌。
3. Auto Layout 记录约束项、relation、constant/multiplier、priority、active 条件；
   content hugging/compression resistance、intrinsic size、safe area 不能只压成绝对坐标。
4. 追 target-action、gesture recognizer、delegate/data source、Notification/KVO、
   collection/table diffable snapshot 与复用生命周期。记录回调顺序及选择状态恢复。
5. 导航同时保留 push/pop、present/dismiss、segue 条件、交互式返回取消、路由参数。

## 4. 混合及特殊 UI

UIHostingController 与 UIViewRepresentable/UIViewControllerRepresentable 保留双边生命周期，
make/update/dismantle、Coordinator/delegate、状态反馈和资源清理。
WKWebView、Metal/SceneKit/SpriteKit、自绘 Core Graphics、地图/相机/视频叠层，
按承载与内容分开记录；插件只提供分析框架，不保证任意引擎自动转写。

## 5. 交互证据与收口

为用户可触发事件记录前置态 → 动作 → 状态变更 → 可观察 UI/导航/副作用。
源码初值优先于 Preview；预览专用假数据、mock Environment 和截图仅用于标注。
无设备时 runtime_status=not_run，不制造截图或点击记录。
可用 iPhone/Xcode 运行证据需含版本、设备、入口、动作、时间与文件引用。

输出每页框架、语言、source_anchors、原生语义、状态矩阵、路由与资源引用。
事实不完整时写 unknown 和获取步骤，交源分析继续追；不要生成假布局文件。
动态字符串、无障碍名称、RTL、键盘/focus、手势冲突与深色模式都要逐项交代。
