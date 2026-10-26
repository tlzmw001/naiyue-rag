# Spec0035：M5.1 正式查询准备——固定版本、范围与成对编码

日期：2026-10-15。状态：**用户已确认继续，已实现并接线；本地验收见第12节**。用户已确认[A/B/C阶段顺序](../project-plan.md)：本片属于阶段A独立RAG核心，系统学习在M1–M6闭环后展开。设计轮完成后用户要求“继续”，本轮按本Spec实施。

## 1. 具体目标和完成边界

活动版本G1包含L1_Module、L2_A和L2_A_测试用例。调用方提出“cvr_ltv关闭后，0.5边界有哪些历史用例”，范围指定A及其用例。本片输出：固定的G1版本描述、实际可检索的文档/片段ID集合、与G1一致的问题向量/词项，以及本次编码用量和准备阶段追踪。

这个结果回答“在哪个版本、哪些片段上，用什么向量和词项检索”。本片没有Dense/BM25召回、RRF或命中正文，status=ready只代表准备完成，不代表检索/答案质量通过。它是可独立执行、可序列化验证的真实编排，后续检索器直接消费同一PreparedQuery，不重新选latest或重复编码。

正常链：

```text
QueryPipeline.prepare(query, scope, exclude, expected_revision)
  → QueryProcessor.process：纯输入/配置限额检查，保留原始query
  → DocumentManager._document_bundle：只选一次active和完整包
  → 核对模型/表示/分词/维度身份，按源注册表解析范围
  → _audit(选定bundle, 版本保存的集合/k1/b)：双索引健康
  → 无活动版本/无范围/无片段：明确空态，无编码
  → QueryEncoder.encode(original_query)：真实Dense/Sparse成对编码
  → 核对编码返回与选定版本/原问题一致
  → PreparedQuery + EncodingReport + TraceContext报告
```

本片不写索引、不切active、不扫描原始Markdown、不查询相似度、不创建Agent/MCP/UI/评测平台、LLM重写或新的Provider。现有凭证装配和QueryEncoder由调用方持有，构造/关闭仍按当前组件合同。

## 2. 来源、参考调用链与差异

详见[本轮M5源码对照](../research/m5-query-chain-2026-10-15.md)。参考URL：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER ，分支main、commit `f658c5a4011c8b826707a65a3b11ce9301b0626f`，2026-10-15核对本机只读工作区干净。19项指纹在data/research/spec0035-evidence/source-review.json；未查询远端、执行参考代码/测试/setup/Skill或复制代码。pyproject声明MIT，依赖范围不能当实际安装版本。

实际参考链：工具execute→每次装配→QueryProcessor.process→并行Dense(original_query→Embedding→Chroma) / Sparse(keywords→BM25→Chroma.get_by_ids)→RRF/单路降级→后置过滤→可选Reranker→ResponseBuilder引用响应→TraceCollector。独立EvalRunner也直接消费HybridSearch；ResponseBuilder本身不执行通用问答生成。README/DEV_SPEC自述与源码/本机测试/真实服务结果分开。

| 项目 | 参考当前事实 | 本片提案与原因 |
|---|---|---|
| QueryProcessor职责 | 纯文本预处理，提取关键词/过滤条件 | 保持纯计算模块；规则校验与纯预检，不让其持有存储/模型；另以QueryPipeline编排已存在组件 |
| 关键词产生 | 另用全局jieba+停用词/长度/去重/max20 | 复用正式QueryEncoder内部Sparse，保证与索引tokenizer_id一致；不再分词、不另加停用词/截断政策 |
| 查询正文 | Dense用原始query，Sparse使用处理后的词 | 原始query原样进入M3，沿用M3前缀/双hash；不折叠空白或删除否定、数值、技术语法 |
| 过滤 | key:value解析且接受任意键；稀疏仅接collection，其余靠融合后过滤 | 显式文档ID scope/exclude，由已选KB验证；query中的source:/collection:/URL为数据，不触发过滤或路径读取 |
| 版本 | 每次重装/重载，并非固定同一版本三件套 | 复用M4活动快照和完整审计，返回保存的两路索引ID与参数；查询中切换active也不混用 |
| 故障 | 单路可降级；工具/评测部分异常会返回[] | 沿用户已确认整次失败，无隐式单路；本片坏包/坏索引明确失败，不能为空态 |
| 参数 | 当前YAML20/20/10/k60；Processor默认min1/max20/parse=True并未通过当前YAML接入 | 首片不增加召回配置；M3词项政策和现有配置限额生效；召回/融合参数在实际消费切片定义与对照 |

