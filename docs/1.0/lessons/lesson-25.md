# Lesson 25：阶段B·4.1 原文、资料包与索引的区别

日期：2026-10-23，第4章共5节，本节第1节。目标：从EncodingResult进入IndexBundle/BundleStore，区分来源Markdown、规范资料快照、Chroma与BM25派生索引及活动版本指针。本节不展开原生索引算法或激活事务。

## 第4章地图

4.1原文/资料包/索引；4.2 Chroma向量存储与相似度索引；4.3 BM25构建与重载；4.4三类产物同版本激活与查询固定快照；4.5重复摄取、更新、移除与历史保留。第1–3章16节已讲解，本节后总计17节讲解覆盖，当前地图余17节，不代表用户掌握。

## 四类对象与三类持久数据产物

| 对象 | 保存/负责什么 | 实际消费者 |
|---|---|---|
| 来源Markdown | 用户维护的需求、方案、用例，后续可变 | MarkdownLoader摄取 |
| 版本资料包Bundle | 已读取的完整Document快照、原文Chunk/上下文/来源位置、关系、完整成对编码、配置与诊断 | 索引构建器、KnowledgeReader、查询来源核验 |
| Chroma向量索引 | 片段ID、向量、检索文本、平面过滤元数据及原生索引 | DenseRetriever经ChromaStore召回 |
| BM25索引 | 按已保存词项构建的词表/权重与片段行映射等持久数据 | SparseRetriever经BM25Store召回 |

“三类持久产物”指Bundle/Chroma/BM25，来源Markdown在摄取目录；另有元目录/活动指针协调版本，不把它当正文或第四路检索。Chroma不是只保存向量，但不能用它的平面载荷代替Bundle完整嵌套来源合同。IndexBundle虽含Index字样，实际是完整建索引资料，不是ANN或BM25搜索结构。

示例：TC-01原文行、表头/测试维度、实际SourceSpan、旧需求链接分别保留；Dense向量找相似，Sparse词项找字面线索，最终仍要能回到保存原文。来源快照表示当时读到什么，不证明历史规则仍现行。

## 实际数据流

```text
MarkdownLoader → prepare_knowledge_base → EncodingInput → BatchProcessor
    ↓ Documents/Chunks/Relations/EncodingResult
prepare_index_bundle → IndexBundle（内存）
    ↓ BundleStore.save
版本资料包（磁盘）
    ├ VectorUpserter/ChromaStore从同包Dense记录建向量索引
    └ BM25Indexer/BM25Store从同包Sparse.tokens建关键词索引
三者核验 → 激活版本（4.4展开）
查询固定版本 → 两路召回与同版本正文/关系回取
```

真实上层入口ingestion/pipeline.py::_build_and_activate：prepare→encode→bundle→vector→bm25→activate，顺序执行；两个索引的数据来源都是同一Bundle，不是让BM25消费Chroma修改后的ID。

KnowledgeReader._bundle消费PreparedQuery.active.version.bundle_id，从BundleStore取保存资料，并核文档/片段数、source_fingerprint、编码身份与范围；不读取当前摄取目录、重选latest或调用模型。这里复用第2章已学的来源/关系，只展开持久化职责。

## 内存输入和输出

prepare_index_bundle接documents、chunks、relations、encoding_result与显式KB/编码/切分配置，返回IndexBundle。prepare函数重新生成准备诊断，IndexBundle.__post_init__重核：

1. 文档ID与KB/逻辑路径对应，Document版本及字段合法。
2. EncodingResult的模型/表示身份与维度符合配置。
3. 从保存的Documents按配置重新运行M2，核Chunk全文、上下文、位置、关系和诊断。
4. 重建EncodingInput，与records中的输入逐项一致；已有结果合同核Sparse ID/hash/统计、向量形状、分词身份与批次范围。

重新解析/切分/准备输入是本地确定性处理，不是重新请求Embedding，也不重新运行Sparse分词编码。校验保证这些对象按当前规则彼此对应，不证明模型向量语义正确或需求内容真实。

IndexBundle是对象；BundleStore.save负责文件IO，返回回执（bundle_id、status、计数等）；BundleStore.load(bundle_id)返回IndexBundle。保存回执不是检索结果，也不是活动索引版本。

## 实际磁盘结构

```text
<storage_root>/<knowledge_base_id的SHA256>/
  artifacts/<bundle_id>/
    documents.json
    chunks.json
    relations.json
    encoding.json
    manifest.json
  vectors/<vector_index_id>/...  # 4.2展开
  bm25/<bm25_index_id>/...       # 4.3展开
```

路径由StorageSettings/ID计算，本节不新增配置。Bundle仅上述5文件：

- documents.json：完整Document文本与元数据，保存摄取时的原文快照，不是在原目录另复制一套.md文件名。
- chunks.json：原文片段、上下文、来源位置、视图/业务字段等。
- relations.json：显式引用、名称配对和相关诊断结构。
- encoding.json：encoding_settings、ingestion_settings、encoding_result、preparation_diagnostics；其中已有Dense向量和Sparse记录。
- manifest.json：包ID/格式/计数/编码身份/源集合指纹，以及前4个文件的字节数与SHA256。清单status=ready表示资料包就绪，不代表双索引已建或已激活。

bundle_id基于规范清单摘要，覆盖各文件内容hash；包含编码报告等内容，不能把相同Markdown字节直接等同为必然相同bundle_id。本节重复保存同一个完整bundle得到同ID，不是声称重新执行编码也必然复用。重复摄取决策留4.5。

