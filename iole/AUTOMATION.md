# Codex Automations 适配

只在用户要求创建、检查或修改周期调度时读取；单次页面执行不需加载本文件。

`interval` 必须按宿主的实际计时语义配置，不能把空闲冷却窗口当作固定巡检周期。IOLE 每次被触发执行 [SKILL.md](SKILL.md#一次-loop) 定义的范围；用户已要求连续完成时，阶段通过不能作为提前结束点。
Claude `/loop` 在当前线程持续触发;Codex 等价适配为当前本地线程的 `heartbeat`,
只有人明确要求“每轮创建独立任务/独立项目任务”时才用 `cron`。
Codex `mcp__codex_app` 命名空间的方法 `automation_update`（完整工具名
`mcp__codex_app__automation_update`）统一适配原流程的三个方法:

| 原方法 | Codex 适配 |
|---|---|
| `create_scheduled_task` | 默认调 `mcp__codex_app__automation_update` 的 `mode=create`,传 `kind=heartbeat`, `destination=thread`, `name`, `prompt`, `rrule`, `status=ACTIVE`;明确要求每轮独立任务时才先用 `codex_app__list_projects` 取得 `projectId`,再以 `kind=cron`, `destination=local`, `executionEnvironment=local` 创建 |
| `list_scheduled_tasks` | 只读检索 `${CODEX_HOME:-$HOME/.codex}/automations/*/automation.toml` 得到候选 ID,再对候选逐个调 `mcp__codex_app__automation_update` 的 `mode=view` 确认 |
| `update_scheduled_task` | 先 `mode=view` 取回完整现值,再对同一 ID 调 `mode=update`;保留原 `kind` 和目标线程/项目,只替换用户要求变更的字段,其余完整传回 |

heartbeat 的唯一身份是 `target thread + link + role`;cron 的唯一身份是
`project + link + role`:已存在则更新,不存在才创建。
创建时 `prompt` 只描述“使用本 skill 和固定参数执行一次 loop”;项目绑定、
线程绑定、周期和状态分别放在 `projectId`/`destination=thread`, `rrule`,
`status=ACTIVE`,不混入 prompt。heartbeat 不传 `projectId`, `model`,
`reasoningEffort`, `executionEnvironment`;cron 的 `model` 和 `reasoningEffort`
有人显式指定时用指定值,否则沿用当前 Codex 会话配置,无法确定时报
`scheduler_config_unavailable`,不猜测。
将 `interval` 转换为宿主接受的 RFC 5545 RRULE。当前 Codex 的分钟间隔 heartbeat 按“上次运行、绑定会话更新时间”的较晚值加间隔计算冷却期；会话活动会推迟派发。用户要求每半小时巡检时，使用按时钟的小时规则、分钟为 0 和 30，保留 heartbeat 及原绑定；只有要求空闲后检查时才选分钟间隔。宿主仍会避开正在执行或等待用户的会话，并可能加入短抖动，不能承诺严格准点。更新后核对实际保存的规则与下一次计划时间，不以 ACTIVE 代替派发验证。此语义以当前宿主实现为准，升级后异常须重新核对。cron 只接受小时周期或周计划;
其他周期报 `unsupported_interval`,不调用调度工具,
也不悄悄更换周期。不直接编写 `automation.toml`。

当前会话未暴露 `mcp__codex_app__automation_update` 时报 `scheduler_unavailable`,
明确“未创建或更新周期调度”;不把业务行标记为 failed,不声称已调度,
也不用进程内 `sleep` 假装周期调度。
`mcp__codex_app__automation_update` 是 Codex Desktop 的本机动态工具,只在 `local` 任务中注入;
当前任务的 `hostId` 为 `slingshot:*` 等远程宿主时同样报 `scheduler_unavailable`,
不直接改写本机 Automation 存储绕过宿主限制。
