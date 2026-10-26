# M4存储与索引生命周期：参考源码和现有资产核验

核验日期：2026-10-14。此轮为源码调研、离线小探针和Spec设计；没有M4生产实现、依赖安装、模型POST、原有索引变更或删除。

## 1. 来源与证据等级

- URL：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER 。只读目录`/Users/zmw/MODULAR-RAG-MCP-SERVER`，分支main，commit `f658c5a4011c8b826707a65a3b11ce9301b0626f`，工作区干净。
- 本轮`git ls-remote ... refs/heads/main`返回同一commit。以下针对该快照，远端将来变化需重新核验。
- 已核README、DEV_SPEC、pyproject及本文所列源码；逐文件SHA和安装版本记录于`data/research/m4-storage-review/sources.json`。
- pyproject声明MIT、Python>=3.10、chromadb>=0.4.0/jieba>=0.42；未发现独立LICENSE/COPYING，未据此锁定参考实际运行版本。此轮没有把参考代码复制进生产包；只读执行独立BM25模块和抽取的ID方法用于局部探针，不运行setup/Skill/Pipeline/发布脚本。
- README/DEV_SPEC是项目自述；调用链是静态事实；reference-probe.json是本机合成局部执行；本项目37测试含SDK替身及真实本地Chroma，均不是远端生产或业务质量证据。

## 2. 参考真实写入与重复摄取链

以[固定commit源码根](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/tree/f658c5a4011c8b826707a65a3b11ce9301b0626f)为准：

```text
IngestionPipeline.__init__
  ├─ VectorUpserter → VectorStoreFactory → ChromaStore
  ├─ BM25Indexer（data/db/bm25/{collection}）
  ├─ FileIntegrity（SQLite）
  └─ ImageStorage

Pipeline.run(file)
  compute_sha256(file)
  → should_skip(file_hash)；成功hash可直接返回skipped，force绕过
  → PDF加载/切分/增强 → BatchProcessor → dense_vectors/sparse_stats
  → VectorUpserter.upsert(chunks,vectors)
      重新生成存储chunk_id → ChromaStore.upsert → collection.upsert
  → 把返回存储ID写进sparse_stats.chunk_id
  → BM25Indexer.add_documents(...,doc_id=document.id)
  → 注册图片 → mark_success(file_hash,path,collection)
  异常：mark_failed并返回失败；上述多存储之间未见共同提交或补偿回滚
```

具体入口：pipeline.py:166–186、229–245、435–453、523–550；vector_upserter.py:100–138、152–166；chroma_store.py:110–128、160–196；file_integrity.py:184–193、243–266。

Chroma采用PersistentClient；配置提供provider/persist_directory/collection_name，实参强制cosine；匿名遥测关闭，参考allow_reset=True。本项目已采用allow_reset=False，继续保持。参考collection构造没有显式embedding_function=None；本项目显式向量路线仍禁隐式Embedding。

参考VectorUpserter存储ID为`sha256(source_path)[:8] + index + sha256(chunk.text)[:8]`。同一片段重复upsert可覆盖同ID；正文改变会得到新ID。该run写入路径未调用旧ID集合差分删除，因此不能把upsert同ID幂等解释为修订后旧片段必然消失。

FileIntegrity主键仅file_hash；should_skip只查hash与success，不传collection/model/representation/tokenizer。因此同字节换路径、换集合或换模型后是否应重建，不能靠这条判断保证。这里描述字段与调用条件，不声称完整运行已经发生串库。

## 3. BM25与查询如何消费存储

参考bm25_indexer.py:100–185从TF、doc_length计算N/DF/IDF和倒排；311–362先尝试移除doc_id对应posting，再重建合并；364–430的匹配条件为`chunk_id.startswith(doc_id)`。JSON `_save`在518–547先临时文件后replace，只覆盖单个文件的替换，不是与Chroma共同事务。

参考IDF实现为`log((N-df+0.5)/(df+0.5))`（436–448），k1=1.5/b=0.75（71–76）。我们现有BM25S实验采用lucene及显式k1=1.5/b=0.75；分数语义不完全相同，不能声称参数相同即算法/分数逐值相同。正式路线继续沿用户已定BM25S，不再手写参考倒排算法。

查询链：SparseRetriever.retrieve（145–182）→load BM25→query得chunk_id和分数→vector_store.get_by_ids补正文/元数据→merge；DenseRetriever使用同集合。未来我们也必须保证两路ID共同指向同版本的规范片段。参考缺BM25文件时返回空列表，与本项目已定“不把存储故障当正常空结果”不同。

DEV_SPEC:272–282及551描述Dense/Sparse/正文原子写入同库；当前主链实际Chroma写dense与正文/metadata，BM25为另一个JSON文件。不能引用设计文字宣布跨存储原子性已实现。

## 4. 更新与删除的实际边界

PDF Loader（pdf_loader.py:99–114）的document.id是`doc_`+内容hash前16位；VectorUpserter存储chunk_id以路径hash前8位开头。Pipeline传前者给BM25.add_documents，清理逻辑按后者前缀判断，两者不匹配。

本机局部合成探针（不是完整PDF Pipeline）：

