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

## 1. 范围、输入与 Asset Catalog 目录枚举

读取源工程 target 资源成员、Asset Catalog `Contents.json`、bundle、strings/stringsdict/xcstrings、字体、Info.plist 与权限说明；**只对计划认领的资源写目标**。先读 `references/resource-workflow.md`，再读包内 `arkts-i18n`、`arkts-app-identity`、`arkts-design-tokens-extractor` 的适用目标规范。

无损打包（imageset PNG 复制）与本地化转换由随包 provider 确定执行（`asset-convert`/`localization-convert` atom，经 `facts --providers <provider-plan.json>` 触发，见 harness-v2）；本 skill 处理其报告的 issues/gaps、动态资源、身份与缺口，**不重复实现确定性装载逻辑**。

### 1.1 Asset Catalog 目录枚举（逐类型，不靠文件名猜）

先枚举 `*.xcassets` 下所有子目录与其 `Contents.json`，按目录名后缀确定资源类型；**不能只看目录名跳过其 Contents.json**。同一 catalog 内每种类型有固定 `Contents.json` 结构：

| xcassets 子目录（后缀） | `Contents.json` 关键字段 | 资源语义 |
|---|---|---|
| `*.imageset` | `images[]`：`filename` / `idiom`(universal/iphone/ipad/tv/watch) / `scale`(1x/2x/3x) / `appearances`(luminosity light/dark/high-contrast) | 图片集（位图/PDF/SVG/可变符号） |
| `*.appiconset` | `images[]`：`idiom` / `size`(20x20/29x29/60x60…) / `scale` / `role`(notification/spotlight/settings) | 应用图标集（一集多处尺寸） |
| `*.colorset` | `colors[]`：`color.components`(red/green/blue/alpha 字符串) 或系统颜色名 / `idiom` / `appearances` | 命名颜色（静态或系统语义色） |
| `*.dataset` | `data[]`：`filename` / `idiom` / `universal-type-identifier` | 非图片数据文件 |
| `*.symbolset`（自定义 SF Symbol） | `symbol image`/`color` 等 | 自定义符号（矢量，许可受限） |

- `appearances: [dark]`/`[high-contrast]` 表示变体只在特定外观下生效；`unassigned` 或缺省表示任何外观。变体组合（idiom×scale×appearance）逐格记录，**不能把 dark 变体静默覆盖到 light**。
- `colorset` 的 `components` 是 0–1 的字符串（如 `"red" : "0xF0"`），不是 CSS `#RRGGBB`；**先按 iOS 语义解码再归一化**，禁止把 `"0.5"` 当 `0x50`。

### 1.2 资源目录枚举总表（超出 xcassets 的源资源）

iOS 资源不只在 `*.xcassets`。逐类枚举，缺一类就漏一类：

| 源位置 | 内容 | 处置方向 |
|---|---|---|
| `*.xcassets/Contents.json`（根） | `info`/`version` + 命名空间 | 记录 catalog 版本，作为子目录类型判定的元信息；先读根再读子目录 |
| `*.lproj/*.strings` | 本地化字符串（UTF-16/UTF-8） | 逐 key 转 `base/element/string.json`；见 §8 |
| `*.lproj/*.stringsdict` | 复数规则 | 复数显式映射；见 §8 |
| `*.xcstrings` | 字符串目录（源语言 + localizations） | sourceLanguage/state/变体逐项转；见 §8 |
| `*.bundle`（内嵌 bundle） | framework 资源包 | 记录 bundle 归属 target；其内资源归所属模块，不拍平到主 bundle |
| `*.ttf / *.otf / 可变字体`（含 `.ttc`） | 字体 | rawfile + 注册方式 + 许可；见 §7 |
| `Info.plist`（各 target） | 身份/权限/启动/场景 | 身份与权限键枚举；见 §9 |
| `*.entitlements` | 权限/能力（associated-domains、App Groups、Keychain、iCloud） | 记录能力清单，授权按真实 API 重新核对 |
| `*.momd` / SQLite 种子 `*.sqlite` | 数据种子/模型 | 数据层归对应 slice，本 skill 不批量复制 |
| `*.storyboard / *.xib`（资源侧仅引用） | 界面骨架 | 其内引用的资源名（image/color/font）解引用归本 skill；布局结构归 ios-ui-analyzer |

- 枚举只认 `xcodeproj` target 成员与 `Package.swift` 资源产物，**不用全局文件名扫描**把测试 fixture、示例图、文档插图误当应用资源。未被 target 引用的目录文件标 `not_applicable`，不写目标。

