---
name: arkts-structural-closure
description: "鸿蒙/ArkTS 目标工程的结构性验证闭环：对目标做骨架占位（L1-L4）、孤立 VM、wiring 四类闭包（C1-C4）、装配/占位债务/沉浸安全区等检测，以 stage/slice/group/pipeline 四模式做一次性 sanity 与三态迭代收敛（CONVERGED/CONTINUE/STALLED/REGRESSED/EXHAUSTED），并把结果嵌入 brief 与 loops JSON。被 a2h-execute §4c（mode=stage）/§6f/§7（mode=pipeline target=final，FV-1）调用。原生 iOS 图片约束前置（无欠约束 Image 才进原 pipeline，否则 NATIVE_INPUT_REQUIRED exit 3）防止错误尺寸自愈；结构 PASS 不等于行为通过。当用户说“结构性验证”“跑 wiring 检查”“扫骨架”“结构闭环”“收敛检查”“验证接线”时使用。不要用于：编译验证（用 hmos-fix-build-errors）、行为/设备/视觉验证（用 a2h-verify / arkts-visual-verify）、生成代码（用 a2h-execute worker）。"
metadata:
  type: domain
  domain: migration
  tags:
  - ios
  - verification
  - structural-audit
  - migration
---

> **派发约定**：本 skill **不自行派发 subagent**——它被 a2h-execute（§4c/§6/§7 内）或 a2h-closer（mode=batch/base/group/final）调用。迭代中 `CONTINUE` 的修复派发由**调用方**按 `dispatch_prompt` + `fixer_layer` 分轨：feat 类（services/viewmodels/repository/store/utils）→ `a2h-migration-worker`，ui 类（pages/components/widgets/resources）→ `a2h-ios-converter`。若宿主支持 subagent，调用方仍须遵守 Join 协议（收口五条款）：① 循环 wait，完成的唯一合法信号是代理 completed 状态，绝不是产物文件存在/条数；② 死句柄与验收，completed≠验收通过，join 点跑门禁验产物；③ 收口锚点，最终报告前收口全部句柄；④ 放行≠遗弃；⑤ 仅正文显式声明“结果丢弃”的派发免收口。**谁派谁收**，契约产物必须出自承担任务的子代理。
>
> 路径约定：`<target>` = 鸿蒙目标工程根（`$IOS_SRC` 仅在核 iOS 源合同/图片前置时经 `<target>/.migbot/config.json` 的 `ios` 字段读取，不改变目标接线责任）；本 skill 自有脚本在 `<sk>/scripts/`。state/result JSON **只落 `spec/execution/autofix-log/round-<正整数>/`**。

# arkts-structural-closure — 鸿蒙目标结构闭包

## 关键约束（Critical）

- **调用前 MUST 读完本 SKILL.md §3**——verdict 处置 + 收敛常量 + repair worker 分轨缺一不可。
- **检测分层**：Stage 1/2 末尾 = `mode=stage`（一次性骨架审计，非迭代 loop）；Slice = `mode=slice` loop；parallel-group = `mode=group` loop；Pipeline-end = `mode=pipeline` loop（target=final）。
- **4 种 mode 共用同一套 verdict 处置**（§3.4 表）；差异只在 mode 参数 + 作用域。
- **goal 计划为 `indexed-v1`，执行中只读**：`source_anchors` 与 iOS 原生 facts 不改变目标接线责任。
- **不引入 `--mode=repair`**：repair worker 复用原 worker 完整上下文，仅追加 `dispatch_prompt` 字段作 findings 提示。

## 0. 定位与纪律