保留向量/词项在Bundle内，同时在检索索引保存派生产物，会增加磁盘和核验成本；换取完整来源、统一建索引依据和可独立重载。当前尚无大库容量/延迟结论，不用小样本测试宣称生产性能。

## 保存、重载与失败分支

保存：_materialize重核Bundle并生成4份规范JSON，逐文件与整包大小检查→构造清单/ID→若同ID存在则load核验，正确时unchanged且不写→否则写.pending临时目录、同步、rename为目标、同步父目录后回ready。

这只描述本地资料包发布，不是跨Chroma/BM25的事务。原目标存在但损坏时拒绝覆盖；异常不自动修复。发布后的IO不确定有单独错误，不在本节展开完整恢复。

重载：先检查目标目录/文件集合→读取清单→核每个文件字节数与hash、严格JSON及规模→IndexBundle.from_dict再次核对象关系→重算清单与保存身份一致才返回。重算依赖当前可用处理实现，有校验CPU开销，不宣称只是一次轻量JSON读取。

| 情况 | 结果 |
|---|---|
| 合法资料包首次保存 | ready回执，随后可按ID重载 |
| 同一完整包重复保存 | unchanged、不写原文件或新增pending |
| 空知识库 | 仍保留明确KB、0文档/0Chunk/0编码 |
| 一份空白Markdown | 1文档、0Chunk/0编码，与无文档不同 |
| 缺文件 | bundle_incomplete，不当空库 |
| 文件hash/大小或内容关系不符 | 明确完整性/来源错误，不返回半包 |
| 超限或IO失败 | 明确StorageError，不能伪造ready |

来源Markdown保存后发生变化，不自动改变已保存快照，必须显式摄取并构建新版本后才改变查询使用资料。当前包是工程读取依据，不是全局业务真理；过期/历史规则仍需按内容判断。

## 本机探针结果

在解析后的临时目录复用既有ingredients/make_bundle测试助手：真实Loader/M2/BatchProcessor，Dense/Sparse为合成替身，不是模型质量验证。实际保存3份Document、8个Chunk、8对编码，目录文件为上述5项。修改临时source/L1_Module.md后load：

```text
reload_equals_saved=True
saved_document_unchanged=True
second_save_status=unchanged
same_bundle_id=True
```

只写测试临时来源/资料包，不修改真实知识库、运行配置或索引。BundleStore本身没有构建原生Chroma/BM25或加载模型。

## Debug Test入口

正常：`tests/test_storage_bundle_wiring.py::test_actual_sdk_sparse_and_new_process_reload`，无参数。Test Explorer→Debug Test，在第37行调用save处断点，F11入BundleStore.save；可F5到_materialize完成后观察header的document_count/chunk_count、list(encoded)与target，不展开完整向量。

选择save帧，在第160行写完后观察pending文件路径，第165行rename后看published；成功返回测试receipt，随后第41行进入load。load第205–208行看name/descriptor/len(raw)，第213行进入IndexBundle.from_dict，artifact_bundle.py第53行后看expected片段ID，核给定by_id与expected_by_id。不要在WATCH重新save或load查看返回值。

该测试使用真实M1/M2、Dense/Provider/SDK与Sparse，HTTPTransport在第31行替换为MockTransport，人工向量及usage；save/load为真实本地文件IO。第55行改临时原文件，新子进程只收到storage配置/包ID，网络禁用，不加载OpenAI/Chroma SDK；返回的资料快照hash与父进程原保存内容一致。证明跨进程重载，不是原生索引测试。

损坏：`tests/test_storage_bundle_wiring.py::test_corruption_is_not_repaired[hash]`，精确参数ID=hash；第101行把chunks.json改为[]而清单未改。load第207–208行检测字节/hash不符，抛StorageError，被pytest.raises捕获；再次save也拒绝覆盖坏包，测试验证文件保持损坏时的字节、不自动“修好”。另missing参数删除的是测试临时chunks文件，load报不完整。

## 本次实际验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_storage_bundle.py::test_lossless_bundle_identity_context_and_roundtrip \
  tests/test_storage_bundle.py::test_empty_bundle_retains_explicit_kb_and_no_fake_records \
  'tests/test_storage_bundle.py::test_mutated_bundle_rejected_without_payload[chunk-view]' \
  tests/test_storage_bundle_wiring.py::test_actual_sdk_sparse_and_new_process_reload \
  tests/test_storage_bundle_wiring.py::test_repeat_does_not_write_or_add_pending \
  tests/test_storage_bundle_wiring.py::test_empty_storage \
  'tests/test_storage_bundle_wiring.py::test_corruption_is_not_repaired[hash]' \
  'tests/test_storage_bundle_wiring.py::test_corruption_is_not_repaired[missing]'
# 10 passed in 1.63s
```

L1已有IndexBundle/BundleStore，L2真实来源重核/规范JSON/清单/发布与读取，L3本次测试含SDK模拟编码→真实保存→新进程独立回读，及源码核对两索引/Reader消费者。不宣称原生双索引本轮已测、真实模型或业务质量通过。无源码/依赖/真实.env/运行配置/原索引修改；构建不适用，不跑全量；git diff --check退出0。

## 学习证据与唯一下一步

4.1已讲解，助手完成临时文件IO探针与10项定向验证；用户理解待反馈，本人独立调试/实现未评估。下一节4.2：Chroma向量存储与相似度索引，沿Bundle中的一条向量进入原生collection、存储ID与回读核验，再解释索引怎样帮助找近邻。
