# page_0001 — CounterScreen计数页

```yaml
source_platform: ios
spec_contract_version: 2
source_languages: [swift]
ios_frameworks: [swiftui]
contract_refs:
  - spec/baseline/features/F001-counter.md#增加计数
  - spec/baseline/features/F001-counter.md#提交保存
  - spec/baseline/features/F001-counter.md#请求取消
source_anchors:
  - role: view
    path: Counter.swift
    symbol: CounterScreen
    line: 25
```

## 页面与范围

page_0001对应CounterScreen，目标CounterPage（候选文件entry/src/main/ets/pages/CounterPage.ets），所属F001。真实页内入口是Add/Save/Cancel三个Button；源码未提供App/Scene，生产宿主如何呈现该View尚未确定。页面类型按顶层View候选记full_screen_page，不把它当作已确认全屏启动页。前置条件为宿主已创建此View；无登录、权限或导航前置条件证据。

Counter.swift:39的#Preview只含Text("Saved")，与CounterScreen初态分离，不能因Preview而把本页初态写Saved。

## iOS 原生语义

@StateObject private store创建并持有CounterStore（26）；ObservableObject的count/message发布变化（3–5）驱动两个Text（29–30），按钮通过同一store方法入口（31–33）。同一View身份下重算body不重新置0/Ready；宿主身份变化机制缺失，不能猜其生命周期。没有Binding或Environment，页面无局部编辑副本。

VStack共有五个按序子节点（28–34），无if/ForEach/overlay；唯一显式modifier是其后的padding(20)（35），没有指定frame、字号、颜色或按钮风格。任务不属于View.task/onDisappear；状态与异步取消归F001动作合同，不能在页关闭时自动调用cancel。

此分析预期关联ios-semantics.json#page_0001，但该机器伴随件不在本次三份输出范围；没有机器fact ID就不伪造known记录。

## 页面结构与视觉

源码确定竖向顺序、16间距、20 padding。尺寸由容器/文本和原生控件测量，未写固定宽高、颜色、字体或safe area扩展。没有截图；SwiftUI默认按钮外观与目标系统按钮的像素差异需实际对齐，不在无运行证据时编造蓝色、圆角或触摸热区尺寸。

## 组件层级

| 节点ID | 父节点 | 源控件/条件 | ArkUI组件 | 内容/事件 | 源证据 |
|---|---|---|---|---|---|
| root | - | VStack，常驻 | Column | 按countText、statusText、add、save、cancel顺序承载 | Counter.swift:28–35 |
| countText | root | Text，常驻 | Text | 格式Count: <count>，读CounterViewModel.count | Counter.swift:29 |
| statusText | root | Text，常驻 | Text | 读CounterViewModel.message；初态Ready | Counter.swift:30,5 |
| add | root | Button("Add")，常驻 | Button | onAdd→CounterViewModel.add，F001-A01 | Counter.swift:31,7 |
| save | root | Button("Save")，常驻 | Button | onSave→CounterViewModel.save，F001-A02 | Counter.swift:32,8–21 |
| cancel | root | Button("Cancel")，常驻 | Button | onCancel→CounterViewModel.cancel，F001-A03 | Counter.swift:33,22 |

源码没有条件子树，不适用分支/循环身份表的理由为Counter.swift:28–34只列五个无条件节点；任务状态只改变statusText内容，不增删按钮。

## 布局约束

| 节点ID | 尺寸/布局/安全区 | 条件/优先级 | 资源引用 | 源证据 |
|---|---|---|---|---|
| root | 竖向排布，子项间距16；随后四边padding20；没有frame或忽略safe area | 所有状态相同；父容器尺寸/对齐由未提供宿主决定 | counter_spacing=16、counter_padding=20；Stage0转换 | Counter.swift:28,35 |
| countText | 内容测量；没有固定宽高、字体、maxLines或截断参数 | 常驻；动态count更新文本 | counter_count_format | Counter.swift:29 |
| statusText | 内容测量；没有固定宽高、字体或颜色 | 常驻；Ready/Saving/Saved/Cancelled/Failed由store决定 | counter_status_* | Counter.swift:5,10,17–19,30 |
| add | 源默认Button布局；未设disabled/style/frame | 保存中仍无禁用条件 | counter_add | Counter.swift:31 |
| save | 源默认Button布局；未设disabled/style/frame | 可重复触发，不添加busy禁用 | counter_save | Counter.swift:32 |
| cancel | 源默认Button布局；未设disabled/style/frame | 无句柄时仍显示可点击 | counter_cancel | Counter.swift:33 |

没有UIKit约束优先级、横屏分支、dark/trait自定义或显式无障碍覆盖；这些字段不是0/固定颜色，而是源无专门设置。系统默认字体/VoiceOver行为与实际宿主安全区需真实设备核对；无证据不指定固定屏幕尺寸。

## 状态接口

| 源状态与类型 | 初值/所有者/生命周期 | 读写者 | UI 影响 | 目标 Owner.state 与类型 |
|---|---|---|---|---|
| CounterStore.count: Int | 0；StateObject持有的store | add写；save入口读快照；Text读 | Count文本更新 | CounterViewModel.count: number；U001极值映射未决 |
| CounterStore.message: String | Ready；同store实例 | save及Task各分支写；Text读 | 状态文本变化，无组件增删 | CounterViewModel.message: string，限定源五种文案 |
| CounterStore.saveTask: Task<Void,Never>? | nil；同store私有句柄 | save替换/取消前句柄；cancel请求取消当前 | 间接影响message；不直接产生“取消中”UI | CounterViewModel.saveTask: 私有可取消任务句柄，目标具体类型U002 |

