# Spec0036：M5.2 固定版本的 Chroma 向量召回

日期：2026-10-15。状态：已实现/接线/本地验收。用户授权沿既定路线推进到独立RAG核心完成，遇到实际决策再讨论。

## 1. 当前链与本片目标

M5.1 `QueryPipeline.prepare`已选择一次活动版本、确定文档/片段范围、审计两索引并生成成对问题编码。本片使该结果实际进入Chroma原生query，返回可定位完整Chunk和排序信息。后续Hybrid消费同一PreparedQuery，不重选active或重复编码。

真实场景：问题要求检索历史需求及其用例；即使全库最近的片段属于其他模块，本次范围内的候选仍应由Chroma在过滤后选取，而非先取全库top_k再过滤。

## 2. 参考与差异

参考 https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER ，本机`/Users/zmw/MODULAR-RAG-MCP-SERVER`，main / `f658c5a4011c8b826707a65a3b11ce9301b0626f`，2026-10-15只读核对。

源码链：`src/core/query_engine/dense_retriever.py::retrieve`→Embedding.embed([原问题])→`src/libs/vector_store/chroma_store.py::query`→原生collection.query(query_embeddings,n_results,where,include)→`1-distance/2`→RetrievalResult。参考转换中坏结果可跳过，原始异常和查询片段进入日志；这里沿既定整次失败和安全日志合同，不跳过或泄漏正文。未运行参考代码/测试或复制实现。

沿用cosine索引与参考分数刻度，显式命名`chroma_cosine_affine_v1`；保留原始距离，score= max(0,1-distance/2)，没有答案置信度含义。原生浮点距离不强行截断或重算，要求有限；浮点小偏差可能让score略超1，保留来源刻度。当前安装Chroma1.5.9，SDK/实际语义通过原生测试核验。

区别：编码已经由M3/M5.1完成；DenseRetriever只消费PreparedQuery。scope使用已核文档ID生成where `$in`，范围不从query文本解析。top_k是必填正整数参数，受StorageSettings.max_chunks限制；不新增未消费的全局配置/默认值。将来Hybrid配置在其Spec提供，不硬编码20。

## 3. 接口与修改范围

- `ChromaStore.query(bundle_id, query_vector, *, document_ids, top_k)`：新增方法，返回list[dict]，每项只有chunk（完整Chunk）、distance、score。复用_prepare/_marker/open_collection/_check_rows，不改变持久格式或旧接口。
- 内部实现若超过职责范围，在`storage/chroma_query.py`单独实现查询函数，ChromaStore委托；存储层不依赖PreparedQuery或Agent。
- `query/dense_retriever.py::DenseRetriever(document_manager).retrieve(prepared, *, top_k)`：核验实际Manager、PreparedQuery及KB；按active保存集合名创建ChromaStore，不读取catalog。严格验证范围集合与原包一致、索引身份与保存version一致；调用存储query，返回严格DenseResult。
- `core/dense_results.py`：DenseHit(rank,chunk,distance,score)，DenseResult(prepared,top_k,hits)。完整深拷贝/to_dict/from_dict，严格字段/唯一ID/排名/范围/score公式，排序按distance升序、ID次序；同距只保证已返回候选内部稳定，不承诺ANN截断外的全局tie顺序。没有独立候选工厂或通用基类。
- `core/errors.py`：扩展QueryJobError阶段dense及query_dense_failed；允许携带已知active/encoding_report。Dense失败在该边界记录固定日志，存储必要IO沿StorageError固定码。
- 根/query导出新增实际入口；新增存储合同、Retriever合同及原生跨进程测试，不改旧测试/conftest/依赖/配置/.env。

成功链：调用方M5.1准备→DenseRetriever验证→已存包/同版Chroma→原生范围过滤query→核对结果列/唯一ID/成员/正文/元数据和向量→完整Chunk→DenseResult。不存在模型请求、原始Markdown读取或active切换。

## 4. 正常与失败合同

1. top_k严格正整数≤max_chunks，拒绝bool、0、超限；向量严格list、维度匹配、有限非零、float32转换后仍有限非零。无效输入在SDK前拒绝。
2. document_ids是实际list，合法、无重复且属于当前包；空列表为空范围。允许零文档/零片段，返回[]。未激活PreparedQuery返回空DenseResult，不初始化SDK；已有版本空态仍核对选定包/索引，不用空范围隐藏损坏。
3. 非空候选时n_results=min(top_k,范围内片段数)，where={'document_id':{'$in': IDs}}，显式query_embeddings，不触发Chroma默认模型。include显式documents/metadatas/distances。
4. 结果必须为单query嵌套列、相同长度/预期条数、有限距离、唯一且在范围的ID；缺列、错文档、错正文、错元数据或原生失败整次报错。_check_rows再核验返回ID的实际原生向量与持久源，不把资料包正文冒充实际命中正确。
5. PreparedQuery范围ID必须精确等于已存包投影；prepared.active完整描述须与选定bundle和索引核验一致；不能相信可伪造的计数或合法ID格式。查询不读latest，激活变化不影响所选版本。
6. 异常无部分hits，QueryJobError保留已知active与本次encoding报告；控制中断BaseException原样传播，原close双失败政策保持。
7. 本片沿用PreparedQuery的准备trace；Dense组件记录固定事件与候选数，ANN内部实际比较次数未知，不填入旧TraceContext.compared_count。统一查询trace在Hybrid实际编排时接入，不能把范围大小声称为ANN实际比较数。
8. 成功结果按max_bundle_bytes有界序列化，结果超限明确query_result_limit，保留已知编码报告。索引只读指业务只读，SDK内部维护写沿原合同。

