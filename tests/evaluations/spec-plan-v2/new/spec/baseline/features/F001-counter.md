# F001: 计数、延迟保存与取消

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
  - role: handler
    path: Counter.swift
    symbol: CounterStore.save
    line: 8
  - role: view
    path: Counter.swift
    symbol: CounterScreen.body
    line: 27
```

## 范围

生产范围为CounterStore及CounterScreen（Counter.swift:3–37）。用户可增加计数、提交延迟保存、请求取消当前保存。页面归page_0001，目标为CounterPage；F001创建页面并拥有CounterViewModel和存储适配边界。源码只有一个文件，未提供App/Scene、Xcode target或有效构建证据；能确认页面内入口，不能宣称已确认应用启动入口。

Counter.swift:39的#Preview只渲染Text("Saved")，不参与产品初值、保存入口或运行观察。此处只记录精确非产品区间，未生成机器排除账本。没有网络、账号、恢复按钮、自动重读或离页取消入口。源码及三个规格产物已读/已生成，未构建或运行应用。

## iOS 源语义

- CounterStore是@MainActor final引用对象；count/message由@Published发布，初始表达式分别为0/"Ready"；saveTask是Optional Task<Void,Never>，初始无句柄（3–6）。状态由同一实例共享，不把count和message复制成按钮自己的状态。
- CounterScreen以@StateObject持有store（26），body读取同一对象（29–33）。body重新求值不等于重建store；具体页面身份由宿主决定，未提供宿主。没有Binding、Environment注入、ForEach身份键、sheet或导航。
- save先请求旧任务取消，再立即写Saving并捕获当前count（9–11）；Task闭包读取captured值，不在100ms后重新读取count。Task继承所在actor上下文的解释来自此@MainActor创建点，未取得编译器绑定或运行trace。
- sleep参数为100_000_000纳秒（100ms），随后checkCancellation，再写UserDefaults的savedCount，最后写Saved（14–17）。不把100ms当作严格设备完成时限或保证最晚时限。
- cancel只对当前Optional句柄发cancel（22），本方法不写message、不清空计数/存储、不清空句柄。取消由任务在sleep/checkCancellation处观察后进入catch，显示Cancelled（18）。已完成或不存在的任务不会因为再次cancel重新执行catch。
- 重复save没有generation检查或旧结果抑制；旧取消任务的catch仍能回写共享message。目标不能擅自添加“只允许最新任务更新状态”行为。源码未在deinit/onDisappear主动取消任务；不批准新增离页自动取消。
- 持久化只有set，没有get、业务重读或重启恢复（16）；Saved表示set调用已执行返回后的状态，不证明磁盘fsync完成。新建store仍从0/Ready开始。
- 预期结构化伴随引用是spec/baseline/ios-semantics.json#F001；本次范围只生成三份规格，尚未提取机器facts或生成此伴随件，不能宣称source-check --harness已通过。

## 数据流

Add按钮→CounterViewModel.add→count加1→计数文本更新。Save按钮→CounterViewModel.save→取消前句柄→message=Saving→复制count为captured→延迟100ms→取消检查→CounterPersistence.writeSavedCount(captured)→message=Saved。取消路径由任务异常分支写Cancelled；其它被捕获错误写Failed。Cancel按钮→CounterViewModel.cancel→当前句柄cancel请求，UI后续显示由动作合同决定。

存储键固定为savedCount，值是保存入口时的整数快照。不是实时绑定count，不在初始化读取该键。计数源类型为Swift Int；目标number映射在正常精确整数范围内可实施，但64位Int极值/溢出行为与目标存储数值域尚未核验，列为U001，不能擅自缩窄源范围。

## 源行为表

| 前态/输入 | 事件 | 条件/运算 | 后态/结果 | 错误/取消 | 源文件:行 |
|---|---|---|---|---|---|
| 新建store | 初始化 | count=0，message=Ready | 页面显示Count: 0与Ready | 不读取savedCount | Counter.swift:4–6,26,29–30 |
| count=n | Add | count += 1 | count=n+1；message不被该方法修改 | Int极值溢出映射待核验 | Counter.swift:7 |
| 任意message/count=n | Save同步入口 | 取消旧句柄；写Saving；captured=n | 入口返回时已有新任务句柄；磁盘尚未由新任务写入 | 旧任务catch可能稍后写Cancelled | Counter.swift:8–12,18 |
| 当前任务等待 | sleep与取消检查正常返回 | 等待100_000_000ns后检查取消 | set(savedCount,captured)，再写Saved | 不从此路径证明磁盘落盘 | Counter.swift:14–17 |
| 当前任务未完成 | Cancel | 仅请求句柄cancel | 方法本身不改message/count/存储 | 观察CancellationError后写Cancelled；不是点击即写 | Counter.swift:18,22 |
| 无句柄/任务已完成 | Cancel | Optional调用或对完成句柄cancel | 没有本方法导致的新message赋值 | 不制造Cancelled反馈 | Counter.swift:6,22 |
| Task中发生非CancellationError | catch | 普通错误分支 | message=Failed | 不假称能由按钮必然构造该错误 | Counter.swift:19 |
| 保存captured=n后count变n+1 | Add后任务成功 | 保存闭包仍读captured | savedCount=n；当前count=n+1 | 不覆盖为最新count | Counter.swift:7,11,16 |

## 动作合同

### 增加计数

```action-contract
{"action_id":"F001-A01","owner":"F001","target":"CounterViewModel.add","source_anchors":[{"role":"handler","path":"Counter.swift","symbol":"CounterStore.add","line":7}],"immediate_effect":"对当前共享count执行加1；该方法不修改message、任务或savedCount。","completion_event":"add同步返回；没有异步完成回调。","final_effect":"计数文本消费新的count值，其它状态保持原方法未修改的值。","failure_cancel":"无取消分支；Swift Int越界与目标整数映射列为U001待核验，不自行定义饱和或回绕。","scope":"active","ac_ids":["F001-AC02"]}
```

### 提交保存

```action-contract
{"action_id":"F001-A02","owner":"F001","target":"CounterViewModel.save","source_anchors":[{"role":"handler","path":"Counter.swift","symbol":"CounterStore.save","line":8}],"immediate_effect":"请求旧saveTask取消，message立即写Saving，按当前count复制captured并创建新任务；save()返回不是保存完成。","completion_event":"新任务的100_000_000ns等待及checkCancellation成功返回后，UserDefaults.set(captured,forKey:savedCount)调用返回，随后写Saved；异常分支分别完成为Cancelled或Failed。","final_effect":"成功分支保存入口快照并显示Saved；不读取存储恢复count，不证明物理磁盘落盘。","failure_cancel":"CancellationError写Cancelled，其它被捕获错误写Failed。旧任务无generation抑制，重复save后旧取消回调仍可覆盖新任务写的Saving；保留这种时序，不擅自优化。","scope":"active","ac_ids":["F001-AC03","F001-AC04","F001-AC05","F001-AC06","F001-AC08"]}
```

### 请求取消

```action-contract
{"action_id":"F001-A03","owner":"F001","target":"CounterViewModel.cancel","source_anchors":[{"role":"handler","path":"Counter.swift","symbol":"CounterStore.cancel","line":22},{"role":"handler","path":"Counter.swift","symbol":"CounterStore.save","line":18}],"immediate_effect":"只对当前Optional saveTask调用cancel()；不立即赋message，不重置count，不清空存储或句柄。","completion_event":"cancel()同步返回仅表示请求已发出；若未完成任务在sleep/checkCancellation处观察CancellationError，再由catch写Cancelled。不存在或已完成任务没有新的catch执行。","final_effect":"被取消的未完成保存不从成功路径写savedCount；观察取消后共享message为Cancelled，但其它并发保存仍可随后写状态。","failure_cancel":"重复取消不创建新任务；不保证已完成保存回滚；没有立即显示Cancelled的额外状态写入。","scope":"active","ac_ids":["F001-AC06","F001-AC07"]}
```

## 服务层（ArkTS 目标接口）

| 目标接口 | 输入/输出/值域 | 错误/取消 | 状态/线程/生命周期 |
|---|---|---|---|
| CounterViewModel.add(): void | 无参；更新count:number，整数值；极值映射U001 | 没有主动取消或message错误分支 | UI线程单一实例；同步 |
| CounterViewModel.save(): void | 无参；入口捕获count:number；100ms延迟参数 | 取消旧句柄；任务取消/错误按F001-A02 | UI状态写入串行化；返回为已提交 |
| CounterViewModel.cancel(): void | 无参；请求当前保存句柄取消 | 不存在/完成句柄不产生新状态写 | 同F001-A03；不是完成Promise |
| CounterPersistence.writeSavedCount(value: number): void | 写键savedCount；不新增read/restore；具体存储Kit/数值映射U002 | 目标适配不得新增“源已恢复/已fsync”的成功含义 | 在保存成功路径调用；与message=Saved的顺序固定 |

目标状态字段：CounterViewModel.count:number初值0；CounterViewModel.message:string初值Ready，源可写值仅Ready/Saving/Saved/Cancelled/Failed；私有当前任务句柄由CounterViewModel拥有。CounterPersistence是实现边界而非已核验平台API。U001/U002解决前不能声称该部分完整可实施。

## API 接口

not_applicable: Counter.swift:1–39未出现HTTP/服务端端点或鉴权。系统调用为Swift Task.sleep/checkCancellation（14–15）、UserDefaults.standard.set（16）；不为此虚构网络api-inventory。存储适配API版本与写入语义需在U002核验。

## 实现映射（Source→ArkTS）

| 源机制 | 目标实现 | 数据/生命周期契约及依据 | 迁移分类 | 决策 |
|---|---|---|---|---|
| StateObject持有ObservableObject/@Published | CounterPage持有一个CounterViewModel；候选@ObservedV2/@Trace，页面@Local持有 | count/message单一真值，body变化不重新创建store；Counter.swift:3–6,26 | 语义映射候选 | 本地V2参考已读，目标SDK/编译未核验 |
| SwiftUI VStack/Text/Button | CounterPage的Column/Text/Button；具体布局见page_0001 | 保留顺序、16间距、20 padding，不猜字号颜色；28–35 | 组件映射 | 无产品差异 |
| Task睡眠与协作取消 | CounterViewModel任务适配层，保留cancel句柄及异步结果 | 100ms、captured快照、取消请求/观察分离、旧回调写共享状态；8–22 | 平台实现待核验 | U002；没有批准替代 |
| UserDefaults.set | CounterPersistence.writeSavedCount | savedCount、捕获值、先写后Saved；没有reload；16–17 | 存储适配待核验 | U002；不添加恢复 |

## 状态管理

CounterViewModel是页面实例持有的唯一领域状态源；count用于计数文本，message用于状态文本，三个按钮只调用方法。页面不复制状态、不增加“busy时禁用按钮”或“取消中”状态。保存进行时Add/Save/Cancel仍有入口，源码未设置disabled。当前任务句柄替换前先cancel旧句柄；已完成句柄未显式置nil。

生命周期边界：新store初态0/Ready，持久值不水合。未提供宿主身份变化、销毁观察和设备行为。任务闭包可在等待期间保留所需对象；无源onDisappear取消，目标不能将页面离开自动解释为取消保存。真实释放与宿主范围列U003，不伪造deinit行为。

## 对接点（与 UI 页面的接口）

- CounterPage.onAdd → CounterViewModel.add()（F001-A01）；CounterViewModel.count → Count文本。
- CounterPage.onSave → CounterViewModel.save()（F001-A02）；CounterViewModel.message → 状态文本；完成从任务分支回写，页面不自行赋Saved。
- CounterPage.onCancel → CounterViewModel.cancel()（F001-A03）；页面不在点击后立刻写Cancelled。
- CounterViewModel保存成功分支 → CounterPersistence.writeSavedCount(captured:number)，返回后回写message；文件写权和共享装配由Plan分配，不在此预造实现。

## 验收标准

- [ ] F001-AC01 新建store，即使此前savedCount有值7，count仍为0、message仍为Ready；页面显示Count: 0/Ready。 `源:CounterStore初始化与CounterScreen.body → 标:CounterViewModel.count` `判:unit | 预置存储7后新建，检查0/Ready且没有read调用` `真:src:Counter.swift:4`
- [ ] F001-AC02 初态点击Add两次，count为2，message保持Ready，存储不被add写入。 `源:CounterStore.add → 标:CounterViewModel.add` `判:unit | 0经两次add得到2；message未改` `真:src:Counter.swift:7`
- [ ] F001-AC03 count=2触发Save，在可控等待未释放时即观察Saving，savedCount不由新任务写入；save同步返回不代表Saved。 `源:CounterStore.save → 标:CounterViewModel.save` `判:unit | 阻塞等待，检查Saving及无set` `真:src:Counter.swift:9`
- [ ] F001-AC04 count=2时Save，等待入口参数为100_000_000ns；成功释放等待和取消检查后依次写savedCount=2、message=Saved。 `源:CounterStore.save → 标:CounterViewModel.save` `判:unit | 可控调度断言等待参数、set先于Saved，不断言真实耗时恰100ms` `真:src:Counter.swift:14`
- [ ] F001-AC05 count=2时Save，等待中Add一次到3，再释放任务成功；savedCount=2，当前count=3。 `源:CounterStore.save捕获与写入 → 标:CounterViewModel.save` `判:unit | 区分入口快照与完成时计数` `真:src:Counter.swift:11`
- [ ] F001-AC06 Save仍在等待时Cancel，cancel调用本身不赋message；任务观察CancellationError后显示Cancelled且该任务不执行savedCount成功写入。 `源:CounterStore.cancel与save的catch → 标:CounterViewModel.cancel` `判:unit | 分别检查请求后与取消观察后的状态，阻止合并两个时点` `真:src:Counter.swift:18`
- [ ] F001-AC07 未曾Save时Cancel不改变0/Ready；一次Save已完成为Saved后再Cancel，不产生新的Cancelled赋值，不回滚已保存值。 `源:CounterStore.cancel → 标:CounterViewModel.cancel` `判:unit | nil与已完成句柄两种前态分别验证` `真:src:Counter.swift:22`
- [ ] F001-AC08 旧保存等待时再次Save，先发旧任务cancel再写新Saving；随后若旧任务进入CancellationError分支，它仍可写共享message=Cancelled，不能被无源generation守卫吞掉。 `源:CounterStore.save → 标:CounterViewModel.save` `判:unit | 可控调度第二次save及旧catch，检查该允许交错` `真:src:Counter.swift:9`
- [ ] F001-AC09 任务do块若抛出非CancellationError，message写Failed；不把该路径改成Cancelled。 `源:CounterStore.save普通catch → 标:CounterViewModel.save` `判:unit | 在测试调度依赖注入独立普通错误，检查Failed；不声称按钮可必然触发` `真:src:Counter.swift:19`
- [ ] F001-AC10 页面按Count、message、Add、Save、Cancel顺序呈现，容器间距16、整体padding20；Save等待时三个按钮仍可操作。 `源:CounterScreen.body → 标:CounterPage` `判:ui | 在真实页面核对顺序/交互及布局，设备未跑` `真:src:Counter.swift:28`

### 未决与交接限制

- U001：Swift Int极值/溢出与目标number/存储数值域尚未核验；受影响为AC02/04/05的极值扩展与接口值域，不能默认为64位完全等价。
- U002：未提供目标SDK配置，尚未核验取消适配及本地存储Kit；需目标API证据与可控时序/存储契约验证，影响AC03–09。
- U003：未提供App宿主/构建范围，页面身份重建与实际入口只能待补；影响页面生命周期/真实UI验证。
- 以上是本次分析的待补内容，不写为已关闭findings。机器facts/semantics/覆盖、全套harness、独立复核、构建、设备与视觉均未执行。
