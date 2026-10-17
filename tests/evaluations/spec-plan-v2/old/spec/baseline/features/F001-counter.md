# F001: 计数、延迟保存与取消

```yaml
complexity: complex
tier: core
depth: full
source_platform: ios
source_languages: [swift]
ios_frameworks: [swiftui]
source_anchors:
  - role: state_owner
    path: Counter.swift
    symbol: CounterStore
    line: 3
  - role: view
    path: Counter.swift
    symbol: CounterScreen.body
    line: 27
```

## 范围

提供CounterScreen中的Add、Save、Cancel三个真实按钮行为；对应page_0001。源根为评测source目录，输入仅Counter.swift，没有App入口、Xcode工程、target/configuration或已批准差异；实际构建范围未解析。计数和消息状态由页面创建的CounterStore拥有。没有网络、扩展、导航或其他页面。第39行Preview仅显示静态Saved，不作为生产初始态或保存成功证据。

本次按旧规则生成一份feature、一份page与meta；公共base/semantics/机器facts、覆盖/决策账本不在评测生成范围，未伪造这些文件或它们的通过状态，因此本交付不代表完整baseline可进入实施。

## iOS 源语义

CounterStore为MainActor隔离的引用对象；count为Int初值0，message为String初值Ready，均以Published发布。saveTask是可空Task<Void,Never>句柄，缺省nil；Task闭包内部捕获创建时的局部count值，并在挂起后使用captured，不重新读取count（Counter.swift:3-17）。CounterScreen以StateObject拥有store，body重算本身不应被迁移为每次重建store（Counter.swift:25-36）。

save先请求旧saveTask取消，再同步写Saving、捕获count、创建新Task；100,000,000纳秒是源请求延迟，实际调度不保证精确100毫秒完成。Task.sleep和checkCancellation均在do内；CancellationError分支写Cancelled，其他抛错分支写Failed（Counter.swift:8-20）。Task句柄的取消是请求；cancel()自身未写message，也未清空句柄。源码没有generation检查、旧结果过滤或任务完成后nil赋值，不得自行加入此类产品行为（Counter.swift:9-22）。

没有显式离页/deinit取消、恢复读取、自动保存、Binding、Environment、自定义权限或后台逻辑。ios-semantics对应F001的伴随记录本次未生成；未进行Swift编译、运行或符号绑定验证。

## 数据流

Add按钮→store.add→count+1→Count文本重新显示；message和已保存偏好不随Add变化。

Save按钮→取消旧句柄（若存在）→message=Saving→captured=count→新Task等待100,000,000纳秒→检查取消→向UserDefaults的savedCount键写captured→message=Saved。写偏好的源调用为同步set；Saved表示该调用返回并执行下一行，不证明物理磁盘刷写完成（Counter.swift:16-17）。

Cancel按钮→可选句柄cancel；若nil则不执行取消调用，也不写消息。待取消任务实际进入CancellationError分支时消息才变Cancelled；若任务已完成，源代码没有回滚保存值或主动改消息的路径。保存中继续Add会改变显示count，但不改变已捕获的savedCount写入值。

## 源行为表

| 前态/输入 | 事件 | 条件/运算 | 后态/结果 | 错误/取消 | 源文件:行 |
|---|---|---|---|---|---|
| 新CounterStore | 初始化 | count=0，message=Ready，saveTask=nil | 文本为Count: 0及Ready | 不读取已存偏好 | Counter.swift:3-6 |
| count=1 | Add | count+=1 | count=2，message不变 | 无自定义上限/错误反馈 | Counter.swift:7 |
| 任意count，可能有旧任务 | Save | 先旧句柄cancel，再Saving，再捕获count并建任务 | 调用返回时已提交异步保存，消息为Saving | 旧任务仍可能执行其catch写消息 | Counter.swift:8-12 |
| captured=2，等待未取消完成 | 任务继续 | sleep后checkCancellation，再set | savedCount写2，随后Saved | 不声称磁盘已flush | Counter.swift:14-17 |
| 当前count=3、captured=2 | 等待期间Add后保存继续 | 最终使用captured | 可同时显示Count: 3和Saved，保存值为2 | 无自动更新捕获值 | Counter.swift:7-17 |
| saveTask=nil | Cancel | optional chaining不调用 | count/message均不变 | 不显示Cancelled | Counter.swift:6,22 |
| 可取消任务仍在等待/取消检查前 | Cancel | 仅发取消请求 | 请求返回不立即写消息；CancellationError分支执行才写Cancelled | 该分支不写savedCount | Counter.swift:14-18,22 |
| Task已执行保存结束 | Cancel | 对句柄请求取消 | 没有显式回滚或主动改变消息 | 没有再次运行catch的承诺 | Counter.swift:16-22 |
| do内出现非CancellationError | 错误分支 | catch兜底 | message=Failed | 不虚构UserDefaults错误检测 | Counter.swift:13-19 |
| 已有savedCount偏好 | 创建新CounterStore | 初值字段再次初始化 | count=0，message=Ready | 源没有reload→业务读取链 | Counter.swift:3-6,16 |

