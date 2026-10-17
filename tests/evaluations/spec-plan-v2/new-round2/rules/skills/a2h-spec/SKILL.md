---
name: a2h-spec
description: "原生 iOS→HarmonyOS 规格生成：从 Swift/Objective-C、SwiftUI/UIKit 源行为交付可实施的 HMigBot baseline、目标公共合同与稳定 AC。用于初次迁移规格分析；不要用于排期、目标代码生成或已有规格的增量修改。"
---

## 控制面入口

先读取 [iOS Harness v2](../ios-source-analysis/references/harness-v2.md)，以该协议决定输入、机器门禁和状态写者。以下原领域规程继续用于规格内容、indexed 计划、接线和真实验证；不得再手工调度或写入三份控制账本。

先 harness-init/import-legacy → source-index（仅首次）→ facts → literals → expertise-plan → 四类 facts-view。完成所需资料审阅并经 expertise-review 记录；MCP 证据按外部协议采集。生产义务绑定稳定 AC；精确 Preview 区间按下述审阅协议记录非产品归属。完成内容与原生源门禁后收口。

## 规格交付与内容门禁

生成baseline前读取 [产物目录](references/artifact-contracts.md) 与 [交付合同](references/spec-delivery-contract.md)：先确定profile/适用产物/唯一作者，源事实、目标设计、批准差异分段，先形成行为模型和公共目标接口，再按模板生成文档与具体AC。不要从源码信号直接套通用句式。

公共设施和全局 UI 分别使用 [基础合同模板](templates/feature-base-template.md)、[UI 索引模板](templates/ui-manifest-template.md)。页面状态接口给明确目标 Owner.state；功能对接点给真实 handler→VM/Service→反馈，供 plan 逐条分配任务。

生成共享/异步/取消/跨层副作用动作时加载 [动作合同](references/action-contracts.md)；页面生成加载页面模板的组件/布局/映射/资源四核心表。核心字段以随包catalog/schema为准，领域步骤在references按需加载，不向每个派发prompt复制整套规则。

Gate C 前按 [独立内容复核](references/spec-content-review.md) 核对实际源行为，并使用 [交接摘要模板](templates/gate-c-summary-template.md)。共享合同通过 contract_refs 精确引用，domains 冻结其传递依赖和决策账本。文档/结构 PASS 不代表已编译或行为等价。



# a2h-spec：从 iOS 源事实生成迁移规格

## 契约与职责

沿用 `spec → plan → execute → verify → retrospect` 主线及原 HMigBot 的
baseline、双计划、稳定 AC、决策与 findings 契约。本步骤原生理解 iOS，
不把视图与状态压成另一平台的页面模型。

必读本技能 [页面模板](templates/page-spec-template.md)、
[功能模板](templates/feature-spec-template.md)、[事实字段](../ios-source-analysis/references/native-facts.md)。
源路径从 `.migbot/config.json.ios` 读取；缺配置先执行 a2h-init。
源不可读是阻塞，不以文件夹名或旧报告补造行为。

## 恢复与已有 baseline

先读 `spec/.a2h/open-findings.json`。本阶段 findings 由产生它的检查重新运行后关闭；
不同阶段的队列保留，不能把整个文件重写成空。
已有完整 baseline 时先比较源版本，走 a2h-incremental-migration/arkts-spec-evolver；
部分 baseline 只续做缺失/受影响部分，保留稳定 page/F/AC/decision ID。

## Phase 0：工程与范围

1. 调用 `ios-source-analysis`，按其四类专业规程建立工程、UI、功能和 API 事实。
2. 明确 app/extension、target/scheme/configuration、依赖与混合语言边界。
   文件索引不代表有效编译成员；没有 Xcode 时保留 static-inferred。
3. 大工程按 target/module/feature 分片，写 `spec/ref/module-index.md` 与范围归属。
   共享事实只有一个作者，分片结束核对文件归属，不能靠扫描目录数量认定完备。
4. 记录证据工具来源、版本、实际是否执行。源码、Apple 文档、运行 trace 分别列出；
   未接入 Apple skill/MCP 时明确 unavailable，不能把自编规程冠为官方。

## Phase A：源事实

源证据由真实文件/符号/行号/快照组成。SwiftUI 的 body、modifier、state/binding、
identity/environment、任务与导航，以及 UIKit 的 controller、view/constraint、
outlet/action、delegate、生命周期分别保存。IB 与程序化改动共同确定运行布局。

每页每功能写 `spec/baseline/ios-semantics.json` 的对应记录。
`known` 必须有源码证据；不适用给具体理由；未知项保持 unknown 并回流分析。
源码涉及宏、二进制或动态配置无法确认时，说明所需额外证据，不伪造解析结果。
Preview、mock 数据与实际入口分开；没有 iPhone 录制不生成运行观察结论。

## Phase B：UI baseline

1. 按真实入口发稳定 page ID，写 `ui-manifest.md`：page_id、iOS 源符号、
   framework、目标页、功能归属、优先级、状态、spec 路径与证据置信度。
