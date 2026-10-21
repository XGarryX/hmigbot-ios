---
name: ios-resources-convert
description: "iOS→HarmonyOS 迁移执行阶段 Stage 0 步：转换 iOS 资源与身份输入——Asset Catalog（xcassets/imageset/appiconset/colorset）、图片变体、字符串/复数/字符串目录（strings/stringsdict/xcstrings）、字体、Info.plist 与权限说明，复用鸿蒙资源/国际化/身份校验技能，并把不可直接转换资源登记为缺口。当 a2h-execute Stage 0 转换资源，或用户说“迁移 iOS 资源/图标/多语言/应用身份”时使用；不要用于：源 UI 分析（用 ios-ui-analyzer）、页面代码生成（用 ios-ui-to-arkui）、源功能行为分析（用 ios-feature-analyzer）。保持 xcassets 子结构与字面量三态，不伪造解码值。"
metadata:
  type: domain
  domain: migration
  tags:
  - ios
  - resources
  - asset-catalog
  - i18n
---

> **调用关系**：本 skill 是 a2h-execute Stage 0 的资源/身份 worker 角色，由 `a2h-execute` 按冻结任务书派发（`fork_turns:"none"`）。本 worker 只对**计划认领的资源**写目标；共享资源 JSON 只允许 append-only 两项例外（见 `../a2h-execute/references/agent-prompts/_common.md`）。遵守 Join 协议：完成唯一合法信号是 `agent_status=completed`；completed≠验收；谁派谁收。本 worker **不派发下级子代理**。
>
> 路径约定：`$IOS_SRC` = 源根；`<target>` = 目标根；`<runtime>` = 本包 runtime。产物落 `<target>/entry/src/main/resources/**`（或目标工程等价路径）与 `<target>/spec/`；目标资源根以目标工程实际结构为准。本 skill 自有：`references/resource-workflow.md`、`scripts/run.py`。

# ios-resources-convert — iOS 资源、国际化与身份输入

## 0. 定位与纪律

- **前置**：a2h-execute 进入 Stage 0，计划含资源/身份认领项。先加载 `../ios-source-analysis/references/harness-v2.md`（v2 协议决定机器产物与状态；资源转换产物须进入 typed plan 的 ownership 与哈希回执；variants/scale/颜色/复数未知保留 finding）。
- **输入**：源工程 target 资源成员、Asset Catalog `Contents.json`、bundle、strings/stringsdict/xcstrings、字体、Info.plist、权限说明、`spec/baseline/literal-ledger.json` 与产品消费视图。
- **输出**：目标资源文件（media/element/rawfile）+ `resource-mapping` 记录 + identity 报告 + 缺口清单；每项带 `converted/copied/reimplemented/unresolved/not_applicable` 五分类与证据。
- **唯一交互点**：无交互追问；缺失/冲突回计划或源，不现场造值。
- **第一条可见输出必须是一行资源转换计划**（字面量投影 → Asset Catalog 分类 → 图片/颜色/字体 → 本地化 → 身份 → 记录与收口）。
- **禁止绕过原 Stage 0 的资源审计**；无转换工具时保留 unresolved，**不输出假 SVG/假值**。

## 1. 范围与输入

读取源工程 target 资源成员、Asset Catalog `Contents.json`、bundle、strings/stringsdict/xcstrings、字体、Info.plist 与权限说明；**只对计划认领的资源写目标**。先读 `references/resource-workflow.md`，再读包内 `arkts-i18n`、`arkts-app-identity`、`arkts-design-tokens-extractor` 的适用目标规范。

无损打包（imageset PNG 复制）与本地化转换由随包 provider 确定执行（`asset-convert`/`localization-convert` atom，经 `facts --providers <provider-plan.json>` 触发，见 harness-v2）；本 skill 处理其报告的 issues/gaps、动态资源、身份与缺口，**不重复实现确定性装载逻辑**。

## 2. Stage 0 命令与字面量三态

| # | 命令 | 产物 | exit code / 失败处置 |
|---|---|---|---|
| 2.1 | `python <runtime>/scripts/a2h_ios.py product-literals --project <target> [--output <path>]` | 产品消费视图（联读源归属、当前覆盖、精确 Preview 区间） | 非 0 → 读错误原文处置；视图不豁免 raw 源义务 |

- profile 2 在 raw `literal-ledger.json` 之外运行 `product-literals`（上面的命令）。同一文本的产品/Preview/测试来源分别保留；**只有明确使用场景和源证据的项**进入目标资源转换。`usage: unresolved` 需回读源调用，不能因 raw `page_level: true` 把协议键或测试断言当 UI 文案。
- **字面量三态（三类信息，禁止混淆）**：`source_expression` 是完整源表达式；`value` 只用于已支持且已解码的静态值；`decoding_status: unresolved` 表示尚无确定值。
- Swift 扩展分隔符字符串（`#"line\nnext"#`、`##"..."##`）保留完整 `source_expression`（`#` 数、单/三引号、内部引号）；`\n` 不能按 JSON 直接解码。当前提取器登记到 `dynamic_texts`（`decoding_status: unresolved`、`reason: extended_delimiter_requires_swift_semantic_decode`）；多行与插值分别记录待解码/待求值。`classification: product` 只表源归属，不是已确认目标文案；**禁止补造 `value`**，受限转换器拒绝时交语义适配处理，**不能删 `#` 后重试**。
- raw 保持完整；投影视图不能豁免源义务、不能按目录名自动排除、不能把 source point 当 vp 自动换算。

