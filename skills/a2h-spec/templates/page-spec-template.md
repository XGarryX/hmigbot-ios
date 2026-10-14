# page_0001 — 页面名称

```yaml
source_platform: ios
source_languages: [swift]
ios_frameworks: [swiftui]
source_anchors:
  - role: view
    path: Screens/ExampleView.swift
    symbol: ExampleView.body
    line: 10
```

## 页面与范围
真实入口、前置条件、所属 target/feature、目标页面和稳定 page ID。

## iOS 原生语义
引用 ios-semantics.json 同 page ID，并展开与迁移有关的事实。
SwiftUI：body 组合/条件/身份、modifier 顺序、状态所有权与 Binding、Environment、
task 取消、NavigationPath/sheet。UIKit：控制器层级/生命周期、约束优先级、
outlet/action/delegate 与程序化覆盖。混合页面分别列桥接边界。

## 页面结构与视觉
容器、子组件、条件、布局约束、safe area、trait/动态字体、深色/RTL、资源和无障碍。
源码事实与截图观察分开；Preview 不作为运行初始态。

## 状态接口
| 源状态与类型 | 初值/所有者/生命周期 | 读写者 | UI 影响 | 目标 Owner.state 与类型 |
|---|---|---|---|---|

## 交互与导航
| 前置态 | 事件/入口 | 状态与副作用 | 导航值/返回行为 | 源证据 | owning_feature |
|---|---|---|---|---|---|

## ArkUI 映射决策
按保留行为解释组件/状态/路由映射；原语义留在前文。无法等价引用 decision ID。
目标状态与公开事件接口在 spec 明确；跨页公共合同用 contract_refs 精确引用。无状态页给源依据，不能用 stateless 隐藏真实状态。

## 资源与运行证据
源文件、variant、字符串/复数、符号、字体。截图/录像若未采集明确 not_run。

## 验收与接线
页面检查与关联 F-AC；真实 handler 到目标 ViewModel/Service 的接线责任归 owning_slice。
