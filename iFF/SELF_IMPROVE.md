# iFF 自我进化操作规程(self-improvement loop)

> 动机:对"任意设计稿一次扇出"不能靠多跑训练轮(本会话 12 轮、26 次手动根因→修→自测→提交,且修复
> 本身反复引回归)。这套规程把那个**元循环自动化**,但有两条铁的安全边界:
> **① 不能静默回归**(语料自测)· **② 不能静默放宽不变量**(路由器强制升级)。
> 现状:安全网(corpus self-test)+ 路由器(classify_blocker)已建并验证;`apply_script_fix` 编排与
> 两个策略决定待人拍板(见末尾 ⛳)。

## 循环(每次 worker 跑完一张设计)
```
worker 跑 → 结构化失败记录(已在产:{visual,interaction,data,blockers[],manual_judgements[]})
  → classify_blocker.py 路由每条失败/绕过 → 按出口分流:
       ① AUTO_FIX_SCRIPT   → 见下"自改脚本纪律"(可自动)
       ② STRENGTHEN_CONTRACT→ 收紧契约/门(parse/completeness/bind 的信号词、IMPL-* 规则),模型填空
       ③ ESCALATE          → 冻结,带证据升级给人(任何会动不变量的修复)
       ④ RECORD_CEILING    → 记 ceilings(必须带 probe,否则 NEEDS_PROBE 退回)
  → 若全部是 ①/④(且 ④ 有 probe)→ autoEvolvable=true,自动进化
  → 出现 ②/③/NEEDS_PROBE → classify_blocker 退出非零,循环暂停等人
```

## ① 自改脚本纪律(determinism 失败,唯一允许 skill 改自己代码的路)
铁律:**每个确定性修复必须把"会触发它的最小用例"沉淀成永久回归 fixture**,否则不许提交。
1. 在 `evolution/regression/<NNNN_concern>/` 放一个**最小、单一关注点**的 fixture:`render_plan.json` +
   `classification.json`(+ `meta.json` 记 origin/exercises/assert)。最小+单概念是硬要求——R11 的回归正是
   因为"双 chevron 在同一 ref 里盖住了单分支 warning"。
2. **红-before**:fixture 在**未打补丁**的脚本上必须 FAIL(`git show HEAD:<script>` 取旧版跑该 fixture)。
3. 写补丁(模型改脚本)。
4. **绿-after + 全量回归**:`python3 scripts/selftest_canvas.py --project <flutter工程>` —— 整个 corpus
   全绿(generate_canvas→flutter analyze 无 warning→trace→check_render_fidelity 逐节点过)。
5. 红-before ∧ 绿-after ∧ 全量绿 → 才允许 commit(commit 信息记 origin 设计 + corpus case id)。

## ② 强化契约(NL 判断滑过门)
不改脚本逻辑,改"逼模型把判断落成可验证证据"的约束:`check_interaction_completeness` 信号词、
`bind_data_slots` 的 `needsModelBinding`、`make_component_manifest` chrome 守卫、`implementation_rules` 某条。
门只能保证"每条判断都接到且可证",判断对错由跨数据/语义回归兜(见⛳决策2)。

## ③ 升级(会动不变量——绝不自动)
`classify_blocker` 的 INVARIANT-touch 守卫已把这类强制路由到 ESCALATE(放宽阈值 / 允许整图铺底 /
放行 Offstage / 重开 golden / 加 analysis_options exclude 等关键词)。**skill 永不自行放宽不变量**——
这是不变量⑤在元层面的落地(严禁为过门放宽真实缺陷判定)。带证据交人决定。

## ④ 天花板(环境/数据物理限)
记 `evolution/ceilings.md`,**必须带 probe**(MissingPluginException / 端点不在 OAS / 跨引擎抗锯齿 /
无切图 / 真机状态栏)。无 probe = NEEDS_PROBE,退回当 ①/② 重路由(防"偷懒造天花板",我自己把 申请5
误判成天花板就是反例)。

## 收敛信号(替代"连续 3 张干净")
不再靠跑通固定语料,而是:**回归 corpus 只增不减 + 最近 N 张全新设计零 ① 类(确定性)失败 +
零静默放宽不变量**。即"新设计不再产生新的确定性 bug",才是 skill 真的稳了。

## 已建 vs 待建
- ✅ 安全网:`scripts/selftest_canvas.py`(corpus 驱动)+ `evolution/regression/{0001_full,0002_backonly}`。
- ✅ 路由器:`scripts/classify_blocker.py`(4 出口 + INVARIANT-touch 强制升级,已在 R11/R12/R9 验证)。
- ⛳ 待建/待决:
  - `apply_script_fix.py` 编排(红-before/绿-after/全量绿;**是否自动 commit 还是关键脚本需人 gate** = 决策1)。
  - **决策2(NL 对错)**:是否加一道"语义回归门"——切 mock 值看可见层/语义是否按预期变(抓"绑错字段")。
  - **R12 不变量①边界**:全屏背景图(其上有真实数据驱动内容)允许当 backdrop 渲染,还是仍按整图铺底禁?
  - evolution 主循环接到 worker 收尾(`failures/` 落盘 → classify → 分流)。
