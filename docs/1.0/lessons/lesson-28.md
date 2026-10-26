# Lesson 28：阶段B·4.4 同版本激活与固定查询快照

日期：2026-10-23，第4章共5节，本节第4节。目标：理解三类不可变候选产物如何经SQLite活动指针共同切换、revision如何防过期写入，以及一次查询如何固定版本。只学习现有实现，不执行真实发布/回滚或修改运行配置。

## 从混版本场景建立边界

旧版本G1=(Bundle B1, Chroma V1, BM25 K1)已在服务。候选G2=(B2,V2,K2)还没建完K2，若分别挑各目录最新项，会得到B2/V2/K1，正文、片段ID、词项统计可能不一致。

当前做法：先完整构建G2三份产物，激活时重新审计三者，成功后切换一个活动指针；此前G1仍保留。B1/V1/K1等是课堂缩写，真实ID为摘要；同版本不是三者ID相同，而是一个IndexVersion绑定三个确切ID与共同来源身份。

G1/G2是工程索引版本，不是L0/L1/L2层级或业务需求生效判断。G2仍可包含历史L2_A；保留旧工程版本与当前集合保留历史需求是不同机制。

## 数据结构与目录

```text
ActiveVersion
  revision: 1
  version: IndexVersion
    version_id: G1
    bundle_id: B1
    vector_index_id: V1
    bm25_index_id: K1
    knowledge_base_id / 文档数 / 片段数 / source_fingerprint
    model_space_id / representation_id / tokenizer_id / dimensions
    chroma_collection_name / SDK版本 / bm25_k1 / bm25_b / SDK版本
```

version_id是整个绑定描述的摘要，不是时间戳；revision是活动指针变更序号。未激活时逻辑revision=0；首次激活为1；切到另一绑定为2；重复激活当前完整绑定返回unchanged、不增加revision。即使再次选择曾用过的绑定，激活序号也不能倒退。

同一KB目录的catalog.sqlite3只有两张核心表：versions保存version_id→descriptor_json；active只有singleton=1的一条当前version_id/revision。它不保存正文/向量矩阵，也不是每次切换的完整事件日志。已登记旧版本描述保留，查询所需旧文件当前也保留；没有本节新增的自动GC。

## DocumentManager.activate实际主链

```text
activate(bundle_id, expected_revision)
  → IndexCatalog.write启动BEGIN IMMEDIATE
  → 读取current；比较expected_revision
  → _audit：Bundle.load → Chroma.audit → BM25.audit
  → 核共同包/KB/文档片段数/编码身份、向量维度等
  → 生成IndexVersion、核已有同ID描述
  → 当前相同则unchanged；不同则publish登记描述/更新active
  → 离开write上下文：COMMIT或失败处理、close
  → 成功才return ActivationReceipt
```

activate不构建产物、不请求模型、不重分词；缺任何候选产物都报错。_audit复用前三节的实质核验，不只看ready文件是否存在。测试把两个build入口替换为forbidden，正常激活仍成功，证明职责分离。

### with与yield：谁负责提交

IndexCatalog.write是@contextmanager生成器：第183行BEGIN IMMEDIATE；第184行yield conn把连接交给activate的with正文；正文正常结束后回到第185–187行提交；正文抛错时异常从yield处回到except，尝试终止事务；finally关闭连接。activate的return receipt在with之外，因此不会在提交完成前把成功回执交给调用方。

