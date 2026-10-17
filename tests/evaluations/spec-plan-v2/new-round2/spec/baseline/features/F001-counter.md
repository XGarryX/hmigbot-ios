# F001: 计数器的增加、快照保存与取消

```yaml
complexity: complex
tier: core
depth: full
source_platform: ios
spec_contract_version: 2
action_contracts: required
source_languages: [swift]
ios_frameworks: [swiftui]
contract_refs: []
source_anchors:
  - role: viewmodel
    path: Counter.swift
    symbol: CounterStore
    line: 3
  - role: service
    path: Counter.swift
    symbol: CounterStore.save
    line: 8
  - role: view
    path: Counter.swift
    symbol: CounterScreen.body
    line: 27
```

## 范围

F001涵盖Counter.swift:3–37的CounterStore及CounterScreen：显示当前计数与状态，Add增加计数，Save延迟保存点击时的计数快照，Cancel请求取消当前保存任务。页面稳定ID为page_0001；目标CounterPage由本功能创建，领域状态归CounterViewModel。

只给出一个Swift源文件，没有App/Scene、Xcode工程或目标SDK配置。页面内三个入口可确定，应用启动入口、宿主呈现形态和有效编译成员均未确认。不能把文件名或View声明当作全屏/启动页证据。

Counter.swift:39是独立#Preview，仅展示Text("Saved")。该行不用于生产初始message或运行验收；本次未执行机器义务排除命令。没有添加自动重读、账号/网络、导航、离页取消、保存中按钮禁用或新任务覆盖旧回调的产品改动。

## iOS 源语义

CounterStore是@MainActor隔离的final引用对象；count和message分别以@Published发布，初始表达式为0和"Ready"。Optional句柄saveTask初始nil（3–6）。CounterScreen的@StateObject创建并持有同一store；两个Text读其状态，三个Button调用其方法（25–33）。视图值和被持有的引用对象分开处理，body求值不能当成新建store。

save()同步部分依次取消旧句柄、写Saving、将当前count复制到captured，再把新Task句柄放入saveTask（8–12）。Task内部先sleep(100_000_000ns)，再checkCancellation，然后UserDefaults.standard.set(captured,forKey:"savedCount")，最后写Saved（14–17）。count在等待期间变化，不会修改captured。100ms是请求的睡眠参数，不是设备运行中保证精确发生的完成时刻。

CancellationError由专门catch写Cancelled；其它被捕获错误写Failed（18–19），Task<Void,Never>不把这些错误再抛给按钮调用者。cancel()本身只调用Optional句柄的cancel，既不赋message，也不清理count、savedCount或句柄（22）。请求取消与任务观察取消是两个边界。

重复save取消旧Task后立即写新Saving，但没有generation ID、旧任务状态写入过滤或等待旧任务退出的逻辑。旧Task的catch仍能覆盖共享message；不擅自修成“仅最新结果生效”。源码没有View.task、onDisappear、deinit取消或句柄完成后置nil（3–37）。任务与页面离开/重建的实际关系需要宿主证据。

持久化路径只有写入，键为savedCount；没有任何get/read、hydrate或恢复业务读取。Saved表示set返回后执行了message赋值，不表示观察到磁盘fsync。即使持久值存在，新store仍从0/Ready创建。

机器伴随件应在完整流水线关联ios-semantics的F001条目；本轮限定三份规格，尚未提取facts/obligations或生成semantics，未填虚构fact ID。

## 数据流

Add→CounterViewModel.add→count加1→CounterPage.build的计数Text消费新值。Save→CounterViewModel.save→取消旧句柄→Saving→捕获count→等待→取消检查→存储入口快照→Saved。任务catch分别输出Cancelled/Failed到同一message，页面不拥有另一个任务终态。

Cancel→CounterViewModel.cancel→当前句柄取消请求；只有任务后续进入CancellationError分支才写Cancelled。不存在句柄或已完成任务时，cancel不重新运行catch，不回滚已保存值。

计数源为Swift Int，目标候选number；普通精确整数的运算可以明确说明，完整Int位宽/溢出与目标存储数值域仍待核验（U001）。本轮不增加裁剪、饱和、回绕或自动负数限制。

## 源行为表

