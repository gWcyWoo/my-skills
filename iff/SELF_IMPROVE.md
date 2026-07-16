# iFF 自我进化操作规程(每张设计跑完即进化)

> 目标:每跑完一张设计,skill 产出一个「让下次更好」的 PR——要么收紧一条脚本,要么加一条案例记忆,
> 要么登记一个边界。两条铁的安全边界:**① 不能静默回归**(corpus 自测)· **② 不能静默放宽不变量**(router 强制升级)。
> 进化是「为下次」,不回头改已跑完的任务。**所有改动都开 PR(审计 + 一键 revert);router 即合并闸**——
> `AUTO_FIX`(脚本补丁,corpus 绿)+ B 案例记忆 → **自动合**(证明=审查,人也看不出 corpus 看不出的);
> `ESCALATE/NEEDS_PROBE`(动不变量)→ **留人**。

## 何时、由谁
每张设计的 worker 跑完(产出失败记录 `{blockers[], manual_judgements[], 命中的 CASE-id, gate 结果}`)→
orchestrator **spawn 一个 evolution 子 agent**,在 **skill 仓的 git worktree** 里干活(不碰当前任务、不碰 `main`)。

## 子 agent 流程
1. **读失败记录 + 跑 router**:`classify_blocker.py --failure <record>` → 每条失败分 A/B/C/天花板。
2. **建 worktree + 分支**:`git worktree add ../iff-evo-<design> -b iff-evo-<design> main`(基于最新 main 或当前迭代分支)。
3. **按类处理**:
   - **A 确定性**(脚本没喂对/没处理):改脚本 + 在 `evolution/regression/<NNNN>/` 放**最小、单关注点** fixture
     → **红-before**(`git show HEAD:<script>` 跑旧版必 FAIL)→ **绿-after + 全量 corpus 绿**(`selftest_canvas.py`)→ 才提交。
   - **B 判断**(绑错字段/漏抽规则/语义归属):往 `evolution/case_memory.md` 加/改一条先例
     (`signature / decision / why / from / seen`)。**只来自被纠正的误判**。见下「seen 与毕业」。
   - **C 边界**(动不变量,如全屏背景图):**不自动改**,登记到升级清单 + `evolution/ceilings.md`(须带 probe),PR 里标 `NEEDS-HUMAN`。
4. **提交 PR + router 即合并闸**:`open_pr.py --branch iff-evo-<design> --title ... --body ... [--auto-merge]`
   (host 自适应:github→gh/web,gitlab→glab/push-option,未知→push+URL,**绝不写死 gh**)。
   - router `autoEvolvable=true`(只有 AUTO_FIX/RECORD_CEILING)+ corpus 绿 → 传 `--auto-merge`(开 PR 后自动合)。
   - 出现 `ESCALATE/NEEDS_PROBE/REVIEW` → **不传** `--auto-merge`,PR 留人,body 标 `NEEDS-HUMAN`。
   - 自动合的 CLI-less 兜底是 fast-forward `push branch:target`,base 动过就安全失败(非 ff)→ PR 留给人,绝不强推。
5. **清理**:`git worktree remove`。一张设计一个 PR。

## B 类:seen 计数与毕业(N=3)
- worker 命中某 CASE 且**应用后过门** → 该 CASE `seen += 1`(确认复用,非裸匹配)。
- 某次判断与已有 CASE **冲突** = 反例 → **改写该 CASE、`seen` 清零、不毕业**。
- `seen ≥ 3` 且零反例 → **毕业**:evolution 子 agent **优先改脚本**(如 `bind_data_slots` 主动喂对),
  改不了**才退而加 `check_*`**(挡误判);毕业后**从 case_memory.md 删除该 CASE**。
  → 即:案例记忆是确定性规则的孵化器,稳定的判断最终沉淀成代码,记忆不无限膨胀。

## 案例记忆怎么被消费
`sync_project_rules.py --memory evolution/case_memory.md` 在 worker 启动时把记忆注入工程 AGENTS.md
(check-if-present / inject-if-absent,空记忆跳过)。worker 在 归属 / ⑥交互绑定 / ⑦数据绑定 前**先读**,
命中 signature 就按 decision 做(看 why 判适用性),并在产物记录命中的 CASE-id 供累计 `seen`。

## 安全边界(为什么不会越改越坏)
- **回归**:A 类每次自改**必须**新增「会触发它」的最小 fixture,全量 corpus 必须绿——corpus 覆盖度 = 自改脚本的安全上限(R5/R7/R11 的教训)。
- **不变量**:`classify_blocker` 的 INVARIANT-touch 守卫把「放宽阈值/允许整图铺底/放行 Offstage/重开 golden/加 analysis_options exclude」强制路由到 ESCALATE,**skill 永不自行放宽不变量**(不变量⑤的元层落地)。
- **合并闸 = router**:`AUTO_FIX`+corpus 绿、B 案例记忆 → 自动合(快,人也 catch 不到 corpus catch 不到的);**动不变量的(`ESCALATE`)留人**——这是唯一「人能 catch 测试 catch 不到」的类(是否放宽 anti-整图铺底、是否真天花板=判断不是测试)。自动合的也开 PR,可 revert,不静默。

## 已建组件
- `scripts/classify_blocker.py` — router(A/B/C/天花板 + 强制升级)。
- `scripts/selftest_canvas.py` + `evolution/regression/*` — corpus 回归自测(语料驱动)。
- `scripts/open_pr.py` — host 自适应 PR/MR 提交。
- `evolution/case_memory.md` + `sync_project_rules.py --memory` — B 类记忆 + 注入。
- `evolution/ceilings.md` — 天花板登记(带 probe)。

## 收敛信号(替代「连续 3 张干净」)
**corpus 只增 + case_memory 持续毕业成脚本 + 最近 N 张全新设计零 A 类失败、零静默放宽不变量**——
即新设计不再产生新的确定性 bug,B 类判断越来越多被记忆/脚本接住。
