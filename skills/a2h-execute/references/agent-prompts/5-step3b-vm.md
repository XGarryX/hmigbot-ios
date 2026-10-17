# Slice Step 3b：ViewModel 与状态

输入 slice、feature/page spec、source_anchors/source_root、已有 .ets、native facts、owned_files。
profile 2 输入同时含plan_item_refs/ac_ids、精确spec_refs与contract_refs闭包；按_common.md分批消费，返回consumed_refs/unread_refs/contract_conflicts。
第一段读取真实 Swift/Objective-C 源码：事件→状态→副作用，解释 Optional、值/引用、
actor/Task/取消或 ARC/delegate/block 语义；把事实写 source-understanding/<slice>-source-notes.md。
第二段对照目标接口/平台决策，列语义差异与数据域、生命周期；未知项回 spec。
第三段读取 arkts-state-manager，实际实现 VM/状态更新、错误/取消/重入逻辑，保持独立 AC 真值。
simple 也要核对源行为；complex 不得省略三段。按 impl 指针读相关 addendum。
生成对象实例化和 page.handler 的明确接口供 Step 3d，不能生成孤立 VM 当切片完成。
返回 owned_files、source-notes、接线需求、占位和验证结果；plan 不写状态。