## 3. Asset Catalog 类型与处置

| iOS 源（`*.xcassets/…/Contents.json`） | 目标 | 处置 |
|---|---|---|
| `imageset`（universal、1x/2x/3x、PNG） | `base/media/<name>.png` | 无损复制最高 scale；校验逻辑尺寸一致；`layout_requirement` 记录源逻辑尺寸（intrinsic size 等价未验证） |
| `imageset`（含 `properties`、多 idiom、SVG/PDF/可变符号/九片、非 PNG） | 不直接转换 | issue：properties/variant 需要映射或目标重画决策；**不能仅改后缀** |
| `appiconset` | 不直接转换 | 目标应用图标按目标规范独立生成，不 copy 源图标 |
| `colorset` | 不直接转换 | 静态色值进 design token；动态 provider/trait 逻辑保留到页面/组件实现 |
| 运行时生成图/动态颜色/自定义字体缩放 | 不直接转换 | 转行为适配，不靠批量文件复制 |

- 建立源引用 → 实际文件 → variant → 目标资源名唯一映射；名称按目标规则归一化并检查大小写/标点碰撞，**不同原资源不能被同名覆盖**。

## 4. 图片变体

图片记录 idiom、scale、尺寸、方向、rendering mode、resizing、capInsets、dark/high-contrast/gamut 等变体。**只复制兼容的实际文件，保留来源 hash**。PDF/vector/SF Symbols/可变符号/九片伸缩不能仅改后缀；明确转换器、许可、栅格化条件或目标重画决策。无转换工具时保留 unresolved，**不能输出假 SVG**。SF Symbols 只记录符号含义与许可/版本约束，不保证任意系统符号有目标同名项。

## 5. 颜色与字体

颜色与字体保存动态 provider/trait 选择逻辑、色域、字重、缩放与注册方式。**静态色值转 design token**（配色体系交 `arkts-design-tokens-extractor`）；动态逻辑保留到页面/组件实现。字体复制到 rawfile 并记录注册方式，运行时动态尺寸转行为适配。

## 6. 本地化

继承确定性装载的结果与 issues，并逐项回应：key、locale、format placeholders、复数分类、上下文、fallback。
- `xcstrings`：sourceLanguage、shouldTranslate=false 的非本地化 key、`stringUnit.state`（translated/source_key_fallback）、localizations 变体。
- `.strings`/`.lproj`：UTF-16/UTF-8 编码、locale 归属；`%` 格式占位符需 typed formatting rule，**不能静默丢失参数类型与顺序**。
- `.stringsdict` 复数规则需显式映射，未映射保留 finding。
- 验证替换参数类型与顺序；多语言截图与 RTL/动态字级是后续真实验证。**不把所有 xcstrings 项直接扁平为一个中文值**。

## 7. 身份输入

身份从实际 display name、图标、启动表现、URL scheme/Universal Link 读取。**目标 bundle 与签名不从源证书拷贝**；目标权限按真正 API/场景重新核对（用途字符串只证明声明，不证明授权）。App Groups/Keychain groups/背景模式交 `arkts-app-identity` 与对应领域技能。

## 8. 记录与收口

1. 写 resource-mapping（源 target/bundle、path、hash、原名、variant 条件、转换方式、目标路径/名称、实际校验结果）、identity 报告与缺口。
2. 逐项检查目标引用存在（`$r`、rawfile、按名访问的资源闭集）；Stage 1/3 新发现资源走同映射追加，由指定 owner 统一合并。
3. 结果五分类 `converted/copied/reimplemented/unresolved/not_applicable` 并附证据，**不能以文件总数或同名资源数量声称资源迁移完成**。
4. 构建前实际校验资源闭集，再由原资源/字面量门检查。原资源名/原文案不因重构擅自改变；缺关键资源会阻断依赖页面的完整交付。

## 9. 硬约束

- **禁止**写计划未认领的目标资源；共享资源 JSON 只 append 缺失键，禁重排/重写/删除既有条目。
- **禁止**补造 `value`、删 `#` 重试扩展分隔符、把未解码项当成已得到目标文案。
- **禁止**输出假 SVG/假图标；无转换工具保留 unresolved。
- **不得**用文件总数、同名资源数量或目录扫描数量宣称资源迁移完成。
- **不得**把用途字符串当授权证据；不从源证书拷贝签名/账号。

## 10. 读取时机（references）

| 触发时机 | 必读文件 |
|---|---|
| 执行前；机器产物/状态写者存疑 | `../ios-source-analysis/references/harness-v2.md` |
| 逐条映射记录与三态纪律 | `references/resource-workflow.md` |
| 占位/P-ID/单写者/资源直写纪律 | `../a2h-execute/references/agent-prompts/_common.md` |
| 本地化目标规范 | `../arkts-i18n/SKILL.md` |
| 应用身份/图标/bundle 目标规范 | `../arkts-app-identity/SKILL.md` |
| 静态色值→design token | `../arkts-design-tokens-extractor/SKILL.md` |

## 11. 交接

- 前置门闸：认领资源逐项五分类且有证据；资源闭集被原资源/字面量门检查通过。
- 移交：resource-mapping、identity 报告、缺口（unresolved/not_applicable）、新增资源请求、占位登记。
- 下一步提示：交原 Stage 0 收口（资源审计）后进入 Stage 1（ios-ui-to-arkui）；翻译类占位交 `arkts-i18n`。