- **前置**：a2h-plan 已产出冻结 indexed 计划（`spec/baseline/plans/feature-plan.md` 的 `plan_format: indexed-v1` + 分片 detail 指针）；`spec/baseline/` 与 `spec/placeholder-registry.md` 就绪。缺计划 → 回 a2h-plan，不代跑。
- **输入**：目标 `.ets` 源码、冻结计划（只读）、`spec/baseline/{ui-manifest,feature-index}.md`、`spec/placeholder-registry.md`、`spec/decision-ledger.md`。
- **输出（调用方消费）**：`spec/execution/autofix-log/round-<R>/` 下 loop/audit/wiring JSON；pipeline 收尾 `loops-final-structural-closure.json`（`final_state==PASS`）；嵌入 brief 的 `final_structural_closure_brief.md`（`spec/execution/briefs/`）。
- **唯一交互点 = 无**：verdict 由 exit code 裁决，主会话只按表分派 repair 与重跑。
- **第一条可见输出必须是一行计划**（预检 → 迭代 → finalize → 交接/冒泡），然后才执行对应 mode。
- **唯一 closer**：pipeline/group 收口由 a2h-closer（mode=final/group）单写者做，本 skill 不重复落账；finalize 只读 state 产出 loops JSON，不写计划、不改产品文件。
- **结构 PASS 不等于行为通过**：结构闭环门只证明骨架/接线/装配/债务收敛，**不证明任何 AC 行为、编译、设备或视觉**。

## 1. 定位

ArkTS 目标工程的结构性验证统一 skill，与 `a2h-execute` 编排解耦，可被任何 pipeline 阶段或独立场景调用：

- **检测维度**（以实际返回的 detector 清单为准）：skeleton 占位（L1-L4）、wiring 四类闭包（C1 orphan / C2 integration_point / C3 cross_slice / C4 parent_replacement）、跨 slice 孤立 VM 与组件孤儿、沉浸式/安全区四件套、占位债务终结闸（registry 残留 + deferred_items 对账）、装配闸（fail-closed 未装配）、能力交付契约（profile 2 capability_schema），以及 vendor 侧主题/字面量/死壳/载体/命中/资源名等 gate（pipeline 模式收编的 13-detector 稳态合集）。
- **执行形态**：一次性 sanity（Stage 末尾 `mode=stage`）+ 迭代收敛 loop（slice/group/pipeline）。

```
a2h-execute 编排
    ├─ §4c  Stage 1/2 末尾        ──►  本 skill mode=stage（一次性骨架审计）
    ├─ §5e  每 parallel-group 收尾 ──►  本 skill mode=group（§2.2b，含 slice 退化）
    └─ §6/§7 Stage 3 完成后 FV-1   ──►  本 skill mode=pipeline target=final（§2.3）
```

## 2. 四种调用入口

### 2.1 Stage 末尾 sanity（`mode=stage`，一次性审计，**非 loop**）

适用 Stage 1/2 末尾（a2h-execute §4c）——99% iter 0 PASS，loop 5 类 verdict 在此无对应的失败升级模式。

```bash
python <sk>/scripts/structural_loop.py iterate --project-root <target> \
    --mode stage --target <1|2|3> \
    --state-file <target>/spec/execution/autofix-log/round-<R>/loop-state-stage-<N>.json \
    --diff-base <STAGE_START_SHA> \
    --handoffs <Stage 产出 brief 路径...> \
    --output-json <target>/spec/execution/autofix-log/round-<R>/loop-result-stage-<N>.json
```

| exit | 处置 |
|---|---|
| 0 | FAIL=0 → 进入下一 Stage |
| 1 | 有 FAIL findings → Read result JSON 的 `findings[]` → 派本 Stage primary worker 修一次 → 重跑本命令；连续 2 次仍 FAIL → 标 BLOCKED |
| 2 | 用法/状态/输入错误 → 读错误修参数重跑 |

Stage 3 末尾自动启用 L4 dangling-fwd-ref 检测（`kind=forward-ref` 占位 `status=resolved` 但代码 marker 残留 → FAIL）。**registry 解析护栏（各 scope 通用）**：registry 存在且含 P-ID 数据行、但解析器加载 0 行 → 只发 1 条 `registry-parse-degraded` FAIL（工具链问题，勿派 worker 改业务代码，修表格式或 `skeleton_lib/registry_resolver.py` 后重跑）。

### 2.2 Slice 模式 loop（`mode=slice`，per-Slice 接线验证）

适用 Stage 3 每个 Slice（§6e Step 3e）。作用域 = 本 Slice `modifies_files` + `cross_slice_edits`。

