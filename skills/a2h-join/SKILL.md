---
name: a2h-join
description: "子代理 join 协议的机械零件库（收口硬闸 join_gate / 活性探针 wait_for_artifact / 事后审计 audit_join_coverage）。不是可独立触发的流水线阶段——由各派发型 skill 的 join 点显式调用其脚本；用户一般不直接调用本 skill。"
metadata:
  type: utility
  domain: migration
  tags:
  - utility
  - migration
---

> **路径约定**：下文 `$SKILLS_ROOT` = 本套 skills 的安装根目录。执行任何脚本前先设一次：`SKILLS_ROOT="$(cd "$(dirname 本SKILL.md)/.." && pwd)"`（用户级安装=`~/.agents/skills`；项目级=`<project>/.agents/skills` 或 `<project>/skills`）。

# a2h-join — 子代理收口协议零件库

## 背景（为什么需要它）

Codex 的子代理完成后**不会**唤醒主会话——结果必须由主会话主动循环 `wait_agent`
再经 `list_agents` 确认取回。协议全文（五条款）在各派发型 skill 顶部的
dispatch banner 里；本 skill 提供三个机械零件，把两类实测事故变成脚本可拦：

- **静默卡死**：模型"字面等待"结束回合（issue #23，AIPPT 断网后挂 4.5h）
- **假交接**：completed ≠ 验收——子代理报完成但产物缺失（实测：7 个分片
  agent 派完即停、functional_points 从未合并）

## 三个零件

### 1. join_gate.py — 收口硬闸（join 点必调）

```bash
python3 $SKILLS_ROOT/a2h-join/scripts/join_gate.py --project <目标工程> \
    --join-point <名字> --rollout <派发方本会话的原始rollout.jsonl>
```

- 本封装显式读取 `--rollout` 指定文件，不扫描其他会话；缺少该参数返回 exit 3。
- 派发前必须有非空 `spec/a2h/_work/expected_<join点>.json`；只选择其中 `task_names`
  匹配的真实直接子任务，不把其他仍在施工的同级任务算作本 join 已收口。
- 派发方身份来自原文件首个 `session_meta` 的 `agent_path` / `source.subagent.thread_spawn.agent_path`；
  fork 继承进来的祖先会话元数据不能替换当前 writer。匹配原 `spawn_agent` 的 call_id 与真实返回身份，
  再把 `/root/派发方/子任务` 等深路径投影成原消费者支持的 `/root/子任务`。
- 完成依据是该句柄最近一次真实 `list_agents` 肯定状态。live 列表回收已完成槽位后的缺席不抹除
  已观测的 completed；真实 `followup_task`、中断或新的 running 观测会重置完成状态，直到再次观测完成。
  `FINAL_ANSWER` 正文、代理自报列表、文件存在和 0 句柄都不能补造完成。
- 投影保留原 call_id、记录顺序、状态及来源 SHA 映射，明确标记 derived；原文件持续追加时可按
  `source_bytes` 指定前缀复验 `source_sha256`。派生文件不能再次当作原始 rollout 输入。
- 原 gate 继续验证普通 joined 的 expected-set 与真实产物，并负责追加原 join 账本。该入口要求全部 expected
  句柄有肯定 completed 证据；unknown/缺证据返回 3，running/failed/dead 或产物不全返回非 0。
- exit 0 → 追加 `spec/a2h/_work/join-ledger.jsonl`；exit 1 → 打印缺口清单，
  **禁止发完成报告/进下一阶段**；exit 3 → 按提示补信息（如先调一次 list_agents）
- 条款⑤ fire-and-forget 豁免 = 脚本内静态 allowlist（改表须过评审），
  正文 `[fire-and-forget]` 声明只是文档层，不能替代本封装非空 expected-set 的完成证据。
- v2 仅凭本次原 gate 新追加的原账本裁决确认 exempt：账本须保留旧字节，并准确覆盖同 join 点、
  带本次源 SHA 的投影文件及全部 expected 句柄，不能重用旧记录或仅凭 stdout 放行。
  exempt 还需通过当前 expected 的非空 artifacts：安全工程相对路径/glob、文件数、min_bytes、
  请求的 JSON 格式。支持 min_count（默认1）、可选精确 count、min_bytes（默认0）、json（默认false）；
  不支持的字段/空合同及不合法类型拒绝。审计保留 exempt，不伪写 joined。
  `--no-ledger` 下无可验证的原 exempt 裁决时保持拒绝，普通 joined 的该模式保持原行为。

