# Lesson 31：阶段B·5.2 余弦相似度、距离与向量召回

日期：2026-10-23。第5章共8节，本节第2节。目标：手算余弦/距离/项目分数，并沿PreparedQuery→DenseRetriever→Chroma→完整Chunk理解正常与失败路径。仅学习现有实现，不新增阈值、归一化、索引或模型策略。

## 输入输出与职责

上一节已产生PreparedQuery：固定active版本、允许文档/片段ID、编码好的dense_vector与query_terms、编码报告。向量召回只消费其中Dense向量、版本和范围；不重新理解原始问题、不再次编码、不选择latest。

```python
result = DenseRetriever(manager).retrieve(prepared, top_k=3)
```

输出DenseResult包含prepared、top_k、hits和score_kind='chroma_cosine_affine_v1'。每个DenseHit是rank、完整Chunk、原生distance、项目score。Chunk包含id、source_ref、text和metadata；text为保存的原文正文，metadata保留真实定位/上下文等。Chroma中检索文本与原文正文可不同，不能直接把查询返回的检索文本当原文正文。

## 先手算二维向量

以下坐标纯教学构造，不代表真实Embedding语义坐标或用户材料结果。q=[1,0]，A=[2,0]，B=[1,1]，C=[0,1]，D=[-1,0]。

点积是逐坐标相乘后求和：q·B=1×1+0×1=1。
长度是平方和开根号：||q||=1、||B||=√2。
余弦cos(q,B)=(q·B)/(||q||×||B||)=1/√2≈0.707107。

| 候选 | 点积 | 余弦相似度 | cosine距离=1-cos | 项目score=max(0,1-distance/2) |
|---|---:|---:|---:|---:|
| A=[2,0] | 2 | 1 | 0 | 1 |
| B=[1,1] | 1 | 0.707107 | 0.292893 | 0.853553 |
| C=[0,1] | 0 | 0 | 1 | 0.5 |
| D=[-1,0] | -1 | -1 | 2 | 0 |

A长度2、q长度1，余弦仍1，体现主要比较方向。零向量长度0会使公式分母0，所以本项目拒绝零查询向量，不当成相似度0。

余弦理想区间[-1,1]、越大越接近；cosine距离理想区间[0,2]、越小越接近；同向/正交/反向分别0/1/2。负相似度只描述几何方向，不能直接判定文档在业务上与问题矛盾；正交也不能直接判定文档业务无关。

项目公式沿Spec0036已核参考刻度：理想情况下score=(1+cos)/2。它是单调变换，主要方便以高分表示更近，和直接按距离升序在该区间保持同样次序。score=0.5仅是cos=0的映射，不是答案正确概率50%。不把该分数与BM25原始分数直接相加；融合在5.5展开。

无需先假定模型返回单位向量才能理解余弦：公式本身除以双方长度。单位化后点积可等于余弦；未经单位化直接点积则不同。当前项目未手工把每条向量单位化，实际Chroma collection显式配置cosine，原生测试核距离语义。响应函数名称中的normalize不等于已经实施L2单位化，沿3.2结论。

原生浮点距离会有小偏差；源码只要求有限，不强制夹到[0,2]。score只做max(0,...)，未做min(1,...)，所以不能把理想[0,1]当程序强保证；接近0的负distance可能令score略大于1。本节按Spec保留该来源刻度，不修改实现。

## 实际调用链与数据转换

```text
HybridSearch._dense：把cfg.dense_top_k传入
  → DenseRetriever.retrieve(prepared, top_k)
      → 核PreparedQuery/参数/KB
      → BundleStore.load固定bundle_id
      → validate_prepared_scope：范围必须精确对应原包
      → 按选定版本的collection/k1/b审计三产物
      → ChromaStore.query(旧有向量, 文档范围, top_k)
          → storage.chroma_query.query_index
          → 输入维度/有限值/非零/float32可表示性校验
          → eligible与limit=min(top_k,片段数)
          → collection.query(query_embeddings, n_results, where, include)
          → 单查询嵌套列/ID/距离/正文/元数据校验
          → 按ID再get核存储向量/正文/元数据
          → 返回固定Bundle中的完整Chunk副本及distance/score
          → 对已返回候选按(distance, chunk.id)排序
      → enumerate(..., 1)生成DenseHit排名
      → DenseResult严格校验、有限序列化后返回
```

