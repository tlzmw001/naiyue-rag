# Spec0038：M5.4 同一问题编码的双路检索、RRF与统一追踪

日期2026-10-15。状态：已实现/接线/本地验收；最终全量见Spec0039。

## 1. 当前与目标

M5.1 QueryPipeline.prepare生成一次固定版本/范围/成对编码，M5.2 DenseRetriever与M5.3 SparseRetriever可各自消费该结果。本片提供HybridSearch.search统一入口，显式配置到两个真实消费者，融合后返回完整来源候选。无Agent、MCP、问答或重排；这些后续分片接入。

参考 https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER ，main/f658c5a4011c8b826707a65a3b11ce9301b0626f，2026-10-15静态核对`src/core/query_engine/hybrid_search.py`及`fusion.py`：默认20/20/10，两个ThreadPoolExecutor worker，RRF k60、1/(k+从1开始的排名)，按score降序/ID升序；参考可能降级且后置过滤。当前项目使用已定前置范围、整次失败，不复制原始查询/异常日志，保持差异可见。

## 2. 接口、配置与数据流

- `core/hybrid_settings.py::HybridSettings(dense_top_k,sparse_top_k,fusion_top_k,rrf_k,bm25_statistics_scope,parallel_retrieval)`及严格YAML加载；所有k严格正整数、模式global/scope、并行严格bool。新增examples/hybrid.example.yaml，显式20/20/10/60/global/true，不改真实运行配置/.env。
- `query/hybrid_search.py::HybridSearch(document_manager,query_encoder,settings).search(query, *, scope_document_ids=None, exclude_document_ids=None, expected_revision=None)`。
- `query/fusion.py::RRFFusion(k).fuse(dense_result,sparse_result, *, top_k)`：严格两路来自相同PreparedQuery；同ID的Chunk正文/元数据必须相等，否则失败，不“取第一次”隐藏冲突；累积等权RRF，保留各路原始排名与分数在返回候选中，不加入权重/导航扩展。
- `core/hybrid_results.py`严格FusedHit(rank,chunk,score,dense_rank,sparse_rank)及HybridResult(prepared,settings,dense_hits,sparse_hits,hits,trace_report)。复用DenseHit/SparseHit/DenseResult/SparseResult的实质校验；严格序列化/深复制，验证两路名次与RRF分数/选定全集排序、来源绑定及trace计数。内部包含查询向量，不能当MCP最终证据。

正常链：配置/限额预检→一次现有prepare→给两路各一个防御复制→按配置并行/串行实际Dense/Sparse→融合→完整HybridResult与有界JSON。无论并行与否不重新选active、解析、分词或Embedding。相同配置和已选快照下两种执行方式结果相同（时间字段除外）。

## 3. 追踪与失败

Hybrid自己的TraceContext在prepare前开始；导入PreparedQuery已完成阶段的安全数据和实际elapsed_ms，record_stage现有显式elapsed参数可直接复用，导入时的timestamp表示收集时点。PreparedQuery的原准备trace保持，两个trace ID为子准备与总查询；不得把导入发生的时刻冒充原阶段结束时间。

Dense/Sparse父编排各记录本次实际耗时和`eligible_count/candidate_count`，eligible是范围内片段数，ANN内部比较次数未知。TraceContext仅新增这两个阶段的显式计数字段变体，保留旧compared_count字段合同；其余字段/旧追踪测试保持。fusion记录union_count与candidate_count。并行耗时不相加冒充总时长。

依赖失败整次报QueryJobError，保留实际版本/编码报告及总查询安全trace，无部分hits。两路都启动时等待并收集两边终态，双失败以Dense为主错误，Sparse另记固定安全日志，不静默吞错、不自动降级。线程执行不提供本地IO的强制中断或整次硬截止，参考future.timeout也不保证退出with时不等待，故不复制为虚假硬截止；BaseException传播且资源清理沿原组件合同。

