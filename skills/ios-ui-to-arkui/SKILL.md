---
name: ios-ui-to-arkui
description: "在 a2h-execute Stage 1 按 iOS 页面 spec 实现 ArkUI；保留 SwiftUI 状态/Binding/身份/任务语义或 UIKit 生命周期/委托/约束，复用包内 ArkTS 组件、状态和导航技能及 batch 收口协议。"
---

## 0.6.0 可执行协议

本技能先加载 [Harness v2 协议](../ios-source-analysis/references/harness-v2.md)。事实、义务、计划和回执由随包脚本检查；本正文的分析责任继续适用，v2 协议决定机器产物和状态，旧版 source-check 不能代替新版门禁。

读取 [语义映射与验收](references/semantic-mapping-v2.md)。按冻结任务书写 owned files，以源 fact/AC 为依据实现完整状态和反馈，再产真实摘要回执；生成不等于行为通过。



# iOS 页面到 ArkUI 的实现

## 输入与所有权

输入 page_id、source_root、page_spec、ui_info、target、owning_slice、
wiring_ownership_map、registered_placeholders、owned_files 与原生 facts。
源只读；本角色只写被分配的页/组件。共享导航、注册、资源账本交 batch closer，
功能 VM/repository 交所属 slice，不能抢写或用独立样例替代应用接线。

先读 [转换决策](references/conversion-decisions.md) 和
`arkts-component-builder/SKILL.md` 的 iOS 参照模式及所需 V2 参考。
需要状态/导航时继续读 `arkts-state-manager`、`arkts-navigation-builder`，
不要只引用技能名字而不读其实际约束。

## Stage 1 执行

1. 回读分页 spec、source_anchors 与 ios-semantics 同 page ID。
   读取真实源文件、子视图和事件实现；核对源 hash，缺失/歧义回 a2h-spec。
2. 列出必须保留的行为：初态、状态所有权、条件显示、输入/输出、导航、
   副作用时机、取消、布局/命中、资源与无障碍。原生机制和目标方案分开记录。
3. SwiftUI 先迁移声明式层级与状态数据流，再迁移 modifier 有序效果、身份键、
   Binding 回写与 Environment 范围；task/id 改变和取消在显式生命周期适配层实现。
4. UIKit 先把 controller/view containment、约束与事件图转成页面组件和布局关系，
   再明确 delegate/data source、复用状态、生命周期和导航的目标责任对象。
5. 复用 ArkTS 组件/状态/路由/资源技能写真实 `.ets`。目标 API 与状态版本以
   目标工程的锁定配置为准，不因 SwiftUI 有 @State 就直接使用同名目标装饰器。
6. 业务暂未实现时登记 P-ID/FWD-REF、触发条件、唯一 owning_slice 与到期点；
   不能把空 handler、恒定假数据或跳过导航写成已实现。
7. 页面函数与 ViewModel 接口使用 plan 的结构化对；调用、实例化与反馈均要接通。
   仅文件存在或结构扫描通过不能证明按钮行为。

## 布局与资源核对

保持源码声明的布局意图。iOS point 与目标 vp 不作无条件等比承诺；
结合 safe area、系统字体、动态字级、缩放、屏幕配置校验目标结果。
颜色/图片/字体走 ios-resources-convert 的映射；SF Symbols 无同名目标资源保证。
不凭截图抹掉源码中的隐藏态、返回语义、VoiceOver 标签或键盘/focus 行为。

## 交付到原 closer

返回实际 owned_files、组件导入/实例化需求、source→target 决策、placeholder、
新增资源请求、未解决事实、需要验证的场景。原 batch closer 负责共享装配、
结构检查、编译与 brief；主控按 apply_writeback 原协议落盘，不在 plan 回填状态。

无设备时交付 generated/compiled 的真实状态，visual/device=not_run。
复杂引擎/自绘/闭源 UI 无可行方案时提出具体边界与候选替代，不声称通用自动转换成功。