## 服务层（ArkTS 目标接口）

| 目标接口 | 输入/输出/值域 | 错误/取消 | 状态/线程/生命周期 |
|---|---|---|---|
| CounterViewModel.initialize(): void | count:number=0，message:string=Ready，task为空 | 不读savedCount恢复count | 页面身份内创建一次模型 |
| CounterViewModel.add(): void | 无参；安全可表示整数上count+1 | 不新增clamp/wrap/提示 | UI执行上下文写count |
| CounterViewModel.save(): void | 无参；捕获调用时count；立即写Saving | 请求取消旧任务；异步映射Cancelled/Failed | 保存任务持有自己的captured值 |
| CounterViewModel.cancel(): void | 无参；仅请求当前句柄取消 | nil句柄不改状态；取消完成由任务分支反馈 | 不即时清空句柄或回滚数据 |
| CounterPreferences.setSavedCount(value: number): void | key固定savedCount；输入为captured | 不以磁盘flush结果重新定义Saved | 保留源set返回后的反馈边界 |

接口为本次目标合同，不代表ArkTS实现或SDK核验已完成。延迟/可取消任务与偏好适配器的实际Harmony API需在工具链/SDK可用时核验。Swift Int全范围与ArkTS number的溢出/精度策略未批准；常规有限小整数场景可据源断言，不声称已解决极值等价。

## API 接口

无HTTP/外部服务端点；唯一平台存储接缝为UserDefaults.standard.set(captured,forKey:savedCount)，Counter.swift:16。没有鉴权、网络权限或响应协议，不为模板创建虚构API清单。系统存储适配不携源签名/账号数据。

## 实现映射（Source→ArkTS）

| 源机制 | 目标实现 | 数据/生命周期契约及依据 | 迁移分类 | 决策 |
|---|---|---|---|---|
| StateObject拥有ObservableObject | 页面拥有CounterViewModel，状态变化通知文本 | 页面身份内单一count/message真值；Counter.swift:3-6,26 | HARD | 无批准行为差异 |
| MainActor＋可取消Task | UI执行上下文＋可取消任务适配 | 先取消旧任务、再Saving、再捕获；保留旧任务回写可能性；Counter.swift:8-20 | HARD | 目标API待核验 |
| Task.sleep(100000000ns) | 延迟100ms请求 | 调度可晚于请求时长，不作精确时钟保证；Counter.swift:14 | HARD | 无批准行为差异 |
| UserDefaults set | CounterPreferences.setSavedCount | 固定键、捕获值、set返回后写Saved，不创造reload；Counter.swift:16-17 | HARD | 持久化API待核验 |

## 状态管理

count与message仅属于本页面模型；page读两个字段，Add写count，Save同步写Saving，异步分支写Saved/Cancelled/Failed。没有双向Binding、全局store或跨页状态共享。UI更新不应重新初始化count。

saveTask为私有控制句柄，完成后源仍保留句柄；重复Save会向旧句柄发取消请求。旧任务catch可在新任务开始后写Cancelled，源没有“只允许最新任务更新消息”的保护，不得自行加latest-wins。具体交错取决于调度；不把某次推断时序写为固定最终结果。

偏好savedCount仅写，不读；新store仍从0/Ready启动。没有源依据证明离开页面会取消或持久化当前值。目标若需要显式资源释放适配，必须先核对其是否改变仍在执行的源任务行为。