## 2. Stage 0 命令与字面量三态

| # | 命令 | 产物 | exit code / 失败处置 |
|---|---|---|---|
| 2.1 | `python <runtime>/scripts/a2h_ios.py product-literals --project <target> [--output <path>]` | 产品消费视图（联读源归属、当前覆盖、精确 Preview 区间） | 非 0 → 读错误原文处置；视图不豁免 raw 源义务 |
| 2.2 | `python <runtime>/scripts/a2h_ios.py validate --project <target>` | 转换器/工具链可用性校验（缺工具→记 issue，不冒充转换成功） | 非 0 → 读报告，缺的转换器标 `unavailable`，对应资源转 unresolved；禁用假转换 |

- 环境预检可选：`python <runtime>/scripts/a2h_ios.py doctor --project <target>`（只读诊断，不修改产物）；结果只用于判断“哪些转换器/栅格化工具可用”，**不作为已完成转换的证据**。
- profile 2 在 raw `literal-ledger.json` 之外运行 `product-literals`（上面的命令）。同一文本的产品/Preview/测试来源分别保留；**只有明确使用场景和源证据的项**进入目标资源转换。`usage: unresolved` 需回读源调用，不能因 raw `page_level: true` 把协议键或测试断言当 UI 文案。
- **字面量三态（三类信息，禁止混淆）**：`source_expression` 是完整源表达式；`value` 只用于已支持且已解码的静态值；`decoding_status: unresolved` 表示尚无确定值。
- Swift 扩展分隔符字符串（`#"line\nnext"#`、`##"..."##`）保留完整 `source_expression`（`#` 数、单/三引号、内部引号）；`\n` 不能按 JSON 直接解码。当前提取器登记到 `dynamic_texts`（`decoding_status: unresolved`、`reason: extended_delimiter_requires_swift_semantic_decode`）；多行与插值分别记录待解码/待求值。`classification: product` 只表源归属，不是已确认目标文案；**禁止补造 `value`**，受限转换器拒绝时交语义适配处理，**不能删 `#` 后重试**。
- raw 保持完整；投影视图不能豁免源义务、不能按目录名自动排除、不能把 source point 当 vp 自动换算。

## 3. Asset Catalog 类型处置

| iOS 源（`*.xcassets/…/Contents.json`） | 目标 | 处置 |
|---|---|---|
| `imageset`（universal、1x/2x/3x、PNG） | `base/media/<name>.png` | 无损复制最高 scale；校验逻辑尺寸一致；`layout_requirement` 记录源逻辑尺寸（intrinsic size 等价未验证） |
| `imageset`（含 `properties`、多 idiom、SVG/PDF/可变符号/九片、非 PNG） | 不直接转换 | issue：properties/variant 需要映射或目标重画决策；**不能仅改后缀** |
| `appiconset` | 不直接转换 | 目标应用图标按目标规范独立生成，不 copy 源图标 |
| `colorset` | 不直接转换 | 静态色值进 design token；动态 provider/trait 逻辑保留到页面/组件实现 |
| `dataset` | `rawfile/<name>` 或按 UTType 分流 | 仅数据文件原样复制并记录 MIME/UTType；可执行/脚本**不复制** |
| 运行时生成图/动态颜色/自定义字体缩放 | 不直接转换 | 转行为适配，不靠批量文件复制 |

- **appiconset 逐尺寸判定**：`role`（notification/spotlight/settings）与 `size`/`scale` 是同一图标的多种场景切片；迁移时**只为目标应用图标规范重新生成**，不把 notification/spotlight 切片当普通媒体资源复制。源图标只作尺寸/设计参照，目标图标按目标尺寸规范独立产出（交 `arkts-app-identity`）。
- 建立源引用 → 实际文件 → variant → 目标资源名唯一映射；名称按目标规则归一化并检查大小写/标点碰撞，**不同原资源不能被同名覆盖**。
- `imageset` 内多 `filename` 候选（同 idiom 同 scale 多文件）按 Xcode 实际选中项（`Contents.json` 顺序 + 平台 build setting）裁定，缺平台信息标 `platform_selection_unverified` 不猜第一项。

### 3.1 imageset `properties` 明细（能否无损复用的判定依据）

`imageset` 的 `properties` 字段决定能否无损复用，逐项判定，不能只按文件后缀决定：

