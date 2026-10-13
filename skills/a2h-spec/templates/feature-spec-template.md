# F001: 功能名称

```yaml
complexity: complex
tier: core
depth: full
source_platform: ios
source_languages: [swift]
ios_frameworks: [nonvisual]
source_anchors:
  - role: service
    path: Services/ExampleService.swift
    symbol: ExampleService.perform
    line: 20
```

## 范围
用户目标、target/extension、所有入口、页面和 feature-base 依赖。

## iOS 源语义
引用 ios-semantics.json 同 F ID，保留 Swift 或 Objective-C 的行为相关语义。
值/引用、Optional/关联值枚举、ARC、actor/Task/委托、错误/取消和资源生命周期逐项有证据。

## 数据流
输入 → 校验/转换 → 服务 → 持久化/副作用 → UI。写单位、值域、线程和失败路径。
HARD-DIV 的替代数据流引用 PD-ID，显式给跨边界转换责任。

## 源行为表
| 前态/输入 | 事件 | 条件/运算 | 后态/结果 | 错误/取消 | 源文件:行 |
|---|---|---|---|---|---|

## 服务层（ArkTS 目标接口）
写目标类型与方法签名，包含异步、错误、取消和生命周期契约；源签名仍保留在源语义节。

## API 接口
引用 api-inventory 端点 ID、静态 method/path/protocol 和公共 auth。未知字段不猜。

## 实现映射（Source→ArkTS）
| 源机制 | 目标实现 | 数据/生命周期契约及依据 | 迁移分类 | 决策 |
|---|---|---|---|---|

## 状态管理
状态持有者、更新方向、共享范围、恢复与清理；区分源事实和目标装饰器选择。

## 对接点（与 UI 页面的接口）
page.handler ← ViewModel/Service；包含参数与结果，交 a2h-plan 分配唯一接线 owner。

## 验收标准
- [ ] F001-AC01 <单个可观察断言>　`源:<源符号> → 标:<目标方法>`　`判:unit | <输入与期望结果>`　`真:src:<源相对路径>:<行号>`

AC ID 稳定且不回收；主文件保留全部 AC。细节可移 addendum，但有 impl 指针。
独立真值也可用 test/trace/device；批准差异用 `决:PD-ID` 与 `真:decision:PD-ID`。
HARD-DIV 同时给 PD-ID、替代数据流、supersedes 旧 AC、新差异 AC；不自行批准替代。