storage/chroma_backend.py显式embedding_function=None、hnsw.space='cosine'；查询传query_embeddings，因此不走Chroma默认Embedding函数。原文来源是固定Bundle，原始Markdown可不在现场；但先核实际索引记录再返回Chunk，不用Bundle中的存在掩盖索引损坏。

示意原生返回：ids=[[C_A,C_B]]，distances=[[0.1,0.3]]，documents=[[检索文本A,检索文本B]]，metadatas=[[元数据A,元数据B]]。外层对应查询个数；当前一次一问，外层长度必须1。内层四列按同一位置对应一条命中，用ID核原包记录，不能拿“第0条”猜文档身份。

校验完后取chunks[uid]，得到带原文和来源的完整Chunk。_check_rows还通过collection.get取得向量，对照保存记录的float32向量；不是只看ID或引用格式存在。查询过程中编码报告沿prepared传递；Dense失败也保留已知编码用量。

## 近似搜索与排序边界

沿4.2已学结论，collection配置HNSW近邻索引。大库近似查找可能漏掉精确最近项；本项目拿到候选后重排distance只能稳定已返回候选，不能恢复未被返回的片段。距离相同按chunk.id排序，仅保证返回集合内部的稳定顺序，不保证ANN截断边界所有等距候选固定。

这不是L0/L1/L2业务引用图，也不是跨文档推理。向量召回提供候选；跨文档覆盖、事实正确性、历史规则有效性仍须业务评测及上层查证。当前Dense路径按数量取候选，没有最低score阈值；存在候选不等于问题有答案。改阈值需实际失败证据，不在本节添加。

## 主要分支与失败

| 条件 | 当前结果 |
|---|---|
| prepared.ready且输入/索引合法 | 返回min(top_k,允许片段数)个完整命中；返回条数不足合同会报错 |
| 未激活 | 空DenseResult，不初始化原生SDK |
| 已激活但empty_scope/empty_index | 审计固定版本，返回空hits，不发向量相似度查询 |
| Sparse词项空但Dense有效 | Dense仍可正常检索，不等于空索引 |
| 维度不符、零/NaN/bool坐标、float32溢出 | SDK查询前明确拒绝 |
| 缺列/重复/越界ID、错正文/错元数据/错向量 | 整次报错，无部分hits交付 |
| 存储读/关闭失败或结果序列化超限 | 明确错误，保留已知active/编码报告；不伪装空结果 |

本节没有自动重试或单路降级。已有active查询仍审计BM25，沿三产物一致性合同，不等于Dense重新进行关键词召回或分词。审计有真实IO/成本；SDK内部维护不承诺文件字节绝对不变。

## Debug Test：看向量输入、原生返回与完整片段

### 正常召回

入口：`tests/test_dense_retrieval.py::test_ready_retrieval_uses_prepared_vector_once_and_never_reads_catalog`，无参数ID。Test Explorer点Debug Test。测试第93行已prepare，第94行将catalog.read替换为pytest.fail，第95行调用retrieve；F11进入query/dense_retriever.py:22，也可先F5到第34行跳过已学启动。

1. retrieve栈帧第34行执行后：看active.revision、len(prepared.encoding.dense_vector)、len(prepared.chunk_ids)、top_k。准备结果早已含向量，当前函数没有调用QueryEncoder。
2. 第38行F11到ChromaStore.query→query_index。到storage/chroma_query.py:36，看limit、query_vector[:3]、len(document_ids)；limit在第28行后产生，当前已有查询向量直接传下去。
3. 第36–37行调用完成、停在第38行，看raw['ids'][0]、raw['distances'][0]。raw在调用返回后才存在；此时尚未核验，不能把它当成功结果。
4. 第52行后，在query_index栈帧看uid、distance、result[-1]['score']和result[-1]['chunk'].metadata['source_path']；再走第54行_check_rows实质核验。F10到第55行返回前，所有候选才完成验证。
5. 回retrieve第41行，rows已产生；执行第41行后hits已产生。看hits[0].rank/distance/score、hits[0].chunk.text[:80]、hits[0].chunk.metadata['body_span']。不要在WATCH重新query/get/encode。
6. 回测试第96行，result已赋值，断言Dense/Sparse编码累计各1次（均来自prepare）、原生查询接口调用1次；catalog.read若被再次调用会让测试失败。

该测试用FakeClient和native_query fixture，后者只是名字，实际是替身计算余弦；真实Bundle/BM25/SQLite在临时目录，Dense/Sparse编码也是替身。不能当原生ANN证明。