```bash
python <sk>/scripts/structural_loop.py iterate --project-root <target> \
    --mode slice --target <N> \
    --state-file <target>/spec/execution/autofix-log/round-<R>/loop-state-slice-<N>.json \
    --output-json <target>/spec/execution/autofix-log/round-<R>/loop-result-slice-<N>.json
```

Loop 内部跑 audit（skeleton + dangling-fwd-ref，限本 Slice 文件）+ wiring（C1-C4）。CONVERGED 后由调用方追加非 loop 校验（placeholders / source-notes / deferred_items —— 见 a2h-execute §6e）。

### 2.2b Group 模式 loop（`mode=group`，per parallel-group 接线验证）

适用 Stage 3 以 `parallel_group` 为粒度收尾（a2h-execute §5e：group-closer 编译 PASS 后自跑并 fix-forward ≤3 轮直到 CONVERGED，非收敛才冒泡主线程）。作用域 = 组内全部 slice 的 modifies_files + cross_slice_edits 并集。

```bash
python <sk>/scripts/structural_loop.py iterate --project-root <target> \
    --mode group --target <groupId> --slices <N,M,...> \
    --state-file <target>/spec/execution/autofix-log/round-<R>/loop-state-group-<G>.json \
    --output-json <target>/spec/execution/autofix-log/round-<R>/loop-result-group-<G>.json
```

`--slices` 必须显式列出组内全部切片（逗号分隔，与 index 中 `parallel_group` 成员一致，重复/遗漏报用法错）。verdict/dispatch_prompt/state 与 slice 模式同构。CONVERGED 后按组内每 slice 巡检 placeholders / source-notes / deferred_items。

### 2.3 Pipeline 模式 loop（`mode=pipeline target=final`，整工程兜底）

适用 Stage 3 全部 Slice 完成后一次性整工程兜底（a2h-execute §7 FV-1）。作用域 = 整工程 `.ets`。**pipeline 先跑 §4 的 iOS 图片约束前置，通过才进原引擎**。

```bash
python <sk>/scripts/structural_loop.py iterate --project-root <target> \
    --mode pipeline --target final \
    --state-file <target>/spec/execution/autofix-log/round-<R>/loop-state-pipeline-final.json \
    --output-json <target>/spec/execution/autofix-log/round-<R>/loop-result-pipeline-final.json
```

- Loop 内部跑 vendor 原 engine 的 13-detector 稳态合集：`audit / assembly / binding / carrier / deadshell / hittest / icon / immersive / ledger / literal / orphans / resname / theme`（`_REQUIRED_DETECTORS` 对齐）。skeleton + dangling-fwd-ref + intentional-default 反查；跨 slice 孤立 VM（候选 `viewmodels/store/repository/service/network`，`NO_IMPORTER`/`IMPORTED_BUT_NOT_INSTANTIATED` 真死信号，`ONLY_INSTANTIATED_BY_NON_UI` 带证据豁免）+ 组件孤儿（E1）；沉浸式/安全区四件套；债务终结闸（registry 残留分类 + deferred_items 对账）；装配闸（fail-closed 未装配 + 空对象占位，含 capability_ledger 换装）；以及 vendor 侧 theme/literal/deadshell/carrier/hittest/resname gate。**以实际返回的 detector 清单为准**。
- **降级执行铁律**：任一 detector 崩溃由 `_safe_detector` 隔离（记 `passed:false` + 计入 FAIL），不中断同轮其余 detector；finalize 会核对 `history[-1].detectors_run` 是否覆盖本 mode 必需集，缺项直接 `final_state: INCOMPLETE` 并列 `missing`，**不会给 PASS**。禁止挑一两个 detector 补跑就宣告完成，禁止手写“看起来通过”的 loops JSON。

## 3. structural_loop 协议（stage / slice / group / pipeline 共用）

### 3.1 收敛常量（`scripts/loop_runner.py` 包内原 HMigBot 实现）

```text
MAX_ITER             = 8      # 单 loop 默认上限
STALLED_THRESHOLD    = 2      # 连续 N 轮 findings fingerprint 相同 → 停滞
REGRESSION_THRESHOLD = 1.5×   # findings 数 > 前轮 × 此倍率 → 退化
```

