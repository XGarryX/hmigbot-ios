# page_0001 — CounterScreen

```yaml
source_platform: ios
spec_contract_version: 2
source_languages: [swift]
ios_frameworks: [swiftui]
contract_refs:
  - spec/baseline/features/F001-counter.md#增加计数
  - spec/baseline/features/F001-counter.md#提交保存
  - spec/baseline/features/F001-counter.md#请求取消
  - spec/baseline/features/F001-counter.md#服务层（ArkTS 目标接口）
source_anchors:
  - role: view
    path: Counter.swift
    symbol: CounterScreen
    line: 25
```

## 页面与范围

page_0001为Counter.swift:25–37的CounterScreen，所属F001，目标CounterPage。该View的两个Text及三个按钮可由源码确认；未提供App/Scene或呈现调用点，无法确认是全屏、弹层、对话框还是子组件，因此meta不填写可选page_type。页面规格描述其内部结构，不声称启动路由已确定。

生产初态由CounterStore的0/Ready决定；39行#Preview的Text("Saved")是另一段内容，不代表此页初始状态或实机截图。

## iOS 原生语义

CounterScreen以@StateObject持有CounterStore（26），对象以@Published发布count/message（4–5）；两个Text读取这两个值（29–30）。所有按钮指向同一store方法（31–33），没有Binding回写、Environment注入、列表身份、条件子树、导航或sheet。

body结构为VStack(spacing:16)的五个按序子节点，随后padding(20)。没有显式frame/字号/颜色/按钮样式/disabled或safe area扩展。CounterStore的Task生命周期不等于View.task；源无onDisappear取消。页面不应另写保存/取消终态；功能合同是唯一动作定义。

完整流水线应关联ios-semantics的page_0001；该伴随文件不在本次三份产物范围。没有机器fact IDs就不伪造结构化known条目。页面身份由未提供宿主决定，U003保持未决。

## 页面结构与视觉

已知是五个常驻子节点的竖向布局；文本和控件使用源系统默认测量与样式。仅16间距及20 padding有数值证据。没有运行截图，不指定源未写的全屏居中、固定宽高、背景色、字体大小或按钮圆角；目标默认按钮样式也不自动等价源默认外观。

## 组件层级

| 节点ID | 父节点 | 源控件/条件 | ArkUI组件 | 内容/事件 | 源证据 |
|---|---|---|---|---|---|
| root | - | 常驻VStack | Column | 顺序承载五子节点 | Counter.swift:28–35 |
| countText | root | 常驻Text | Text | Count: <count>；读CounterViewModel.count | Counter.swift:29 |
| statusText | root | 常驻Text | Text | 读CounterViewModel.message的显示投影 | Counter.swift:30 |
| addButton | root | 常驻Button | Button | Add→CounterPage.handleAdd | Counter.swift:31 |
| saveButton | root | 常驻Button | Button | Save→CounterPage.handleSave | Counter.swift:32 |
| cancelButton | root | 常驻Button | Button | Cancel→CounterPage.handleCancel | Counter.swift:33 |

not_applicable: Counter.swift:28–34没有if/ForEach/overlay，不额外生成条件节点、列表键或覆盖层；状态变化只更改文本。

## 布局约束

| 节点ID | 尺寸/布局/安全区 | 条件/优先级 | 资源引用 | 源证据 |
|---|---|---|---|---|
| root | 竖排；相邻子项间距16；组合完成后四边padding20；无frame或忽略安全区 | 所有源状态相同；宿主约束未知 | counter_spacing、counter_padding | Counter.swift:28,35 |
| countText | 由内容测量；无固定宽高/font/maxLines | 常驻，count变化时文本变化 | counter_count_format | Counter.swift:29 |
| statusText | 由内容测量；未写固定字号或颜色 | 常驻，只切换消息文本 | counter_ready/saving/saved/cancelled/failed | Counter.swift:5,10,17–19,30 |
| addButton | 源默认Button布局，未指定frame/style | 没有任务状态禁用条件 | counter_add | Counter.swift:31 |
| saveButton | 源默认Button布局，未指定frame/style | 保存等待时仍可再次触发 | counter_save | Counter.swift:32 |
| cancelButton | 源默认Button布局，未指定frame/style | 无任务/已完成也存在 | counter_cancel | Counter.swift:33 |

UIKit约束relation/priority为not_applicable：源是SwiftUI且未桥接UIKit（1,25–37）。没有自定义trait/dark/动态字体或无障碍修饰；保留默认语义并在真实宿主核对。安全区沉浸策略未决，meta也不填needs_immersive_safearea以避免把缺证据写false结论。

## 状态接口

| 源状态与类型 | 初值/所有者/生命周期 | 读写者 | UI 影响 | 目标 Owner.state 与类型 |
|---|---|---|---|---|
| CounterStore.count: Int | 初值0，StateObject对象持有 | add写；save入口复制；Text读 | Count文本改变 | CounterViewModel.count: number；极值域U001 |
| CounterStore.message: String | 初值Ready，同store | save入口及Task分支写；Text读 | Ready/Saving/Saved/Cancelled/Failed | CounterViewModel.message: string |
| CounterStore.saveTask: Task<Void,Never>? | 初始nil，同store私有 | save替换、cancel请求取消 | 间接决定反馈，无额外“取消中”控件 | CounterViewModel.saveTask: 私有可取消任务句柄，具体类型U002 |