| `properties` 键 | 含义 | 处置 |
|---|---|---|
| `preserves-vector-representation` | 矢量保留（PDF/SVG 按矢量缩放） | 记录为矢量意图；位图切片不可假称矢量 |
| `template-rendering-intent` | 模板渲染意图（tint 着色） | 记录 `render_as: template`；不预生成 tint 变体 |
| `compression-resistance` / `hugging` | 布局压缩/拉伸优先级 | 属布局语义，交 ios-ui-analyzer；资源侧只记录 |
| `on-demand-resource-tags` | 按需资源标签 | 目标按需下载映射；无等价物列缺口 |
| `auto-scaling`（九片） | 自动九片缩放 | 九片映射或目标重画决策，不拷贝拉伸 |
| `gamut`（P3/sRGB） | 色域 | 标注；渲染差异交 decision-ledger |
| `localization` | 区域变体 | locale 归属；见 §8 |

## 4. 图片变体与密度

图片记录 idiom、scale、尺寸、方向、rendering mode、resizing、capInsets、dark/high-contrast/gamut 等变体。**只复制兼容的实际文件，保留来源 hash**。

### 4.1 @2x/@3x 密度变体

iOS 的 scale 是相对 point 的栅格倍率；目标媒体资源不按 point 组织。处置原则：**每个名称只落一份最高 scale 无损副本到 `base/media`**，@1x/@2x/@3x 是同一张图的变体，不是三个独立资源。

| 源 variant | 含义 | 处置 |
|---|---|---|
| `1x` | point:px = 1:1 基准 | 仅当无更高档时使用 |
| `2x` | 2 倍栅格 | 与 3x 并存时选 3x；单独存在时作最高档 |
| `3x` | 3 倍栅格 | 无损复制；记录源逻辑尺寸（point 值），不做重采样缩图 |
| 缺失某档 | 系统曾降/升采样 | 目标不代补缺失档；需要时列 `resource-pending-asset` 缺口，**不缩放位图** |

- 目标多密度分档（如需）按 scale 参考密度带，但**缩放复制位图会引入重采样**，本 skill 不做；桥接需要时交对应领域技能（如 `arkts-icon-sizing`）决策并登记。
- **不可改后缀冒充格式**：PDF/vector/可变符号/九片伸缩不能仅改后缀；明确转换器、许可、栅格化条件或目标重画决策。无转换工具时保留 unresolved，**不能输出假 SVG**。

> 目标若需按密度分档（一般不强制），参考映射：`1x`→基准档、`2x`→约 xldpi、`3x`→约 xxldpi；媒体通常统一 `base/media`，不逐档重采样。iOS 无 `drawable-hdpi` 这类目录级 qualifier，密度由 `scale` 字段表达——**不要臆造 Android 式 qualifier 目录结构**。

### 4.2 外观与变体（非密度维度）

| 变体 | 记录 | 处置 |
|---|---|---|
| `appearances: dark` | 深色变体 | 与 light 分列成对，不静默覆盖；目标深色能力交页面实现 |
| `appearances: high-contrast` | 高对比变体 | 记录；目标无障碍高对比分列 |
| `dir`（方向） | 横竖屏 | 目标 orientation 分列，不丢弃 |
| `gamut`（P3/sRGB） | 色域 | 标注；渲染色域差异交 decision-ledger |
| `resizing` / `capInsets` | 九片/切片 | 九片映射或目标重画，不拷贝拉伸 |
| `rendering mode` | template/original | 只记录意图（见 §5），不预生成变体 |

## 5. SF Symbols 与模板渲染

- **SF Symbols**（系统符号，如 `arrow.right`、`heart.fill`）：只记录符号名、语义、weight/scale 变体与许可/系统版本约束；**不保证任意系统符号有目标同名项**，也不批量渲染为位图假符号。自定义 `symbolset`（矢量）许可受限，**无许可不转 SVG**。
- **模板渲染**（`rendering mode: template`，`.alwaysTemplate`）只表达“以 tint 着色”的意图，不是额外图片变体；记录 `render_as: template` + 默认 tint 来源，**不预生成各色 tint 图标**。`original` 模式保留原像素。
- `preserves-vector-representation`（矢量保留）与位图是两个不同态；目标落地方式（矢量符号 vs 位图）由目标组件决策，本 skill 只给源事实。
- SF Symbols 的 `weight`/`scale` 变体与无障碍符号（`image.isSymbolRenderingMode` / 视觉描述）分别记录；目标无障碍等价语义交 `arkts-accessibility`，**不以符号名替代辅助功能标签**。

## 6. 颜色