QueryPipeline是具体应用编排，两个直接调用方是库用户与确定性接线测试，后续承接查询入口；没有通用插件层/回调工厂。QueryProcessor的纯预检防止无效请求启动存储审计/模型请求，PreparedQuery作为明确跨层结果供后续Dense/Sparse共用，不为模拟Agent建立第二条链。

## 3. 当前资产和兼容边界

- M1–M4已保存/核验原文、片段、关系、成对编码和索引版本。_document_bundle只读一次目录、完整加载选定包并核验身份；_audit按显式版本参数核对真实Chroma/BM25。
- M3 QueryEncoder.encode接受原始问题，严格返回QueryEncodingResult、query_sha256、模型/表示身份、实际tokenizer_id、向量/去重词项与完整EncodingReport。Sparse空词项仍是合法编码，Dense可以继续使用。
- 当前ChromaStore只有build/audit/get_by_ids，BM25Store只有构建/保存/审计，尚无正式查询；不得写成它们已支持M5召回。
- 旧retrieval.py/a2_snapshot.py仍依赖experiments；旧core.types.QueryRequest还包含固定3072/20/8000限制并拒绝scope=[]。按[ADR0005](../decisions/0005-formal-encoding-entry.md)正式入口独立，不改旧签名/限制，也不新增兼容包装；它们仍有实质消费者，本片无删除候选。
- TraceContext固定安全字段可用于准备的request/resources/embedding；本片沿用现有七阶段定义，不把未执行的检索/融合阶段填为成功。

## 4. 接口与职责

新增以下具体组件：

1. `query/query_processor.py`：`QueryProcessor(encoding_settings, *, max_scope_documents)`；`process(query, *, scope_document_ids=None, exclude_document_ids=None, expected_revision=None)` 返回私有不可变的_ProcessedQuery（query原文、scope元组或None、exclude元组、expected_revision）。无IO/环境读取/分词/编码，不接受Strategy/回调。
2. `query/pipeline.py`：`QueryPipeline(document_manager, query_encoder)`；公开 `prepare(query, *, scope_document_ids=None, exclude_document_ids=None, expected_revision=None) -> PreparedQuery`。
3. `core/query_preparation.py`：严格PreparedQuery及JSON往返，见第6节。顶层导出QueryPipeline、PreparedQuery；QueryProcessor在query模块可定位，不强制扩展顶层公开面。
4. `core/errors.py`：新增QueryJobError，见第7节；不复用旧实验RetrievalError的开放文本合同，不改变IngestionJobError。

构造要求实际DocumentManager和实际QueryEncoder；防御保存当前StorageSettings/EncodingSettings/tokenizer_id，装配纯Processor，入口核对编码器/Dense/Sparse当前配置与保存身份一致，拒绝原地替换组件。沿现有M3配置校验函数/实际tokenizer_id取值，不仅相信构造时某个名称。编码服务/稀疏资源初始化由调用方负责；不声明无Key构造所有组件，prepare本身不加载.env、创建Provider或关闭调用方资源。

本片公开方法没有candidate_k或context预算：还没有消费者，不预建配置。未来search入口在其Spec中增加实际检索参数，prepare签名保持。

## 5. 请求、快照和所有分支

### 5.1 请求预检

