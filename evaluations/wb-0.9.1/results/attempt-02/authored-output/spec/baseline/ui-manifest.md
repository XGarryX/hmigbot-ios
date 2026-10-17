# UI
## 全局约定
Single page Counter owns count; native safe area.
## 页面与覆盖层
| page_id | 源文件/入口/框架 | 类型 | ArkTS 目标文件/组件 | 功能归属 | 优先级 | confidence | 状态 | spec |
|---|---|---|---|---|---|---|---|---|
| page_0001 | Counter.swift:2/entry/swiftui | page | entry/src/main/ets/pages/CounterPage.ets | F001 | P0 | high | pending | ui/page_0001_Counter.md |
## 页面内部显示态
| 页面 | 前态/条件 | 显示结果 | 事件/转移 | 源依据 |
|---|---|---|---|---|
| page_0001 | count=0 | Count:0 | Add -> count+1 | Counter.swift:3-7 |
## 共享组件与嵌入（子组件表）
not_applicable: no shared components; source: Counter.swift:1-16
## 范围与证据
No excluded production paths; screenshot=null/runtime=not_run.
