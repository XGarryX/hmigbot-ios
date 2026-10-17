# 0.6.0 原生事实与执行协议

本规程是七个 iOS 技能共同的控制协议。程序检查范围是确定性合同和已检测信号；业务解释、动态绑定与设备行为需要独立复核。不得把 token_signal 写成 compiler_binding 或 runtime。

规格交付按 [公共合同](../../a2h-spec/references/spec-delivery-contract.md) 形成。0.8.0 的只读 spec-check 校验正文、目标锚点、状态映射和显式共享引用，source-check --harness 内置同一检查；字段齐全仍不证明语义正确。精确 Preview 义务的哈希审阅排除、旧 baseline 升级及共享引用写法见该合同。import 仅为依赖线索，不产生持久化行为义务。

内容profile与harness载荷分别版本化：新项目 `ios_harness.spec_contract_version=2`，旧profile 1按兼容路径；升级补齐 [产物合同](../../a2h-spec/references/artifact-contracts.md)、独立复核并重跑门禁，不继承旧PASS，已采用2不得降级绕过。核心MD提纲/表头、页面meta、动作定义/引用与按需附件格式由随包catalog/schema及实际校验器限定；自然语言语义仍按 [独立联读](../../a2h-spec/references/spec-content-review.md) 裁定。

0.7.0 增加 [外部专业 skill/MCP 规程](external-expertise.md)：facts 后运行 expertise-plan，
由对应分析 owner 读取固定原文并用 expertise-review 保存源观察。source-check --harness
要求此清单/审阅通过，包括 0.6.0 项目升级。可选 mcp-query 保存实际响应，known claim
以 tool_evidence_ids 关联；响应本身只为 tool_response。domains 计划冻结这些证据。

## 初始化与机器事实

从配置读取源、目标。源不可读即阻断。首次依次执行随包 runtime 的：

```text
python <runtime>/scripts/a2h_ios.py harness-init --project <target>
python <runtime>/scripts/a2h_ios.py source-index --project <target>
python <runtime>/scripts/a2h_ios.py facts --project <target>
python <runtime>/scripts/a2h_ios.py literals --project <target>
```

有 0.5.0 baseline 时用 `import-legacy` 代替 `harness-init`；旧声明存入 history 并转 unknown，稳定 page/F/AC ID 保留。已有外来 state.json 时拒绝混用写者，先审阅迁移方案，不能删除账本绕过。

facts 生成 ios-facts.json 与 ios-obligations.json。这两件禁止模型手改。fact ID 与行号分离，源片段、文件摘要、owner、symbol、kind、value、解析层级和构建范围均保留。状态初值保留源表达式文本，不擅自求值。

仓库扫描包含未选中的配置，effective_build=unresolved。`--variant` 的 selected-build 必须携 source_build 证据包及已哈希 source-files.json；导入文件的完整性不证明捕获真实性。遇到条件编译、宏、动态派发或解析未知，不能用扫描数量声称有效构建已解析。

`--providers <provider-plan.json>` 执行指定 SwiftSyntax/Clang/构建设置/IB/资源 provider，记录源摘要和实际产物。provider 只提升自身证据层级，不自动消除业务未知。工具失败保留 failure.json；不伪造 AST。配置格式见 [provider 计划示例](../assets/provider-plan.json)。

## 模型事实与覆盖

逐 page/feature 维护 `ios-semantics.json` v2，每个必需维度仍按 native-facts.md 枚举。known 的 value 必须是对象，fact_ids 指向所属源码的机器事实，evidence 必须落在这些事实片段内。复杂语义说明放 value 中，但须解释操作、状态、错误和观察结果。

state_ownership.value 固定为 `{ "states": [{ "fact_id", "owner", "storage", "type", "initializer" }] }`，内容精确匹配状态事实。0、false、nil 与 Optional 默认值分别保留。

unknown 必须带原因并阻断受影响实现。not_applicable 只有在完整调用链审阅后才可记录具体理由；源码信号与不适用矛盾时程序拒绝。不准用“已处理”“无特殊情况”覆盖全部维度。