- query严格str，去空白后不能为空，UTF-8有效；保留原始字节对应文本，不重写、不截取。复用prepare_query_encoding_input/plan_encoding_batches的纯预检，按当前EncodingSettings.runtime.max_input_utf8_bytes、max_batch_input_utf8_bytes、max_inputs、max_requests等限制（含query_prefix字节），不新硬编码3072或默认模型。
- scope=None表示当前KB全体；scope=[]表示明确空范围；exclude=None归一为空。非None必须实际list，每项严格 `doc-`+64小写hex、无重复，每份列表长度≤当前StorageSettings.max_documents；tuple/set/字符串/bool/绝对路径/前缀均拒绝。
- expected_revision=None表示选取一次当前活动版本；给出时严格非bool整数0..MAX_REVISION。非法请求在catalog.read/原生SDK/编码前拒绝。
- 显式字段决定范围，query内相似语法不覆盖字段。检索材料仍为数据，不解释为指令/授权。本项目内部共享KB，不新增用户/角色授权清单；范围与授权不同。

### 5.2 固定一次版本与范围

1. 调用 `_document_bundle(expected_revision)` 一次；不先list再open_active，也不在编码后重新选latest。已知revision冲突在模型前失败。无active时revision按0核对。
2. 以该包文档注册表核对scope/exclude；所有显式ID都必须属于当前版本，包括exclude，未知或其他KB合法格式ID报query_invalid_scope。未激活时非空显式列表也报范围错误，不能悄悄扩大到全库。
3. effective_document_ids = (全部ID或scope) 减exclude，排序去向由严格输入保证；从同包chunks按source_ref投影effective_chunk_ids，按ID排序。用例与普通正文执行相同范围规则，不自动扩展引用、L0或父文档。
4. 已激活时，核对编码器model_space_id、representation_id、实际tokenizer_id、expected_dimensions与选定version/bundle一致；不一致报query_identity_mismatch，无模型POST。不要求查询端的文档切分配置重新提供；实际tokenizer/模型/表示必须一致，runtime批大小/超时/缓存路径不作为语义身份。
5. 使用选定version保存的chroma_collection_name/bm25_k1/bm25_b，结合manager当前合法batch_size调用原 `_audit`，结果必须等于已选IndexVersion。manager当前默认集合/k1/b变化不能把同一次查询重绑定到另一个索引。
6. 有active时，即使scope为空或片段为零，也执行该健康审计，不用空范围隐藏坏索引；无active不初始化两路SDK、不创建目录。现有目录/包的当前读取限额照常生效，不因有效范围很小绕过整包核验。

### 5.3 空态、编码和并发

| 条件 | 状态与动作 |
|---|---|
| 没有active，且显式范围合法 | unactivated；active=None、两个ID列表空、encoding=None，无POST/索引创建 |
| active本身文档数为0 | empty_index；保存该active，两个列表空，无编码 |
| active有文档，但有效文档集合为空（含显式[]或全部排除） | empty_scope；两个列表空，无编码 |
| 有效文档存在但没有片段（例如空白文档范围） | empty_index；保留有效document_ids、chunk_ids=[]，无编码 |
| 有有效片段 | 恰好调用一次QueryEncoder.encode(原始query)，严格核对返回后ready |

ready的query_terms=[]仍合法，不再编码或主动改成单路；未来Sparse返回合法空候选与Sparse调用失败是不同情况。它不表示问题无答案。

编码期间其他writer激活G2，本次始终返回选定G1，不做末尾revision重验/刷新/重试。expected_revision约束选择时点，不承诺返回后版本仍最新；后续召回只使用PreparedQuery.active内的索引/包ID。旧版本留存是当前M4合同，若将来GC必须另设读者/保留协调，不能提前清理。

M4只读业务审计可能产生Chroma SDK内部维护写，不能承诺存储字节/mtime不变；本片不改变文档成员、版本记录或active。纯预检阶段无需源目录；已有Manager.project_root仍须合法，模型/Sparse资源和SDK初始化限制沿已有合同。

## 6. PreparedQuery：内部执行结果

严格字段只有：`status、active、query_sha256、document_ids、chunk_ids、encoding、trace_report`。