> `--max-iter <N>` 是重试上限（透传至 `iterate`），**不是忽略失败条件**：低风险/纯 UI 切片可传 `--max-iter 2` 封顶省迭代；支付/会员/双签名/成环等高危域保留默认 8。封顶后仍有未决 finding 照常 STALL→ESCALATED 浮出复核，不静默放行。

### 3.2 调用契约

每次 `iterate` 执行 1 轮迭代：state 文件自动累积 `history`；各 detector 详细 JSON 由 engine 内部产出。CONVERGED 后 `finalize` 收尾：

```bash
python <sk>/scripts/structural_loop.py finalize \
    --state-file <target>/spec/execution/autofix-log/round-<R>/loop-state-<mode>-<target>.json \
    --output-json <target>/spec/execution/autofix-log/round-<R>/loops-<mode>-<target>.json
```

- **state/result JSON 落点铁律**：自定义 `--state-file` / `--output-json` 的 JSON 数据直接放 `spec/execution/autofix-log/round-<正整数>/`；basename 可用字母、数字、下划线、连字符、点（不以点或连字符开头）。该平层 JSON 命名空间是派生证据，名称不必匹配固定前缀；不授权产品、脚本、嵌套任意 JSON、相邻目录或自定义 `.log/.md` 名称，原有明确日志模式保持。**轮次不含 0 或前导 0，不使用路径穿越**。
- pipeline 收尾产物 = `spec/execution/autofix-log/round-<R>/loops-final-structural-closure.json`（含 `final_state`）——a2h-execute §7 / FV-1 的 gate 对象；show 嵌入 `spec/execution/briefs/final_structural_closure_brief.md`。

### 3.3 收敛 verdict 处置表

| exit | verdict | 触发条件 | 调用方动作 |
|---|---|---|---|
| 0 | `CONVERGED` | findings 全 clean | 调 `finalize` 产 loops JSON → 嵌入 brief `final_state: PASS`；**读取所有 detector 结果及缺失检查，合并 brief，不能只看总体字样** |
| 1 | `CONTINUE` | findings 仍存在 | Read result JSON 的 `dispatch_prompt` → 派 repair worker（fixer_layer 分轨：feat→`a2h-migration-worker` / ui→`a2h-ios-converter`）**原 prompt 末尾整段追加 dispatch_prompt** → 回 `iterate`；回读代码再迭代，不写空报告骗收敛 |
| 2 | `STALLED` | 连续 2 轮 fingerprint 相同 | 调 finalize → brief `final_state: ESCALATED` + pipeline 继续 |
| 2 | `REGRESSED` | findings 数 > 前轮 × 1.5 | 调 finalize → 回滚本单元改动 + brief `final_state: ROLLED_BACK` + 阻断下游 `depends_on` |
| 2 | `EXHAUSTED` | 满 8 轮未 CONVERGED | 同 STALLED |
| 3 | `NATIVE_INPUT_REQUIRED`（仅 pipeline 前置） | 图片前置有欠约束 Image | 回到资源/源事实/结构输入的责任 owner 修复后重跑（§4）；不进入原 pipeline |
| 2 | 用法/输入错误 | 状态 mode/target 不一致、缺失分片、非法参数 | 读错误修参数重跑 |

- STALLED/REGRESSED/EXHAUSTED：**保留具体失败/历史与决策需求**，独立工作可继续；不伪造 CONVERGED。
- **状态/报告缺失不是成功，未运行 detector 保持 incomplete**。

### 3.4 Stage 末尾闸

ESCALATED Slice 累计 > 10% → 阻断进下一 Stage / a2h-verify。该判定由 a2h-execute 主流程做，本 skill 不持有累计统计。

### 3.5 Repair worker 派发原则

复用原 worker 完整上下文（spec + iOS 源 + plan），**不引入 `--mode=repair`**；仅在原 prompt 末尾追加 `dispatch_prompt`；指令统一“按 suggested_action 修复，不做无关变更”；feat→`a2h-migration-worker`、ui→`a2h-ios-converter`；pipeline 按 finding/orphan 的 `file` 路径推断所属层。

