# Spec0042：M6.2 完整证据预算与独立入口

2026-10-15，按已批准 M6 路线推进，实施前规范。承接0040/0041，不新增 Agent、MCP 或问答生成。

## 现有链与参考

固定 HybridResult→CoreReranker→RerankResult 已有本地测试；重排结果仍含内部向量，不能直接送模型。参考 main/f658c5a4011c8b826707a65a3b11ce9301b0626f 的 CitationGenerator→ResponseBuilder 把候选转换为引用和 MCP 内容。此处采用相同职责拆分，但以核心 JSON 字典输出、真实 SourceSpan 及完整用例替代未知来源兜底/200字摘要；MCP 只在后续适配。

## 新链与合同

ResponseBuilder(KnowledgeReader, EvidenceSettings).build(RerankResult)：防御复制并验证排序→通过现有 reader 固定包审计一次→逐一比较候选与保存 Chunk（包括全部正文/元数据）→按最终排序原子装入上下文→引用与 JSON 限额检查。没有 active 的合法空查询可输出空；非空必须有固定 active。不重新读 latest、不重新编码或检索，原 Markdown 不在磁盘仍可回取。

EvidenceSettings(max_context_characters,max_response_bytes) 严格 YAML。context 是带 [E1] 标记、来源路径、实际行号、必要 contexts 和完整 chunk.text 的文本。预算覆盖格式文本，整个证据超预算则整片跳过并记录 chunk_id/reason，后续更小片段仍可装入；测试用例不截行。max_response_bytes 覆盖整个 UTF-8 JSON（含追踪/报告），超限整次 EvidenceError，无截断 JSON。两种预算不混淆。

输出：schema_version、status(retrieved/empty/no_evidence_fits)、answerability(unknown)、active、query_sha256、context_text、evidence、omitted、observations。每份证据含 citation_id、最终排名、文档/片段 ID、source_path、source_sha256、实际 body_span、完整 body、必要 contexts、kind、原 Dense/Sparse 排名/分数与score_kind、RRF k/原排名/分数及重排分数。source_span/contexts 均源自已审计包，不依赖表头手写行号。observations 分别为原 retrieval trace、embedding 用量、rerank 报告、retrieval/rerank 实际配置（含provider/model）、packing 实际耗时/数量，绝无向量或 prompt/原始模型响应。非空不表示可回答，无证据不凭此断言知识库无答案。

错误仅固定 code/安全 observation，无原始内容；source 不一致/IO/预算均不返回部分成功。新 RetrievalPipeline(search,reranker,builder).query(...) 为薄编排消费者，直接传播查询/重排/证据各自错误，保留失败归因。

## 独立使用入口

新增 app 模块和 python -m naiyue_rag，使用 argparse 子命令 ingest/query/documents；无 HTTP/UI。配置为严格 YAML，引用既有 encoding/sparse/storage/chroma/bm25/hybrid/rerank/evidence 配置文件，路径相对应用 YAML；project_root 指定凭证解析的本项目根。key_env 只给环境变量名。重排 none/llm/cross_encoder 可选；none 不加载重排凭证/后端。query 从 stdin 或 --query 读入，范围 ID 显式传参；正常只在 stdout 输出结构化 JSON，错误输出安全 JSON/非零 exit，不输出 traceback。入口拥有并可靠关闭客户端；关闭失败不得掩盖主失败。无自动改 .env、无静默下载；本地模型装配在下一片补齐。

ingest 复用 IngestionPipeline，expected_revision 必填；无删除/移除 CLI，防止本片扩大破坏范围。documents 不加载模型。新增配置示例是可复制模板，不修改真实配置。可复现合成样本与真实服务监督验证分账。

## 影响/验收/回退

新增 core/evidence_settings.py、response/builder.py、query/retrieval_pipeline.py、app.py、__main__.py、examples/core-demo/ 的配置和合成材料，以及对应单元/跨进程接线测试。root 仅追加导出。先红灯，后最小实现：完整用例/预算边界/空态/篡改来源/active 变化/原文移走、全 JSON 限额、无向量泄漏、CLI 配置接线、真实 SDK MockTransport+原生存储全过程。

无新第三方依赖，无旧入口/存储格式删除。回退可不调用新入口并关闭重排，不操作已有数据。服务验证遵守0041最多12次请求/300秒监督，不随失败自动扩大；本片成功前不登记核心整体完成。

## 实施证据（2026-10-15）