SQLite[官方事务说明](https://www.sqlite.org/lang_transaction.html)确认同一时刻只有一个写事务，BEGIN IMMEDIATE会立即尝试开始写事务，竞争可能BUSY。当前逻辑在持有写事务期间执行三类产物审计，写锁覆盖审计与提交，不是只持续一次轻量UPDATE；其大库并发代价未验证。

publish先参数化INSERT版本描述，再参数化INSERT/UPDATE active，两步在同一SQLite事务内。原子边界是这两张表的提交，不把Bundle文件、Chroma、BM25和SQLite当作一个跨库事务。已建好且不会原地更新的产物配合单一指针，是当前一致性方案。

## expected_revision防止什么

调用方观察revision=1，随后构建候选。另一任务先成功激活，让current=2；旧调用再带expected_revision=1会报catalog_revision_conflict，不覆盖已变更状态。当前通过BEGIN IMMEDIATE串行化写入，在事务内读取/比较revision；不是仅在SQL外先看一眼，或只靠Python线程锁。

expected_revision=0表示期望尚未激活，不是关闭检查。冲突后本节不自动重试、回滚活动版本或替用户决定采用谁的候选。合法未激活返回None；目录损坏不是未激活。首次审计失败可能已经初始化一个有效空元目录，但没有active。

## 查询固定的是描述，不是长时间数据库锁

QueryPipeline.prepare调用manager._document_bundle，读取一次已提交ActiveVersion及对应Bundle，关闭目录连接；_identity核编码合同及三产物，ready才编码。PreparedQuery保存这个active与有效文档/片段范围。后续Dense/Sparse/KnowledgeReader消费prepared.active.version中的ID/参数，不在每一路重选latest。

示意时间线：Q开始选G1/revision1→Q编码期间另任务激活G2/revision2→Q继续使用B1/V1/K1→之后开始的新查询可选G2。Q不会自动升级成一半G1一半G2，也不会仅因为active后来变化就自动失败。

查询expected_revision只在选定快照时核对，不是后续每一步都要求全局指针不变。这里靠持久描述和旧产物保留固定逻辑快照，不是整个模型请求期间持续持有SQLite读事务。新读取仍可能遇到IO/锁错误，不能据此承诺更新时所有请求永远无失败。

open_active重开时用保存的collection_name、bm25_k1/b，而非当前manager默认值；运行批大小仍取当前调用设置。此前M3模型/表示/分词身份不兼容仍会拒绝，不因固定版本而绕过。

## 失败与提交不确定

| 条件 | 当前结果 |
|---|---|
| 三产物齐全且一致、revision符合 | activated，revision+1 |
| 当前绑定相同 | unchanged，revision不变 |
| revision过期 | catalog_revision_conflict，不切换 |
| 候选缺BM25/Chroma损坏/来源身份不符 | 审计失败，旧active保持，不登记候选 |
| 另进程占写事务 | catalog_busy，不隐式排队重试 |
| 正式提交前的明确写入失败并可终止事务 | 报错，旧active保持 |
| 提交阶段或提交后关闭异常，结果不能可靠判断 | catalog_commit_uncertain，重新读取确认，不宣称旧active一定未变 |

故障注入证明commit-before与commit-after都可能得到commit_uncertain，但新连接读回分别是revision1和2。异常不等于事务一定没提交。测试中的close异常发生在真实提交成功后，也读到2；生产调用方应读取确认实际落点，不能盲目覆盖或补偿。

本节不运行真实回滚，不引入跨库事务/分布式部署。文件被外部改坏仍要按前三节校验失败，固定ID不等于文件永远不会损坏。SQLite同步配置也不代替断电/大库/生产并发验收。

## Debug Test入口

正常：`tests/test_document_manager.py::test_activate_repeat_reopen_and_fixed_identity`，无参数。第42行activate入口断点，F11到DocumentManager.activate；进入catalog.write时先走生成器BEGIN/yield，随后回到activate正文。选activate帧第60行后看revision/current，第62行执行后看version中的三个索引ID与chunk_count；publish前查看active.revision。离开with时F11跟入write的COMMIT，回到activate第72行后才返回receipt。

prepared fixture使用真实Bundle/BM25/SQLite，Chroma new_client替成FakeClient，编码资料为合成记录；本节正常业务测试不冒充原生Chroma证明。

候选失败：`tests/test_document_manager.py::test_failed_candidate_keeps_old_active_and_no_new_registration[missing-bm25]`，精确ID=missing-bm25。第100行将候选BM25配置改成没有对应索引的9/.1，不是删除真实文件；第107行激活，在_audit的BM25.audit失败，write回滚，测试第108–110行核active仍old、versions只有1条。pytest.raises捕获预期异常，测试通过。

固定查询：`tests/test_query_preparation.py::test_actual_activation_during_encoding_does_not_change_selected_snapshot`，无参数。第164行给Dense替身安装hook，编码时真实调用另一manager.activate；第165行prepare入口，F5到query/pipeline.py第129行，此前active已选旧版；执行encode时hook将目录切到2，回第132行后仍看prepared所用active.revision=1。回测试result.active==旧active，同时catalog.read()==新active。WATCH观察选定变量，不重新activate/encode查值。

提交不确定：`tests/test_document_manager.py::test_catalog_failures_are_observable_without_partial_success[commit-after]`，精确ID=commit-after；另commit-before/close。第128–130行附近包装_commit，先调用真实COMMIT再抛OSError。catalog.write第193–194行归一commit_uncertain，测试用未注入故障的manager.catalog读取revision2。不同调用栈帧选择conn.in_transaction只能观察已有连接状态，不在WATCH调用提交/回滚。

## 本次实际验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_document_manager.py::test_activate_repeat_reopen_and_fixed_identity \
  tests/test_document_manager.py::test_switch_and_stale_revision_preserve_pinned_version \
  tests/test_document_manager.py::test_failed_candidate_keeps_old_active_and_no_new_registration \
  'tests/test_document_manager.py::test_catalog_failures_are_observable_without_partial_success[commit-before]' \
  'tests/test_document_manager.py::test_catalog_failures_are_observable_without_partial_success[commit-after]' \
  'tests/test_document_manager.py::test_catalog_failures_are_observable_without_partial_success[close]' \
  tests/test_index_versions.py::test_catalog_atomic_registration_repeat_and_schema \
  tests/test_query_preparation.py::test_actual_activation_during_encoding_does_not_change_selected_snapshot \
  tests/test_document_manager_wiring.py::test_native_three_artifacts_activate_and_restart \
  tests/test_document_manager_wiring.py::test_process_lock_and_stale_revision_without_sleep \
  tests/test_knowledge_reader.py::test_complete_case_and_actual_lines_without_sdk_or_latest
# 17 passed in 13.46s
```

原生四态normal/zero/all-empty/mixed使用真实Bundle/Chroma1.5.9/BM25S0.3.13/SQLite，新进程重开相同ActiveVersion；Embedding为SDK MockTransport。进程锁测试用事件握手持有写事务，另一连接读已提交1，竞争写busy，释放后新revision2，旧expected1被拒绝；不使用紧sleep。查询固定快照测试的Dense/Sparse为替身，hook实际激活但没有原生并发全查询压力测；Reader测试禁止重选latest/模型，读取保存原文。

L1已有DocumentManager/IndexCatalog/IndexVersion，L2真实三类审计/事务/版本消费，L3上述17项覆盖正常/失败/不确定/原生重启/进程锁。无真实模型、源码/依赖/本项目真实.env/运行配置/原索引修改；临时测试目录包含合成配置和故障注入。构建不适用，不跑全量；git diff --check退出0。

## 学习证据与唯一下一步

4.4已讲解，助手完成源码/SQLite官方说明与定向验证；用户理解待反馈，本人独立调试/实现未评估。讲解覆盖20/34节，余14节。下一节4.5：重复摄取、文档更新、移除与历史保留，沿实际IngestionPipeline解释何时复用活动版本、何时构建新集合，以及移除后为什么还能再次摄取。