颜色保存动态 provider/trait 选择逻辑、色域、字重、缩放与注册方式：
- 静态色值（`components` 解码后的 sRGB）→ 记录到 design token（目标颜色命名与角色交 `arkts-design-tokens-extractor`），**不得丢失 alpha 通道**（alpha 0.5 不能记成不透明）。
- 动态 provider（asset 目录系统色/Gamut 语义色/trait 切换）→ 保留选择逻辑到页面/组件实现，**不拍平成单一 hex**。
- 色域（P3 vs sRGB）标注；目标渲染色域不同时算平台差异，交 decision-ledger，不静默丢广色域。

## 7. 字体

字体复制到 rawfile 并记录注册方式与许可；自定义字体缩放、动态字号转行为适配，不靠批量文件复制。字重/斜体/可变字体轴保留完整描述，**不能把变体字重当独立字体名覆盖**。

## 8. 本地化

继承确定性装载的结果与 issues，并逐项回应：key、locale、format placeholders、复数分类、上下文、fallback。
- `xcstrings`：sourceLanguage、shouldTranslate=false 的非本地化 key、`stringUnit.state`（translated/source_key_fallback）、localizations 变体。
- `.strings`/`.lproj`：UTF-16/UTF-8 编码、locale 归属；`%` 格式占位符需 typed formatting rule，**不能静默丢失参数类型与顺序**。
- `.stringsdict` 复数规则需显式映射（复数分类 zero/one/two/few/many/other 与目标逐项对齐），未映射保留 finding。
- 验证替换参数类型与顺序；多语言截图与 RTL/动态字级是后续真实验证。**不把所有 xcstrings 项直接扁平为一个中文值**。
- locale 归属：`.lproj`/`xliff`/xcstrings 的 locale 与目标语言目录（base/en_US/zh_CN 等）逐项对照；缺失 zh_CN/en_US 时按多语言强制规则登记 `[TODO: translate]` 占位并写 `spec/placeholder-registry.md`（`kind=resource-pending-translation`）。

### 8.1 多语言强制规则

1. 扫描全部 `.lproj`/`xcstrings`/`stringsdict`，列出检测到的 locale。
2. **至少生成 2 套语言**：缺省语言（源 base/sourceLanguage）+ 目标 `en_US`/`zh_CN`（缺省非中/英时补齐中英）。
3. key 一致性：所有语言文件 key 集合**完全一致**；base 有而某语言无的 key，用源值补齐并加 `[TODO: translate]` 前缀后登记占位。
4. 语言数 N ≤ 10 全转；N > 10 只转 base + en + zh + 计划指定语言。
5. 占位必须登记 `spec/placeholder-registry.md`（`kind=resource-pending-translation`），实际翻译交 `arkts-i18n`（Stage 0 收口后由 a2h-execute 自动触发），本 skill 只发占位与登记。

## 9. 身份输入与 Info.plist / 权限说明

身份从实际 display name、图标、启动表现、URL scheme/Universal Link 读取：

| Info.plist / 输入 | 读取目的 | 目标处置 |
|---|---|---|
| `CFBundleDisplayName` / `CFBundleName` | 显示名 | 目标应用名，不拷证书/签名 |
| `CFBundleIdentifier` / Bundle id | 包标识 | 目标 bundle 按目标规范，源 id 仅参照命名 |
| `CFBundleIcons`/`CFBundleIconFiles` | 图标引用 | 目标图标独立生成（见 §3 appiconset） |
| `UILaunchStoryboardName` / `UILaunchScreen` | 启动表现 | 目标启动页/icon 规范，不照拷 Storyboard |
| `CFBundleURLTypes`/`CFBundleURLSchemes` | URL scheme | 目标 deep link 能力，逐项核对用途 |
| `com.apple.developer.associated-domains`（entitlement） | Universal Link | 目标关联验证规则，不直接平移 | 
| `UIApplicationSceneManifest` | 场景生命周期 | 记录入口结构，实现归页面 skill |
| `UISupportedInterfaceOrientations` | 方向 | 目标方向配置，逐设备核对 |
| `NS*UsageDescription`（相机/定位/相册/麦克风等） | 权限说明 | 目标权限按真正 API/场景重新核对（见下） |

- **目标 bundle 与签名不从源证书拷贝**；目标权限按真正 API/场景重新核对（用途字符串只证明声明，不证明授权）。App Groups/Keychain groups/背景模式交 `arkts-app-identity` 与对应领域技能。
- 用途字符串是“声明文本”，不是“授权证据”：目标权限清单以实际调用的系统 API 为准，缺失用途说明记 `not_applicable`，不把声明当授予。