2. 写 `ui/page_NNNN_Name.md`，按模板填写组件层级、布局约束、具体ArkUI映射、资源引用，保持公共段落：页面结构、视觉、状态接口、
   交互、导航、资源、验收、目标接线责任；同时完整保留 `ios` 原生语义部分。
3. `ui-snapshots/<page_id>/meta.json` 存 source_platform、框架、source refs、
   状态条件与真实截图路径（若有）。没有运行截图时 screenshot=null、runtime=not_run。
   不创建伪造的布局树文件，程序化 UI 按真实代码与语义树表达。
4. 状态接口写明持有者、变化来源、消费者、清理边界及已确定的目标接口。
   原语义与 ArkTS 决策分段，不能用目标装饰器反向修改源事实。
5. 运行 ios source-check；UI覆盖用 `arkts-ui-coverage-auditor`：入口/页面/交互
   逐项核对，出 `spec/ui-coverage-report.md`。静态覆盖与运行验证分别记录。

Gate B 提供可审查页面清单、原生特征与缺口。沿用本轮已有授权；需要新的产品选择时
只问具体未决点，不能用阶段名要求重复批准已授权的开发。

## Phase C：功能 baseline

### C1 总分结构

写 `feature-index.md`、`feature-base.md`、`features/FNNN-name.md`。
公共基础设施与领域行为分开；功能以完整行为为粒度，文件/类不是 feature 边界。
复杂状态机、协议、生命周期细节放 addendum，主 spec 保留稳定 AC 与 impl 指针。

### C2 源原生语义

主 YAML 使用 `source_platform: ios`、`source_anchors`；每条包含 role、真实 path、
symbol/line（有符号时）。语言/UI 框架分别声明，不使用旧平台字段。
Swift Optional/值与引用/枚举载荷/throws/actor/task，Objective-C nullability/ARC/
delegate/block/selector 等影响行为的语义写在“iOS 源语义”，不能直接丢成普通类图。

### C3 行为和目标契约

源事实写状态转移、数据变换、错误/取消、并发、持久化恢复、平台条件。
适用动作先由唯一owner定义即时效果、完成事件、最终效果与错误/取消；页面和AC引用，不各自重新解释完成时点。无适用动作给有据N/A，unknown继续回流。
目标服务层写 ArkTS 接口；对接点写 page.handler ← ViewModel/Service，保留数据域、
单位、线程与资源生命周期约束。平台能力实际对应哪一 Kit/API 必须查目标版本证据。
服务清单复用 api-inventory 公共契约；业务常量/字面量必须保留实际值。

### C4 AC 与差异

每条 `- [ ] F001-AC01` 后给 `源:<符号> → 标:<目标方法>`、
`判:<方式> | <可观察结果>`、`真:src:<路径>:<行>`（或独立 test/trace/device）。
已批准替代用 `决:<ID>` 和 `真:decision:<ID>`；禁止以生成的目标实现作真值。
不设 AC 数量门槛，核对实际入口、分支、常量、错误与副作用的覆盖。
同构组可列成员，但不能因分组省略真实不同行为。删减保留 skip-list 理由。

HARD-DIV 按四件套：decision ID、替代数据流、supersedes 源 AC、新差异 AC。
同名 API 不等于行为等价；StoreKit、iCloud、扩展、后台等要逐项决定。
没有设备的 device/visual AC 仍保留该验证强度，不能改 static 来凑通过。

### C4.1 决策账本

读取 [决策类目](references/migration-decision-categories.md)，写 decision-ledger 的 D0 与适用决策。
已有授权直接复用；未知技术事实继续查证，产品取舍才提出具体选择。plan 消费同一账本。

### C5 实际校验

在目标根执行本包工具，所有 exit code 和报告路径保留：

```text
python <runtime>/scripts/a2h_ios.py spec-check --project <target>
python <runtime>/scripts/a2h_ios.py source-check --harness --project <target>
python <skills>/a2h-spec/scripts/lint_addenda_closure.py --spec <target>/spec/baseline
python <skills>/a2h-spec/scripts/lint_divergence.py --spec-dir <target>/spec/baseline/features --gate
python <skills>/a2h-spec/scripts/extract_literals.py --spec-dir <target>/spec/baseline --out <target>/spec/baseline/literal-ledger.json
python <skills>/a2h-spec/scripts/build_traceability_index.py --project-root <target>
```

参数以工具 `--help` 为准；原源语言专用画像检查不用于 iOS。
原生 facts checker 检查身份、条件字段和溯源，不声称证明完整语义理解。
`requirements-index.json` 仍由原 HMigBot helper 从稳定 AC 生成，交 a2h-plan。

## 出口

Gate C 交付 feature/index/base/API/decision 与未关闭 findings；全部依赖明确后进入 plan。
报告区分：已读源码、已生成规格、已编译源、已运行观察。任意一种均不能代替其他项。