- status闭集ready/unactivated/empty_scope/empty_index，query_sha256为原始query UTF-8 hash。active严格ActiveVersion或None，ID列表为有序、唯一、合法的doc-/unit-64hex，数量不能超过active对应总数。
- unactivated要求active=None、列表均空、encoding=None；其他状态要求active存在。empty_scope要求active文档数>0、两个列表空；empty_index要求chunk_ids空且encoding=None（零库或有效空白文档范围）；ready要求两个列表非空且严格QueryEncodingResult。
- ready核对encoding.input.query_sha256==query_sha256、input.kind/query ID、模型/表示/分词/维度与active一致；复用QueryEncodingResult自身对向量、双hash、词项/报告的完整校验，禁止只传一个裸向量。
- 调用链必须核对每个有效document_id在已选包内、每个chunk_id准确属于范围；DTO不能仅凭数量证明成员来源。to_dict/from_dict负责本对象可独立验证的不变量；不在DTO里读取存储，防止序列化重新选版本。
- 深拷贝嵌套结果、严格字段集与JSON往返、安全repr。成功结果最后按现有max_bundle_bytes有界序列化检查；超限明确query_result_limit，已知编码报告仍在错误中保留。
- 这是提供给检索器的内部对象，encoding含查询原文/向量/词项；禁止直接当工具最终证据、trace内容或日志。面向Agent/MCP的正文/证据响应由M6/M8另定，不把内部向量发给模型充当知识。

## 7. 最小追踪与失败合同

复用现有TraceContext（不修改其字段集）：

- request：validated，仅在纯预检完成后记录。
- resources：verified，corpus_id映射选定version.source_fingerprint、index_id映射version.version_id；只在有active且健康核验完成后记录。未激活只记录请求阶段。
- embedding：adapter_calls取实际EncodingReport.requests.dense_calls_started，source_kind和usage取唯一实际批次对应字段；未知usage保持None，详细累计观察仍以EncodingReport为准。
- 正常finish(success)只表示本片准备成功，包含空态；若trace已经结束而随后结果合同/序列化失败，以本次已结束报告的防御副本更正error终态并重新校验，不重复finish或改变原context。没有dense/sparse/fusion/packing等未执行阶段。只返回内存trace_report，不新写JSONL或观测平台，不把查询原文、词项、向量、源正文或绝对路径塞入trace。

新增 `QueryJobError(stage, code, *, active=None, encoding_report=None, trace_report=None)`：

- stage闭集request/resources/embedding，描述准备执行阶段；编码后结果/序列化检查位于embedding；空态回执检查位于resources。后续检索阶段仅在实际消费切片扩展，不预填未实现阶段。
- code为既有StorageError.CODES、M3 EncodingReport.ERROR_CODES及本片闭集query_invalid_request、query_invalid_scope、query_identity_mismatch、query_result_limit、query_prepare_failed、query_request_failed、query_resources_failed、query_embedding_failed、query_trace_failed。消息/repr仅安全码，字段严格JSON往返/防御复制，不携带部分向量/词项、原始cause或str(error)。
- request非法用对应安全码；StorageError保留实际安全码；M3 EncodingJobError保留实际失败报告/安全码；编码成功后下游失败仍保留本次成功报告。编码前report=None，不拿旧包报告或伪造0token补位。active只在本次读取返回合法绑定后可知。
- trace终态映射：非法请求invalid_request，范围invalid_scope，身份invalid_resources，其他资源失败snapshot_load_failed，编码及编码后失败embedding_failed；原始详细安全code在QueryJobError保留，不扩充旧TraceContext码表。异常时返回可得的错误trace；如果trace自身构造失败，固定日志query_trace_failed，保留原主错误/已知编码报告，trace_report=None。仅trace故障时整次准备报query_trace_failed，不宣称已有成功trace。这不是结果持久化写失败策略：本片尚无检索结果或可选文件写入。
- KeyboardInterrupt/SystemExit不变为普通失败；无隐式降级/自动重试/索引修复。Provider和Manager资源生命周期按现有组件，审计失败/关闭失败明确可见，不关闭外部拥有的客户端。