目标V2候选为CounterPage的@Local持有一个@ObservedV2 CounterViewModel，其可观察字段用@Trace；这是本地参考支持的状态表达，不是源装饰器或已编译目标。页面不另持一份count/message，不做持久化水合。

## 交互与导航

| 前置态 | 事件/入口 | 状态与副作用 | 导航值/返回行为 | 源证据 | owning_feature |
|---|---|---|---|---|---|
| 页面已由宿主创建 | Add | handleAdd调用F001-A01；count变化投影到countText | 无导航 | Counter.swift:7,31 | F001 |
| 任意任务态，包括等待中 | Save | handleSave调用F001-A02；statusText只消费VM结果，不自行赋Saved | 无导航；方法返回非保存完成 | Counter.swift:8–21,32 | F001 |
| 无/未完成/已完成句柄 | Cancel | handleCancel调用F001-A03；不在点击同步阶段写Cancelled或清空值 | 无导航；方法返回非取消完成 | Counter.swift:22,33 | F001 |

```action-use
{"action_id":"F001-A01","contract_ref":"spec/baseline/features/F001-counter.md#增加计数","ac_ids":["F001-AC02"]}
```

```action-use
{"action_id":"F001-A02","contract_ref":"spec/baseline/features/F001-counter.md#提交保存","ac_ids":["F001-AC03","F001-AC04","F001-AC05","F001-AC08","F001-AC09"]}
```

```action-use
{"action_id":"F001-A03","contract_ref":"spec/baseline/features/F001-counter.md#请求取消","ac_ids":["F001-AC06","F001-AC07"]}
```

not_applicable: Counter.swift:25–37没有NavigationStack、sheet、dismiss、返回参数或导航按钮。不能因目标页面名添加标题栏/返回按钮。

## ArkUI 映射决策

| 源机制 | 目标实现 | 约束/差异 | 源证据 |
|---|---|---|---|
| VStack及随后padding | CounterPage.build内Column({space:16})后padding(20) | 来源数值不丢；不额外指定屏幕宽高/居中；point/vp与实际宿主需视觉核对 | Counter.swift:28,35 |
| Text字符串与插值 | Text使用count格式资源、message资源投影 | 保留Count:空格及数字意义；不添加省略号/颜色 | Counter.swift:29–30 |
| 三个Button(action:) | Button.onClick→CounterPage.handleAdd/handleSave/handleCancel | 默认目标外观需验证，不能未经依据改胶囊；保持可点击入口 | Counter.swift:31–33 |
| StateObject/Published | CounterPage持有CounterViewModel的V2可观察实例 | 单一所有者，组件重绘不主动重建VM；宿主身份U003 | Counter.swift:3–6,26 |
| 异步完成反馈 | CounterViewModel.message回读至statusText | 各动作行为只引用F001合同，页面不重定终态 | Counter.swift:8–22,30 |

## 资源引用

| 资源ID | 类型 | 目标引用 | 源证据 |
|---|---|---|---|
| counter_count_format | 格式字符串 | app.string.counter_count_format：Count: <count>；Stage0规划 | Counter.swift:29 |
| counter_ready | 字符串Ready | app.string.counter_ready | Counter.swift:5 |
| counter_saving | 字符串Saving | app.string.counter_saving | Counter.swift:10 |
| counter_saved | 字符串Saved | app.string.counter_saved；生产来源17，非Preview39 | Counter.swift:17 |
| counter_cancelled | 字符串Cancelled | app.string.counter_cancelled | Counter.swift:18 |
| counter_failed | 字符串Failed | app.string.counter_failed | Counter.swift:19 |
| counter_add | 字符串Add | app.string.counter_add | Counter.swift:31 |
| counter_save | 字符串Save | app.string.counter_save | Counter.swift:32 |
| counter_cancel | 字符串Cancel | app.string.counter_cancel | Counter.swift:33 |
| counter_spacing | 尺寸16 | app.float.counter_spacing | Counter.swift:28 |
| counter_padding | 尺寸20 | app.float.counter_padding | Counter.swift:35 |

图片、SF Symbol和外置字体为not_applicable：25–37没有这些资源引用。以上目标名为Spec资源合同，尚未生成Stage0映射或资源文件，不表示资源转换完成。

## 资源与运行证据

静态源为Counter.swift，行25–37；source根和摘要记录在run.json及inputs/Counter.swift快照。meta的runtime=not_run、screenshot=null，无设备图像或SwiftUI Preview执行。17份实际规则的原字节快照和hash在rules/及run.json；它们记录输入版本，不证明语义或行为通过。

## 验收与接线

F001服务接口表已声明CounterPage.build及三个handle方法。F001-AC10以CounterPage.build定位UI结构验收；不是仅以组件名充当可执行锚点，也不以build存在替代真实UI结果。AC01–09按VM/任务/存储真值验收，页面通过action-use消费同一合同。

接线为Button→对应handle→同一CounterViewModel实例→count/message→Text；Plan分配唯一文件owner和装配者。source中的无disabled、无导航、无离页cancel都不能变成目标自由补充。U001/U002/U003及机器伴随件缺失保持未完成；本轮未进行完整harness、独立复核、编译、设备或视觉验证。