## 5. 验收与边界

- TDD先确认新方法/模块缺失的红灯；固定合成向量覆盖cosine距离0/1/2及参考分数1/0.5/0、范围前置（最近的全库项在范围外）、top_k与稳定排序、正常与空态。
- 故障注入覆盖列形状/重复/越界/非有限值/正文元数据与向量不一致、SDK和close失败；非法请求不进入SDK，安全日志无正文。
- 原生跨进程：现有IngestionPipeline实际构建/激活→现有QueryPipeline实际编码（SDK MockTransport）→另进程DenseRetriever/Chroma native query→原包完整Chunk对照；空/正常/混合/空词项分支，socket阻断、不再编码。
- 旧M3/M4/M5.1与全量测试回归；compileall、pip check、资产/依赖/格式检查。真实模型请求0，无真实.env读改、参考执行、旧产物删除或提交/push。
- 本片不承诺ANN大库精确召回或问答正确率。BM25范围统计、RRF、重排、证据预算和导航后续分片；已有A2质量结果保持，不把接口接通当业务质量通过。

## 6. 回退与下一步

新增只读方法/组件可撤回，旧入口/产物格式保持，无自动数据删除或回滚。若发现实际行为需偏离本Spec，先更新合同与原因。

下一步为M5.3 Sparse范围评分：M4.3已明确全库统计过滤与旧A2范围内重算不同；先用最小对照展示实际排序差异，再对需要的语义进行决策，不隐式改排序。

## 7. 实施与接线记录

新增`storage/chroma_query.py`承载原生查询/完整性检查，ChromaStore新增方法委托；新增DenseRetriever及严格DenseHit/DenseResult，根/query模块实际导出。QueryJobError增加dense阶段及安全通用码；原持久格式/配置/旧查询入口不变。本片日志仅固定阶段/错误码/候选计数，PreparedQuery原追踪和编码报告继续可用，不伪造ANN比较次数。

TDD记录：45项先因缺方法/导出预期失败（red-tests.txt，45 failed in6.71s）；首轮44 passed/1 failed in11.98s。该失败是测试故障样本改了IndexVersion却未同步trace.index_id，导致在PreparedQuery构造时被正确拒绝，尚未到达预期审计分支。补齐测试输入的关联字段后，仍断言伪造描述在真实审计时报catalog_identity_mismatch；没有放宽生产合同或失败断言。unit-tests.txt保留首次失败。

```zsh
.venv/bin/python -m pytest -q tests/test_dense_retrieval.py tests/test_dense_retrieval_wiring.py tests/test_query_processor.py tests/test_query_preparation.py --tb=short
# 149 passed in 48.22s
```

其中51项为本片新增（45合同/6原生），98项是M5.1原有检查。5种正式接线场景完成真实构建/激活→SDK MockTransport新问题编码→另进程Dense查询和完整Chunk对照，关闭编码与catalog读取并阻断socket。另一原生场景控制向量为同向/正交/反向，实测距离0/1/2与分数1/0.5/0；全库最近项在范围外时，scope内top1仍返回合法候选，证实过滤发生于top_k选择前。

真实模型请求0，合成.env位于测试临时目录；未读改本项目真实.env、升级依赖或删除旧代码/产物。源码存在、主方法实际调用和原生SDK结果分别核验，不能据此声明真实文档/大库召回或问答质量。

全量命令`.venv/bin/python -m pytest -q tests --tb=short`实际输出**1934 passed in263.99s（0:04:23）**，exit0。compileall、pip check与git diff --check通过；当前无独立打包构建命令。195项旧资产中仅根导出/错误/query导出/ChromaStore四源码变化，新增3源码/2测试；旧测试/配置/锁文件、137安装包版本保持，源码最大266行。原始日志与验收JSON在data/research/spec0036-evidence/。

## 8. 下一个实际决策：BM25统计范围

最小原生BM25S内存实验，参数沿已存k1=1.5、b=.75、lucene/float64。问题词项为“校准、开关”，指定范围有A=[校准,校准]和B=[开关]；范围外另20片均为[校准]。

| 统计语义 | A分数 | B分数 | 范围内排名 |
|---|---:|---:|---|
| 旧A2：只在范围内统计 | 0.3577533835 | 0.3261869085 | A、B |
| 全库统计，仍只在范围内选择 | 0.0297939872 | 1.1138034498 | B、A |

证据`data/research/spec0036-evidence/bm25-scope-counterexample.json`。两种都不返回范围外片段，但稀缺性与长度统计改变排序，不能当完全等价。现有正式M4索引保存全库统计；参考BM25Indexer也是按已加载整索引统计，旧实验keyword_index.pool_data/build_index则先取范围再统计。

初始建议首版全库统计、范围内选top_k；用户随后明确要求配置同时支持两种统计，便于对照。已接受：默认global，可配scope；每次结果明确实际模式，scope从保存词项在内存构建，不重新解析/分词、不写持久索引。额外计算成本与两种排序分别记录，实施见Spec0037；不再等待本问题确认，完整RAG核心仍在进行中。
