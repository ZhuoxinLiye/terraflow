# 保存与复用分析流程

成功完成一次基于目录影像（`SceneInput`）的分析后，助手显示“保存为可复用流程”卡片。点击保存后，该流程作为带版本的快照加入现有工作流列表。点击“暂不保存”不会发布。自动继续模式也会等待这项确认。

后续在新会话描述任务即可，例如：

> 比较色萨利 2023-09-01 和 2023-09-13 两景 Sentinel-1 VV 影像，分别提取水体并统计面积。先检查可比性，创建并执行工作流，给出日期、阈值、有效区面积、水体面积与占比。只讨论单景水体估计和面积差。

助手先检索已确认的流程。匹配的子任务在画布上显示为“可复用流程”节点，引用真实 Flow ID 和版本，输入绑定为本次目录影像。每次调用都重新运行，生成独立输出路径和运行记录。两景任务仍需在父画布保留可比性预检；失败的预检会阻止子流程执行。

结果与日志中的节点 JSON 包含引用 ID、版本、输入绑定、调用 ID、子流程运行 ID 和各工具的真实输出。原 Flow 不会被新输入改写。查看保存的快照可使用确认回复中的链接。编辑快照或输入输出契约会使版本校验失败，应重新执行并生成新版本。

当前自动封装支持已有目录可提供的 `SceneInput` 输入。输入必须满足示例影像声明的传感器、数据类型、尺度和来源类别，路径必须存在。其他输入类型、自动跨传感器转换、版本迁移和一般性的效果评估仍需后续支持。保存成功只证明一次工程执行通过，不能证明分割准确性或跨事件有效性。

## 实现入口

- 现有 `Flow.data.reusable_flow` 保存草稿/发布状态、图与契约散列、输入输出、一次执行证据；列表沿用现有工作流管理。
- `search_reusable_flows` 只返回当前用户拥有的已发布且版本完整的资产；确认发布由原生确认卡直接请求后端处理，模型工具不具有确认权限。
- `ReusableFlow` 是统一目录中的原生组件；检查所有者、版本、输入条件和递归深度后，在副本绑定输入并执行。输出包含测量值、引用和本次证据。
- `run_flow` 汇总所有数据节点的科学输出，跳过工具描述等大块元数据。完整数据仍可在原生节点结果中查看；超出汇总容量时明确报告不完整。

## 定向验证

```bash
.venv/bin/python -m pytest src/backend/tests/unit/agentic/services/test_reusable_flows.py src/backend/tests/unit/agentic/services/test_flow_run.py src/backend/tests/unit/agentic/services/test_run_flow_tool.py
cd src/frontend
node_modules/.bin/jest --runInBand src/components/core/assistantPanel/hooks/__tests__/use-assistant-chat-plan-refining.test.ts src/components/core/assistantPanel/components/__tests__/assistant-plan-card.test.tsx
npm run build
```

这些单元测试使用合成契约、模拟执行或合成 SSE；真实在线运行证据另记于 Earthmind N061，不把单元测试称为遥感精度验证。