## 8. 影响文件、复用与清理

预计涉及**9个源码/测试文件**，加阶段文档超过8个，范围明确：

| 文件 | 修改 |
|---|---|
| naiyue_rag/query/__init__.py | 新模块仅导出实际组件 |
| naiyue_rag/query/query_processor.py | 纯预检和私有不可变_ProcessedQuery |
| naiyue_rag/query/pipeline.py | 选定版本/范围/审计/成对编码/追踪的具体编排 |
| naiyue_rag/core/query_preparation.py | PreparedQuery严格合同 |
| naiyue_rag/core/errors.py | QueryJobError安全闭集 |
| naiyue_rag/__init__.py | 导出QueryPipeline、PreparedQuery |
| tests/test_query_processor.py | 请求与技术文本/空范围纯计算测试 |
| tests/test_query_preparation.py | 快照/范围/配置/失败/DTO/并发确定性测试 |
| tests/test_query_preparation_wiring.py | 真实M1–M4与新问题编码、跨进程接线 |

不改配置/真实.env/依赖，不另建YAML入口、Provider、SDK worker或通用任务基类。原DocumentManager/BundleStore/Chroma/BM25、QueryEncoder和TraceContext公开合同保持；扩展以调用它们为主。旧实验仍有消费者，删除候选0；本片不通过替代旧消费者删除整个实验目录。单源码文件≤500行。

## 9. TDD与实际接线验收计划（实际结果见第12节）

先写测试确认缺少QueryPipeline/PreparedQuery的预期红灯，再实现最小链；沿现有fixture/Fake/SDK MockTransport/真Sparse和本机索引，不修改conftest/旧断言。

| 分支/风险 | 验收 |
|---|---|
| 原始文本与限额 | 空、非str、非法UTF-8、含前缀超字节/请求限额在IO前拒绝；空白/大小写/否定/source:/collection:/URL内容原样到M3，scope不会被改写 |
| 显式范围 | None全体、[]空、exclude、交集、空白文档、重复/未知/跨KB ID、错误容器、列表超限；范围内unit集合精确，无关系自动扩展 |
| 版本固定 | select只读一次catalog；已知陈旧revision/坏身份在POST前拒绝；编码回调中真实activate G2后仍返回G1，目录保持G2且无重试 |
| 配置/参数 | 模型/表示/tokenizer/dimensions不符无POST；运行批大小可变；当前manager默认collection/k1/b变化时按选定version保存参数核验旧索引；非法/原地修改组件拒绝 |
| 空态 | 未激活不创建存储；活动零库/空scope/全排除/零片段不编码；已有active即使空scope也不能掩盖坏包/坏一路 |
| 正常编码 | 调用恰好一次现有QueryEncoder；QueryEncodingResult三身份/原始hash/向量/词项精确绑定；空词项合法，usage未知保持未知 |
| 失败 | catalog/load/审计/关闭IO、Dense错误、Sparse错误、配对/编码后合同错误、结果超限、trace错误；安全阶段/实际报告/已选active明确，未知异常固定码，无原文或凭证泄漏 |
| DTO/中断 | 严格字段/状态/ID/排序/重复/计数/身份/报告/JSON/深拷贝；无部分编码结果进入异常；BaseException传播，必要资源清理保持 |
| 原生跨进程 | 第一进程沿现有IngestionPipeline构建三件套；第二进程以真QueryEncoder/Dense SDK MockTransport+真Sparse准备一个新问题，第三进程按PreparedQuery.active及片段IDs回取同版本完整用例，空/正常场景均覆盖；全程外部网络阻断 |
| 原主链 | 原M3查询、M4存储/管理/摄取/移除和M0追踪回归，全量通过；旧consumer不受影响 |

