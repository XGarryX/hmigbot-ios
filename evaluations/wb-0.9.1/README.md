# 0.9.1 中性样本与实际迁移评估

[源行为矩阵](source-review.md)覆盖 SwiftUI Binding/条件身份/导航、UIKit/Objective-C/Interface Builder、跨页异步保存/取消。它们有真实中性源文件与本轮事实提取，尚未各自迁移成完整目标应用，不计入完成率。

Counter 是本轮实际作者读源后编写的完整 profile 2 合同与 ArkTS 候选。`run_evaluation.py` 使用现有严格合同夹具的固定提纲作为种子，再按本例补入实际 App 入口、模型/页面接口、源语义、覆盖、两个 AC 与 indexed-v2 Plan。不存在网络/存储/任务的维度按完整源文件说明原因，状态/事件/数据流/组合等真实维度保留结构化事实。它不是全 not_applicable 的空合同。

评估脚本重放这一个已编写候选：通过真正的 `plan-ir`、`next-batch`、同路径 ios-receipt 和 `land-results` 调度/生成/落账，三份控制账本只由原工具写入。它不是新一轮独立模型采样，不能用重复运行次数计算模型首次成功率。目标工程由原 scaffolder 与本例作者实现共同生成；不读取 Chunky 或任何活动迁移项目。

## 复现

需要本机实际 DevEco Studio（Node、Hvigor、HarmonyOS SDK），默认路径可用 `--deveco` 改写。每次使用新的输出目录保留失败。构建证据位于 output/build，和 source/target 分离。

```text
python evaluations/wb-0.9.1/inspect_matrix.py --output work/wb-fixes-0.9.1/evaluation/matrix-new
python evaluations/wb-0.9.1/run_evaluation.py --output work/wb-fixes-0.9.1/evaluation/attempt-new
python evaluations/wb-0.9.1/capture_delivery.py --attempt work/wb-fixes-0.9.1/evaluation/attempt-new
```

输出保留 source gate、typed JSON、只读 plan-check、原四拍 actions、真实构建 stdout/stderr/HAP 摘要、行为观察、变异结果与派生 summary。运行中若工具合同发生变化，应保留 stale 失败，再从新输出目录重跑；不能手改冻结 pin。

## 独立真值与观察边界

[独立源复核](review.json)绑定 Counter 源摘要和实际 Model/Page 文件摘要。根线程独立确认源初态0、Add每次+1，期望 `counts=[0,1,2]`；同样检查静态接线，未声称看到真实设备结果。

`host-behavior.cjs` 转译并执行实际生产 `CounterModel.ets`，不复制模型逻辑。变异把实际模型中的 `+=1` 改成 `+=2` 后得到 `[0,2,4]`，必须与源期望区分。宿主逻辑测试覆盖 F001-AC01；F001-AC02 的实际控件点击/文案仍待设备验证，所以完整 `behavior-check` 应为 UNVERIFIED，不能改写成 PASS。

本机实际 `hdc list targets` 为 `[Empty]`。本轮没有 Xcode 源编译、iOS 运行、鸿蒙设备点击或视觉对齐，也没有 Swift Int 全值域/溢出等价验证；评估值域限于0、1、2。

词法适配仍有明确受限边界：插值表达式内含 Swift regex literal（例如 `"\("x".contains(#/[(]/#))"`）时，当前适配器不识别 regex 字符类，可能返回下一行的 unterminated 错误。该路径抛错并阻断源提取，不会产出截断产品文案或PASS；错误定位也不代表源程序真的未闭合。[Swift词法文档](https://docs.swift.org/latest/documentation/the-swift-programming-language/lexicalstructure/)和[Apple Regex](https://developer.apple.com/documentation/swift/regex)支持其表达式/字面量依据，本轮未Swift编译。`probe_regex_boundary.py`保存实际阻断结果；完整前端覆盖仍是后续能力缺口，本次没有用泛化正则猜测Swift语法或绕过源门禁。

## 首轮保留记录

attempt-01 在 source gate、Plan 检查、Base/Counter 两任务落账后，真实 Hvigor 首次构建成功，产出新的 unsigned HAP。施工中的工具 schema 随后改变，final 落账被 `Frozen tool contract revision changed` 拒绝。这是保留的真实 stale 失败，不能算完整四拍完成。

随后 `observe_existing.py` 只补采绑定独立复核的宿主观察，不恢复或修改控制账本。实际 `[0,1,2]`、+2变异 `[0,2,4]`，完整行为结果 UNVERIFIED（F001-AC02待验）。最终工具稳定后的重跑结果见 `results/`。

独立样本审查另指出UIKit种子XIB缺少FileOwner.view→root连接；已补齐该连接，再采matrix-02。初次matrix-01及attempt-01摘要保留原样，几何约束歧义继续披露；补连接不等于实际UIKit运行通过。

## 稳定工具后的正式结果

[attempt-02结果](results/attempt-02/result.json)与[逐页证据摘要](results/attempt-02/summary-excerpt.json)保留真实范围；[独立复查](results/independent-review.json)与作者分离。

| 检查 | 实际结果 |
|---|---|
| 当前源/Spec门禁 | PASS，独立交付复跑退出0 |
| indexed-v2 Plan | 只读plan-check与plan-ir通过；所有写权/AC/依赖进入冻结合同 |
| 原调度四拍 | base、counter、final各1次落账OK，最终done |
| 实际目标编译 | Node24.14.1、Hvigor6.26.4、ETS SDK26.0.0.105；34任务全部执行，BUILD SUCCESSFUL in20.408s；15472B unsigned HAP |
| 宿主业务与变异 | 生产模型[0,1,2]；+2变异[0,2,4]，独立源期望可区分 |
| 全部行为 | UNVERIFIED，F001-AC02设备UI待验，behavior_verified=false |
| page_0001漏斗 | generated / compilation passed / behavior unverified / visual not_run；未将Model的unit AC01摊成页面通过 |
| 实际交付消费者 | source/spec/plan/summary/report生成/report校验6项退出0，migration-report --check为current |

正式HAP的SHA256为 `489d32adf982fb521a018ad6872610090263adde959282fb9ccce35c6541c7a2`。实际MD/Plan/ArkTS产物快照在 `results/attempt-02/authored-output/`；[迁移报告](results/attempt-02/migration-report.md)由live命令生成，[调用记录](results/attempt-02/delivery-capture.json)绑定命令、退出码和输出摘要。原始HAP及完整执行材料保留在ignored work目录，不把二进制加入源仓。

首次stale异常的原始runner拷贝见[失败附件](results/attempt-01-failure.txt)和[指纹记录](results/attempt-01-failure.json)，没有重写首次结果。regex边界的[实际阻断结果](results/regex-boundary.json)单独记录；它不计入可迁移语法通过数。
