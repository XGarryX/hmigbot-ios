"""Small, behavior-specific migration contract shared by harness regressions."""
from pathlib import Path

from hmigbot_ios.core import read_json, write_json


def complete_contract(project: Path):
    config_path = project / '.migbot/config.json'
    config = read_json(config_path)
    config.setdefault('ios_harness', {})['spec_contract_version'] = 1
    write_json(config_path, config)
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


def strict_contract(project: Path):
    """Upgrade only authored contracts, keeping all source facts and stable IDs."""
    complete_contract(project)
    config_path = project / '.migbot/config.json'
    config = read_json(config_path)
    config['ios_harness']['spec_contract_version'] = 2
    write_json(config_path, config)
    base = project / 'spec/baseline'
    na = 'not_applicable: no network; source: Counter.swift:1-10'
    base_text = '''# Shared contract
## 数据模型
| 模型/字段 | 目标类型 | 初值/可空性 | 单位/身份/值域 | 源证据 |
|---|---|---|---|---|
| Counter.count | number | 0/non-null | integer/count | Counter.swift:3 |
'''
    for title in ('数据库与文件恢复', '网络与外部合同', '事件系统', '偏好设置', '权限声明', '公共组件与资源'):
        base_text += f'\n## {title}\n{na}\n'
    base_text += '''
## 公共服务与状态
| 目标接口 | 输入/输出/错误 | 所有者/线程 | 初始化/释放 | 定义方/消费方 |
|---|---|---|---|---|
| CounterPage.add | void/no error | page/main | page lifetime | F001/page_0001 |
## 跨栈映射基线
| 源机制 | 目标实现 | 行为/值域/生命周期 | 核验依据 | 决策 |
|---|---|---|---|---|
| @State | CounterPage.count | starts 0, page owned | Counter.swift:3 | D0 |
'''
    (base / 'feature-base.md').write_text(base_text, encoding='utf-8')
    (base / 'feature-index.md').write_text('''# Features
## 领域模型概览
Counter owns integer count and increments it by one.
## 功能清单
| ID | 功能 | 优先级 | 排序依赖 | 契约依赖 | 关联页面 | 创建页面 | complexity | tier | depth | 状态 | spec |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F001 | Counter | P0 | base | base | page_0001 | page_0001 | simple | standard | full | pending | features/F001-counter.md |
## 依赖图
base -> F001
## 执行顺序（拓扑排序）
base, F001
''', encoding='utf-8')
    (base / 'ui-manifest.md').write_text('''# UI
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
not_applicable: no shared components; source: Counter.swift:1-10
## 范围与证据
No excluded production paths; screenshot=null/runtime=not_run.
''', encoding='utf-8')
    (base / 'skip-list.md').write_text('''# Scope exclusions
## 排除项
not_applicable: no excluded production paths; source: Counter.swift:1-10
''', encoding='utf-8')
    (base / 'source-coverage-report.md').write_text('''# Source coverage
## 源归属
| 源路径 | feature | page_id | 范围处置 | 源证据 |
|---|---|---|---|---|
| Counter.swift | F001 | page_0001 | active | Counter.swift:1-10 |
## 覆盖口径与限制
One production source file; static review only; behavior not executed.
''', encoding='utf-8')
    feature = base / 'features/F001-counter.md'
    feature.write_text(feature.read_text(encoding='utf-8').replace('source_platform: ios',
        'action_contracts: not_applicable\naction_contracts_reason: Synchronous page-local increment; source: Counter.swift:7\nsource_platform: ios'), encoding='utf-8')
    feature.write_text(feature.read_text(encoding='utf-8').replace(
        '| 目标接口 | 输入输出与生命周期 |\n|---|---|\n| `CounterPage.add(): void` | Increments this page\'s count by one; count starts at 0 and lives with the page |',
        '| 目标接口 | 输入/输出/值域 | 错误/取消 | 状态/线程/生命周期 |\n|---|---|---|---|\n| `CounterPage.add(): void` | increment count by 1 | no async cancellation | page/main; initial 0; page lifetime |').replace(
        '| 源机制 | 目标实现 | 契约 |\n|---|---|---|\n| Counter state and Button | `CounterPage.add` | Add changes count by exactly 1; page-local state |',
        '| 源机制 | 目标实现 | 数据/生命周期契约及依据 | 迁移分类 | 决策 |\n|---|---|---|---|---|\n| Counter state and Button | `CounterPage.add` | count + 1; Counter.swift:7 | equivalent | D0 |') +
        '\n## 动作合同\nnot_applicable: synchronous page local increment only; source: Counter.swift:7\n\n## API 接口\nnot_applicable: no remote APIs; source: Counter.swift:1-10\n', encoding='utf-8')
    page = base / 'ui/page_0001_Counter.md'
    page.write_text(page.read_text(encoding='utf-8') + '''
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
''', encoding='utf-8')
    page.write_text(page.read_text(encoding='utf-8').replace(
        'VStack becomes Column; Text shows count; Button invokes CounterPage.add.',
        '| 源机制 | 目标实现 | 约束/差异 | 源证据 |\n|---|---|---|---|\n| VStack | Column | native vertical stack | Counter.swift:5 |'), encoding='utf-8')
    page.write_text(page.read_text(encoding='utf-8').replace(
        '| 源状态 | 目标状态 | 类型 | 初值/所有者/读写与UI影响 |\n|---|---|---|---|\n| Counter.count | `CounterPage.count` | number | 0; page owned; Add writes and Text reads |',
        '| 源状态与类型 | 初值/所有者/生命周期 | 读写者 | UI 影响 | 目标 Owner.state 与类型 |\n|---|---|---|---|---|\n| Counter.count/Int | 0/page/view identity | Add writes Text reads | Count text refresh | `CounterPage.count`: number |').replace(
        'Add -> CounterPage.add -> Count text; no outgoing navigation.',
        '| 前置态 | 事件/入口 | 状态与副作用 | 导航值/返回行为 | 源证据 | owning_feature |\n|---|---|---|---|---|---|\n| count=0 | Add | count+1 | no outgoing navigation | Counter.swift:7 | F001 |'), encoding='utf-8')
    write_json(base / 'ui-snapshots/page_0001/meta.json', {
        'schema_version': 1, 'spec_contract_version': 2, 'page_id': 'page_0001', 'source_platform': 'ios',
        'frameworks': ['swiftui'], 'source_refs': ['Counter.swift:2'],
        'source_anchors': [{'path': 'Counter.swift', 'line': 2}], 'screenshot': None, 'runtime': 'not_run'})
