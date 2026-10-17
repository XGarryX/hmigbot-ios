# 迁移证据报告

<!-- hmigbot-derived-report:2 -->

- source_sha256: `1844c685b73467c094a93980e090ab6877d89429076ad0cdc0903599ddfe44d3`
- summary_sha256: `586ed612f28cfa0388729c2b09ba2c371995c5e097f27ff98b2b720c1309342f`

| 范围 | 数量 |
|---|---|
| acceptance | 2 |
| features | 1 |
| pages | 1 |

| 证据轴 | 当前状态 |
|---|---|
| generation | generated |
| compilation | passed |
| behavior | unverified |
| visual | not_run |

| 页面 | 计划项 | 任务 | AC | 生成 | 编译 | 行为 | 视觉 |
|---|---|---|---|---|---|---|---|
| page_0001 | SLICE:F001:3a, UI:PAGE-0001 | counter | F001-AC02 | generated | passed | unverified | not_run |

生成依据原内核落账和当前文件哈希；编译依据绑定当前输入的构建证据。
行为仅覆盖已执行的独立 AC 观测；宿主逻辑测试不证明设备 UI。视觉与结构检查需各自证据。
not_run、unverified、unmapped、unlanded、stale 均不等于通过。完整明细见同轮 spec-summary JSON。
