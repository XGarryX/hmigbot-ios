# page_0001 — CounterScreen

```yaml
source_platform: ios
source_languages: [swift]
ios_frameworks: [swiftui]
contract_refs:
  - spec/baseline/features/F001-counter.md#服务层（ArkTS 目标接口）
  - spec/baseline/features/F001-counter.md#状态管理
source_anchors:
  - role: view
    path: Counter.swift
    symbol: CounterScreen.body
    line: 27
  - role: state_owner
    path: Counter.swift
    symbol: CounterStore
    line: 3
```

## 页面与范围

源为CounterScreen.body，关联功能F001，目标页面组件为CounterScreenPage。该片段没有App根或导航调用点；只证明可构建的View，实际宿主呈现、target/configuration和设备尺寸unknown。评测中将它视为一个页面候选，不宣称已证明全屏入口可达。没有权限或登录前提。

本次产物局限为feature/page/meta三件，未生成完整ios-semantics或工程索引；不声称任何阶段门禁通过。

## iOS 原生语义

StateObject在CounterScreen身份内拥有单一CounterStore；Published count/message由两个Text读取。没有Binding、Environment、ForEach、条件子树、显式id、task视图修饰符或导航。保存任务属于store的显式Task字段，不能因没有.task修饰符就遗漏取消与存储行为（Counter.swift:3-22,26-35）。

body创建VStack，先计数字符串，再消息文本，再Add/Save/Cancel按钮；VStack的spacing=16，之后对整个容器应用padding(20)。文本字体、颜色、按钮样式、容器对齐、宽高及safe area没有显式覆写，随实际SwiftUI宿主/系统默认；未采集运行画面，不能给出固定颜色或截图尺寸。无UIKit/IB/桥接内容，相关控制器/约束/委托不适用。ios-semantics的page_0001伴随记录本次未生成。

## 页面结构与视觉

```text
CounterScreen（拥有store）
└─ VStack(spacing: 16) → padding(20)
   ├─ Text("Count: <store.count>")
   ├─ Text(store.message)
   ├─ Button("Add") → store.add
   ├─ Button("Save") → store.save
   └─ Button("Cancel") → store.cancel
```

结构由Counter.swift:28-35确定，没有随保存状态隐藏、替换或禁用按钮的分支。两个Text内容变化，节点序列保持不变。间距16及外padding20是源布局数值，目标先以同等逻辑尺寸表达，再以真实截图核验平台差异；不擅自设置子组件固定宽高或全屏拉伸。

safe area保留宿主默认，源没有ignoresSafeArea。横竖屏、动态字体、深色、RTL和无障碍使用原生默认行为，未有自定义规则；仍需真实宿主/设备验证。按钮使用可见文本标签，文字和计数读取顺序来自树；不得把Preview中仅有的Saved当作初始页面。源码无图片、图标、字体文件或自定义颜色资产。

## 状态接口

| 源状态与类型 | 初值/所有者/生命周期 | 读写者 | UI 影响 | 目标 Owner.state 与类型 |
|---|---|---|---|---|
| count: Int | 0；CounterStore；页面StateObject身份内 | add写，save读取捕获；计数Text读 | 显示Count: n | CounterViewModel.count: number |
| message: String | Ready；CounterStore；页面StateObject身份内 | save同步写Saving，任务写Saved/Cancelled/Failed；消息Text读 | 状态字符串原样展示 | CounterViewModel.message: string |
| saveTask: Task<Void,Never>? | nil；CounterStore私有 | save读取消并替换，cancel读；源未完成清空 | 不直接渲染；取消结果间接影响message | CounterViewModel.saveTask: CancelHandle或null |

目标模型由页面创建一次并提供反应式更新；实际ArkTS装饰器/SDK实现未核验。没有需要双向Binding的输入控件，也不建立全局计数store。

## 交互与导航

| 前置态 | 事件/入口 | 状态与副作用 | 导航值/返回行为 | 源证据 | owning_feature |
|---|---|---|---|---|---|
| 页面存在，任意消息 | Add按钮 | count+1；message不变 | 无导航 | Counter.swift:7,31 | F001 |
| 页面存在，count=n | Save按钮 | 旧任务cancel→Saving→捕获n→新任务；等待和检查后写savedCount=n再Saved | 无导航 | Counter.swift:8-20,32 | F001 |
| saveTask为nil或存在 | Cancel按钮 | 请求句柄取消；不即时写消息；取消catch执行后Cancelled | 无导航；不关闭页面 | Counter.swift:18,22,33 | F001 |

保存期Add只改变当前count，已发起保存继续使用captured。重复Save时旧任务可能晚到写Cancelled，源无latest-wins过滤；页面展示真实message，不能忽略它。保存完成后Cancel不会由handler主动改Saved或回滚偏好。页面消失没有源回调执行取消，也没有返回值合同；实际宿主未提供。

## ArkUI 映射决策

| 源机制 | 目标方向 | 保留的约束与依据 |
|---|---|---|
| VStack(spacing:16).padding(20) | Column容器，spacing 16、外padding20 | 保留五个子节点顺序；不创造固定尺寸；Counter.swift:28-35 |
| 两个Text | 绑定CounterViewModel.count/message的Text | 动态字符串及原消息取值；Counter.swift:29-30 |
| 三个Button(action:) | 明确onAdd/onSave/onCancel入口并调用模型 | 三按钮始终存在；不新增disabled条件；Counter.swift:31-33 |
| StateObject＋Published | 页面持有可观察CounterViewModel | 单一状态真值与身份内生命周期，不因重渲染重建；Counter.swift:3-6,26 |

具体目标组件API仍需目标SDK核验，系统默认按钮/字体视觉没有等价证明。公开目标方法与状态语义引用F001对应精确合同；若实现需要行为变化，先提交决策，不能在页面层临时改保存时序。

## 资源与运行证据

源中生产文字为Count:格式、Ready、Saving、Saved、Cancelled、Failed、Add、Save、Cancel（Counter.swift:5,10,17-19,29-33）。偏好键savedCount属于功能存储合同，不作为界面文案。Preview中的Saved与生产成功消息同值但来源区间分开；没有资产目录、复数规则或自定义字体证据。

runtime=not_run，screenshot=null；无iPhone/目标设备运行、截图、点击或编译记录。不将静态读取写为已观察。目标资源转换由执行阶段按这些真实文字登记，当前未声称生成resource-mapping。

## 验收与接线

F001 slice拥有onAdd→CounterViewModel.add、onSave→save、onCancel→cancel的唯一真实接线；count/message订阅触发Text更新。页面构建任务消费这些接口，不能创建重复服务状态。关联F001-AC01、AC02、AC03、AC05、AC06、AC07、AC10、AC11、AC12。

需以UI用例观察初态、Add后的计数、保存中的Saving和最终状态；以功能用例控制取消/延迟与捕获值。视觉核验五个子节点顺序、间距16和padding20，平台默认外观结合实际源系统版本比较。本次所有检查not_run，实际宿主入口和极值数值映射为后续证据缺口。