投影保存在 `spec/reports/host-oracle/support/join-<join点>-<源SHA>.log`，来源、身份映射、
工具版本/文件 SHA、原 gate 退出码及输出保存在
`spec/reports/derived/a2h-join/<join点>/<源SHA>.json`。stdout 只给身份、状态、计数、SHA 和审计路径；
消息正文仅留在本地相关证据，不输出或上传。`--no-ledger` 仍保留这些派生审计证据，原 gate 不追加 join 账本。

### 2. wait_for_artifact.py — 活性探针（条款②辅助）

```bash
python3 $SKILLS_ROOT/a2h-join/scripts/wait_for_artifact.py --path 'entry/**/*.ets' --window 120
```

⚠️ **不是 join oracle**——完成判定唯一权威 = `list_agents` 的
`{"completed": …}`；文件会中途落盘，存在/条数 ≠ 完成（两条实测事故铁律）。
本脚本只回答"产物还在长吗"：exit 0=活；exit 2=零增长（结合连续 wait 超时
按条款②判死活）。

### 3. audit_join_coverage.py — 事后审计（回归 oracle + ledger 防伪）

```bash
python3 $SKILLS_ROOT/a2h-join/scripts/audit_join_coverage.py <rollout.jsonl>... \
    [--ledger spec/a2h/_work/join-ledger.jsonl] [--json out.json]
```

对每个句柄判 joined / fire-and-forget / ORPHAN，出句柄回收率；
`--ledger` 做防伪交叉验证（ledger 声称 joined 但 rollout 无 completed 观测
= 伪造/失配）。

## expected-set 契约（治"completed 但产物缺失"）

并行派发（T1 类 join 点）在 **spawn 前**由派发方落盘：

```json
// spec/a2h/_work/expected_<join点>.json
{"join_point": "stage1_batch2",
 "task_names": ["conv_page_*"],
 "artifacts": [{"path": "entry/src/main/ets/pages/*.ets",
                "min_count": 8, "min_bytes": 200, "json": false}]}
```

- 契约必须来自**派发方**——不认子代理自报 manifest（摸鱼者的 manifest
  会与其半截产物完全吻合）
- 原库的**原子信封**协议保留在 vendor：`spec/a2h/_work/done/<task_name>.done`。
  当前封装使用非空 expected-set；缺少它时返回 3，不自动切换到信封或空句柄成功。
- `task_name` 必须唯一化（带 page-id/slice-id/round-N 后缀），这是
  task_name↔completed 机械配对不误配的前提

## 判定表（audit / gate 共用语义）

| 状态 | 判定 |
|---|---|
| completed + 契约/信封通过 | ✅ joined |
| 静态 allowlist 命中 | ⏭ fire-and-forget |
| Gate 摘要列明 + 指定 join 点的跨 Gate 存活 | ✅ alive-across-gate(declared) |
| 死句柄已按条款②断点重派 | ✅ dead-redispatched（原句柄免 FINAL） |
| completed 但契约 FAIL 且未重派 | ❌ completed-but-incomplete |
| 其余悬空 / 无 gate 记录即发完成报告 | ❌ 漏收 |

## 职责边界

- "做错了"（内容级）不归本套管——gate 验齐不齐/格式对不对；内容对错归
  verify / reviewer 轮（反摸鱼质检另有闭环）
- 无法读取指定原始 rollout 时返回 3，先补足真实来源与状态观测后再调用。
- 巡检 expected 产物按原 `patrol-routing.md` 闭表填完整域角色：
  `spec/fix/round-<正整数>/patrol/arkts-<ui-build|ui-adapt|data-network|system-component|thirdparty-component>-<batch|group>-<数字ID>.md`。
  原 apply 打印的 `<域>` 用该完整角色名替换；task_name 中的 `build/network` 简写不作为文件域别名。
