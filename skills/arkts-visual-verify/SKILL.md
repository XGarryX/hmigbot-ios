---
name: arkts-visual-verify
description: "按 iOS 原生页面和状态对比真实 iOS 与鸿蒙截图、交互结果；复用 HMigBot fix 轮次和目标修复角色，未采集或未执行时保留缺口。"
---


# iOS 与鸿蒙的视觉及交互对齐

## 输入门

读取 ui-manifest、页面 spec、ios-semantics、独立源截图/运行证据与目标构建版本。
没有源图时只能分析源码布局和目标画面，结论是 source_visual_unverified。
不能把 Preview/mock 图当实际状态，也不能只比较两张不同场景的截图。

## 执行

1. 按 page ID 与前置态分场景：设备尺寸、横竖屏、语言、字体、深色、账号和权限。
2. 用 arkts-scenario-runner 实际到态；采集操作前后画面并保留日志/版本。
3. 分别核对内容、层级、间距、对齐、颜色、字体、图片裁切、safe area、键盘和命中区。
4. 核对动作后的状态与导航；视觉相似不代表事件接线、网络或持久化行为正确。
5. 差异写 `spec/fix/round-N/ui/`，功能差异写同轮 feat；每项带 page/F-AC、
   expected/actual、source/target evidence、复现步骤、责任范围与验收方式。
6. 按文件所有权交 visual-fixer 或对应业务 fixer，修复后重建当前目标并重跑原场景。
   reviewer 回读新证据，不能删除问题文件来冒充关闭。

## 覆盖与收口

每页每态统计 visited/observed/compared/fixed/reverified/not_run；不按截图张数算通过率。
无设备/无授权操作/平台不可等价的场景分别记录原因。批准差异引用 decision ID。
批次结束回收所有任务与真实证据，汇总未完成项，不能以“页面已生成”代替视觉验收。
原目标 ArkTS 组件、布局、字号、安全区修复能力继续使用各自包内技能。
