---
name: ios-resources-convert
description: "在 a2h-execute Stage 0 转换 iOS Asset Catalog、图片/颜色变体、字符串/复数、字体与应用身份输入；复用鸿蒙资源、国际化和身份校验，并记录不可直接转换资源。"
---

## 0.6.0 可执行协议

本技能先加载 [Harness v2 协议](../ios-source-analysis/references/harness-v2.md)。事实、义务、计划和回执由随包脚本检查；本正文的分析责任继续适用，v2 协议决定机器产物和状态，旧版 source-check 不能代替新版门禁。

资源转换产物也必须进入 typed plan 的 ownership 和哈希回执；variants/scale/颜色/复数未知保留 finding。禁止绕过原 Stage 0 的资源审计。



# iOS 资源、国际化与身份输入

## 范围与输入

读取源工程 target 资源成员、Asset Catalog Contents.json、bundle、strings/stringsdict/
xcstrings、字体、Info.plist 和权限说明；只对计划认领的资源写目标。
先读 [资源规程](references/resource-workflow.md)，再读包内 `arkts-i18n` 与
`arkts-app-identity`、`arkts-design-tokens-extractor` 的适用目标规范。

## Stage 0

1. 建立源引用 → 实际文件 → variant → 目标资源名的唯一映射。
   名称按目标规则归一化，并检查大小写/标点碰撞；不同原资源不能被同名覆盖。
2. 图片记录 idiom、scale、尺寸、方向、rendering mode、resizing、capInsets、
   dark/high-contrast/gamut 等变体。只复制兼容的实际文件，保留来源 hash。
3. PDF/vector/SF Symbols/可变符号/九片伸缩不能仅改后缀；明确转换器、许可、
   栅格化条件或目标重画决策。没有转换工具时保留 unresolved，不能输出假 SVG。
4. 颜色与字体保存动态 provider/trait 选择逻辑、色域、字重、缩放与注册方式。
   把静态色值转 design token；动态逻辑保留到页面/组件实现。
5. 本地化保留 key、locale、format placeholders、复数分类、上下文和 fallback。
   验证替换参数类型与顺序；多语言截图与 RTL/动态字级是后续真实验证。
6. 身份从实际 display name、图标、启动表现、URL scheme/Universal Link 读取。
   目标 bundle 与签名不从源证书拷贝；目标权限按真正 API/场景重新核对。
7. 写 resource-mapping、identity 报告和缺口，逐项检查目标引用存在；
   Stage 1/3 新发现资源走同映射追加，由指定 owner 统一合并。

## 收口

结果列 converted/copied/reimplemented/unresolved/not_applicable 和证据，
不能以文件总数或同名资源数量声称资源迁移完成。
原资源名/原文案不应因重构被擅自改变；缺关键资源会阻断依赖页面的完整交付。
构建前实际校验 `$r`、rawfile 和按名访问的资源闭集，再由原资源/字面量门检查。