L1：新 EvidenceSettings、ResponseBuilder、RetrievalPipeline、app/__main__ 和 core-demo 模板均存在；L2：有完整来源核对/原子预算/引用及严格装配，不是占位；L3：`test_core_app.py::test_cli_real_assembly_sdk_and_native_indexes[query/documents/ingest]` 从配置进入 SDK/原生本机索引、跨进程消费最终证据。source原目录移走后query仍能生成完整证据。

测试：Evidence9项预期红灯→与0041联合64 passed in20.88s；app初稿测试存在一处括号错误，修正后确认5项因为入口缺失失败，再实施→5 passed in9.17s。示例路径回归6 passed in10.12s。没有改旧断言/skip；输入标签 ID 限制与严格结构后来新增6项红灯→总8 passed in0.11s。独立 metric 只计算已选 ID 与 gold 的交集，不按模型分数反推标签。

真实监督命令（本次执行脚本及报告位于本地忽略目录，移机可用 examples/core-demo/README.md 的公共命令）：`.venv/bin/python /tmp/naiyue-core-live.py`，外层300秒监督、最多12请求。首次示例 storage_root 含`..`违反既有严格校验，0请求失败；新增测试复现，改本次新模板为`./data/indexes`和`./data/cache`，保留原失败，不放宽存储校验。新输出目录运行成功：5文档/12片段、3 HTTP、11.539秒、5证据/717 context字符；三请求均HTTP200。Embedding建库572tokens/查询25tokens、GLM1795tokens，费用未知。未输入真实业务材料。

固定样本命令：

```bash
.venv/bin/python -m naiyue_rag.validation.retrieval_smoke --config /Users/zmw/naiyue-rag/examples/core-demo/app.example.yaml --questions /Users/zmw/naiyue-rag/examples/core-demo/questions.json --output-dir /Users/zmw/naiyue-rag/data/research/spec0042-evidence/quality-glm-01 --max-requests 8 --deadline-seconds 240
```

实际8请求/34.279秒，Embedding80tokens、GLM7027tokens；含首闭环累计11请求，未超12。先固定助手构造标签再运行，未用户审核；gold按唯一 source_path/body anchor定位实际片段，前三题分母分别3/1/1，Q4无gold时recall=null。

| 问题 | RRF候选池Recall@10 | 关闭重排Recall@5 | GLM Recall@5 | 最终预算后GLM Recall |
|---|---:|---:|---:|---:|
| Q1 跨历史需求/用例/模块回归 | 3/3 | 1/3 | 3/3 | 3/3 |
| Q2 具体旧用例预期 | 1/1 | 1/1 | 1/1 | 1/1 |
| Q3 日志归档 | 1/1 | 1/1 | 1/1 | 1/1 |
| Q4 无依据的实时汇率 | null | null | null | null |

Q4依旧可返回片段，answerability=unknown；没有无答案分类器。此对照只有4题/12片段，不当真实资料质量、性能规模或业务验收；也不能推出任意LLM重排必然增益。没有问答生成验证。

产物：data/research/spec0042-evidence/live-glm（原0请求失败）、live-glm-02（真实闭环）、quality-glm-01（同池对照）；hybrid/rerank缓存只含本次合成材料及内部编码，不能作为最终模型上下文直接公开。compileall、pip check、diff检查已通过；收尾前全量结果2131 passed in381.24s；随后新增10项（schema6、关闭/环境2、版本切换1、分数来源1）纳入最终95项定向回归，95 passed in33.42s。当前collect-only共2141项；两次覆盖结果如实分列，不称为单次2141全量。137包保持，未改真实.env/其他仓库/旧测试，无提交或push。

M6整体仍待0043本地依赖决策与原生CPU验收；GLM闭环完成不代替两后端目标完成。本人完整课堂/独立实现证据无新增。

收尾来源信息修正：最终响应显式携带 retrieval_configuration 与 rerank_configuration（provider/model/top_k），每条证据标明 Dense/Sparse score_kind、RRF k 和原排名；新增测试先因缺字段红灯后修正。用四份已保存的真实GLM排序缓存离线重新组装新增字段，阻断socket，context_text/片段ID完全相同，0网络尝试；原始服务产物不覆盖，当前组装另存`Q*.evidence-current.json`。未重新请求模型或改标签。

当前编译命令`.venv/bin/python -m compileall -q naiyue_rag` exit0；`.venv/bin/python -m pip check` 输出`No broken requirements found.`；`git diff --check` exit0。原137包版本逐项相同。证据分别为full-suite.txt/final-slice.txt/final-collection.txt与asset-audit.json；不是完整生产容量/真实知识库验收。