| 前态/输入 | 事件 | 条件/运算 | 后态/结果 | 错误/取消 | 源文件:行 |
|---|---|---|---|---|---|
| 新CounterStore | 初始化 | count=0，message=Ready，saveTask=nil | Count: 0与Ready；无存储读取 | 不使用Preview的Saved作初值 | Counter.swift:4–6,26,29–30 |
| count=n、任意message | Add | count += 1 | count=n+1，其它字段不由add修改 | 极值语义U001 | Counter.swift:7 |
| 任意count=n/任务态 | Save同步入口 | cancel旧任务；Saving；captured=n；创建新任务 | 提交完成，尚不是保存完成 | 旧取消catch可能随后写message | Counter.swift:9–12 |
| 新任务等待中、未取消 | 等待/取消检查返回 | sleep参数100_000_000ns；检查成功 | set(savedCount,captured)后写Saved | 无设备时不声称精确100ms | Counter.swift:14–17 |
| count=n的保存正在等待 | Add | count变n+1，captured仍n | 成功时保存n，UI计数仍n+1 | 不临完成时再读count | Counter.swift:7,11,16 |
| 当前任务未完成 | Cancel | 对当前句柄调用cancel | 请求当下不写message/count/存储 | Task观察取消后才写Cancelled | Counter.swift:18,22 |
| 无句柄或句柄任务已完成 | Cancel | Optional调用/完成句柄cancel | 本方法没有新的状态写 | 不制造Cancelled或回滚 | Counter.swift:6,22 |
| Task的do块抛其它错误 | 普通catch | 非CancellationError | message=Failed | 错误被消费，不向Save按钮再抛 | Counter.swift:19 |

## 动作合同

### 增加计数

```action-contract
{
  "action_id": "F001-A01",
  "owner": "F001",
  "target": "CounterViewModel.add",
  "source_anchors": [{"role": "handler", "path": "Counter.swift", "symbol": "CounterStore.add", "line": 7}],
  "immediate_effect": "对共享count执行加1；add不写message、句柄或savedCount。",
  "completion_event": "同步方法返回，没有异步完成回调。",
  "final_effect": "计数文本消费增加后的count；其余字段没有来自add的新写入。",
  "failure_cancel": "源没有取消或显式错误分支；Int极值/溢出目标映射为U001，未批准裁剪或回绕。",
  "scope": "active",
  "ac_ids": ["F001-AC02"]
}
```

### 提交保存

```action-contract
{
  "action_id": "F001-A02",
  "owner": "F001",
  "target": "CounterViewModel.save",
  "source_anchors": [{"role": "handler", "path": "Counter.swift", "symbol": "CounterStore.save", "line": 8}],
  "immediate_effect": "请求旧句柄取消，message写Saving，复制当前count为captured，创建并保存新Task句柄；save返回只表示已提交。",
  "completion_event": "新任务sleep与checkCancellation均成功返回后，set(captured,savedCount)返回，再执行message=Saved；任务异常由各catch结束。",
  "final_effect": "成功路径保存提交入口时的整数快照，显示Saved；没有恢复count、清空句柄或物理落盘保证。",
  "failure_cancel": "CancellationError写Cancelled，其它错误写Failed；旧任务无generation过滤，重复save后旧catch仍能回写共享message。",
  "scope": "active",
  "ac_ids": ["F001-AC03", "F001-AC04", "F001-AC05", "F001-AC08", "F001-AC09"]
}
```

### 请求取消

```action-contract
{
  "action_id": "F001-A03",
  "owner": "F001",
  "target": "CounterViewModel.cancel",
  "source_anchors": [{"role": "handler", "path": "Counter.swift", "symbol": "CounterStore.cancel", "line": 22}, {"role": "handler", "path": "Counter.swift", "symbol": "CounterStore.save", "line": 18}],
  "immediate_effect": "仅对当前Optional句柄调用cancel；不立即写Cancelled，不清空count/存储/句柄。",
  "completion_event": "cancel同步返回是请求边界；未完成任务在sleep或checkCancellation处观察取消并进入CancellationError分支时，才发生Cancelled赋值。",
  "final_effect": "被取消任务若在成功写入前观察到取消，不执行其savedCount成功写；其它任务仍可随后写共享状态。",
  "failure_cancel": "无句柄为无状态变化；已完成任务不会重新执行catch；取消请求不是已成功写入内容的回滚。",
  "scope": "active",
  "ac_ids": ["F001-AC06", "F001-AC07"]
}
```