### 错正文分支

入口：`tests/test_dense_retrieval.py::test_bad_native_result_fails_whole_query[text]`，参数ID=text。测试第85行设置fault，native_query fixture第39行把返回documents[0][0]改成PRIVATE；没有更改原包。query_index第49–51行比较失败，53行归一StorageError('chroma_integrity_failed')，pytest.raises在测试88行捕获。测试通过表示预期错误被观察到；不会返回先前已暂存的部分result。metadata/outside分支分别注入错元数据/范围外ID。

### 原生验证入口

`tests/test_dense_retrieval_wiring.py::test_native_cosine_geometry_and_scope_before_top_k`，无参数ID。子进程手工赋同向/反向/正交三维向量，真实Chroma持久化后查询，断言distance集合0/1/2、score集合1/0.5/0，并让全库最近项在scope外，scope内top1仍有合法结果。这是人为向量的几何工程验证，不是真实Embedding业务质量。子进程普通Debug Test默认不自动进入子进程，不修改IDE；先用上述同进程测试走读。

`test_native_dense_after_preparation_in_new_process[normal-False]`：真实保存/激活→SDK MockTransport查询编码→新进程Dense真实查询→完整Chunk核对；在消费者中禁止catalog.read和QueryEncoder.encode。另normal-True为空范围，all-empty-False验证Sparse词项空时Dense仍工作；没有真实模型请求。

## 本次实际验证

教学数学探针用.venv/bin/python标准math逐项打印，输出：

```text
A: dot=2.000000, cosine=1.000000, distance=0.000000, score=1.000000
B: dot=1.000000, cosine=0.707107, distance=0.292893, score=0.853553
C: dot=0.000000, cosine=0.000000, distance=1.000000, score=0.500000
D: dot=-1.000000, cosine=-1.000000, distance=2.000000, score=0.000000
q_norm= 1.0 A_norm= 2.0
```

确定性/原生接线命令：

```sh
.venv/bin/python -m pytest -q \
  tests/test_dense_retrieval.py::test_store_query_projects_scope_and_complete_chunks \
  tests/test_dense_retrieval.py::test_ready_retrieval_uses_prepared_vector_once_and_never_reads_catalog \
  tests/test_dense_retrieval.py::test_pinned_result_ignores_new_active_version \
  tests/test_dense_retrieval.py::test_explicit_empty_scope_returns_no_hits_and_still_audits \
  tests/test_dense_retrieval.py::test_invalid_store_input_does_not_query_sdk \
  'tests/test_dense_retrieval.py::test_bad_native_result_fails_whole_query[text]' \
  'tests/test_dense_retrieval.py::test_bad_native_result_fails_whole_query[metadata]' \
  'tests/test_dense_retrieval.py::test_bad_native_result_fails_whole_query[outside]' \
  tests/test_dense_retrieval_wiring.py::test_native_cosine_geometry_and_scope_before_top_k \
  'tests/test_dense_retrieval_wiring.py::test_native_dense_after_preparation_in_new_process[normal-False]' \
  'tests/test_dense_retrieval_wiring.py::test_native_dense_after_preparation_in_new_process[normal-True]' \
  'tests/test_dense_retrieval_wiring.py::test_native_dense_after_preparation_in_new_process[all-empty-False]'
# 22 passed in 16.09s
```

原生使用Chroma1.5.9/临时Bundle/BM25/SQLite，禁外部网络，源目录移开后新进程真实Dense检索，Embedding由MockTransport提供。没有真实模型/真实知识库质量/大库ANN召回性能验证。临时合成.env/配置不影响本项目真实.env或原索引；不新增测试/源码/依赖。

L1 DenseRetriever/ChromaStore.query/DenseResult已存在；L2有实际原生调用/范围/完整性审计；L3由22项验证正常、空、固定版本、坏返回与真实跨进程消费者。只改学习记录，构建不适用，不跑全量；git diff --check退出0。

## 学习证据与唯一下一步

5.2已讲解，助手完成数学探针/源码/原生接线验证；用户理解待反馈，本人独立调试/实现未评估。讲解覆盖23/34节，余11节（第5章6节、第6章5节）。唯一下一步：5.3 TF/DF/IDF、长度归一化与BM25，从三条短片段手算词频与稀有度，再追Sparse查询的实际得分。