### 9.1 权限用途字符串（NS*UsageDescription 键分类）

用途字符串只证明“声明存在”，不证明授权；逐键归类并重新核对目标真实 API：

| 键族 | 例 | 目标核对 |
|---|---|---|
| 相机 | `NSCameraUsageDescription` | 拍照/录像 API 实际调用 + 权限声明 |
| 位置 | `NSLocationWhenInUse/AlwaysUsageDescription` | 前台/后台定位场景分列 |
| 相册 | `NSPhotoLibraryUsageDescription` / `NSPhotoLibraryAddUsageDescription` | 读/写相册权限分列 |
| 麦克风 | `NSMicrophoneUsageDescription` | 录音权限 |
| 通讯录/日历/提醒 | `NSContacts/Calendars/RemindersUsageDescription` | 对应数据权限 |
| 健康/运动/HomeKit | `NSHealth*/Motion*/HomeKit*UsageDescription` | 领域能力交对应 arkts-* 技能 |
| 蓝牙/网络 | `NSBluetooth*UsageDescription` | 连接类权限 |

- 目标权限清单以**实际调用的系统 API** 为准，不以声明文本为准；声明了但源码未调用 → `not_applicable`；调用未声明 → 记 finding 交 `arkts-app-identity`。

## 10. 引用解析与 $r() 落地

源内引用（`.image("name")`、`Color("name")`/`UIColor(named:)`、`NSLocalizedString` key、字体 PostScript 名、URL scheme）逐一解析到目标引用形式，并核对目标资源闭集：

| 源引用 | 目标资源类 | 目标引用形式 |
|---|---|---|
| imageset 名称 | media | `$r('app.media.<name>')` |
| colorset 静态色 → token | color | `$r('app.color.<name>')`（token 层，非直引 colorset 名） |
| 字符串 key | string | `$r('app.string.<key>')` |
| 复数 key | plural | `$r('app.strarray.<key>')` / plural |
| 字体/杂数据 | rawfile | `$rawfile('<path>')` 或 `$r('app.rawfile.<name>')` |

- **只落地“真实存在且已被计划认领”的引用**；引用到未转换资源时，不落空 `$r` 兜底，而落 `MISSING_<name>` 显式缺失（见 §11）到缺口清单与 `spec/placeholder-registry.md`。
- 引用归一化后仍要回读 Stage 1/3 页面生成结果，确认 `$r`/`rawfile` 引用名与资源名一字不差（大小写、下划线、连字符）。
- **引用闭合核对（收口前逐条）**：
  1. 每个源引用名唯一映射到一个目标资源名（或 `MISSING_<name>`）；
  2. 每个目标 `$r`/`$rawfile` 引用名可解析到真实资源或已登记占位；
  3. 无大小写/标点不一致导致的“引用名 ≠ 资源名”；
  4. Stage 1/3 生成结果回灌后重跑闭集核对，新增引用走同映射追加。

## 11. 命名冲突闭集、未映射与 MISSING_xxx

- **命名冲突闭集**：目标资源名做大小写/标点归一化（APFS 默认大小写不敏感、HF 更不敏感，目标资源名大小写敏感）后，同一目标名只能归属一个源资源；撞名必须改目标名并把映射写进 resource-mapping，**不同原资源不能被同名覆盖**。闭集 = 目标资源名集合 ∩ 源资源名集合，逐名核对无重名、无遗漏、无假引用。
- **未映射（unmapped/unresolved）**：PDF/vector/可变符号/九片/波纹/动态颜色/运行时生成图/SF Symbols 非同名项 → `unresolved`；确无目标等价物（如启动 Storyboard 布局、App 图标源图）→ `not_applicable`，均附 reason，**不编造假产物**。
- **MISSING_xxx 显式缺失**：目标代码/资源引用了某个名称但该资源未转换或不存在时，产出显式 `MISSING_<name>` 条目（在缺口清单 + placeholder-registry `kind=resource-pending-asset`），**绝不静默消失**。缺关键资源会阻断依赖页面的完整交付，必须先登记再放行。

### 11.1 冲突处置阶梯

已存在的目标条目/文件与本次转换值不一致时：

