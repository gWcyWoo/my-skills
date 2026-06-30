# iFF 案例记忆(B 类:模型判断的先例)

> 来自**被纠正的误判**。worker 在 归属 / ⑥交互绑定 / ⑦数据绑定 之前读这些先例,自问「我的情况匹配哪条
> signature」——**LLM 看 why 判适用性,不是 code 查表**。
> `seen ≥ 3` 且零反例 → 由 evolution 子 agent 升级为脚本(优先喂对)或 check(挡误判),升级后从本文件删除。
> `seen` 只在「新设计命中该 case + 应用后过门」时 +1;与某 case 冲突的判断 = 反例 → 改写该 case、清零、不升级。

## CASE-001 level_money 分级额度回退
- signature: 金额槽 + OAS 同时存在 `level_money` 与 `max_money`
- decision : 绑 `level_money`;为 0 或缺失时回退 `max_money`
- why      : `level_money` 是分级授信额度,用户未分级时为空,此时展示上限 `max_money`(不变量④)
- from: 取款页   seen: 1