## 4. iOS 图片约束前置（NATIVE_INPUT_REQUIRED，exit 3）

pipeline 模式在调用原 engine **前**，先用**只读** Image 约束检测器生成 native-images 报告（`<state-file stem>-native-images.json`）。这是 iOS 迁移的固定红线：

- **有欠约束 Image（无 width+height / size / width+aspectRatio）→ verdict `NATIVE_INPUT_REQUIRED`，exit 3，不进入会按 Android 密度改图片尺寸的原 pipeline**——原 pipeline 的尺寸自愈是 Android density 推断，iOS 无 adb/无统一 density 桶，自愈会写出错误尺寸。
- 处置：按 `arkts-icon-sizing` 从**真实 iOS 布局 / asset scale** 修复 owned ArkUI 尺寸（不统一推测密度），再重跑；预检无候选后才进原 pipeline，此时原尺寸自愈没有待改对象。校验期间独占目标写锁。
- 源合同豁免：只读检测对 `ONE-DIM-NO-ASPECT` 逐条尝试 `source_bounded_image` 证明（typed `image.PixelMap` + `spec/baseline/ui/*.md` 冻结的 Swift `resizable().scaledToFit().frame(maxHeight:)` 合同）；证不出的保留原 finding = 仍需源尺寸。**绝不推测 point→vp scale，绝不伪造视觉 PASS**。

## 5. 现代计划的能力静态义务（profile 2 capability_schema）

profile 2 使用 `plan-delivery-contract` 的 `capability_schema:2` 声明；先核已验证责任集合的 Base1..6/Slice3c ownership 全覆盖，再核真实规范表、scoped 消费者及结构化初始化。

```bash
python <sk>/scripts/gen_capability_manifest.py --project-root <target> --output-json <target>/spec/execution/capability-manifest.json
python <sk>/scripts/capability_ledger_gate.py --project-root <target> --output-json <target>/spec/execution/capability-ledger-iterN.json
```

- 调用现有 `gen_capability_manifest.py` / `capability_ledger_gate.py` 的 `--project-root` / `--output-json`，**不另造无人消费的 CLI**；gen 默认落 `spec/execution/capability-manifest.json`。
- `--emit-interface` 明确不支持：不生成/覆盖产品接口，按声明真实导出接线。
- **缺声明不回退旧空成功；pending 不等于实现**；gate 每轮重新派生并核摘要。
- `stage_runtime` 的一次性 pipeline 也消费同一模块，失败保留；**不得忽略 ledger、或以其它 detector 通过制造 CONVERGED**。
- legacy 原协议透传；`framework-created` 仅支持已核 SDK 的 `FormExtensionAbility` 与 `InsightIntentEntryExecutor` 模式，必须真实导入/装饰器/精确注册且无产品 `new`。严格字段/支持语法见 `../a2h-plan/references/plan-delivery-contract.md`。
- **始终 `runtime_verified=false`**：静态门不证明编译、设备、行为或视觉。本机 C7 集成必须显式提供冻结快照，缺输入只可标 skip/未验证。

## 6. 实现脚本对照

