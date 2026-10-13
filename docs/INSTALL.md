# 安装、升级和卸载 0.7.0

从发行 ZIP 解压，在 hmigbot-ios 目录执行 `install.ps1 -Workspace <现有工作区>`；macOS 使用 `PYTHON=python3 sh install.sh <工作区>`。Windows 可用 `-Python` 指定解释器。要求 Python 3.11+，无需原 HMigBot 地址。若当前 PowerShell 策略拒绝未签名脚本，用 `powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Workspace <工作区>` 启动本次安装进程；这不修改系统执行策略。卸载可用同样方式调用 uninstall.ps1。

## 安装结果

- `.agents/skills/`：96 个启用技能及其 references、templates 和本地辅助入口，直接可被宿主发现。
- `.codex/agents/`：29 份角色规程。实际派发取决于宿主工具和当前授权，不支持时按角色契约串行执行。
- `.migbot/bin/`、`.migbot/policies/`：原运行时与辅助工具。a2h-tool 仅执行 iOS validate/build。
- `.hmigbot-ios/plugin/`：完整独立运行资源；新增 iOS 辅助脚本通过 runtime.json 定位。完整原资源单独保存在 vendor/hmigbot，校验器入口通过 runtime.json 解析；建议为发行包、解压与安装预留 4 GB。
- `.hmigbot-ios/install.json`：版本、托管路径和内容摘要，用于升级和卸载。
- `AGENTS.md`：只替换本工具标记块，其他用户规则保留。

仅在 `.codex/config.toml` 不存在时创建最小角色并发配置；已有用户配置原样保留。不自动注册上传会话的遥测 hooks、不修改宿主权限设置。不在安装时创建虚假的源工程配置或完成标记。

## 升级

再次运行 install 即升级。0.4.x 的 10 个源平台专用技能和 4 个源角色退出发现范围；0.3.x 的六个 a2h-ios-* 入口与外部 hmigbot-binding.json 由旧安装清单安全退出，新入口为原 a2h-*。用户编辑过的任何托管文件会阻止覆盖，错误指出具体路径；先合并该修改再重试。已有其他插件占用同名技能时拒绝覆盖，不能强删解决。

安装先验证所有路径、所有权和修改，再写入；写入异常恢复原文件。未托管项目文件不会纳入清理。旧研究文档和兼容 CLI 留在插件中，但 README 和主技能只指向新主线。

升级后重新打开会话，核对 `$a2h-run` 和 `$ios-source-analysis` 可发现；当前会话缓存可能仍显示旧入口。示例初始化：

```powershell
python .hmigbot-ios/plugin/scripts/a2h_ios.py init --source 'D:/Projects/NativeApp' --project '.'
```

随后由 a2h-init 核对真实 SDK、hvigorw、node 等并确认配置；源码与目标必须是互不包含的独立目录。

## 卸载

`uninstall.ps1 -Workspace <工作区>` 或 `sh uninstall.sh <工作区>`。只删除摘要与清单相符的文件，修改过的文件会保留并逐项报告；spec、应用源码、构建成果及其他插件都保留。未改动的 AGENTS.md 恢复原字节；用户在安装后新增的规则仍保留。

## 环境边界

Windows x64 是本次实测环境。原校验器的 macOS arm64 资产已复制，但缺少 Mac，未实测。Linux 缺少原发行的多个编译校验器，安装成功仅代表资料可用。原二进制运行时报缺失或平台不符时不能略过对应检查并标通过。

鸿蒙编译需要用户本机 SDK，真机安装还需要对应签名/设备。源 iOS 静态理解无需 Mac；云 Xcode 和 iPhone 是另行记录的证据来源。安装不上传源码或使用账号凭证。

## 0.6.0 baseline 升级

工具安装升级不会把 App 的旧 PASS 转为新 PASS。旧 baseline 先 import-legacy，再重提取和复核 v2 事实/覆盖。保留稳定 ID 和旧原始记录，存在外来状态写者时拒绝混用。详见 [Harness](HARNESS-0.6.md)。

## 0.7.0 专业资料和 MCP

三个固定 MIT 资料快照位于 `.hmigbot-ios/plugin/vendor/ios-expertise`，不会作为独立开发
入口自动替代迁移技能；由本轮 expertise-plan 输出绝对资源根与相对清单，分析 owner 按需读取。
0.6.0 的 v2 baseline 无须再次 import-legacy；先 expertise-plan，补源审阅、重跑 source-check --harness，
旧事实/AC 保持，冻结计划通过显式 replan 更新，不自动继承旧 PASS。

安装器不安装或自动启动 MCP 服务，不下载 Apple SDK，不改全局 MCP 配置。源 MCP 服务
按项目显式配置并固定版本，stdio 读客户端通过 mcp-query 调用；本机未连接 Mac/Xcode。
本版没有 HTTP transport。详见 [接入规程](../skills/ios-source-analysis/references/external-expertise.md)。
