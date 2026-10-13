# UI 事实：组合、事件、状态与布局

先执行 facts-view --scope ui。输入是真实页面入口、源码、IB 与机器信号，输出是页面规格与 v2 原生语义。扫描只给信号，不能推定视图运行树。

SwiftUI：逐 body 分支读取组合顺序、modifier 顺序、ForEach key、id 重置边界、State 创建者、StateObject/ObservedObject 所有权、Binding 双向流、Environment 范围、task(id:) 启停、Navigation/sheet 参数和关闭后的状态。UIKit：读取 controller 创建/包含/appear/disappear/deinit、view 构建、target-action、delegate/dataSource、outlet/segue 与程序化覆盖。

每个用户动作记录：入口控件及触发条件→handler→校验/状态改变→服务或委托→显示结果。状态写说明被哪些 view 读取；禁止只登记 Button 和 addTarget 的存在。

Auto Layout 保留 first/second item、relation、constant、priority、intrinsic/hugging/compression，核对运行期改约束。资源尺寸必须来自 source/asset scale/真实布局，不能由文件像素猜点数。Snapshot 有真实设备与场景才登记；Preview 不作运行行为证据。

输出模板：page ID、framework/language、入口、source anchors、composition、ordered modifiers、state ownership、event chain、navigation/return、layout、variants/accessibility、未知。value 对象和 fact_ids 与机器图链接，状态 states 字段精确匹配。target mapping 单独写入决策，源事实不含目标装饰器猜测。

失败恢复：机器未知回 provider 或源码；动态 UI 回真实场景采集；来源不符回所属页面 owner。harness-check 中 NA_CONTRADICTION、STATE_VALUE_CONTRADICTION 和 CLAIM_SIGNAL_MISSING 不允许以“页面已生成”关闭。