| 文件 | 职责 |
|---|---|
| `scripts/structural_loop.py` | 本 skill 统一入口（带 iOS 图片前置）；`iterate` 单轮 + verdict 计算 + `dispatch_prompt`，`finalize` 收尾；state/result 由其真实写入 |
| `scripts/loop_runner.py` | 收敛 verdict 计算核心（包内原 HMigBot 实现，5 类 verdict + 常量定义） |
| `scripts/audit_skeletons.py` | skeleton 检测（stage/slice/all scope）；被 structural_loop 内部调用，亦可独立跑 |
| `scripts/verify_slice_wiring.py` | C1-C4 接线检查（slice 单切片 / group 逐切片合并）；**能拦截孤立 VM，但可能接受只有空 handler 的页面** |
| `scripts/verify_closure_ledger.py` | 债务终结闸：registry 残留分类 + deferred_items 对账（pipeline） |
| `scripts/assembly_gate.py` | 存量工程兜底装配闸：fail-closed 骨架未装配 + 空对象占位 |
| `scripts/binding_gate.py` | 显隐绑定收货闸（pipeline）：dead-render-flag + binding-dropped 逐条核销 |
| `scripts/gen_capability_manifest.py` | 能力键集清单生成（profile 2，闸每轮重生成，防篡改） |
| `scripts/capability_ledger_gate.py` | 新制主闸（plan 含组装根任务时换装 assembly）：闭集收货五检 |
| `scripts/plan_lib/` | 冻结计划解析器（indexed-v1 布局：索引 detail 指针 → `plans/slices/` 文件） |
| `scripts/ref_graph_lib/` | 全工程 import + instantiation 引用图（orphan 检测、usage evidence） |
| `scripts/skeleton_lib/` | taxonomy + patterns + classifier + registry_resolver + deferral_policy |
| `scripts/README.md` | CLI 与 sub-package 简要对照 |
| `references/output-schema.md` | 各 detector / iterate / finalize 的 JSON schema 速查 |

## 7. 输出 JSON schema 速查

> **MUST**：各阶段（audit / wiring / iterate / finalize）输出 JSON schema 速查见 `references/output-schema.md`。finalize 嵌入 brief 的 `loops.structural` 段含 `final_state`；iterate 的 `dispatch_prompt` 字段是 repair worker 的唯一 findings 输入。

## 8. 调用方对照（a2h-execute）

| 调用点 | a2h-execute 章节 | 本 skill 入口 |
|---|---|---|
| Stage 1/2 末尾骨架审计 gate | §4c | §2.1 `mode=stage target=<1|2|3>` |
| Stage 3 每 parallel-group 接线验证 | §5e group 收尾 | §2.2b `mode=group`（size-1 组退化仍走 group） |
| Stage 3 所有 Slice 完成后最终闭包（FV-1） | §6f / §7 | §2.3 `mode=pipeline target=final` |

a2h-execute §7 定义的收尾 evidence（缺失或 `final_state ≠ PASS` 不允许进 a2h-verify）：

- `spec/execution/autofix-log/round-<R>/loops-final-structural-closure.json`（`final_state == PASS`）
- `spec/execution/briefs/final_structural_closure_brief.md`（嵌入 loops.pipeline 段）

## 9. 读取时机表（references）

| 触发时机 | 必读文件 |
|---|---|
| iterate / finalize 后核对 JSON 字段 | `references/output-schema.md` |
| 能力清单 verb / capability_schema 严格字段 | `../a2h-plan/references/plan-delivery-contract.md` |
| 骨架审计 gate（§4c）细则 | `../a2h-execute/references/skeleton-audit.md` |
| 派发 repair worker 的 prompt 模板与占位纪律 | `../a2h-execute/references/agent-prompts/_common.md`（随读） |
| 图片/尺寸修复口径 | `../arkts-icon-sizing/SKILL.md` |

## 10. 交接

- **前置门闸**：pipeline 最终 `finalize` 后 `loops-final-structural-closure.json` 的 `final_state == PASS`（结构 PASS）；随后进入行为验证——**行为由独立源真值 unit/UI/device 验证**，终态全量编译交 `hmos-fix-build-errors`，最后交 `a2h-verify`。
- **移交产物清单**：`spec/execution/autofix-log/round-<R>/**`（loops/audit/wiring JSON + native-images 前置报告 + native-pipeline 有效 detector 证据）、`spec/execution/briefs/final_structural_closure_brief.md`、`spec/execution/capability-manifest.json`（若 profile 2）。
- **下一步**：`mode=stage/slice/group` → 回 a2h-execute 对应与阶段继续；`mode=pipeline` CONVERGED → 交 hmos-fix-build-errors（FV-2 终态全量编译）→ a2h-verify。

---

## 收尾：上报本阶段用量

本 skill 为域步骤（由 a2h-execute 内嵌调用），不独立上报阶段用量；token 用量随 a2h-execute 的 `usage-*` 账本由宿主生命周期采集，本步不采集。**若有可用 usage 账本则尽力上报，忽略其退出码，绝不阻断流水线。**