# Lesson 29：阶段B·4.5 重复摄取、更新、移除与历史保留

日期：2026-10-23。第4章共5节，本节为最后一节。学习现有IngestionPipeline的成员集合变化，复用Lesson28的同版本激活机制；不实施增量编码或真实资料移除。

## 场景、输入与结果

下面文件名和G1/G2为课堂示意，与现有更新测试一致；不是用户真实材料实测。

旧活动G1/revision1包含：L1_Module(v1)、L2_A、L2_A_测试用例。
本次目录扫描提供：L1_Module(v2)、L2_B、L2_B_测试用例。

计划按document_id分类：updated=[L1]，added=[B,B用例]，retained=[A,A用例]，unchanged=[]。
合并后的G2候选含5份文档：L1(v2)、A、A用例、B、B用例。当前实现对这5份文档重新准备/成对编码，再构建完整Bundle/Chroma/BM25，经审计才激活。

IngestionReceipt示意字段：status=activated，active.revision=2，added_document_count=2，updated_document_count=1，unchanged_document_count=0，retained_document_count=2，encoding_report为本次实际编码报告。计数之和等于合并后文档数。

若完整目录仍提供A和A用例，它们会计为unchanged；本例故意不提供，计为retained。两者都会在新集合里。

## 谁负责哪一段

```text
IngestionPipeline.run(expected_revision, force)
  → DocumentManager._document_bundle：选择活动描述和已有资料包
  → MarkdownLoader.load_all：读取本次目录、生成真实SHA/路径身份
  → plan_ingestion：比较并合并文档，不做IO/模型调用
  → 当前文档/片段/编码输入限额检查
  ├─ 可复用：_activate_existing(旧bundle_id)
  │           → DocumentManager.activate：审计、revision检查，返回unchanged
  └─ 需重建：_audit_base(旧版参数) → _build_and_activate(合并集合)
              → prepare_knowledge_base → _inputs → BatchProcessor.process
              → BundleStore.save → VectorUpserter.build → BM25Indexer.build
              → _activate_existing(候选bundle_id)
  → IngestionReceipt
```

规划只描述事实；Pipeline选择动作；DocumentManager决定是否能提交活动指针。失败沿IngestionJobError返回阶段、错误码、已知报告/候选ID/激活状态。提交不确定与固定查询快照沿用Lesson28，不在本节另造恢复流程。

## 文档身份与变化判别

- document_id由knowledge_base_id与规范source_path共同计算；同知识库同路径改内容，ID保持不变。
- source_sha256由MarkdownLoader读取的文件字节计算；与资料包保存的同ID文档SHA比较。字节变化即updated，不用LLM判断业务是否变化；只改空白也可能变化。
- 不同路径即使字节相同也是不同文档，不是内容去重。同路径的新L1进入新活动集合，旧L1仍在旧工程版本里。
- 保留历史L2靠它作为独立路径继续存在于合并集合；工程快照保留靠旧Bundle/索引不被新版本原地覆盖。这两种历史不同，均不自动判定业务规则当前有效。

关键实现：`ingestion/file_integrity.py:49–59`。

```python
added = sorted(set(new) - set(old))
retained = sorted(set(old) - set(new))
merged = old | new
```

old/new是document_id→Document字典。集合运算比较字典键；共同ID再比较SHA，分为updated/unchanged。`old | new`是字典合并，相同键采用右边new的Document；普通写法是先复制old，再逐项赋值new。retained未被覆盖，所以保留旧包中的完整Document。sorted仅使计划顺序稳定，不代表相关性排序。

## 重复摄取的分支

复用活动产物需要：已有active、force=False、没有added/updated，且profiles_match通过。retained不阻止复用；合法空目录也不会清空已有知识库。

profiles_match核：分块设置、model_space_id、representation_id、tokenizer_id、Chroma collection与SDK版本、BM25 k1/b与SDK版本。不只是比较文件SHA。批大小等执行参数不直接改变这组语义身份；当前资源限额仍会重新检查。

