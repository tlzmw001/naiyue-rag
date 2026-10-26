# Lesson 26：阶段B·4.2 Chroma向量存储与相似度索引

日期：2026-10-23，第4章共5节，本节第2节。目标：区分向量存储与ANN索引，沿Bundle→原生collection写入/重开/按ID回读，了解查询距离与来源核验。本节不修改参数或实现，不展开第5章的完整召回策略。

## 算法概念与来源

保存向量不等于已具备高效近邻搜索。全量扫描可对N条d维向量逐一计算距离，比较量随N×d增长；大库通常使用ANN索引减少需要探索的候选，但可能漏掉真正最近的点。ANN是数值近邻的近似，不代表业务相关性或答案正确。

[Chroma官方配置文档](https://docs.trychroma.com/docs/collections/configure)说明单机使用HNSW多层近邻图；[HNSW原论文](https://arxiv.org/abs/1603.09320)描述多层结构与从高层向下的搜索。课堂直观过程：上层较稀疏，先导航到接近区域，向下细化候选，在底层寻找较近向量；不是比较全部数据的数学精确保证。官方文档描述一般机制，本机实际版本/显式参数仍以源码与测试为准。

HNSW的节点是向量记录，边为几何邻近连接，不是L0/L1/L2需求引用或模块依赖知识图谱。提高搜索候选规模通常可换取召回、增加计算，具体收益要实测；当前不调参。项目只显式space=cosine，ChromaSettings只开放collection_name与应用层batch_size，其他原生有效配置由SDK返回并保存核验，未宣称已优化。应用写入/回读batch_size不同于Embedding批大小及HNSW搜索候选参数。

## 当前本机链路

实际安装chromadb=1.5.9，chroma_backend固定校验SDK版本。new_client使用PersistentClient与显式project_root，原生RustBindingsAPI；业务代码在当前进程调用本机SDK，不是HTTP部署服务。本轮测试在隔离子进程中执行用于隔离测试状态，不代表产品存储本身是worker服务。

```text
BundleStore.load(bundle_id)
 → ChromaStore._prepare：records→rows/identity/header/index_id
 → VectorUpserter.build
 → pending目录内PersistentClient/create_collection
 → 分批upsert显式向量/ID/正文/metadata
 → count + get逐记录审计
 → 关闭后重开审计
 → ready.json + 发布候选目录
 → 后续ChromaStore.audit/get_by_ids/query
```

上层IngestionPipeline在资料包保存后调用build，成功后才构建BM25并激活（4.4展开）。向量索引ready不等于知识库已经激活。

## 单条记录的字段映射

| Bundle中的值 | collection.upsert参数 | 含义 |
|---|---|---|
| record.input.item_id | ids | 沿用原片段ID，不生成第二套ID |
| record.dense_vector | embeddings | 已有Dense向量，不重新模型编码 |
| record.input.retrieval_text | documents | 可含标题/表头的检索文本，不冒充原始chunk.text |
| 来源/版本/两文本hash及chunk hash | metadatas | 核对来源及按document_id过滤 |

collection层metadata绑定bundle_id/KB/模型/表示/分词身份/维度。行metadata包括bundle_id、document_id、source_sha256、embedding_text_sha256、retrieval_text_sha256、chunk_sha256。一个版本的Bundle片段进入一个配置collection，不按L0/L1/L2各自强制拆collection；同名collection在不同index目录中仍是隔离产物。

创建与重开都显式embedding_function=None，configuration={'hnsw':{'space':'cosine'}}。Embedding由M3负责；这里发送embeddings，查询发送query_embeddings，不让Chroma隐式调用另一模型。空间/collection身份不符时拒绝，不静默使用默认距离。

float32预检确保向量在后端表示范围内仍有限/非零。回读使用np.allclose对每个坐标比较float32合同，rtol=1e-6/atol=1e-8，不要求JSON/Python浮点逐位相同，也不是只核余弦方向相同。

## 写入与持久产物

目录：<storage_root>/<KB摘要>/vectors/<index_id>/ready.json与chroma/原生文件。index_id由bundle_id、collection_name、SDK版本及explicit-cosine-v1策略等摘要得到；应用批大小不改变该逻辑身份。ready.json保存逻辑记录指纹、配置及发布时必要原生文件名；不把SDK内部文件的每个字节永久锁死，原生维护可能写文件。

VectorUpserter名字含upsert，当前build只构建完整新版本，不原地修改已发布索引。目标存在则完整审计后返回unchanged，不再upsert；损坏报错不覆盖。新目标：pending→创建集合→逐批写→核count/ID/向量/正文/metadata→关闭→重开核验→关闭→写ready→rename发布。全量审计有IO/CPU成本，当前没有大库容量/延迟证明。

## 按ID读取与按向量查询

get_by_ids(bundle_id,ids)用于已知ID的回读，不做相似度搜索。它先核原生集合内记录与Bundle对应，再返回Bundle中完整Chunk副本。缺记录/错向量/错正文时抛错，不能直接从Bundle补齐后假装索引正常。

query(bundle_id,query_vector,document_ids,top_k)按向量检索：核输入/范围→读取固定索引→collection.query(query_embeddings=[query_vector],n_results=limit,where={'document_id':{'$in':...}})→核返回ID/正文/metadata/向量→从Bundle取完整Chunk。where进入原生查询，限定候选范围，不是先全库top_k再删除范围外结果。

人工三维几何示意与本轮原生测试：查询q=[1,0,0]，同向[1,0,0]距离0，垂直[0,1,0]距离1，反向[-1,0,0]距离2。cosine distance=1-cos；项目score=max(0,1-distance/2)，因此这三例score=1、0.5、0。该分数是排序适配值，不是答案概率；算法细节见3.2与后续5.2，不重复完整推导。

原生query返回外层列表对应本次查询个数，当前一问所以取[0]；内部每条结果带ID/距离/正文/metadata，并非拿数组位置猜原文。最后按(distance,chunk.id)排序已有返回候选；近似搜索/并列边界不因此保证全库精确top_k或完全固定候选集。

## 正常、空态和失败

| 场景 | 当前行为 |
|---|---|
| 合法首次构建 | ready回执，不自动激活 |
| 完整同版本已存在 | 审计后unchanged、不写重复记录 |
| 空包/空白文档 | 建零记录collection，不发空upsert；维度仅由业务标记声明，不声称空集合已绑定原生维度 |
| 写入第2批失败 | 停止后续、关闭client，不发布ready；pending可能保留，不自动删除 |
| count/get发现缺记录或任一字段不符 | chroma_integrity_failed，不回填掩盖 |
| 无效ID/维度、零/NaN/bool或float32溢出 | 明确请求/完整性错误，不当空结果 |
| 缺ready/原生必要文件或配置身份不同 | 拒绝重开，不自动新建或修复 |
| client.close失败 | 明确失败；若已有主错误则记录关闭错误，不覆盖主错误 |

索引只读是业务层不修改记录；SDK重开可能维护内部文件，不承诺文件系统只读。访问本项目真实.env/配置修改权限未改变；测试只使用临时项目的合成配置，产品参数读取按先前已授权的显式project_root。

## Debug Test入口

正常：`tests/test_chroma_index.py::test_formal_roundtrip_repeat_and_isolation`，无参数。测试第79行writer.build断点，F11到build；在chroma_index.py:172–175看group及rows[group[0]]的text/metadata键和vector[:3]，避免展开全部对象。upsert后第176行看count，再进入_check_rows第112行看get原始返回；FakeClient故意反序get，_check_rows以uid取expected而不是按原请求位置配对。

执行到第179行离开with后client关闭，第180行重新audit，发布后回测试看receipt.status/index_id；第81行第二次build进入已有路径，upsert事件数不增；第85行get_by_ids返回got完整原文Chunk，和Chroma的retrieval_text不是同一字段。WATCH只看已有变量，不重复build/get。

此测试通过setup_index fixture将chroma_backend.new_client替换为FakeClient；Bundle/VectorUpserter/ChromaStore/审计与文件发布是真实业务实现，不能当原生SDK证明。

损坏：`tests/test_chroma_index.py::test_read_corruption_not_hidden_by_bundle[vector]`，精确ID=vector。第96行开启flags；FakeClient.get在第52行附近把回读向量第一坐标加1，_check_rows第121行allclose失败、第123行归一StorageError，pytest.raises捕获。另missing/text/metadata分支同理。写失败入口test_write_failure_stops_batches_and_no_ready第102行设置第2次upsert抛OSError；build通过call包装为chroma_write_failed，with关闭，测试确认没有ready文件。

原生入口：`tests/test_chroma_native.py::test_real_formal_encoding_store_and_new_process`，无参数。隔离测试进程中使用真实SDK1.5.9与本地持久目录；编码HTTP用MockTransport，Sparse真实，写入/重开是原生，另进程不同cwd仍按显式project_root读取同一索引与Bundle。生产函数断点默认不跨测试子进程，教学先用上述同进程业务测试；不自动修改IDE子进程调试设置。

几何/范围入口：`tests/test_dense_retrieval_wiring.py::test_native_cosine_geometry_and_scope_before_top_k`，无参数。人工向量替换Bundle编码，真实Chroma返回距离集合{0,1,2}/score集合{0,0.5,1}；排除最近记录所属文档后仍在范围内返回top1，说明过滤进入检索。没有真实Embedding或业务相关性评测。

## 本次实际验证与证据边界

```sh
.venv/bin/python -m pytest -q \
  tests/test_chroma_index.py::test_formal_roundtrip_repeat_and_isolation \
  tests/test_chroma_index.py::test_read_corruption_not_hidden_by_bundle \
  tests/test_chroma_index.py::test_write_failure_stops_batches_and_no_ready \
  tests/test_chroma_index.py::test_non_float32_vector_rejected_before_index_creation \
  tests/test_chroma_native.py::test_real_formal_encoding_store_and_new_process \
  tests/test_chroma_native.py::test_real_empty_index_and_reload \
  tests/test_dense_retrieval_wiring.py::test_native_cosine_geometry_and_scope_before_top_k
# 10 passed in 7.10s
```

本轮原生测试证明本机SDK写入/重开/回取与几何、范围，不证明大库速度或ANN召回率，也未跟踪原生内部每次是否走HNSW图或小数据其他路径；不拿配置存在替代索引性能验证。没有真实模型、源码/依赖/真实.env/运行配置/原索引修改；测试原生索引只在临时目录。

L1已有VectorUpserter/ChromaStore及backend/query，L2显式向量/原生配置/写入/审计实现，L3上述真实原生跨进程测试与摄取消费者源码核对。构建不适用，不跑全量；git diff --check退出0。

## 学习证据与唯一下一步

4.2已讲解，助手完成本机SDK核对、原始论文/官方说明阅读及10项定向验证；用户理解待反馈，本人独立调试/实现未评估。当前讲解覆盖18/34节，剩16节。下一节4.3：BM25索引的构建与重载，追Sparse记录如何变成持久词表、权重与片段行映射。