本片编码和原生接线真实模型POST预算0，只用临时公开/合成材料与模拟Key/.env。无需新账号、MCP或第三方CLI；当前本机Python/SDK依赖已存在且按锁版本核验，不安装升级。真实服务验证不包含在本Spec授权中，另给材料/模型/请求数和截止时间后执行。

本片检查的是范围/来源/版本/编码接线，不输出Recall或问答正确率。阶段A小型固定检索集在Dense/Sparse/Hybrid实际存在时比较：明确文档级/片段级标注与Recall@k，保留多文档、历史用例、技术标识符、缺证据样本；完整评测平台留阶段C。

## 10. 后续M5边界、风险与回退

- 后续Dense切片：正式Chroma原生query、范围前置、距离/分数刻度、完整来源核验；Sparse切片：同一范围、BM25统计语义和空词项；Hybrid切片：RRFFusion及两路失败合同；导航/补读切片：显式请求、范围/版本/预算受控。各片独立Spec，不在首片创建空检索器。
- BM25全库统计过滤与范围内重算不同，Sparse编码前由本会话给最小对照并讨论；首片仅确定成员，不预先声称采用某种评分语义。参考三top_k与旧A220/8000不是首片默认值，实际参数在消费者建立时配置/验证。
- 主要成本：每次准备完整加载旧包并审计两路，可能重复读取/SDK维护写；10倍数据下成本会增长。本片先保证正确绑定，不加缓存/长连接；性能优化基于后续测量，不能称轻量实时生产查询。
- 版本留存与模型空间一致是前提；依赖服务故障直接失败，Provider现有超时/编码deadline只覆盖其合同，不宣称包括所有本地IO的整次硬截止。
- 本片不改变索引/active/源数据，设计撤回只有文档；实施代码可在保持旧入口/产物的前提下撤回，不做自动回滚/数据删除。SDK内部维护写沿既有边界，不能承诺文件字节回滚。
- 原子版本/范围/编码准备完成不代表推理或检索效果接近大模型搜索；需要实际固定样本和后续真实材料验证。阶段B学习基于阶段A完整链，不登记已独立掌握。

## 11. 设计轮实际证据（历史，实施结果见第12节）

- 既有基础：`.venv/bin/python -m pytest -q tests/test_query_encoding.py tests/test_query_encoding_wiring.py tests/test_index_versions.py tests/test_document_manager.py tests/test_document_manager_wiring.py --tb=short` → **155 passed in24.06s**；不是M5.1新功能通过。
- 合成现有组件探针：原文保留，数字/技术词完整，模拟Dense1次，范围投影2文档/5片段；同时记录Sparse单字否定可能丢失、旧QueryRequest拒绝[]的事实。见current-query-probe.json和[调研](../research/m5-query-chain-2026-10-15.md)，不能据此声称新入口已接线。
- 编译/依赖/diff/链接/188项源码与配置资产及137包版本检查见 `data/research/spec0035-evidence/design-verification.json`。1780全量为Spec0034上一轮，本轮未重跑全量；无真实模型请求、真实.env读改或参考执行，无提交/push。
- L1：Spec/调研/阶段计划存在；L2：QueryProcessor/QueryPipeline/PreparedQuery仍是提案；L3：M5.1尚未接入。阶段A必要机制与结果说明已进行，完整课堂及本人独立调试/实现证据无新增。

**设计轮的下一步（已执行）**：确认本Spec后完成单片TDD与接线；进入Dense等后续片前分别定其Spec。

## 12. 实施与验收（2026-10-15）

用户在设计轮后要求“继续”，本片实施范围按上述合同执行。新增4源码、3测试；已有源码只追加QueryJobError与根导出，不改M3/M4/TraceContext、旧测试、配置或依赖。

### TDD与修正