| 条件 | 当前行为 |
|---|---|
| 文档与语义配置未变 | 校验输入、审计旧产物、核revision；不再编码/建索引，report=None |
| 只有本次未出现的retained | 可沿同一复用路径，不推断删除 |
| 新增、内容变化、相关配置变化 | 对合并集合全量准备与编码，构建完整候选 |
| force=True | 不走预编码复用，仍审计、构建与核revision |
| 文件读取/解码失败 | load阶段报错，不降为retained成功 |
| 当前限额更严格 | 即使内容未变也可能明确失败 |

“不再编码”不等于零成本：仍有扫描/hash、资料包核验、输入检查和索引审计。force要求重新执行，不保证描述摘要一定不同或revision必然增加，最终由实际候选绑定与activate决定。

当前即使只改BM25参数，正式run变化路径也会走完整编码；独立BM25Indexer能消费已有包，不等于run已做该分支优化。文档级增量编码已记录future-work，尚未实施；本节不展开片段级diff。

## 显式移除的输入、分支与副作用

```text
remove_document(document_id, expected_revision)
  → _document_bundle：从已保存快照选文档，不扫描源目录
  → 没有活动版本：not_found，active=None
  → profiles_match：移除不兼任配置迁移
  → project_detail：查目标；从base.documents过滤该ID
  ├─ 不存在：检查当前限额、审计并复用原活动版本，not_found/report=None
  └─ 存在：审计旧版 → _build_and_activate(其余文档)
             → RemovalReceipt(removed, previous_active, active, removed_document, report)
```

例如从3份文档G1移除L2_A，G2只有L1和A测试用例。新Bundle/Chroma/BM25不含A对应文档/片段/编码；关系重建后无指向已移除节点的有效边，但可留下missing_pair/target_not_loaded诊断。不自动级联移除A用例，也不改写其他原文引用。

源Markdown不删除，旧G1三类产物保留，旧版本已有ID消费者仍可回读。此处“移除”是活动知识库成员变化，不是彻底擦除。删除最后一份文档会发布合法空版本，report.status=empty、请求数0，不退回尚未初始化状态。

源文件还在目录：以后主动run会相对当前活动包把A判断为added，再纳入。没有后台自动恢复，也没有持续忽略标记；这是Spec0034中用户已确认的策略。

更新/移除构建失败：不激活不完整候选；在没有其他写者提交的情况下旧active保持。并发冲突、提交不确定、已消费用量参照Lesson28/24，异常不能统一解释为零调用或已回滚。

## Debug Test：本节建议先走更新分支

VS Code Test Explorer选择下面精确测试的Debug Test。F10逐步、F11进入、Shift+F11返回；先F5到生产函数边界也可以。不要在WATCH重新调用run/remove/build/encode。

### 1. 更新与合并

入口：`tests/test_ingestion_pipeline.py::test_update_merges_history_and_replaces_current_l1`，无参数ID。
测试第51行建G1，第52–55行修改临时源材料，第56行调用第二次run。先在第56行停，再启用`file_integrity.py:49`断点，避免先走首次建库。

在plan_ingestion栈帧执行到第59行，观察：

```python
sorted(d.metadata['source_path'] for d in old.values())
sorted(d.metadata['source_path'] for d in new.values())
[len(added), len(updated), len(unchanged), len(retained)]
```

预期3、3份文件，分类计数[2,1,0,2]；各变量在第49–54行执行后才产生。回run栈帧，在第128行执行后观察`len(documents)`=5、`plan.reuse_active`=False；F11到第95行共享构建函数，看输入仍是5份。`chunks`到第98–99行完成后产生，`result`到第101行完成后产生；不要求先展开整棵编码对象。

返回测试第57行后second已赋值，观察`second.active.revision`=2及四计数；第65行断言paired_input_count等于全部新包片段数，证明当前不是只编码新B。

### 2. 重复复用

入口：`tests/test_ingestion_pipeline.py::test_first_ingestion_and_repeat_skip_encoding_and_builds`，无参数ID。测试第45行第二次run；Pipeline第138行观察reuse_active=True，第141行返回后看again.status/encoding_report。
测试将BatchProcessor.process、Bundle.save、两个build换成forbidden；误调用即pytest.fail。manager._audit仅包一层记录，仍调用真实审计逻辑。断言没有新Dense调用，且确实审计旧包。

