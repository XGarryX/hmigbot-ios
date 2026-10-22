---
name: arkts-router-verify
description: "对照 iOS 源导航与页面 spec 静态核验鸿蒙入口、目的页、触发控件、参数和返回/模态状态；复用目标导航技能，运行可达性由真实场景验证。"
---


# iOS 导航到鸿蒙的核验

输入 ios-ui-analyzer 的导航/身份事实、ui-manifest、目标源码和批准决策。
先读 arkts-navigation-builder 与页面 source_anchors；不根据同名类型猜源路由。

1. 源 SwiftUI：NavigationPath 值、destination 分派、Tab、sheet/item/dismiss、深链与恢复。
2. 源 UIKit：push/pop、present/dismiss、segue、controller containment、交互返回取消。
3. 对照目标 Navigation/NavPathStack 与实际事件绑定，逐条检查页面/弹窗/触发控件是否存在。
4. 检查参数类型/值域、返回传值、栈清理、重复进入、权限/登录条件和模态状态反馈。
5. 检查声明页面是否真实实例化、入口是否 loadContent、动态路由是否实际注册。
6. 缺页/缺 handler 在原文件按 owning_slice 修复；不能以空壳或恒定成功回调替代。
7. 用原结构接线工具检查目标连接，再用 arkts-scenario-runner 实测可达性和返回状态。

输出 `spec/verify/route/` 下源路径→目标事件/目的地→证据→状态表。
静态存在、可达和功能正确分别记账。无设备时保留 not_run，不声称完成点击。