1. 新组件尚不存在时运行前两测试文件，得到**31 failed, 62 errors in6.70s**，均为缺少查询准备模块/导出的预期红灯。见red-tests.txt。
2. 首轮实现得到**3 failed, 90 passed in17.38s**。编码后错误路径构造QueryJobError时漏传已选active，严格校验将目标错误变为通用失败。修正源代码：追踪辅助函数抛既有TraceError、在外层统一附带版本；编码身份/结果限额错误显式附active。保留原断言，93项转绿，见first-green-attempt.txt及unit-tests.txt（**93 passed in17.72s**）。
3. 在此基础上补5项边界验证（活动空库/空白文档2项、存储关闭失败、结果限额故障注入、错误DTO严格复制），另有5项原生接线。全部新增检查：

```zsh
.venv/bin/python -m pytest -q tests/test_query_processor.py tests/test_query_preparation.py tests/test_query_preparation_wiring.py --tb=short
# 103 passed in 33.30s
```

以上5项补充验证发生在实现后，不作为首轮红灯证据；结果限额通过故障注入现有序列化器的bundle_limit_exceeded验证错误映射/用量保留，不宣称已用真实大响应测得容量边界。

### 接线与验收范围

- **L1存在**：QueryProcessor、QueryPipeline、PreparedQuery及QueryJobError，根入口实际导出QueryPipeline/PreparedQuery。
- **L2实质**：原文保留/前缀预检、严格ID与revision、四种状态、固定模型身份、按已存参数审计、已知用量及安全追踪/错误均为实际实现。
- **L3接线**：`QueryPipeline.prepare`→纯Processor→`DocumentManager._document_bundle`一次catalog选择→`_audit`两路→现有`QueryEncoder.encode`一次→PreparedQuery/有界序列化；源文件移走仍使用已存快照。实际编码回调激活G2时本次仍返回G1，无刷新重试。
- 原生测试5场景：normal、normal显式空scope、zero、all-empty、mixed。第一进程经IngestionPipeline/SDK MockTransport/真Sparse构建并激活，第二进程准备新问题，第三进程按结果active/IDs从实际Chroma回取完整片段并与资料包逐字段相等；正常用例case_fields完整。当前默认集合/k1/b刻意不同仍按保存版本读取，空态不编码，全程socket阻断。
- 故障覆盖请求/范围/revision/身份、坏资料包或一路索引（含空scope）、Dense/Sparse/配对、编码后合同与序列化、关闭失败、追踪失败及BaseException传播；整次错误保留已知active/report，无部分向量结果或原始异常正文进入安全错误。

### 全量回归与最终检查

```zsh
.venv/bin/python -m pytest -q tests --tb=short
# 1883 passed in 229.56s (0:03:49)
.venv/bin/python -m compileall -q naiyue_rag tests
# exit 0，无错误输出
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0，无错误输出
```

项目当前无独立打包构建入口，compileall只证明Python源码可编译，不代替运行测试。上述命令均实际运行且exit 0；完整输出和检查记录见`data/research/spec0035-evidence/full-suite.txt`及`implementation-verification.json`。

实施前188项源码/测试/实验/配置/依赖资产对比：仅errors.py与根__init__.py追加，原有内容前缀hash保持；新增4源码/3测试，旧测试、配置/锁文件无变更或缺失。137安装包名称/版本、19项参考指纹保持，源码最大266行；9份文档399个相对链接、差异格式及新增源码/测试白空检查通过。明细见implementation-assets.json。未替代旧实验的召回入口，仍有真实消费者，本片无删除候选。

### 限制与下一步

当前是本机合成/MockTransport/真实本机索引的工程验收，真实模型POST0；未读取或修改真实.env，未运行参考代码/测试，未升级安装包、删除旧产物、提交或push。未新增召回/RRF/重排/证据响应、Agent或MCP；不能用ready或测试通过声称检索质量通过。每次准备的完整包加载与双索引审计成本、真实材料/大库性能、生产并发和整次IO硬截止未验。

阶段A必要机制与运行结果已说明，完整课堂继续暂挂，本人独立调试/复写/追问无新增证据。

**唯一下一步**：对照参考DenseRetriever与现有ChromaStore，梳理M5.2正式Dense召回链并制定Spec，明确scope前置、距离/分数刻度及同版本来源绑定。
