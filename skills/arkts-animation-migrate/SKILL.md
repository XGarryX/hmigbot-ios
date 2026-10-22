---
name: arkts-animation-migrate
description: "读取 iOS SwiftUI/UIKit/Core Animation/第三方动画的时间、状态和生命周期，复用 ArkTS 动画能力实现目标效果与取消/重入行为。"
---


# iOS 动画到目标实现

输入动画源代码、页面 facts、资源与实际运行证据。先读 arkts-animation-builder
的目标 API/动画规程；不能靠文件格式或相同 duration 判等价。

1. 从 SwiftUI animation/withAnimation/transition/matchedGeometryEffect，或 UIKit
   UIView.animate/PropertyAnimator、Core Animation、Lottie 等调用提取实际动画。
2. 记录驱动状态、起止值、曲线/弹簧参数、延迟/重复、叠加、交互进度和 completion。
3. 把视图身份与结构插入/移除、可中断/反向、取消和资源销毁纳入转换决策。
4. 使用目标 animateTo/transition/属性动画或明确帧序列；逐参数验证单位和效果。
   共享元素、path/mask、自定义 shader 无直接支持时记录替代与视觉影响。
5. 三方动画资源验证目标库版本/支持特性，保留版权与素材来源，不保证所有 JSON 可直接播放。
6. 页面离开时清理 timer/animator/监听；重复进入、减少动态效果和低帧率场景列验证点。

输出源码状态→目标状态映射、参数表、未等价项和对应 AC。
编译通过不能当动画对齐证据；视觉/交互验证由真实设备场景完成。
