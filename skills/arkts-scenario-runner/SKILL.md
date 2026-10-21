---
name: arkts-scenario-runner
description: "iOS→HarmonyOS 迁移到态器：把 iOS 与鸿蒙应用带到指定状态（登录/上传/权限/前置数据），为下游 arkts-visual-verify、a2h-verify 提供“已到态”就绪快照。按每端实际可用设备工具执行并保存证据；iOS 无自动控制 API 时记录 unavailable、凭用户采集证据推进，绝不把脚本配置或源码推断当已完成点击。当用户说“先登录再截图”“造一个已登录场景”“首页要登录态怎么办”“visual-verify 过不了登录页”“复杂交互测试”时使用。不要用于：视觉对比（用 arkts-visual-verify）、路由/导航核验（用 arkts-router-verify）、代码修复（交给对应 fixer）。"
metadata:
  type: tool
  domain: migration
  tags:
  - ios
  - automation
  - scenario
---

> **派发约定**：本 skill 主会话执行，**不派发 subagent 去探索/学配方**——未知场景的学习统一归外层 `scenario-builder`（合成优先、报缺不装会、证据准入）。本 skill 是纯“回放+到态”侧，只回放已知 YAML 场景并执行设备动作。
>
> **路径约定**：`$IOS_SRC` 从 `<target>/.migbot/config.json` 读；`<runtime>` = 本包 runtime（`scripts/a2h_ios.py` 所在根）。场景 YAML 与产物一律落 `<target>/spec/scenarios/`（场景私有，跨项目复用 skill 不落 skill 目录）；`creds.local.json` 含凭据**永不进 repo、不进报告**。本 skill 自有脚本 `scripts/scenario_run.py`、`scripts/recipe_ingredients.py`（thin wrapper，转发 vendor/hmigbot helper），确有才可调用。

# arkts-scenario-runner — 双端场景到态

## 0. 定位与纪律

- **前置**：读到稳定 `page/feature/AC` ID、应用版本、设备与目标状态、页面导航事实（`spec/ref/ios-ui-facts.md`）、本任务授权的操作范围。**付款、发送、删除等动作遵守该任务授权，不自动补造授权**。
- **输入**：目标状态（如“已登录”“已选图”“成员中心 VIP 态”）、双端应用安装状态、可用设备工具。
- **输出**：`<target>/spec/scenarios/artifacts/<timestamp>_<scenario>/result.json`（含 `success / signals / device / duration_ms` 与 evidence 引用），供下游读档决定是否继续。
- **唯一交互点**：凭据/验证码/人工交互类输入由脚本写 `needs_input.json` 后交上层在对话里问；其余**禁交互追问**。
- **第一条可见输出**必须是一行到态计划（双端工具探测 → 场景解析 → 逐步执行 → 状态断言 → 证据落盘），然后执行。

## 1. 定位与边界

解决的问题：下游验证常卡在“进不去页面”。本 skill 负责把 App **开到目标状态**，再把控制权交回。

| 不做 | 归属 |
|---|---|
| 视觉对比 | `arkts-visual-verify` |
| 代码修复 | 对应 fixer |
| 后端 mock | 缺后端配合 → 明确告诉调用方缺什么 |

## 2. 双端工具探测（三态，每端分别确认）

每端独立确认**实际可调用的设备工具**与**应用安装状态**，三态：`available`（探测到）/ `configured`（用户已配置）/ `executed`（本轮实际执行过）。

| 端 | 可用路径 | 缺失处置 |
|---|---|---|
| iOS 源 | Xcode/设备驱动、或用户采集证据（真实截图/录像/操作回执） | 端侧记 `unavailable` |
| 鸿蒙目标 | 已配置 hdc/测试工具（`<runtime>` `doctor` 读 host_profile 给出路径） | 同上记 `unavailable` |

> **红线**：**Windows 上有 iPhone 不代表存在自动控制 API**——iOS 侧不默认“全自动到态”；源侧可用手段是 Xcode 设备驱动（macOS）或用户采集，缺则记 unavailable 由上游决定降级，**不脑补运行态**。
> **坐标系铁律**：元素优先用稳定标识与无障碍名称；**坐标仅在已知设备尺寸/当前截图下使用**（YAML 里标 `resolution` 与来源截图名，给后人提醒）。

## 3. 工作流决策树

```
场景名 → 查 spec/scenarios/<name>.yaml
   ├─ 存在 → 进入 YAML 回放（§4）
   └─ 不存在 → 交外层 scenario-builder 学（本 skill 不学习）
                 builder 产出 YAML → 回到“存在”分支回放
```

已知场景走 YAML（确定性+可回放+可审计）；未知场景学习归 builder。本 skill 不做 LLM 实时探索。

## 4. 场景结构（写死字段）

场景必须写清：`入口`、`前置数据/权限/账号状态`、`动作`、`期望状态`、`可观察断言`。

```yaml
name: login
platforms: [ios, harmonyos]      # 或只写一端
preconditions: []                 # 依赖的其他场景
steps:
  - action: launch_app
    bundle: com.example.app
  - action: inject_token
    strategy: auto
  - action: wait_for
    signal: ui_contains
    value: "首页"
    timeout_ms: 5000
success_signals:
  - type: ui_contains
    value: "首页"
artifacts:
  - screenshot: after.png
  - recording: after.mov
```

## 5. action 速查（按 action 类型分发）

