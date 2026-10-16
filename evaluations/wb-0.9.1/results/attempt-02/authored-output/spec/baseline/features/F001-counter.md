# F001: Counter
```yaml
complexity: simple
tier: standard
depth: full
action_contracts: not_applicable
action_contracts_reason: Synchronous page-local increment; source: Counter.swift:7
source_platform: ios
source_anchors:
  - path: Counter.swift
contract_refs:
  - spec/baseline/feature-base.md#数据模型
```
## 范围
page_0001 Counter Add button and displayed count; no external services.
## iOS 源语义
Counter owns @State count=0 during the identity of this view.
## 数据流
CounterApplication @main -> WindowGroup -> Counter; source: Counter.swift:11-15.
Tap Add -> count + 1 -> refresh Count text. No persistence or external calls.
## 源行为表
| 前态/输入 | 事件 | 条件/运算 | 后态/结果 | 错误/取消 | 源文件:行 |
|---|---|---|---|---|---|
| count=0 | Add | count + 1 | Count:1 | no asynchronous work | Counter.swift:7 |
## 服务层（ArkTS 目标接口）
| 目标接口 | 输入/输出/值域 | 错误/取消 | 状态/线程/生命周期 |
|---|---|---|---|
| `CounterModel.add(): number` | increment count by 1 and return the next count | no async cancellation | page/main; initial 0; page lifetime |
## 实现映射（Source→ArkTS）
| 源机制 | 目标实现 | 数据/生命周期契约及依据 | 迁移分类 | 决策 |
|---|---|---|---|---|
| Counter state and Button | `CounterPage.add` | count + 1; Counter.swift:7 | equivalent | D0 |
| Counter Button | `CounterModel.add` | return count + 1; Counter.swift:7 | equivalent | D0 |

## 状态管理
CounterPage.count: number = 0; page owns updates, Text consumes count.
## 对接点（与 UI 页面的接口）
CounterPage Button -> CounterPage.add -> CounterModel.add -> CounterPage.count -> Count text.
CounterModel is created once per page instance; page state starts at 0. No global/shared instance.
Evaluated numeric range: 0..2; full Swift Int overflow/large integer equivalence remains unverified.
## 验收标准
- [ ] F001-AC01 从初值0依次调用两次Add，业务状态依次为0、1、2 `源:Counter.body → 标:CounterModel.add` `判:unit | counts=[0,1,2]，加2或丢失更新必须失败` `真:src:Counter.swift:3`
- [ ] F001-AC02 App进入显示Count:0，点击Add后同页显示Count:1 `源:Counter.body → 标:CounterPage.add` `判:ui | 实际控件点击后文本从Count:0变为Count:1` `真:src:Counter.swift:7`

## 动作合同
not_applicable: one synchronous page-local increment; no cross-page or asynchronous action; source: Counter.swift:3-9

## API 接口
not_applicable: the complete native app has no network, external service or storage API; source: Counter.swift:1-16