## 对接点（与 UI 页面的接口）

page_0001.CounterScreen.onAdd→CounterViewModel.add()→count→Count文本；onSave→save()→同步Saving/异步终态→message文本；onCancel→cancel()→取消请求，真正catch写回后再更新message。三个按钮始终按源码创建，没有disabled或隐藏条件（Counter.swift:29-33）。接线owner由Plan分配为F001 slice；页面创建任务只实现界面与事件入口，不创建第二套计数状态。

## 验收标准

- [ ] F001-AC01 新模型初始化后count=0、message=Ready，已有savedCount也不参与初始化。 `源:CounterStore → 标:CounterViewModel.initialize` `判:unit | 初始count为0且message为Ready，未调用读取savedCount` `真:src:Counter.swift:4`
- [ ] F001-AC02 count=1时Add使count=2，并保持message原值。 `源:CounterStore.add → 标:CounterViewModel.add` `判:unit | 输入count=1/message=Ready，结果count=2/message=Ready` `真:src:Counter.swift:7`
- [ ] F001-AC03 Save发起时先取消旧句柄，再写Saving并捕获当前count。 `源:CounterStore.save → 标:CounterViewModel.save` `判:unit | 记录调用序列为旧任务cancel、message=Saving、捕获count、新任务创建` `真:src:Counter.swift:9`
- [ ] F001-AC04 未取消的保存任务请求100000000纳秒延迟后检查取消状态。 `源:CounterStore.save → 标:CounterViewModel.save` `判:unit | 可控任务中延迟请求为100ms，取消检查先于偏好写入` `真:src:Counter.swift:14`
- [ ] F001-AC05 Save时count=2、等待中Add到3，成功保存仍写savedCount=2且随后message=Saved。 `源:CounterStore.save → 标:CounterViewModel.save` `判:unit | 偏好写入值2，屏幕计数真值3，set返回后才写Saved` `真:src:Counter.swift:11`
- [ ] F001-AC06 当前句柄nil时Cancel不改变count或message。 `源:CounterStore.cancel → 标:CounterViewModel.cancel` `判:unit | 空句柄调用后count与message逐值不变` `真:src:Counter.swift:22`
- [ ] F001-AC07 等待期Cancel只请求取消，CancellationError处理时才显示Cancelled且不执行该任务偏好写入。 `源:CounterStore.cancel → 标:CounterViewModel.cancel` `判:unit | cancel返回前无主动消息写入；调度取消catch后message=Cancelled且该任务set调用为0次` `真:src:Counter.swift:18`
- [ ] F001-AC08 已完成保存后的Cancel不回滚savedCount，也没有主动重写Saved的路径。 `源:CounterStore.cancel → 标:CounterViewModel.cancel` `判:unit | 完成后调用cancel，不产生额外偏好写入或主动message赋值` `真:src:Counter.swift:22`
- [ ] F001-AC09 do分支的非CancellationError进入兜底后message=Failed。 `源:CounterStore.save → 标:CounterViewModel.save` `判:unit | 注入非取消错误后message精确为Failed` `真:src:Counter.swift:19`
- [ ] F001-AC10 重复Save保留旧任务错误分支回写message的源路径，不擅自过滤旧任务。 `源:CounterStore.save → 标:CounterViewModel.save` `判:unit | 控制旧任务取消catch晚于新Saving执行时，旧catch仍可写Cancelled` `真:src:Counter.swift:18`
- [ ] F001-AC11 页面初始显示Count: 0及Ready，三个按钮均存在，点击Add可观察到Count: 1。 `源:CounterScreen.body → 标:CounterViewModel.add` `判:ui | 沿页面真实入口点击Add后计数字符串由Count: 0变Count: 1` `真:src:Counter.swift:29`
- [ ] F001-AC12 成功提示只来自生产任务中的message赋值，不把Preview的Saved文本作为运行成功。 `源:CounterStore.save → 标:CounterViewModel.save` `判:static | 产品成功状态对应set之后的Saved赋值，Preview行不进入产品初值` `真:src:Counter.swift:17`

所有AC尚未执行。设备、目标编译、独立复核、完整source/harness门禁均not_run。