| action | 用途 | 关键参数 |
|---|---|---|
| `launch_app` / `relaunch_app` / `kill_app` | App 生命周期 | `bundle` / `ability` |
| `inject_token` | 写登录态 | `strategy`, `token_file` |
| `push_file` | 推图/文档到设备 | `src`, `dst` |
| `tap` / `long_press` / `swipe` | 基础交互 | `selector` 或 `x,y`+`resolution` |
| `input_text` | 键盘输入 | `text`, `selector` |
| `wait_for` | 等待信号 | `signal`, `value`, `timeout_ms` |
| `screenshot` / `record` | 产物采集 | `save_to` |
| `assert` | 断言成功条件 | `signal`, `value` |
| `run_scenario` | 嵌套调用 | `name` |

## 6. 执行与证据

1. 逐步执行并观察回执/新状态——**不能用等待时长、点击函数无异常替代状态确认**。
2. 源与目标保持等价前置条件；无法达到的状态列原因与最后成功步骤。
3. 保存证据：设备/系统/应用版本、场景、步骤结果、**真实截图/录像引用**与失败日志。

## 7. 登录与敏感输入纪律

- 登录凭据（token/手机号/验证码）**不进 repo 和报告**；`creds.local.json` 文件名带 `.local.` 视为不可上传，写入时自动加 `.gitignore`，顶层 `_marker.do_not_ship: true`。
- 需要验证码/用户交互时：写 `needs_input.json`（含 `kind/fields/resolve_cmd/then_rerun`）+ exit 2，交上层问；**保持该场景 pending，继续独立场景**，不阻塞其余。
- 登录策略 `auto`：有缓存 → `static` 静态注入；无缓存 → `sms` 走 UI（成功后拉回缓存）。iOS 侧无自动控制时回退用户手工登录 + 采集。
- 返回 `observed / pass / fail / not_run` 四态；**不用空截图或构造 JSON 伪装设备操作**。

## 8. 上传/权限场景

- push 图片到相册 → 触发媒体扫描 → 驱动选图入口 → 系统 picker 选图（iOS `PHPickerViewController`/`UIActivity`，鸿蒙 PhotoPicker）→ wait_for 页面回“已选图”态。
- 权限类（相机/相册/通知/定位）到态前先处理授权态，授权被拒/被允纳入前置态等同对账。

## 9. 产物协议（供下游消费）

```jsonc
{
  "scenario": "login",
  "device": "harmonyos",
  "success": true,
  "duration_ms": 8432,
  "signals_matched": ["ui_contains:首页"],
  "artifacts": {"screenshot_after": "after.png", "ui_dump_after": "…", "recording": "…"},
  "notes": ""
}
```

`success=false` 时 `notes` 写清哪个 action 卡住、超时还是断言失败。下游只信此文件 + exit code（0=成功 / 1=通用失败 / 2=缺输入）。

## 10. precondition kind → 场景映射（源头固化）

| precondition.kind | scenario name | 何时触发 |
|---|---|---|
| `login_required` | `login` | isLogin() 检查 |
| `login_conditional` | `login` | 条件登录 |
| `vip_required` | `mock_member` | isVip() 检查 |
| `credits_required` | `mock_credits` | 余额/次数≤0 |
| `permission_required` | `grant_<perm>` | 权限授权门 |
| `param_required` | 按 required_params 映射 | 页需参数渲染 |
| `state_required` | case by case | 需特定运行时状态 |

未知 `param_required` / `state_required` → 写 `needs_input.json` 让主会话补 YAML，不盲猜。

## 11. 命令表（仅真实 CLI）

| 命令 | 用途 | exit 语义 |
|---|---|---|
| `python <runtime>/scripts/a2h_ios.py doctor --project <target>` | 读 host_profile：hdc 路径、目标设备/工具可用性 | 0/1 |
| `python <本skill>/scripts/scenario_run.py --scenario <name> --device harmonyos [--device-id <id>]` | 到态回放（thin wrapper） | 0/1/2 |

## 12. 常见坑

- token 注入后不认 → 三路存储（AppStorage / UserPreferences / 网络层 UserData）不同步，需同步写或冷启动读。
- 坐标在不同分辨率失效 → 永远优先 selector（稳定标识/无障碍名称），坐标最后手段且带 `resolution`。
- 输入框静默失效（鸿蒙 ArkUI TextInput）→ 走真实软键盘逐键输入，别用一次性 `input` 文本命令。
- 图片进相册但 App 看不到 → 未触发媒体扫描，补扫描动作。

## 13. 交接

- 前置门闸：`result.json` 的 `success=true` 且 evidence 齐全（或明确 `not_run/unavailable` 有据）才交接。
- 移交产物：`spec/scenarios/<name>.yaml` + `artifacts/<ts>_<scenario>/result.json` 与截图/录像引用。
- 提示进入 `arkts-visual-verify`（在已到态上截图对比）或 `a2h-verify`；同会话可直接续跑。

## 收尾：上报本阶段用量

本 skill 的最后一步（无论经 a2h-run 还是单独触发）：

```bash
python <runtime>/scripts/a2h_ios.py usage-finish --project <target> --run-id <本轮run-id>
```

写入 `<target>/spec/reports/derived/usage-budget.json`，尽力而为。token 用量由宿主生命周期采集，本步不采集。**忽略其退出码，绝不阻断流水线。**