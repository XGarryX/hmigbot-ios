---
name: arkts-structural-closure
description: "复用 HMigBot 目标骨架、接线、孤立 VM、装配、占位债务与收敛检查；原生 iOS 图片约束前置防止错误尺寸自愈，结构通过仍需行为验证。"
---

# 鸿蒙目标结构闭包

沿用原阶段/slice/group/pipeline 四类检查与迭代状态、修复派发、唯一 closer。
目标 plan 为 indexed-v1，执行中只读。source_anchors 与 iOS 原生 facts 不改变目标接线责任。

## 运行一次检查迭代

```text
python <skill>/scripts/structural_loop.py iterate --project-root <target> --mode slice --target 1 --state-file <state.json> --output-json <result.json>
```

自定义 `--state-file` / `--output-json` 的 JSON 数据直接放在 `spec/execution/autofix-log/round-<正整数>/`；basename 可用字母、数字、下划线、连字符、点（不以点或连字符开头）。该平层 JSON 命名空间是派生证据，名称不必匹配固定前缀；不授权产品、脚本、嵌套任意 JSON、相邻目录或自定义 `.log/.md` 名称，原有明确日志模式保持。轮次不含0或前导0，不使用路径穿越。

stage 模式额外传 --diff-base 与 --handoffs；group 模式传 --slices 1,2；
pipeline 模式 target=final，覆盖完整目标。参数来自当前计划，不能硬编码另一项目 ID。
--max-iter 为重试上限，不是忽略失败条件。收口用 finalize，实际参数先核对 --help。

## 原目标检查保留

- stage：真实 skeleton 审计。
- slice/group：骨架、孤立 VM、page.handler/target 结构接线、FWD-REF 与跨 slice 所有权。
- pipeline：全量骨架、跨 slice 组件/VM、沉浸安全区、占位债务、装配、能力/主题/字面量/
  空壳驱动/载体降级/命中/资源等原目标检测；以实际返回的 detector 清单为准。
- 参数与输出来自随包原 HMigBot helper，退出码/报告完整保留，不自行伪造 CONVERGED。

## iOS 图片前置

pipeline 在调用原引擎前先用原只读 Image 约束检测器生成 native-images 报告。
有欠约束 Image 时返回 `NATIVE_INPUT_REQUIRED`（exit 3），不进入会修改图片尺寸的原 pipeline。
先按 arkts-icon-sizing 从真实 iOS 布局/asset scale 修复，再重跑；不统一推测密度。
预检无候选后才进入原 pipeline，原尺寸自愈没有待改对象；校验期间独占目标写锁。

## 结果处理

CONVERGED：读取所有 detector 结果及缺失检查，合并 brief，不能只看总体字样。
CONTINUE：按 dispatch_prompt 给对应 owner 修复，回读代码再迭代；不写空报告骗收敛。
STALLED/REGRESSED/EXHAUSTED：保留具体失败/历史与决策需求，独立工作可继续。
NATIVE_INPUT_REQUIRED/输入错误：回到资源/源事实/结构输入的责任 owner，修复后重跑。
状态/报告缺失不是成功，未运行 detector 保持 incomplete。

原 verify_slice_wiring 能拦截孤立 VM，但可能接受只有空 handler 的页面；
因此结构 PASS 不证明 AC 行为通过，必须继续独立源真值的 unit/UI/device 验证。
原闭包修复结束后由 hmos-fix-build-errors 做终态全量编译，最后交 a2h-verify。


## 现代计划的能力静态义务

profile 2使用plan-delivery-contract的capability_schema:2声明；先核已验证责任集合的
Base1..6/Slice3c ownership全覆盖，再核真实规范表、scoped消费者及结构化初始化。
调用现有gen_capability_manifest.py/capability_ledger_gate.py的--project-root/--output-json，
不另造无人消费CLI；gen默认spec/execution/capability-manifest.json。现代--emit-interface
明确不支持，不生成/覆盖产品接口；按声明真实导出接线。缺声明不回退旧空成功，pending不等于
实现，gate重新派生并核摘要。stage_runtime的一次性pipeline也消费同一模块，保留失败；
不得忽略ledger或以其它detector通过制造CONVERGED。legacy原协议透传；framework-created仅支持已核SDK的FormExtensionAbility与
InsightIntentEntryExecutor模式，必须真实导入/装饰器/精确注册且无产品new。参见a2h-plan/references/plan-delivery-contract.md
的严格字段/支持语法与普通checkout可运行示例。始终runtime_verified=false；静态门不证明
编译、设备、行为或视觉。本机C7集成必须显式提供冻结快照，缺输入只可标skip/未验证。
