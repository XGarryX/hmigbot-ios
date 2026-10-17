<!-- when: Package.swift未求值，或需区分Xcode产品与测试编译源时读取；topics: manifest-evaluate、manifest-evidence、project-targets、续跑 -->
# 清单求值与产品成员证据

两种输入分别回答“这个清单在当前宿主求值得到什么声明”和“这个Xcode工程声明哪些源文件属于所选产品”。按实际需要使用，可组合传给 `facts`。它们不证明iOS有效构建、依赖已解析或运行行为。不要为了消除工具缺口删改应用的合法清单或测试。

## SwiftPM清单实际求值

先确认源根与目标根分离，当前宿主可运行与源清单兼容的Swift。配置JSON放在目标工程，例如 `<target>/spec/ref/manifest-evaluate.config.json`：

```json
{
  "schema_version": 1,
  "manifests": [{
    "path": "Package.swift",
    "command": ["swift", "package", "--package-path", "{package_dir}", "dump-package"],
    "version_command": ["swift", "--version"],
    "timeout_seconds": 120,
    "conditions": "当前宿主的SwiftPM清单求值；未运行iOS构建"
  }]
}
```

`path` 是源根内真实 `Package.swift` 的精确相对路径；嵌套包逐项列出。`command`、`version_command` 必须为显式argv数组，前者包含独立的 `package`、`dump-package` 参数，后者包含 `--version`。`command` 必须且只能给出一个显式 `--package-path`，解析后的目录须等于 `path` 所指清单的父目录。版本输出须包含合法的 `Swift version 主.次[.补丁]`（可带 `Apple` 前缀）；原始dump含 `packageKind` 时，其 `root` 必须唯一且与同一清单父目录匹配。`timeout_seconds` 为1至3600的整数，省略时120；`conditions` 为可选说明字符串。用 `python <当前技能目录>/scripts/run.py --runtime-root` 定位 `<runtime>`，字段与报告合同以随包runtime的 `<runtime>/schemas/source-manifest-evidence.schema.json` 为权威；安装到 `<workspace>/.agents/skills/` 后不要按技能相对路径寻找 `.agents/schemas/`。采集程序校验实际配置，不接受未知字段。

`{source}` 与 `{package_dir}` 展开为采集程序所在宿主的绝对路径；程序不会自动做WSL路径转换。若使用WSL，先核对真实映射，再提供例如 `["wsl", "--", "swift", "package", "--package-path", "/mnt/d/path/to/package", "dump-package"]` 及同一环境的版本命令；不能将Windows路径直接作为WSL目录，也不能把此示例路径当成实际证据。记录宿主差异，清单中的平台条件仍以实际执行环境为限。

```text
python <runtime>/scripts/a2h_ios.py manifest-evaluate --project <target> --config <target>/spec/ref/manifest-evaluate.config.json --output <target>/spec/ref/ios-manifest-evidence/<capture-id>
python <runtime>/scripts/a2h_ios.py facts --project <target> --manifest-evidence <target>/spec/ref/ios-manifest-evidence/<capture-id>
```

输出须位于目标的 `spec/ref/ios-manifest-evidence/` 内，目录必须不存在或为空，且不能与源根重叠；每次重试选新capture-id。`facts --manifest-evidence` 接受该目录或其中的 `manifest.json`，只读取当前源绑定且可回放的成功证据。

采集器实际运行Swift版本查询和 `dump-package`，保存argv、cwd、超时、退出码、原始stdout/stderr、前后源快照和摘要。版本失败、超时、非零退出、非法JSON或采集期间源变化均返回 `capture_failed`（CLI exit 2）；保留日志，修正环境或清单中的真实错误后重采。只有真实源错误才修改源代码，不能手写成功报告。

验证器按当前源与原始日志重算 `name`、`targets`、`dependencies`，拒绝过期、缺失、篡改或摘要与原始结果不符的证据。通过仅表示 `manifest_evaluated`，范围为 `current_host_manifest_evaluation`；`dependency_resolution`、`behavior_equivalence`、`capture_authenticity` 均保持 `not_verified`。摘要核对不认证执行器身份或证据作者。

事实提取只解除证据中精确匹配路径的 `Package.swift` 未求值问题；其他包清单、Podfile、Cartfile的问题仍保留。包的targets/dependencies是清单声明，不能据此宣布依赖解析、编译或鸿蒙迁移完成。

## Xcode工程声明的产品成员

有可解析的真实 `.xcodeproj/project.pbxproj`，需要把产品源与测试oracle区分时，创建variant输入，例如 `<target>/spec/ref/project-targets.json`：

```json
{
  "scope": "project-targets",
  "project_path": "Example.xcodeproj/project.pbxproj",
  "targets": ["Example"],
  "configuration": "Release"
}
```

仅提供这四个字段；替换为源根内真实工程路径、精确app/app-extension根target名字及已声明configuration。解析器从工程推导 `source_files`、`source_membership`、`excluded_sources`、`target_closure` 与摘要，回放时重新推导；调用者不能自写文件白名单或改派生字段。闭包包括 `PBXTargetDependency` 及产品引用中的嵌入扩展/本地依赖，不能只扫描主target目录。

```text
python <runtime>/scripts/a2h_ios.py facts --project <target> --variant <target>/spec/ref/project-targets.json --manifest-evidence <target>/spec/ref/ios-manifest-evidence/<capture-id>
```

无清单证据需求时省略 `--manifest-evidence`。测试独占文件由工程成员确定并列为 `test_only_oracle`，不作为本轮产品编译源扫描；与产品共享的文件仍保留。完整source-index不缩小，测试/依赖的disposition及验收真值责任仍保留，不能按Tests目录名直接排除。头文件因隐式包含关系保守保留全仓扫描，产品源中的活动 `#if` 等未解析信号继续阻断。

结果只标 `evidence=project_declared_membership`、`effective_build=unresolved`。条件build settings不用于删减成员；未知/歧义/越界路径、无归属编译单元、构建脚本、同步组、外部或跨工程依赖、自定义build rules及不支持的产品编译语言均拒绝推断。需要真实所选构建时仍走既有 `selected-build` 与 `source_build`、已哈希 `source-files.json` 证据协议，不能改标记冒充。

## 旧图续跑与交接

保留原失败现场。源未变时，用新输入重新执行 `facts`，由工具归档旧图；源已变时先按Harness的 `source-refresh --review` 协议更新索引并重新采集证据。新图把清单报告路径和 `report_sha256` 绑定到 `manifest_evidence`；`validate_graph` 重放当前源与原始证据，domains计划冻结清单目录中的原始产物。

重生成专业视图及 `expertise-plan`，由原owner复审受影响的semantics、coverage、disposition、规格和专业观察，再运行 `spec-check`、`source-check --harness`。门禁失败就处理当前finding，不复用旧PASS；已有冻结计划按Harness的 `replan` 协议重排。工具输入问题消除后仍可能有未完成规格或行为未知，按实际检查结果继续推进。
