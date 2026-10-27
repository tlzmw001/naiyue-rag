# Spec0047：优化分片4／文档级编码复用计划与失效规则

日期：2026-10-26。状态：已实现/接线/本地验收，本片完整回归2196项通过；实际增量执行见后续0049。

## 1. 当前路径与本片边界

run先选择固定活动包→加载输入目录→plan_ingestion按document_id/source_sha256分类并合并历史→完全未变时reuse_active，否则全库准备/编码。当前profiles_match把编码相关条件与Chroma/BM25索引条件共同判断。

本片扩展既有file_integrity规划，不另造第二套文件注册表。输出文档级复用决策，生产run消费并检查集合完整性；编码优化在0049启用。本片不得把规划已接线写成已节省编码。

## 2. 规划输出与规则

保留merged_documents、added_ids、updated_ids、unchanged_ids、retained_ids、reuse_active；私有计划追加encode_document_ids、reuse_document_ids、encoding_profile_matches及index_profile_matches。两执行集合有序、不交叠、并集等于完整新文档集合；文档变化分类与执行分类分开。

document_id仍由知识库+源路径决定。相同内容不同路径是不同文档，不进行跨文档缓存。源文件不存在于本次输入仍按现有语义保留，只有显式移除才排除。

| 场景 | 编码与版本行为 |
|---|---|
| 首次 | 所有文档整份准备/编码；构建完整版本 |
| 完全未变且全部身份相同 | 沿既有reuse_active，不编码/构建，仍审计及revision门禁 |
| 新增/源字节变化 | 对应文档整份重算；未变化/历史保留文档可复用 |
| chunking policy/size/overlap、结构准备规则、文档表示、模型空间/维度或tokenizer变化 | 所有文档失效，整份重算 |
| 仅Chroma集合或BM25 k1/b等索引策略变化 | 复用编码，完整重建两路新索引；不把索引变化当必须重新调用模型 |
| 仅执行批大小/超时/预算变化 | 不改变语义身份；当前限额仍须校验，不绕过现有预算门禁 |
| force=True | 保持既有语义：全库重新准备/编码及构建，非“只强制建索引” |

沿当前model_space_id/representation_id做保守失效；例如query_prefix目前属于统一representation_id，变化仍失效，不顺便拆分文档/查询身份。M2规则必须有可核验策略身份；规则版本不明确时拒绝复用或全量重算，不能猜可复用。

处理身份取实际Chunker profile的规范摘要，加现有ChunkRefiner规则标识markdown-retrieval-view-v1（沿实际POLICY_ID，不另造重复版本标签）和document_text_mode/text_layout/document_prefix等既有表示身份。现有旧包仅在完整M2重核通过后识别为当前规则v1；后续规则行为变化必须升级版本。本片不增加LLM摘要/标签或把诊断文本当编码身份。

## 3. 校验、错误与接口

公开run/prepare/query签名保持；plan_ingestion的既有参数保持。规划只依据已严格验证的活动包及当前配置，不在纯规划中做网络/写索引。损坏基线在复用前失败，force不绕过损坏。

同一文档只有一个源版本；新文档即使字节等于旧文档也整份重算。可复用文档的旧片段必须与当前所选文档来源及处理profile匹配，不能只检查旧向量维度。

本片run只消费规划分区用于完整性预检，暂仍沿原全量执行路径；0049在此基础上实际只编码encode集合。已有外部结果在本片保持。

## 4. 影响与验收

ingestion/file_integrity.py、ingestion/pipeline.py、tests/test_file_integrity.py、tests/test_ingestion_pipeline.py；身份如需集中解释沿0045现有机制扩展，不新增Provider/数据库/配置。

先写失败测试覆盖首次/重复/空输入保留、增改/路径变化/全空文档、策略/模型/表示/tokenizer变化、索引参数变化、runtime变化、force、未知库/重复/坏源。用源变化分类和执行分区分别断言，不把updated_ids当encode集合。

L1计划字段存在；L2纯规划实际计算正确；L3run读取规划并执行分区完整性检查。尚未启用增量编码，未出现模型调用节约证据。

计划命令：

```sh
.venv/bin/python -m pytest -q tests/test_file_integrity.py tests/test_ingestion_pipeline.py --tb=short
.venv/bin/python -m pytest -q tests --tb=short
.venv/bin/python -m compileall -q naiyue_rag experiments tests
.venv/bin/python -m pip check
git diff --check
```

构建不适用；无持久化格式变更或数据回退步骤。完成后讲解0048为什么需要区分完整编码快照与本次EncodingResult/Report，沿已确认D3改产物合同。

## 2026-10-26实施记录

新增test_document_reuse_plan.py：8 failed/1 passed in1.74s预期红灯；拆分编码/索引身份并在run核对完整互斥分区后，相关119 passed in24.14s。本片只接规划消费，编码仍全量，未提前宣称节约。沿既有ChunkRefiner.POLICY_ID验证准备身份，不添加重复注册表。第4片启动时所收集完整回归2196 passed in408.25s（0:06:48）；通过后开始第5片测试/实现。
