# Shared contract
## 数据模型
| 模型/字段 | 目标类型 | 初值/可空性 | 单位/身份/值域 | 源证据 |
|---|---|---|---|---|
| Counter.count | number | 0/non-null | integer/count | Counter.swift:3 |

## 数据库与文件恢复
not_applicable: no database/file save or reload exists; a new root initializes count to 0; source: Counter.swift:1-16

## 网络与外部合同
not_applicable: no request, remote response, external application or SDK call exists; source: Counter.swift:1-16

## 事件系统
Button Add directly invokes its synchronous closure; no application event bus or observer subscription. Source: Counter.swift:7.

## 偏好设置
not_applicable: no UserDefaults/preferences key is read or written; source: Counter.swift:1-16

## 权限声明
not_applicable: this sample performs no protected capability or permission request; source: Counter.swift:1-16

## 公共组件与资源
No reusable child component. Page-local Count format and Add label map to app.string.count_text and app.string.add_text in Base-0; source: Counter.swift:6-7. The evaluation scaffold icon is a demo artifact, not evidence of migrated source app identity.

## 公共服务与状态
| 目标接口 | 输入/输出/错误 | 所有者/线程 | 初始化/释放 | 定义方/消费方 |
|---|---|---|---|---|
| CounterModel.add | next count/no error | page/main | page lifetime | F001/page_0001 |
## 跨栈映射基线
| 源机制 | 目标实现 | 行为/值域/生命周期 | 核验依据 | 决策 |
|---|---|---|---|---|
| @State | CounterPage.count | starts 0, page owned | Counter.swift:3 | D0 |
