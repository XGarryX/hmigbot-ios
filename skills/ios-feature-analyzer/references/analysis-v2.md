# 功能事实：沿完整行为提取

facts-view --scope feature 给出状态、写操作、分支、任务、持久化和系统调用线索。以用户入口/生命周期/后台入口为起点继续读完整调用链，函数与文件不直接等于 feature。

每个行为记录 input、precondition、processing、state transition、side effects、observable。保留边界数值、guard 的拒绝分支、Optional/nil/default、错误/重试、取消/重入、主线程/actor、弱引用和释放。图中的 token 片段不是已绑定的跨函数调用，接收者与泛型/宏/动态派发需要额外证据。

持久化必须记录 key/schema/序列化/写入/重读/业务读取/恢复失败。网络必须记录服务参数、鉴权、编码、响应和错误到用户反馈。状态要区分值复制与对象共享；不能把普通 var 直接翻译成全局 store。

AC 按行为与源中实际分支制定，无数量上限。每项给独立真值，unit 用源规则与边界样本，contract 用真实协议样本，ui/device 用真实动作与观察。任何只能由静态扫描看到的调用不能宣告运行通过。

输出模板：稳定 F ID/source anchors、行为链、状态转移表、边界与错误、并发/取消/lifetime、存储/服务契约、独立 AC、unknown 和平台决策。把每条机器 obligation 绑定真实 AC 与 source_review；一个 AC 可以覆盖多个事实，但场景必须具体。

失败恢复：有信号无义务属规则 bug；有义务无 AC 回 spec；无独立 oracle 保持 unknown；目标缺实现交 execute。复核人与代码作者分开记录，不能从生成的目标结果反推 expected。
