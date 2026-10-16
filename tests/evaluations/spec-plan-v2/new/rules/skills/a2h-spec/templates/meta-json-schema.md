# iOS 页面meta：载荷v1与Spec profile v2

载荷schema_version与项目spec_contract_version分别版本化，不能看到新profile就批量把已有JSON的schema_version改2。以下是新profile示例：source_refs规范为path:line字符串列表，source_anchors保存结构化锚点，二者必须描述同一页面源证据。旧profile 1的对象式source_refs只保留历史兼容，显式升级时转换并重新检查。完整机器字段以随包schema/catalog及实际解析器为准。

```json
{
  "schema_version": 1,
  "spec_contract_version": 2,
  "source_platform": "ios",
  "page_id": "page_0001",
  "source_languages": ["swift"],
  "frameworks": ["swiftui"],
  "source_refs": ["Screens/Screen.swift:10"],
  "source_anchors": [{"role": "view", "path": "Screens/Screen.swift", "symbol": "Screen.body", "line": 10}],
  "page_type": "full_screen_page",
  "needs_immersive_safearea": false,
  "semantics_ref": "spec/baseline/ios-semantics.json#page_0001",
  "runtime": "not_run",
  "screenshot": null,
  "state_conditions": [],
  "resource_refs": [],
  "navigation_refs": []
}
```

page_type 取 full_screen_page/modal_overlay/dialog/sub_component，按真实呈现与生命周期判断。
needs_immersive_safearea 是目标适配决策，有源布局依据，不由目录或类名后缀猜测。
source_refs 必须实际存在；截图字段只引用真实采集文件，runtime 与 observed 状态相符。
runtime为not_run/captured/verified；未采集必须not_run和screenshot=null。captured/verified需引用存在的真实截图；verified仅指该记录的审阅状态，不能当作整个页面/应用行为通过。条件、资源与导航数组按真实能力填写，空数组不能掩盖已有源分支。
meta的frameworks使用本schema枚举swiftui/uikit/appkit/interface-builder/webview/other；ios-semantics的frameworks继续使用其既有枚举（Interface Builder为ib），升级/生成时按各自协议转换，不跨文件直接复制不兼容枚举。