## 服务层（ArkTS 目标接口）

| 目标接口 | 输入/输出/值域 | 错误/取消 | 状态/线程/生命周期 |
|---|---|---|---|
| CounterViewModel.add(): void | 无参，count执行整数+1；number极值映射U001 | 不改变message | 页面单实例；同步UI状态串行化 |
| CounterViewModel.save(): void | 无参，捕获count；异步等待参数100ms；返回为已提交 | 按F001-A02，错误不再抛给按钮 | 当前句柄归VM；任务结果回写共享message |
| CounterViewModel.cancel(): void | 无参，取消当前可选句柄 | 按F001-A03，返回非取消完成 | 不创建新任务或清理状态 |
| CounterPersistence.writeSavedCount(value: number): void | 固定键savedCount；只写提交时快照 | 适配具体Kit/数值域为U002；不新增源未声明的恢复行为 | 源set返回与Saved先后关系必须保留 |
| CounterPage.build(): void | 构建Count、message与三个按钮的可观察树 | 不在构建入口完成存储或任务终态 | 页面渲染入口，AC10定位此成员 |
| CounterPage.handleAdd(): void | 调CounterViewModel.add() | 不加独立message反馈 | 绑定Add按钮 |
| CounterPage.handleSave(): void | 调CounterViewModel.save() | 不在按钮返回时赋Saved | 绑定Save按钮 |
| CounterPage.handleCancel(): void | 调CounterViewModel.cancel() | 不在按钮返回时赋Cancelled | 绑定Cancel按钮 |

目标状态合同：CounterViewModel.count:number初始0；CounterViewModel.message:string初始Ready，源写入值为Ready/Saving/Saved/Cancelled/Failed；CounterViewModel.saveTask为私有可取消句柄，其具体目标类型待U002。接口表是目标设计，非已生成、编译的实现或经设备验证的Kit承诺。

## API 接口

not_applicable: Counter.swift:1–39不存在网络端点、HTTP方法、鉴权或外部服务。系统调用为Task.sleep、Task.checkCancellation和UserDefaults.standard.set（14–16）。不能从import SwiftUI推导额外存储API或恢复路径。目标存储/任务适配须在U002核验，不虚构api-inventory端点。

## 实现映射（Source→ArkTS）

| 源机制 | 目标实现 | 数据/生命周期契约及依据 | 迁移分类 | 决策 |
|---|---|---|---|---|
| StateObject持有ObservableObject | CounterPage持有CounterViewModel单实例；V2候选@Local与@ObservedV2/@Trace | 一个count/message真值，普通重绘不重置；Counter.swift:3–6,26 | 状态所有权映射 | 无产品差异；目标SDK未确认 |
| VStack/Text/Button | CounterPage.build以Column/Text/Button承载 | 顺序、16间距、20 padding来自28–35；不补颜色字号 | UI映射 | 本地组件参考，不声称视觉已对齐 |
| Task协作取消 | CounterViewModel.save/cancel的显式任务适配 | 保留captured、请求/观察边界、旧catch可回写；8–22 | 并发适配 | U002，未批准改成只接受最新结果 |
| UserDefaults.set | CounterPersistence.writeSavedCount | 键savedCount；先set返回后Saved；无read/reload；16–17 | 持久化适配 | U001/U002待核验 |

## 状态管理

count和message由VM持有，页面只读并发事件，不复制为按钮局部状态，不全局共享。Page对message的资源化只是显示投影，不改写源状态机。保存中三个按钮始终存在且没有disabled条件（31–33）。

句柄在save时先取消旧的再替换，没有完成后置nil。新VM实例仍从0/Ready开始，不从savedCount水合。源码未指定宿主、页面身份变化或离页处理；不能自行把离页销毁解释为自动取消。宿主/释放与目标API未知保留为U002/U003。

## 对接点（与 UI 页面的接口）