页面持有CounterViewModel，不把count/message提升成跨页面全局存储。目标V2候选@Local持有@ObservedV2实例、count/message为@Trace；这是候选目标映射，非源装饰器同名替换或已编译结论。

## 交互与导航

| 前置态 | 事件/入口 | 状态与副作用 | 导航值/返回行为 | 源证据 | owning_feature |
|---|---|---|---|---|---|
| 页面存在，任意任务态 | Add | 调用F001-A01，count文本消费新值 | 无导航 | Counter.swift:31,7 | F001 |
| 页面存在，包括保存等待中 | Save | 调用F001-A02；UI投影为message文本，页面不自行决定任务完成 | 无导航；同步调用返回不是保存完成 | Counter.swift:32,8–21 | F001 |
| 页面存在，包括无句柄/已完成 | Cancel | 调用F001-A03；页面不立即赋Cancelled、清空count或存储 | 无导航；cancel返回不是取消完成 | Counter.swift:33,22 | F001 |

```action-use
{"action_id":"F001-A01","contract_ref":"spec/baseline/features/F001-counter.md#增加计数","ac_ids":["F001-AC02"]}
```

```action-use
{"action_id":"F001-A02","contract_ref":"spec/baseline/features/F001-counter.md#提交保存","ac_ids":["F001-AC03","F001-AC04","F001-AC05","F001-AC08"]}
```

```action-use
{"action_id":"F001-A03","contract_ref":"spec/baseline/features/F001-counter.md#请求取消","ac_ids":["F001-AC06","F001-AC07"]}
```

导航/返回为not_applicable：Counter.swift:25–37没有NavigationStack、链接、sheet、dismiss或路由参数；不能补返回按钮。

## ArkUI 映射决策

| 源机制 | 目标实现 | 约束/差异 | 源证据 |
|---|---|---|---|
| VStack(spacing:16)后padding(20) | CounterPage的Column({space:16})后padding(20) | 保留操作顺序与源数值；vp/point的设备视觉需核对；不擅自width100%或全屏居中 | Counter.swift:28,35 |
| 两个Text | Text读取格式化count与message资源投影 | 不截断、不猜字号颜色；保留源输出文案与数字含义 | Counter.swift:29–30 |
| 三个Button(action:) | Button+onClick调用页面onAdd/onSave/onCancel | 本地组件参考确认此组件存在；目标默认胶囊外观不自动等价SwiftUI默认样式，需视觉验证后定具体样式 | Counter.swift:31–33 |
| StateObject/Published | 页面持有CounterViewModel单实例，V2可观察属性 | 单一所有者；没有双向Binding；未核验目标SDK | Counter.swift:3–6,26 |
| store方法入口与Task反馈 | 页面仅发事件、VM按唯一F001动作合同回写 | 不增加spinner/按钮禁用/离页cancel/旧结果抑制 | Counter.swift:8–22,31–33 |

## 资源引用

| 资源ID | 类型 | 目标引用 | 源证据 |
|---|---|---|---|
| counter_count_format | 字符串格式 | app.string.counter_count_format，语义Count: <十进制count>；Stage0生成格式资源 | Counter.swift:29 |
| counter_status_ready | 字符串Ready | app.string.counter_status_ready | Counter.swift:5 |
| counter_status_saving | 字符串Saving | app.string.counter_status_saving | Counter.swift:10 |
| counter_status_saved | 字符串Saved | app.string.counter_status_saved；生产依据17，不以Preview39为依据 | Counter.swift:17 |
| counter_status_cancelled | 字符串Cancelled | app.string.counter_status_cancelled | Counter.swift:18 |
| counter_status_failed | 字符串Failed | app.string.counter_status_failed | Counter.swift:19 |
| counter_add | 字符串Add | app.string.counter_add | Counter.swift:31 |
| counter_save | 字符串Save | app.string.counter_save | Counter.swift:32 |
| counter_cancel | 字符串Cancel | app.string.counter_cancel | Counter.swift:33 |
| counter_spacing | 尺寸16 | app.float.counter_spacing，Stage0转换 | Counter.swift:28 |
| counter_padding | 尺寸20 | app.float.counter_padding，Stage0转换 | Counter.swift:35 |

没有图片/符号/字体文件引用，源证据为Counter.swift:25–37全组合。资源ID为目标规划名，尚无resource-mapping或真实资源文件，不宣称Stage0已完成。

## 资源与运行证据

source_root为本评估的source目录，源相对路径Counter.swift；原文静态审阅覆盖3–37。页面meta的runtime=not_run、screenshot=null；未打开模拟器、未采集视频/截图，未执行SwiftUI Preview或目标ArkUI。文件哈希和规则哈希记录在new/run.json，哈希只证明读入版本，不证明行为通过。

## 验收与接线

关联F001-AC01–10，页面专门验收AC10；状态初态及按钮观察仍以F001各AC和动作合同为唯一源。CounterPage的onAdd/onSave/onCancel分别接CounterViewModel.add/save/cancel；count/message必须从该实例读回。Plan分配唯一owning_slice/文件owner，三个按钮不能保持空handler。异步取消时点、snapshot和重入由功能AC验证，页面不重定义完成条件。

未决U001数值边界、U002目标任务/存储API、U003宿主与身份来自F001；补证前相关实现/验证保持未完成。本页没有独立源复核或全套harness PASS。
