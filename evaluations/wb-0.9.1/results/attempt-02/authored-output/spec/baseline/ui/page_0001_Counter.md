# page_0001: Counter
```yaml
source_platform: ios
source_anchors:
  - path: Counter.swift
```
## 页面与范围
App entry is this single CounterPage; feature F001.
## iOS 原生语义
@State count belongs to this view identity; initial value 0.
## 页面结构与视觉
VStack with Count Text followed by Add Button; no image resources.
## 状态接口
| 源状态与类型 | 初值/所有者/生命周期 | 读写者 | UI 影响 | 目标 Owner.state 与类型 |
|---|---|---|---|---|
| Counter.count/Int | 0/page/view identity | Add writes Text reads | Count text refresh | `CounterPage.count`: number |
## 交互与导航
| 前置态 | 事件/入口 | 状态与副作用 | 导航值/返回行为 | 源证据 | owning_feature |
|---|---|---|---|---|---|
| count=0 | Add | count+1 | no outgoing navigation | Counter.swift:7 | F001 |
## ArkUI 映射决策
| 源机制 | 目标实现 | 约束/差异 | 源证据 |
|---|---|---|---|
| VStack | Column | native vertical stack | Counter.swift:5 |
## 资源与运行证据
Text literals only; screenshot=null; runtime=not_run.
## 验收与接线
F001-AC02; Button.onClick invokes CounterPage.add on this page instance.

## 组件层级
| 节点ID | 父节点 | 源控件/条件 | ArkUI组件 | 内容/事件 | 源证据 |
|---|---|---|---|---|---|
| root | - | VStack | Column | count and Add | Counter.swift:5 |
| count | root | Text | Text | count | Counter.swift:6 |
| add | root | Button | Button | CounterPage.add | Counter.swift:7 |
## 布局约束
| 节点ID | 尺寸/布局/安全区 | 条件/优先级 | 资源引用 | 源证据 |
|---|---|---|---|---|
| root | native stack spacing and safe area | always/default | system.default | Counter.swift:5-8 |
## 资源引用
| 资源ID | 类型 | 目标引用 | 源证据 |
|---|---|---|---|
| count_text | string | $r('app.string.count_text') | Counter.swift:6 |
| add_text | string | $r('app.string.add_text') | Counter.swift:7 |

CounterApplication WindowGroup is the source entry; page lifetime owns model and visible count.
