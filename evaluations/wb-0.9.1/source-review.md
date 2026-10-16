# 中性样本与源行为评估矩阵

这是本次作者实际逐文件读取后的源规则记录，不是 Swift 编译、设备观察或模型准确率统计。
独立复核结论另存 `review.json`；不能把本文件作者的自审当独立 oracle。

| 样本 | 源证据 | 必须保留的规则 | 会被识别的错误 | 本轮范围 |
|---|---|---|---|---|
| Counter | `sources/counter/Counter.swift:3,7` | 初态0，每次Add对当前值+1；前缀0、1、2 | +2、重复返回1、把计数存成全局/持久化状态 | 完整profile 2 Spec、Plan、真实ArkTS生成/落账/构建；生产Model宿主逻辑运行；设备UI待验 |
| Binding所有者 | `sources/binding-navigation/BindingNavigation.swift:3,7,15-16,19-20` | 根拥有enabled，SwitchRow/Detail通过Binding回写同一根状态 | 子页复制初始值后独立修改、不写回父页 | 源语义矩阵及机器事实提取；尚未生成完整目标工程 |
| 条件身份 | 同文件`:8` | false时Text子树不存在；true时是固定id的Enabled节点；删除后不能凭id假定所有子树状态永存 | 隐藏占位替代条件移除、每次刷新随机id | 同上，运行/视觉待验 |
| 导航与回传 | 同文件`:5,9,19-20` | Details接收当前根Binding；Disable写false，返回后根条件标签消失 | 导航时传Bool副本、返回时又初始化false/true | 同上，真实返回栈待验 |
| UIKit生命周期 | `sources/uikit-ib/CounterController.m:6-10` | 新控制器viewDidLoad初始count=0并更新Label；没有viewWillAppear重置 | 每次回到页面重置、只写模型不刷新Label | 源/IB结构提取，未编译iOS或目标UIKit样本 |
| ObjC事件与所有权 | `.h:3-4`、`.m:11-13`、`.xib:5,12` | weak IBOutlet countLabel接label；touchUpInside接owner.add:；NSInteger逐次+1并格式化 | 断outlet、错selector、改为long-lived单例状态 | 同上；不把XML连接存在当真实点击已验证 |
| IB约束优先级 | `.xib:16-17` | label.centerX=root.centerX；button.top=label.bottom+16，priority750 | 丢priority、把相对约束改成固定屏幕坐标 | XIB的完整几何约束不足，布局有歧义，需源设备/设计补证；不能自动声称视觉等价 |
| 共享跨页对象 | `sources/cross-page-async/SharedSave.swift:23,30,36-37` | Home单一StateObject传给Detail的ObservedObject；两页读写同一模型 | Detail创建新模型、离开子页重置共享状态 | 源语义与机器事实提取；完整目标/运行待验 |
| 保存快照 | 同文件`:8,12-15` | Save捕获入口count；等待中Add改变当前count，但保存旧captured；Saved在set调用后 | await结束再读当前count、同步返回就显示Saved | 同上，需可控调度和存储真实证据 |
| 取消完成边界 | 同文件`:13,16,20` | cancel()只请求最新job取消；Cancelled由catch写入，不是cancel()同步效果 | 立即写Cancelled、宣称所有旧任务永不回写 | 同上，设备/调度执行待验 |
| 重入及旧任务 | 同文件`:10,16,20` | 新Save覆盖job句柄，不先取消旧任务；Cancel只能访问最新job；旧任务仍可写共享message | 擅自加latest-wins、取消全部任务、过滤旧回调 | 同上，必须用两个重叠Save区分 |
| 存储与恢复 | 同文件`:14` | UserDefaults.set不证明磁盘flush；源码没有savedCount读取/启动恢复 | 推断重启恢复、把内存Saved当磁盘持久化成功 | 同上，恢复不适用有明确源依据 |

共同限制：词法fact/obligation能提示遗漏检查，不能自行绑定Swift泛型/宏/ObjC动态接收者。没有Xcode源编译、iOS设备和鸿蒙设备时保留相应缺口。不能用Counter编译或宿主逻辑结果替代另外三个样本的目标验收，也不能由本矩阵推断0.9.1相对0.9.0的语义正确率提高。