CounterPage.handleAdd→CounterViewModel.add（F001-A01）→CounterViewModel.count→CounterPage.build的countText。CounterPage.handleSave→CounterViewModel.save（F001-A02）→CounterPersistence.writeSavedCount与message反馈→CounterPage.build的statusText。CounterPage.handleCancel→CounterViewModel.cancel（F001-A03）→任务观察取消后的message反馈；页面没有另一条即时Cancelled赋值。

Plan确定文件唯一owner、按钮接线与VM实例化；目标入口均已在本文件声明，AC不临时创造接口。共享动作定义唯一在上述三个精确标题，页面用action-use引用。

## 验收标准

- [ ] F001-AC01 预置savedCount=7后新建VM，count=0、message=Ready，没有持久化read；页面显示Count: 0/Ready。 `源:CounterStore属性初始化 → 标:CounterViewModel.count` `判:unit | 新实例检查初值和无读取调用` `真:src:Counter.swift:4`
- [ ] F001-AC02 从0连续Add两次得到2，message保持Ready，add没有写savedCount。 `源:CounterStore.add → 标:CounterViewModel.add` `判:unit | 两次输入与状态/副作用期望分开检查` `真:src:Counter.swift:7`
- [ ] F001-AC03 count=2时Save，受控任务未释放等待时，message已为Saving，新任务尚未写存储；方法返回不表示保存完成。 `源:CounterStore.save → 标:CounterViewModel.save` `判:unit | 暂停等待，对比同步入口与异步完成` `真:src:Counter.swift:10`
- [ ] F001-AC04 无取消时，等待参数为100_000_000ns，等待和取消检查成功后依次写savedCount=2、message=Saved；不要求实测耗时恰100ms。 `源:CounterStore.save → 标:CounterViewModel.save` `判:unit | 可控等待检查参数、顺序及结果` `真:src:Counter.swift:14`
- [ ] F001-AC05 count=2时Save，等待中Add到3再完成保存，写入2而非3，当前count仍3。 `源:CounterStore.save的captured → 标:CounterViewModel.save` `判:unit | 区分入口快照和完成时状态` `真:src:Counter.swift:11`
- [ ] F001-AC06 Save等待时Cancel，请求函数不赋message；任务观察CancellationError后写Cancelled，取消任务不走成功存储分支。 `源:CounterStore.cancel及save取消catch → 标:CounterViewModel.cancel` `判:unit | 先检查请求阶段，再释放取消观察阶段` `真:src:Counter.swift:18`
- [ ] F001-AC07 尚无任务时Cancel保持0/Ready；保存已完成为Saved后Cancel不触发新的Cancelled赋值，不回滚保存值。 `源:CounterStore.cancel → 标:CounterViewModel.cancel` `判:unit | nil句柄与已完成句柄分别构造` `真:src:Counter.swift:22`
- [ ] F001-AC08 旧保存等待时再次Save，顺序是cancel旧句柄、写新Saving；若随后调度旧取消catch，旧任务仍能写Cancelled，不被额外generation守卫过滤。 `源:CounterStore.save → 标:CounterViewModel.save` `判:unit | 可控重入交错，不声称真实设备唯一顺序` `真:src:Counter.swift:9`
- [ ] F001-AC09 do块若出现非CancellationError，普通catch写Failed，不写Cancelled且不向按钮继续抛。 `源:CounterStore.save的普通catch → 标:CounterViewModel.save` `判:unit | 测试等待适配注入普通错误，按钮可达性不作假设` `真:src:Counter.swift:19`
- [ ] F001-AC10 在真实已承载页面核对Count、message、Add、Save、Cancel的顺序，子项间距16、整体padding20；保存中按钮不被新增条件禁用。 `源:CounterScreen.body → 标:CounterPage.build` `判:ui | 真正渲染和点击核对；本轮未运行` `真:src:Counter.swift:28`

### 未决与交接

U001：Int极值/溢出与目标数值/存储域未核验，影响AC02/04/05极值范围。U002：没有目标SDK及任务/存储适配证据，影响AC03–09；需要目标版本资料、可控调度与独立存储合同验证。U003：宿主入口/呈现/身份未知，影响真实页面与生命周期验收；需要App/Scene/工程或运行证据。

本轮是三份规格的实际生成，未生成完整baseline、machine facts、semantics或覆盖账本；未执行完整harness、源/目标构建、设备或独立复核。上述未决不标PASS、不写已关闭finding。
