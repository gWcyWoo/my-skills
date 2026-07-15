# iFF 脚本职责总表(权威索引)

> 按固定链 **取稿 → scene → render_plan → canvas → fixture → 交互 → 数据 → trace → fidelity → 10 道门** 归类。
> 每条列**消费 → 产出 → 验它的门**,数据流(artifact 链)显式可见——加/删脚本时,断链(产出无人消费)和
> 漏注册(不在 `verify_pipeline_scripts.py`)一眼可查。I/O 来自各脚本 argparse 实测,非记忆。
> 约定:产物默认落该设计 `spec_dir`(`lanhu/specs/<设计名>/`);app 代码落 `lib/`。**消费/产出方含"模型"**,不只脚本。

## ① 取稿
| 脚本 | 消费 | 产出 |
|---|---|---|
| `reconcile_feature` | lib-root, feature manifests, route/state hints | reconcile_decision.json(new/variant/revision 事实) |
| `check_feature_manifest` | .iff/features/*.json | (门)route/state/文件所有权无冲突 |
| `run_fetch_pipeline` | row.json(多 design URL), skill scripts | **fetch_report.json**(逐板命令/exit/SHA;部分失败可见;无模型调用) |
| `check_state_change_scope` | feature manifest + `state_changes.json`(或单 state 兼容参数) | (门)覆盖全部 state、文件不跨 state 重复、实际 diff 不越界 |
| `fetch` | url, cookie | **raw.json** + 切图 |
| `write` | raw.json | spec.md(人读) |
| `download_cover` | url, cookie | **reference.png** |
| `classify_design` | raw.json, reference.png | **classification.json** |

## ② scene
| 脚本 | 消费 | 产出 |
|---|---|---|
| `export_figma_scene` | raw.json, assets | **scene.json** |
| `check_figma_scene` | scene.json | (门)scene 合法性 |
| `export_tokens` | scene.json | **tokens.json** |
| `export_assets_manifest` | scene.json | **assets_manifest.json** |
| `group_figma_layout` | scene.json | **groups.json** |
| `make_figma_layout_contract` | scene.json, groups.json | **layout_contract.json** |

## ③ render_plan
| 脚本 | 消费 | 产出 |
|---|---|---|
| `make_render_plan` | scene.json, assets, layout_contract | **render_plan.json**(每节点渲染方式,核心) |
| `check_render_plan` | render_plan.json | (门)整图铺底/合法性 |
| `check_design_artifacts` | spec-dir | (门)全 artifact id 互相可回溯、尺寸一致 |

### 公共组件 registry v2(扇出前/扇入)
| 脚本 | 消费 | 产出 |
|---|---|---|
| `detect_shared_components` | 多 board scene/groups + registry | reuse/missing/candidate + 仅差异 variation matrix + local 挂载 |
| `make_component_model_packet` | batch candidates + 当前业务事实 | **component_model_packet.json**(≤8KB,正好一个候选语义决策) |
| `apply_model_decision` | v2 packet + model decision | 校验当前 source SHA、allowed decision 与精确 write paths 后原子写一个 JSON source |
| `check_component_contract` | family contract + widget source | (门)固定骨架、语义 variants、受控 slots、无原始视觉 override/业务依赖 |
| `register_shared_component` | contract/widget/alias/role-map/consumers | `.iff/shared_components.json` v2 + widget/contract hashes |
| `check_shared_component_consumers` | registry + project + board gates | (门)组件或合同变化后全部 consumer 已复验 |

## ④ canvas
| 脚本 | 消费 | 产出 |
|---|---|---|
| `make_component_manifest` | render_plan, classification, groups, scene | **component_manifest.json** + 动态文本槽候选 |
| `generate_canvas` | **render_plan, tokens** | **canvas.dart + expected.json + slots.json + colors**(带 key 数据驱动画布,模型写0像素) |
| `make_implementation_map` | render_plan + generated expected | **implementation_map.json**(可见 required node→widget/bbox/render mode,确定性) |
| `copy_assets` | assets_manifest, target | assets/images/* |
| `update_pubspec_assets` | pubspec, asset | pubspec.yaml 注册 |
| `sync_project_rules` | implementation_rules, project-root | 注入工程 CLAUDE.md |

## ⑤ fixture
| 脚本 | 消费 | 产出 |
|---|---|---|
| `make_visual_fixture` | feature, slots.json | **`<Feature>VisualFixture` + `.source.json`**(设计 seed/fixture SHA 同源) |
| `check_fixture_source` | root, fixture-name | (门)真实 import+消费同一 fixture,seed/生成文件 SHA 当前 |

## ⑥ 交互
| 脚本 | 消费 | 产出 |
|---|---|---|
| `parse_interactions` | 交互散文, input | **interaction_contract.json**(只做确定性句法拆分;复合规则/语义非规则留给模型确认) |
| `check_interaction_completeness` | interaction_contract | (门)每条来源恰好进入规则或经模型确认的非规则/复合决策 |
| `check_interaction_contract` | interaction_contract | (门)每规则有三类结构化 observable target + 完整 feature/board/key node 或受限 system gesture |
| `make_interaction_tests_plan` | interaction_contract, api_contract | **interaction_test_plan.json** |
| `run_interaction_tests` | plan, test-root, Flutter `--machine` | **interaction_test_evidence.json**(用例级 red/green+当前指纹) |
| `check_interaction_wiring` | lib-root, test-root, contract | (门)每规则有运行时调用点 |
| `check_interaction_coverage` | test_plan, test-root, evidence | (门)每 case 的公开 UI action 直接绑定目标,assertion 直接绑定结构化 observable,用例级 red→green,非 skip,指纹当前 |
| `run_interaction_device_tests` | plan, integration tests, Flutter App, Android/iOS device | **interaction_device_evidence.json**(目标客户端用例结果+当前输入哈希) |
| `check_interaction_device_evidence` | plan, integration tests, Flutter App, device evidence | (门)Android/iOS 平台、公开 App 入口、精确 action/assertion、全部 case 与当前哈希 |
| `check_interaction_feature` | spec-root, project-root, feature manifest | **interaction_gate_report.json**(重算契约/状态/锚点/覆盖/wiring/flow/目标客户端证据) |
| `make_interaction_model_packet` | 当前交互产物 | **interaction_model_packet.json**(≤8KB,正好一个语义/状态决策;不静默截断,候选过多先选 board) |

## ⑦ 数据
| 脚本 | 消费 | 产出 |
|---|---|---|
| `normalize_api_contract` | OAS(Apifox) | **api_contract.json**(本地 schema/response/parameter/requestBody/pathItem ref;`--check` 重算 canonical) |
| `bind_data_slots` | component_manifest, api_contract, interaction_contract | **data_slot_bindings.json**(模型确认绑定) |
| `merge_feature_data` | feature manifest + 各 state board manifest/bindings + API contract | feature-root manifest/bindings(`state,node` 唯一,冲突/旧 SHA 失败) |
| `check_data_bindings` | manifest, api_contract, bindings | (门)当前指纹+每槽恰好一个真实字段或模型确认静态理由+transform 类型安全 |
| `check_data_runtime` | project, runtime manifest, api contract, bindings | (门)当前 feature operation 闭包;非 SLOT operation 模型确认;public identity;real/mock 同 interface/DTO/mapper;入口可达;状态完整 |
| `check_data_coverage` | bindings, runtime manifest, Flutter tests | (门)SLOT 两输入/两可见输出;REPO public API+本地 HTTP method/path/status/DTO;STATE public UI 精确 key/text |
| `data_test_cases` | bindings, runtime manifest | 纯函数:slot/repository/state required case IDs |
| `run_feature_tests` | interaction plan + data artifacts + Flutter `--machine` | **一次 Flutter run 同写 interaction/data RED 或 GREEN evidence** |
| `run_data_tests` | bindings, runtime manifest, test-root | 单域兼容入口;**worker 不与交互 runner 分开调用** |
| `run_data_device_tests` | bindings, runtime, integration tests, Flutter App, Android/iOS device | **data_device_evidence.json + PNG captures**(`app.main`,machine case,当前输入 SHA;SLOT 两张不同 PNG,STATE 一张) |
| `run_client_device_tests` | interaction plan + data bindings/runtime + 同一 integration test root | **一次 Flutter test** 同写 interaction/data device evidence 与自动 PNG captures |
| `check_data_device_evidence` | bindings, runtime, integration tests, Flutter App, runner evidence | (门)拒绝 Browser/手写 observations;重算 public observable、current hashes、PNG 字节 |
| `check_data_evidence` | bindings, runtime, tests, TDD/device evidence | (门)同指纹 RED→GREEN、全 case并委托自动 Android/iOS evidence checker |
| `check_api_integration` | api_contract, lib-root, runtime manifest | (门)当前 feature operation 在声明的 real repository 有正确 method+path 调用表达式 |
| `run_live_api_tests` | api contract, runtime closure, request config, HTTP base URL | **live_api_report.json**(真实 HTTP status/schema 结果) |
| `check_live_api_evidence` | 当前 contract/runtime + live report | (门)重算指纹并再次发真实 HTTP;手写 report 失败 |
| `check_data_feature` | spec-root, project-root, runtime manifest | **data_gate_report.json**(重算全部数据子门;live API 状态不虚报) |
| `make_data_model_packet` | 当前数据产物 | **data_model_packet.json**(≤8KB,正好一个字段/状态/修复 action) |
| `complete_worker` / `check_worker_compliance` | v3 contract input + prompt + result + outputs + feature manifest | 原子 receipt / canonical 重算;拒绝 v2、陈旧或越界输出 |
| `check_model_context` | feature manifest + 精确 receipt roster + component/每板 visual/interaction/data packets + 累计 ledger | **model_context_report.json**(每文件≤8KB、单 action、源 SHA 当前;区分 current/cumulative/baseline/unmeasured;done 重算) |

## ⑧ trace
| 脚本 | 消费 | 产出 |
|---|---|---|
| `gen_layout_trace_test` | expected.json, page-import/type | 真实页 trace 测 → **actual_layout_trace.json** |

> 喂 trace/fidelity 前的**真机诊断旁路**:`capture_runtime_screenshot`(→actual.png 真机像素)· `visual_diff`(像素 diff,**仅诊断**,跨引擎天花板)· `make_repair_plan`(diff→repair_plan.json,单次修复输入)。

## ⑨ fidelity
| 脚本 | 消费 | 产出 |
|---|---|---|
| `check_render_fidelity` | trace, expected, tokens | **视觉 PASS 门**:真实渲染 vs render_plan 逐节点(bbox≤2/色≤3/字号·圆角≤1/文案·token 100%) |
| `make_visual_gate_report` | reference/actual/fidelity/diff/manifest + component registry | 指纹化 `visual_gate_report.json`(viewport/fidelity/shape/provenance 硬失败;SSIM 仅诊断) |
| `check_visual_board` | board + visual_gate_report | (门)所有输入 SHA 当前且无 hardFailures |
| `check_visual_provenance` | PNG + layout + trace + expected + tokens + 两份视觉报告 | (门)重跑 `visual_diff`/`check_render_fidelity` 并逐字段比对,拒绝手改报告 |
| `check_visual_feature` | feature manifest + 全 state boards | (门)每个 state 独立视觉通过 |

## ⑩ 10 道门(done 前 barrier)
done 前统一再跑一遍,全过才 `done`(SKILL.md L280-300)。**不是另外 10 个脚本**——是各阶段的门 + 跨切面门汇总:
- 跨切面门:`check_visual_manifest`(actual=真机非派生)· `check_implementation_plan`(产前对齐)· `check_implementation_map`(可见节点覆盖率)· `check_worker_compliance`(bounded 合同+三份规则 SHA)· `check_model_context`(当前上下文/单 action/字节门)。
- barrier 再跑的阶段门:`check_render_plan` · `check_design_artifacts` · `check_fixture_source` · `check_interaction_completeness` · `check_interaction_coverage` · `check_interaction_wiring` · `check_data_feature`(内含 bindings/runtime/evidence/API) · `check_render_fidelity`。

## 编排 / 辅助(不在链上)
- `verify_pipeline_scripts`(语法/import/SHA 预检)· `make_worker_prompt`(manifest 推导 board+assembly v3 合同,≤8KB)· component/visual/interaction/data model packet(均≤8KB,每次一个 action)· `apply_model_decision`(有界原子写回)· `check_model_context`(receipt/packet/ledger 确定性报告)。
- `common`(共享库,~24 脚本 import)· `selftest_canvas`(可见层回归自测,corpus 驱动)· `classify_blocker`(自进化路由,旁路)。

## 断链/漏注册自查规则
> 消费/产出方含"模型":模型只给 packet 的当前语义/状态决策;`implementation_map.json`、统计、哈希与报告由脚本产。判死链前先确认不是模型判断后经 `apply_model_decision` 写回的 artifact。
1. 任一脚本的产出 artifact 必须有下游消费(脚本或模型),否则死产物。
2. 任一被消费的 artifact 必须有上游产出(脚本或模型),否则 worker 读到空。
3. 各阶段的核心产物(scene/render_plan/canvas/contract/api_contract…)必须有 ≥1 道门验它。
4. 所有非辅助脚本必须在 `verify_pipeline_scripts.py` REQUIRED 中(曾抓到 generate_canvas 漏注册)。