对QueryJobError扩展fusion阶段/query_fusion_failed，对QueryPipeline._fail仅扩展已存在阶段的安全trace映射（dense/sparse/fusion→retrieval_failed），不重写原准备行为。失败trace自身不可用时保留主错误/usage并安全记录。结果超限明确query_result_limit。

## 4. 验收与影响

先Spec/红灯，新增配置/融合/编排/DTO及测试；扩展根/query导出、错误与TraceContext计数字段变体，原持久格式/旧入口/测试/配置/依赖保持。模块本身不依赖experiments，旧实验仍有消费者不删除。

- 手算RRF、单路合法空候选/双空、同分ID、跨路正文冲突与配置/DTO错误；不把合法Sparse空当错误降级。
- 一次真实QueryEncoder，两路实际消费同一query hash/active/范围；配置k/统计模式/并行值确实生效，限额在模型前拒绝。
- 故障覆盖两路单/双失败、融合/trace/序列化及控制中断，错误原身份/本次用量/无部分hits和安全日志保持。
- 并行用事件/barrier证明两个分支启动，不用极短sleep；原生临时Chroma/BM25两个worker并行实际重开查询，验证SDK生命周期能共存，串行/并行同结果。
- 原生跨进程正常/空scope/零/全空/混合与两个统计方式；模型只用MockTransport，socket阻断；QueryPipeline原回归及全量、compileall/pip/资产/格式检查。
- 固定合成检索质量与预算在M6最终证据入口可执行后对照，不能用单测全绿声称业务通过。

## 5. 回退与下一步

只增加库级只读编排，无索引格式变更或自动数据回滚/删除。新入口可撤回、旧产物可用。完整审计在两路会重复，先验证正确性再依据测量优化；不添加缓存/长连接层。

下一片受控关系导航/原文补读：使用已存关系及实际位置，保持版本/范围/预算，检索内容作为数据。随后进入M6重排、证据与引用，具体后端和成本约束到需要时判断。

## 6. 实施与切片验证

30项新测试先出现缺少组件/新trace字段的预期红灯（red-tests.txt，30 failed in4.41s）；最小实现后30 passed in13.31s。新增HybridSettings/RRFFusion/HybridSearch/FusedHit/HybridResult，实际一次prepare→两个真实Retriever→等权RRF；来源冲突拒绝，参数/模式/并行设置实际消费。TraceContext只增加明确eligible_count变体；原准备阶段安全数据/实际耗时导入总查询trace，ANN内部比较次数不编造。

原生SDK 7场景分别实跑并行和串行，输出顺序/来源/排名/分数一致，两个Chroma/BM25 worker的重开/关闭可共存；每次search只有一次SDK MockTransport编码，空态零次。正常/两种统计、空scope、零、全空词、混合均通过，socket阻断，保存源根移走，完整Chunk与RRF手算核对。

收尾补回归发现：准备失败且trace不可用时，外层曾把原embedding错误重包为request，丢失已知版本/用量。单条回归先确认1 failed in0.51s（preparation-error-red.txt），最小修正以明确preparation_error身份原样传播该异常；不放宽断言。原错误/trace存在或缺失均不再由Hybrid改写。

最终切片命令：

```zsh
.venv/bin/python -m pytest -q tests/test_hybrid_search.py tests/test_hybrid_search_wiring.py tests/test_query_preparation.py tests/test_tracing.py --tb=short
# 148 passed in 53.95s（38新增）
```

首次回归命令误写不存在的test_trace_context.py，未运行测试，保留initial-command-path-error.txt；核对实际test_tracing.py后执行上述命令。M5.5同属M5只读查询能力，随后连续推进；最终M5全量在Spec0039收尾统一运行，2046 passed in341.34s（0:05:41），exit0。本条148是切片证据，最终日志在spec0039-evidence/full-suite.txt。无真实模型/.env/依赖/旧测试变更、参考执行或提交/push，完整课堂暂挂。