- 直接载入参考BM25Indexer（仅标准库）；抽取原VectorUpserter._generate_chunk_id方法在内存执行，没有在项目内复制第三方实现。
- 合成文档ID`doc_aaaaaaaaaaaaaaaa`，实际生成片段ID`90b612ed_0000_ca024752`，前缀匹配false。
- 同一条term_stats连续add_documents两次，num_docs实得1→2；remove_document('a'*64)实得false。
- 修改片段正文后实际生成不同ID`90b612ed_0000_a685da63`；探针不运行Chroma，不能据此报告Chroma里实际留有多少旧记录。
- 输出`data/research/m4-storage-review/reference-probe.json`，模型0。该探针说明这些参数组合下方法不保证去重/删除，不外推所有调用入口都失败。

DocumentManager.list/detail沿FileIntegrity成功记录取doc_hash，再查Chroma/image计数。delete_document:218–266依次按doc_hash删Chroma、按source_hash前缀删BM25、删图片、删integrity，收集errors后决定success；即使前面失败仍执行后续清理。它有部分失败结果，但没有跨库回滚。get/list若干辅助方法异常返回0/[]，不能当成已证明空库。本项目需保留故障与空结果的区别。

## 5. 本项目已有Chroma/BM25资产

| 资产 | 当前事实 | M4如何复用 |
|---|---|---|
| naiyue_rag/chroma_store.py | 原生PersistentClient、cosine、显式向量/禁默认Embedding、readonly reopen、身份/来源/向量回读校验、错误固定码；依赖experiments和legacy unit，要求旧embedding_identity/corpus_id/index_id/授权列表 | 保留底层调用/完整验证原则；正式适配消费M3 DTO，不从新主线导入旧实验/加入假unit转换 |
| experiments/chroma_probe/worker | 隔离无.env的工作目录、已缓存52向量写入/重复/另进程重载/范围和来源审计 | 做原生后端参考和回归，旧实验/产物保留；不将整段验收worker变成正式存储服务 |
| experiments/keyword_index.py | BM25S0.3.13，lucene/k1=1.5/b=.75；原生save/load、allow_pickle=False、映射/词项/hash/矩阵审计；旧Tokenizer与旧片段格式 | 正式BM25Indexer直接消费SparseRecord.tokens，保持输入配对/映射和矩阵检查；不重复分词，不复活旧单字策略 |
| a2_snapshot.py/bootstrap.py | 读冻结实验路径；scope下重建/缓存BM25，load_snapshot_from_settings未装配Chroma | 是实验对照入口，不能当成新M3→M4→M5已接通 |
| M1/M2/M3 | Document/Chunk原文、真实位置/上下文/显式关系；EncodingResult含Dense/Sparse及各自hash、三类身份和报告 | 直接作为正式存储输入，保留chunk.id，不重新改存储ID |

本轮实际：`.venv/bin/python -m pytest -q tests/test_chroma_store.py tests/test_chroma_probe.py --tb=short` → **37 passed in2.41s**。原生断言包括写入/重复/另进程重载均52条、max_vector_error<=1e-6、无reset/自动Embedding、query重开不创建/补写。没有重跑四题以外业务集或完整1266测试；1266是上一轮证据。

兼容事实：旧ChromaStore:89发现cwd/.env就拒绝原生SDK构造。已安装chromadb1.5.9的config.py:320配置env_file=.env，__init__.py:112导入时构造Settings；仅随后传Settings(_env_file=None)不能证明导入阶段没有读文件。当前项目已有.env，因此正式M4.2必须独立定好SDK初始化/凭证边界并做合成.env探针；本轮没有读取真实.env或删除该guard。

## 6. 建议与代价（设计推断，待确认）

沿参考职责保留VectorUpserter、Chroma适配、BM25Indexer、DocumentManager；沿已定A2使用Chroma+BM25S。增加同版本规范文档/片段/关系与编码包，避免将复杂SourceSpan/case_fields/list/dict压成不可逆字符串。

推荐先构建一个完整的新索引版本，再用单一活动版本指针切换：失败时现有版本继续可读；查询打开一次版本后，两路和原文都固定到它，不每个阶段重新读latest。不声称Chroma与BM25能共同事务提交。建议目录级版本隔离、SQLite元目录（后续片）记录版本/活动指针和精确doc→chunk映射；此为对参考SQLite历史记录的职责扩展，尚未实施/确认。

首期选择完整知识库重建派生索引，代价是额外磁盘/CPU/写放大；后续更新仅对变更片段重新编码、复用旧配对记录的优化单独验收。规模10倍时先测构建时间/空间，不能宣传局部upsert即高效增量。对照方案为原地修改并在失败后阻断整库查询，代码少但恢复路径和可用性差，暂不推荐。

历史L2_A和新L2_B是不同文档，新的活动版本仍保留二者；同路径L1改版只替换当前版本中该逻辑文档的片段。保留旧索引版本用于工程恢复，不等于自动证明历史功能现行有效。消失文件默认不推断用户删除，删除必须显式提出；自动清理旧版本/向量/真实文档不在本轮。

最小首片只持久化并重载可严格核验的M1/M2/M3完整资料包；后续Chroma、BM25、激活和文档管理逐片接入。具体首片合同见[Spec0028](../specs/0028-m4-artifact-storage-and-lifecycle.md)。