1. 保留既有项，除非是模板占位符；**不 `--force` 覆盖**（未明确要求时）。
2. 冲突逐条记录 源值 vs 既有值 vs 差异，进入 `conflicts` 清单，由指定 owner 统一裁决。
3. 裁决后写回 resource-mapping 的决策与依据；未裁决不重跑转换器改状态。
4. 共享资源 JSON 只 append 缺失键，禁重排/重写/删除既有条目（`_common.md` 单写者纪律）。

## 12. 记录与收口（质量门）

1. 写 resource-mapping（源 target/bundle、path、hash、原名、variant 条件、转换方式、目标路径/名称、实际校验结果）、identity 报告与缺口。
2. 逐项检查目标引用存在（`$r`、rawfile、按名访问的资源闭集、`MISSING_xxx` 无遗漏）；Stage 1/3 新发现资源走同映射追加，由指定 owner 统一合并。
3. 结果五分类 `converted/copied/reimplemented/unresolved/not_applicable` 并附证据，**不能以文件总数或同名资源数量声称资源迁移完成**。
4. **质量门**：构建前实际校验资源闭集（每项源资源可追到目标资源或显式缺失/MISSING_xxx；每项目标引用可追到真实资源或登记占位），再由原资源/字面量门检查。原资源名/原文案不因重构擅自改变；缺关键资源会阻断依赖页面的完整交付。

### 12.1 转换报告结构（收口产物附报告）

收口时在 resource-mapping 之上生成一份人类可读报告，固定包含：

| 段 | 内容 |
|---|---|
| 资源来源 | catalog/target 成员 + provider 装载结果（`converted`/`copied` 由脚本写，本 skill 只处理报告 leftovers：issues/gaps/动态资源/身份/缺口） |
| 转换明细 | 每项 源路径 → 目标路径/名称 / 类型 / 五分类 |
| 未映射/未解析 | reason + 证据；`unresolved`/`not_applicable` 全列 |
| 缺失（MISSING_xxx） | 显式缺失清单 + placeholder 登记号 |
| 权限/身份 | Info.plist 键 → 目标身份/权限核对结论（重新核对，非拷贝） |
| 语言资源 | 检测语言 N / 生成 M / 每语言 key 数 / key 一致性 PASS/FAIL / 占位 `[TODO: translate]` 数 |
| 校验结果 | 资源闭集逐项 PASS/FAIL；缺关键资源列名并说明阻断哪些页面 |

## 13. 硬约束

- **禁止**写计划未认领的目标资源；共享资源 JSON 只 append 缺失键，禁重排/重写/删除既有条目。
- **禁止**补造 `value`、删 `#` 重试扩展分隔符、把未解码项当成已得到目标文案。
- **禁止**输出假 SVG/假图标、生成假 SF Symbols 位图、缩放位图冒充多密度变体；无转换工具保留 unresolved。
- **不得**用文件总数、同名资源数量或目录扫描数量宣称资源迁移完成。
- **不得**把用途字符串当授权证据；不从源证书拷贝签名/账号。
- **禁止**只改文件后缀冒充格式（PDF/vector/九片 → .png/.svg）；转换器、许可、栅格化条件必须写清。

## 14. 读取时机（references）

| 触发时机 | 必读文件 |
|---|---|
| 执行前；机器产物/状态写者存疑 | `../ios-source-analysis/references/harness-v2.md` |
| 逐条映射记录与三态纪律 | `references/resource-workflow.md` |
| 占位/P-ID/单写者/资源直写纪律 | `../a2h-execute/references/agent-prompts/_common.md` |
| 本地化目标规范与 `[TODO: translate]` 占位 | `../arkts-i18n/SKILL.md` |
| 应用身份/图标/bundle 目标规范 | `../arkts-app-identity/SKILL.md` |
| 静态色值→design token | `../arkts-design-tokens-extractor/SKILL.md` |

## 15. 交接

- 前置门闸：认领资源逐项五分类且有证据；资源闭集被原资源/字面量门检查通过；`MISSING_xxx` 全部登记占位。
- 移交：resource-mapping、identity 报告、缺口（unresolved/not_applicable/MISSING_xxx）、新增资源请求、占位登记。
- 下一步提示：交原 Stage 0 收口（资源审计）后进入 Stage 1（ios-ui-to-arkui）；翻译类占位交 `arkts-i18n`。

## 16. 收尾：上报本阶段用量

```bash
python <runtime>/scripts/a2h_ios.py usage-finish --project <target> --run-id <run-id>   # 若存在；否则等价物
```

最后一步执行、**忽略退出码、绝不阻断流水线**；token 用量由宿主生命周期采集，本步不采集。