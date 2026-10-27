# Spec0049：优化分片6／正式摄取文档级增量编码

日期：2026-10-26。状态：已实现/接线/本地验收，本片完整回归2227项通过；移除路径复用和最终闭环见0050。

## 1. 目标、输入与范围

IngestionPipeline.run(expected_revision=...,force=...)签名保持。复用未变化且处理身份相同的文档片段/两路编码，只对新增/修改/身份失效文档整份重新准备编码。旧目录的增补语义、历史保留及固定revision合同保持。

不做片段差分、跨文档缓存、向量索引原地更新、BM25局部权重修补、异步并发、断点恢复、自动重试、GC或旧版本删除。模型/分词器/存储后端沿现有实现，无新依赖/真实配置修改。

## 2. 正常数据流

```text
固定active/base → 校验并审计基线 → load incoming → plan_ingestion
  ├─ reuse_active：原有审计及revision门禁，无编码/新版本
  └─ 新版本：encode_document_ids / reuse_document_ids
       → 变化文档prepare_document及prepare_document_encoding_inputs
       → 有编码输入才调用一次BatchProcessor.process（内部仍按原规则分批）
       → 复用文档复制来源绑定正确的chunks与StoredEncodedRecord
       → 完整文档集重新解析relations
       → 合并chunks/diagnostics/EncodingSnapshot及本次summary
       → IndexBundleV2.save → 完整Chroma.build → 完整BM25.build
       → 全候选审计 → expected_revision原子切换 → 新回执
```

变化文档的旧片段全部排除；不能只追加新片段。所有chunks/records使用确定顺序，完整来源/布局/hash匹配。新增文档可能使旧链接从missing变为resolved，关系必须基于完整文档集合重建；文档级诊断按当前完整快照核验，不直接拼旧全库诊断。

活动版本是整个作业的唯一基线，构建期间其他写者切换版本不改变本次来源。激活冲突不覆盖胜者；报告仍属于本次实际执行。

## 3. 复用和预算边界

复用来源必须是已审计base里的当前文档版本及正确处理身份。零片段文档也属于完整文档集合，不因没有编码记录而丢文档。编码身份失效/force对全部文档重算；只有索引策略变化时可以零新编码但生成完整新版本。

源文档/快照max_documents、max_chunks、文件/总字节限制对完整新集合校验；每项模型输入字节限制仍校验完整实际输入，防止复用绕过当前保护。max_inputs/max_requests/编码deadline仅约束本次需要提交的编码任务，不用历史输入数量伪造本次请求计划；完全复用且无新版本路径保留既有预检语义。

Bundle存取会全量读取及重新核验M2/输入，关系也全量计算；本片不保证准备/核验耗时仅与变化量相关。明确收益指标是本次实际Dense调用、编码输入数量和服务观察用量，不能以Mock耗时承诺生产加速。

## 4. 异常与结果

变化文档预检/准备/编码任一步失败整次停止，无部分成功快照。Dense成功后Sparse失败保留实际用量。保存/Chroma/BM25失败不切活动指针；已产生候选保留供检查，不自动清理。

激活提交不确定仍为unknown，调用方重新读取open_active确认，不宣称自动回滚。最终回执失败保留已知激活状态及本次summary/report。日志只固定stage/code/hash/数量，不写原文、词项、向量或凭证。

## 5. 影响文件与验收

ingestion/pipeline.py（沿现有边界必要拆分且每源文件≤500行）、knowledge_preparation.py、file_integrity.py、core/ingestion_types.py；扩展tests/test_ingestion_pipeline.py、test_ingestion_pipeline_wiring.py，新增tests/test_incremental_ingestion.py。若共享构建路径影响remove，先保持其旧执行语义并在0050适配，禁止半接线破坏已有测试。

先失败测试：A/B/C基线→修改B新增D；精确断言仅B/D触发准备的生产入口及模型编码，A/C成对数据保持，当前records不含B旧片段，旧版本仍可回读。覆盖首次、重复、历史保留、空/全空词项、编码身份失效、索引变化、runtime、force与限额。

原生新进程审计完整新双索引；BM25必须按最终完整片段集计算DF/avgdl，不能把变化子集索引与旧矩阵拼接。本片使用真实本地Chroma/BM25/分词器及Embedding SDK MockTransport，真实模型请求0。

计划命令：

```sh
.venv/bin/python -m pytest -q tests/test_incremental_ingestion.py tests/test_ingestion_pipeline.py tests/test_ingestion_pipeline_wiring.py tests/test_file_integrity.py tests/test_ingestion_types.py tests/test_document_removal.py --tb=short
.venv/bin/python -m pytest -q tests --tb=short
.venv/bin/python -m compileall -q naiyue_rag experiments tests
.venv/bin/python -m pip check
git diff --check
```

L1增量生产路径存在；L2实际分区/合并/本次账务；L3run→V2→双索引→激活→新进程查询消费者。构建不适用，功能回退可用原force全量路径验证，但不因异常自动回退或重跑模型。完成后讲解0050的移除适配及增量/全量同最终集合对照。

## 2026-10-26实施记录

新增test_incremental_ingestion.py：7 failed in3.32s预期红灯，最小实现后7 passed in4.55s。run实际按规划只准备/编码变化文档，ingestion/encoding_reuse.py复制已审计来源和成对数据，完整新V2资料包及双索引沿原激活边界提交。索引参数变化和新增空文档可零编码生成新版本，本次报告为None且summary明确0编码；force/语义身份变化全量重算。

已有“本次报告等于全库片段数”的旧断言按已确认D3更新为encoded+reused=完整快照，保留来源/旧版/错误/用量断言；原生Dense/Sparse/摄取/移除测试消费者改用同一bundle_encoding读取真实新旧类型，未改conftest或放松数值校验。相关171 passed in74.01s，原生Dense/Sparse/CLI另外17 passed in53.38s。语法/依赖/diff检查退出0，第6片完整回归2227 passed in483.45s（0:08:03）。

本片验收时移除仍对保留集全量编码，已同步新V2回执和空库零输入合同；后续0050已改为复用。Bundle仍全量核验M2/输入与关系，不宣称全部CPU处理只与变化量相关。

## 提交前复核：零编码路径的作业限额

用户授权提交/push后的架构复核发现：受限增量成功后，重复摄取及未命中移除仍把完整快照交给批次规划，错误消耗本次max_inputs/max_requests。新增两项回归先复现2 failed in1.36s；沿原_inputs增加私有job_limits开关，仅两条零编码路径传False。文档数量/字节、片段总量、来源、模型表示和单项输入字节校验仍执行；没有新编码或新资料包。

原test_reuse_still_applies_new_input_limits混用了作业数量与快照安全限制，现改为两条零编码路径×两种单项字节限额的四项负向回归，保留原错误stage/code和旧活动版本不变断言；新正向测试严格核对unchanged/not_found、零调用、不保存资料包及revision不变。相关摄取、移除、规划、V2回归131 passed in36.68s，架构复审通过。最终全量及提交记录见0050与Git历史。
