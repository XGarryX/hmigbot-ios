<!-- when: 每次落账、阶段收口与最终交付时生成并检查 spec/migration-report.md -->
<!-- topics: 迁移报告, 派生汇总, 页面证据, 阶段细节 -->

# a2h-execute 迁移报告协议

按 [a2h-execute §10](../SKILL.md#10-迁移报告) 实际运行 `spec-summary`、`migration-report` 和 `migration-report --check`。工具生成 `spec/reports/spec-summary.json` 与 `spec/migration-report.md`；本文件说明其消费方式，不提供可手工填成功数的报告正文。

## 工具生成的固定结构

`migration-report` 的当前生成器是唯一结构来源。报告标题为“迁移证据报告”，携 `source_sha256` 与 `summary_sha256`，依次输出以下三张表：

| 表 | 固定列 | 值来源 |
|---|---|---|
| 规格数量 | 范围、数量 | 当前 feature/page/AC 清单 |
| 全局证据轴 | 证据轴、当前状态 | 当前生成、编译、行为、视觉证据 |
| 逐页关联 | 页面、计划项、任务、AC、生成、编译、行为、视觉 | 同轮 summary 的 `pages`，逐页关联与状态 |

summary JSON 保留 Markdown 未展开的 `target_paths`、AC 观测状态、原内核落账、当前回执/文件摘要及证据输入。需要核查一页时沿该页的 `page_id → plan_item_refs/task_ids → target_paths → ac_ids` 阅读明细，不用页面文件数量或回执数量代替成功率。

## 状态的证据边界

- 生成通过须有当前冻结计划、回执摘要、目标产物摘要与原调度器成功落账；仅有回执、文件或旧 converted/verified 不够。
- 编译只说明本次全工程构建证据覆盖声明的目标页面文件；不证明该页注册、可达、点击有效或满足行为。缺少目标输入绑定的旧构建报告保留 `legacy_unclassified`。
- 行为按本页关联 AC 的独立期望、实际执行与观测层级计算；部分 AC 通过不得向其他页面或未测 AC 扩散。宿主逻辑用例不能证明设备 UI。
- 当前没有可校验的逐页视觉证据协议，页面视觉为 `not_run`；旧视觉报告只作 `legacy_unclassified`。真实视觉结论另引 verifier 报告，不能手改派生状态。
- `not_run`、`unknown`、`unverified`、`unmapped`、`unlanded`、`stale` 均保持原义，不按口头 PASS 翻转。

结构检查独立引用 `loops-final-structural-closure.json` 与 `final_structural_closure_brief.md`。summary 不生成结构结论，构建通过也不能替代结构检查。

## 生成与复核

构建证据可用时，三次命令传入同一个真实 `--build-evidence` 路径；未构建则不传。先读 summary JSON，再读派生 Markdown，最后运行 `--check`。检查会从当前证据重算并拒绝过期或手改报告；输入或目标变化后重跑，不直接修改结果。三份控制账本的原写者保持不变。

## 另写的阶段细节

需要 Stage/Batch/Slice 详情时，写入 `spec/execution/` 的阶段报告，链接同轮派生报告、summary JSON 及原始证据。可记录下列事实，不复制示例成功数：

| 明细 | 必须带的定位依据 |
|---|---|
| 阶段任务、失败与恢复条件 | 原计划项、task_id、真实退出码、receipt/brief 路径 |
| 页面产物与接线 | page_id、拥有文件、真实结构检查路径 |
| Skill 调用与覆盖决定 | 实际调用记录、任务、原建议、使用能力及原因 |
| 编译与修复轮次 | 构建报告、日志、目标输入和产物摘要 |
| 占位与未完成项 | registry 的实际 P-ID、状态、owner、恢复条件 |
| 结构收口 | 实际 loops JSON、brief、final_state 与 verdict |

阶段细节不能覆盖工具派生的页面状态；有冲突先核查输入和证据，再重建报告。