### 3. 移除与保留关联用例

入口：`tests/test_document_removal.py::test_remove_one_document_preserves_sources_and_old_indexes[L2_A.md]`，精确参数ID=L2_A.md。测试第25行→Pipeline第145行；执行到第159行时documents已产生，观察只含L1/A用例；info含被移除A的信息。第168行进入共享构建；返回测试第26行后receipt已赋值，观察status=removed、previous_active.revision=1、active.revision=2。

在测试第36行观察诊断类别，`current`在第30行赋值后才存在。第39–46行核临时原文未变、旧版本仍能回读。它不删除真实资料。

上述setup_job以FakeClient替换Chroma客户端，Dense/Sparse为测试替身；文件、Bundle、BM25和SQLite使用临时实际存储。不要将这些测试当作真实Embedding或原生Chroma接线证明。下列两个wiring测试补充真实SDK边界，Embedding仍为MockTransport，真实网络连接禁止。

异常调试入口：`tests/test_ingestion_pipeline.py::test_read_error_is_not_retention_and_configuration_cannot_change_in_place`。第208行写入临时非法UTF-8字节b'\xff'，第209行调用run；Loader读取时出错，由run的load分支通过_fail抛IngestionJobError，pytest.raises捕获；测试通过正是因为观察到预期错误，旧指针仍保持。它后半段另核组件配置不能被原地替换。

## 本次实际验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_ingestion_pipeline.py::test_first_ingestion_and_repeat_skip_encoding_and_builds \
  tests/test_ingestion_pipeline.py::test_update_merges_history_and_replaces_current_l1 \
  tests/test_ingestion_pipeline.py::test_empty_input_retains_saved_sources \
  tests/test_ingestion_pipeline.py::test_force_rebuild_and_execution_only_change_reuse \
  tests/test_ingestion_pipeline.py::test_read_error_is_not_retention_and_configuration_cannot_change_in_place \
  'tests/test_ingestion_pipeline.py::test_profile_change_executes_full_pipeline_with_pinned_old_audit[bm25]' \
  'tests/test_document_removal.py::test_remove_one_document_preserves_sources_and_old_indexes[L2_A.md]' \
  tests/test_document_removal.py::test_removed_source_is_added_by_next_explicit_ingestion \
  tests/test_document_removal.py::test_removal_never_loads_live_sources \
  tests/test_document_removal.py::test_missing_is_noop_without_encoding_or_new_artifacts \
  tests/test_document_removal.py::test_last_document_becomes_active_empty_library \
  tests/test_document_removal.py::test_repeat_removal_and_stale_revision \
  'tests/test_ingestion_pipeline_wiring.py::test_public_pipeline_restart_reuse_and_existing_chunk_consumer[normal]' \
  'tests/test_document_removal_wiring.py::test_native_removal_preserves_old_version_and_existing_consumer[normal]'
# 16 passed in 19.60s
```

两个normal原生测试在隔离子进程中走真实Markdown/成对编码SDK、Bundle、Chroma、BM25、SQLite与既有ID消费者；HTTP用MockTransport模拟，model_requests=0，连接尝试即失败。更新测试重开后核历史保留，移除测试分别消费新版本并重开旧版本。临时合成.env/源文件只在tmp_path，不改本项目真实.env或原索引。

L1入口/规划/回执均已存在；L2实质执行身份比较、集合合并/排除及整套构建；L3由上述16项测试覆盖复用/更新/移除/再纳入和原生持久消费者。本轮只改学习记录，构建不适用，不跑全量，不调用真实模型；文档diff检查退出0。真实材料质量、大库性能、文档级增量编码与历史GC未在本节验证或实现。

## 学习证据与唯一下一步

4.5已讲解，助手完成源码核验及16项定向验证；用户理解待反馈，本人独立调试/复写未评估。第1–4章讲解覆盖21/34节，还剩2章13节：第5章8节，第6章5节。

唯一下一步：5.1查询处理、范围与top_k，从一条QueryRequest进入QueryPipeline，先讲候选范围与数量合同，再展开后续两路检索算法。
