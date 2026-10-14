"""Small, behavior-specific migration contract shared by harness regressions."""
from pathlib import Path


def complete_contract(project: Path):
    base = project / 'spec/baseline'
    documents = {
        'feature-base.md': '# Shared contract\n\n## 数据模型\nCount is an integer initially 0; Add increments it by 1.\n\n## 跨栈映射基线\nSwift @State maps to page-owned observable count. No network, database or preferences exist in this counter.\n',
        'feature-index.md': '# Features\n\n| ID | 范围 | 依赖 | 页面 |\n|---|---|---|---|\n| F001 | Counter Add and visible count | base | page_0001 |\n',
        'ui-manifest.md': '# UI\n\n## 全局约定\nOne counter page owns count; no navigation or external services.\n\n| page_id | 目标页面 | 功能 |\n|---|---|---|\n| page_0001 | CounterPage | F001 |\n',
        'skip-list.md': '# Scope exclusions\nNo excluded production paths in this ten-line counter fixture.\n',
        'source-coverage-report.md': '# Source coverage\nCounter.swift belongs to F001 and page_0001. Static ownership only; behavior not run.\n',
        'features/F001-counter.md': '''# F001: Counter
```yaml
complexity: simple
tier: standard
depth: full
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
Tap Add -> count + 1 -> refresh Count text. No persistence or external calls.
## 源行为表
| 前态/输入 | 事件 | 条件/运算 | 后态/结果 | 错误/取消 | 源文件:行 |
|---|---|---|---|---|---|
| count=0 | Add | count + 1 | Count:1 | no asynchronous work | Counter.swift:7 |
## 服务层（ArkTS 目标接口）
| 目标接口 | 输入输出与生命周期 |
|---|---|
| `CounterPage.add(): void` | Increments this page's count by one; count starts at 0 and lives with the page |
## 实现映射（Source→ArkTS）
| 源机制 | 目标实现 | 契约 |
|---|---|---|
| Counter state and Button | `CounterPage.add` | Add changes count by exactly 1; page-local state |
## 状态管理
CounterPage.count: number = 0; page owns updates, Text consumes count.
## 对接点（与 UI 页面的接口）
CounterPage.onAdd -> CounterPage.add() -> CounterPage.count -> displayed Count text.
## 验收标准
- [ ] F001-AC01 初值count=0时点击Add，文本显示Count:1 `源:Counter.body → 标:CounterPage.add` `判:ui | 点击后文本为Count:1` `真:src:Counter.swift:7`
''',
        'ui/page_0001_Counter.md': '''# page_0001: Counter
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
| 源状态 | 目标状态 | 类型 | 初值/所有者/读写与UI影响 |
|---|---|---|---|
| Counter.count | `CounterPage.count` | number | 0; page owned; Add writes and Text reads |
## 交互与导航
Add -> CounterPage.add -> Count text; no outgoing navigation.
## ArkUI 映射决策
VStack becomes Column; Text shows count; Button invokes CounterPage.add.
## 资源与运行证据
Text literals only; screenshot=null; runtime=not_run.
## 验收与接线
F001-AC01; CounterPage.onAdd invokes CounterPage.add on this page instance.
''',
    }
    for path, text in documents.items():
        target = base / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
    (project / 'spec/decision-ledger.md').write_text('# Decisions\n\nD0: Preserve counter behavior. No platform divergence.\n', encoding='utf-8')