`ios-coverage.json` v2 的每条 mapping 包含 obligation_id、ac_ids、source_review。review 必填 status=reviewed、input、processing、observable、reviewer；说明来自源行为。义务只能由规则生成，不能自行少列一个。AC 沿用原稳定 ID 和 `判:... | 真:...`，判定方式至少满足 ios-obligations 给出的候选之一。义务可共享 AC，但必须确实被该 AC 的具体场景覆盖。

执行 `harness-check` 或 `source-check --harness`。只运行无旗标 source-check 是旧消费者兼容检查，不能进入新版实现。检查将问题写入原 open-findings 的 spec.ios-harness section，不清空其他 section。

## 计划与四拍

原 indexed UI/Base/Slice 计划继续保留作为可读责任合同。再将任务交给 `plan-ir --input <typed-plan.json>`。输入包含 schema_version=2、wave=domains、graph_sha256、tasks、max_parallel（缺省 1）、decisions。

每 task 必填 id、role、goal、ownership（具体文件，禁止通配）、fact_ids、ac_ids、parents。角色必须随包存在；共享导航、资源和注册文件必须分配单一 owner。所有 AC 进入任务，不能遗漏检测义务的事实。代码任务包含原资源、UI、Base、Feature、组装责任，按实际依赖排 DAG。将占位、接口及平台差异决定写入计划/决策，禁止在执行时临场造替代行为。

计划生成器写 canonical blueprint、原版 plan IR、任务书。计划、任务书和 baseline 均按摘要冻结。不要自写 state.json、dispatch.json 或 journal.json。

```text
next-batch --project <target> --wave domains
按 action=dispatch 返回的任务书执行
任务产出同一路径的 ios-receipt v2
land-results --project <target> --wave domains
```

以上命令均经 a2h_ios.py 调用。宿主不可派代理时串行执行同一任务书并写同样回执，不另造计划。wait 只等待在途任务；escalate 保留失败并修根因；done 只代表代码任务已落账。原版最多重派一次，源合同错误不能通过欠账放行。

回执示例见 [receipt](../assets/receipt.json)。source_sha256、plan_sha256、task_id、ac_ids、file_hashes 必须真实。generated + final_state=PASS 表示生成已完成，behavior_verified=false；blocked + BLOCKED 表示未完成。原版兼容字段 domain、fixed、skipped、files_touched 同时保留。禁止把 blocked 回执改 PASS，缺产物、越权文件、摘要不符和开放 findings 均拒绝落账。

## 验证与恢复

调用原结构、编译、UT、UI/视觉技能执行真实检查。构建与设备环境不足时，记录受影响范围，继续独立任务；不得声明该范围 PASS。

维护 ios-behavior.json v2：事件链为 input→processing→feedback；存储链为 save→reload→business_effect。每节点携 target path/line/symbol/sha256。review 指明独立审阅者。源 oracle 绑定 source_fact、expected、reviewer；目标用真实命令/设备 provider 观察，不能将目标实现生成的期望反过来当真值。

`behavior-check` 默认只查链路，未运行用例返回 UNVERIFIED（exit 3）。`behavior-check --run` 才执行声明命令、保存 stdout/stderr/退出码，并比较独立 expected。单个 unit 结果不能证明 ui/device AC，任何未覆盖 AC 保持待验。源码或目标改动后必须重测；结构检查不能证明功能等价。

源码变化后 `facts` 归档旧图并重提取，重审覆盖、规格和计划。冻结计划不会自动重写；续跑前对变更及已落账范围做明确重排，不继承过期回执。失败按原 finding owner 处理，复跑产生该 finding 的检查才能关闭。

源索引更新使用 `source-refresh --review <review.json>`，必填 reviewer/reason/previous_source_sha256/source_sha256；仍须重审并复跑门禁。已冻结计划用 `replan --input <typed-plan.json>`，附 replan_review 的 reviewer/reason。在途任务须先落账或明确终止，旧三账和任务书归档，新 run 不继承旧成功。行为用例必须携 target_hashes，执行前后核对实际目标输入未变。
