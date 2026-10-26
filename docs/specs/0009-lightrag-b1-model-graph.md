# Spec0009：B1原生模型回调、建图与mix对照

日期：2026-10-10（America/Chicago）。状态：B1模型/图/证据接线、工程复核、固定评测与无Key标准CLI重放已完成；首个live run因审计bug失败并保留，完整产物明确标engineering_revalidation。质量无收益且Q02退化，详见第11节。用户已确认A1/A2/A3/B0/B1、glm-5.2、embedding-3、标准API来源和8000字符预算；本Spec确定新的模型回调接法与工程上限，先审阅再实施。代码课堂继续暂停。

## 1. 问题、基线与本轮决定

B0实际原11源/52单元、单源10单元写入/新进程重载/naive验证通过，368 tests passed是前轮结果。B0与A1四题候选/返回/指标相同，Q01必要返回2/8、Q02 0/5；A2为3/8、1/5，A3退化。下一步检验模型实体/关系能否补回分散在历史需求、模块和旧用例中的原文，而不是把建出一张图或生成答案视为收益。

推荐：固定LightRAG1.5.7与现有独立环境，使用其原生JSON抽取、native graph/merge/mix机制；关闭补漏gleaning，保留原公共片段。先做一个原生协议小探针，通过后自动继续完整两个scope建图和四题mix；最后无Key/阻断网络重放。图和描述只作定位线索，最终8000字符仍是原文证据。

最小替代是只完成原生抽取/关键词兼容探针，它不能回答跨文档质量。默认分隔符文本抽取是SDK另一方案，少一个JSON约束但更依赖分隔符/容错；当前glm标准API已在旧短探针返回过JSON，因此优先JSON。新的实体/关系schema并未被旧短探针验证，须真实小探针通过后再建全图。

本轮不升级/安装依赖，不改原52单元/语料/查询/标签/向量缓存，不调A2/A3，不生成答案/用例或实现MCP/服务，不实现文档更新/复杂权限/CPU Embedding。

## 2. 固定源码与一手证据

- SDK发布wheel1.5.7，SHA256 `895b81d94ca447afc6290c0e049d339f6caed46fbf29e4324f6db987046c6fcb`；官方tag commit `28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c`。实际读取本机已装1.5.7，B0 manifest记录172个SDK源码的RECORD校验身份。来源：[发布包](https://pypi.org/project/lightrag-hku/1.5.7/)、[固定源码](https://github.com/HKUDS/LightRAG/tree/28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c)。MIT；本项目只接接口，未复制第三方算法源码。
- Modular参考保持main/f658c5a4011c8b826707a65a3b11ce9301b0626f：所读EmbeddingFactory与LLMFactory分开，摄取refine/元数据和重排是LLM消费者，不等同LightRAG原生抽图。详见[参考核验](../research/modular-rag-mcp-server-2026-10-09.md)。
- 本轮读到1.5.7 `pipeline`的C自定义切分→`extract_entities`→`use_llm_func_with_cache(cache_type=extract)`→EXTRACT role→原生JSON parser→merge/EXTRACT summary→实体/关系VDB；查询`aquery_data(mix)`→`get_keywords_from_query`→KEYWORD role→原查询/高低关键词Embedding→实体/关系/片段召回→关联原文→round-robin去重→token裁剪→结构化chunks。
- `llm_roles.py:180`只把role raw_func绑定hashing_kv/kwargs，不把role名称直接传给回调。需显式EXTRACT/KEYWORD闭包；QUERY/VLM和base回调直接报错，不能凭_priority猜角色。摘要也使用EXTRACT角色，依据固定native协议分初始JSON与无system/无JSON的summary调用。
- `operate.py:4181`原生JSON调用是system/user及response_format=json_object；`prompt.py`schema为entities{name,type,description}与relationships{source,target,keywords,description}。它不同于旧generation_probe的entities/relations/keywords/quote，不能复用其固定SOURCE/FACTS/validate_extraction。
- `operate.py:611`摘要调用cache_type=summary；`utils.use_llm_func_with_cache`并不把cache_type/chunk_id透传到provider回调。单纯统计extract role不能自动分清抽取与摘要，需协议分类及SDK缓存/来源索引关联。
- `operate.py:5047`关键词调用返回high_level_keywords/low_level_keywords；非空QueryParam手填关键词会绕过模型，这轮不预填。`_perform_kg_search`把原查询及逗号连接的高低关键词作为query Embedding输入，不能只复用旧4个查询向量。
- native实体/关系描述形成新的document Embedding输入，可能有多次合并后更新；`_truncate_vdb_content`可裁剪派生描述。它们不是原52正文向量；按实际输入hash记账/缓存，派生文本裁剪另列诊断，公共正文变化直接失败。
- `_merge_all_chunks`按向量→实体→关系三路round-robin去重，非本项目RRF；出口不提供统一可比较cosine。保留native顺序，不伪造融合分。
- 原生JSON parser及关键词parser有容错/跳过行为；批量Embedding预计算和图关联选片段存在捕获后回退路径。本项目callback失败计入不可清除的失败状态；SDK吞掉它或回退也不能标complete。记录固定类别回退事件，不把正常无图命中与IO/模型失败混为一谈。
- SDK `llm/zhipu.py`导入时检查并可安装zhipuai，函数有3次重试且还依赖openai。故不导入该适配器，沿用本项目标准HTTP方式，不扩展新依赖。
- [智谱对话官方契约](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8)本轮列出glm-5.2、Bearer、thinking和messages；Embedding以已实测标准端点及旧探针响应为依据，不能由通用文档证明新输入成功。两个端点无认证HEAD均401，证明当前网络到达且需认证，不证明Key有效/模型权限。记录在data/research/b1-design-20261010/endpoint-reachability.json；没有POST或新模型调用。

以上为源码/文档/HEAD事实。模型当前权限、原生输出、图质量和本次请求量仍未知。

## 3. 数据流与自动阶段门

```text
原公共语料/A1缓存/B0结果 → 严格前检、按scope分池
                   ↓
原生小探针：CASE-001中TC-01完整单元 + Q01关键词
                   ↓ 通过协议及真实native parser；失败保留输出并停止
两个新workspace：11源/52单元；CASE-001/10单元
                   ↓ C（去掉!，原chunk回调不变）
EXTRACT JSON → native实体关系/摘要 → graph及辅助VDB
                   ↓ flush/finalize；新进程审计
同索引naive诊断 + mix四题（KEYWORD/关键词Embedding）
                   ↓ native chunks、graph来源和原生顺序
原文映射/完整8000 → 最后加载固定标签评测 → 报告/完成标记
                   ↓
无Key/全网络阻断的新进程重放 → 原生结果与评价一致
```

小探针直接调用固定SDK `extract_entities`，仅传CASE-001/TC-01原单元的native ID/content/file_path/tokens，保留其真实来源；不是重新包装成一份伪文档，不产出Recall或共同52单元完成声明。关键词直接调用native `extract_keywords_only`，输入原Q01，无手填关键词。JSON/完整结束状态/native parser及来源通过后，需至少一个实体和一条关系，证明选定完整用例可产生可用图输入；合法空抽取标pilot_no_graph_signal，保存真实输出并停止完整建图，不重试。零结果对其他普通片段仍合法，逐片段报告。

小探针成功响应以完整request hash保存，完整阶段只有实际请求完全相同时复用，不保证可以省掉指定次数。抽取/关键词真实响应不人工修补，不拼入预期关系，不把标签交给provider。

完整阶段复用Spec0008的原source/native ID/输入hash/闭包chunk/原文映射。两个scope独立存储和进程，范围在建图前约束，范围外不作关系桥。原raw Markdown进full_docs；自定义C输出52/10公共单元；不使用B0的C!旧存储转为建图，避免复用已processed跳过抽取。新建B1目录，不写B0。

## 4. 模型适配、响应与调用控制

唯一凭证为已授权标准Key，通过NAIYUE_RAG_ZHIPU_API_KEY在live子进程环境传入；不在CLI参数/job/SDK config/metadata/日志/缓存中保存，不加载真实.env。replay环境不带Key。父进程本身不发HTTP；仅新transport允许两个明确HTTPS端点，NoRedirect、不自动安装/换模型/重试。

| 角色/用途 | 请求 | 回调返回/检查 |
|---|---|---|
| extract_initial | glm-5.2、native system+user、JSON object、max_tokens4096 | 严格唯一JSON键；顶层仅entities/relationships；实体3字段、关系4字段为非空字符串；规范化唯一名称/端点存在/非自环；最多40总记录/20实体；native parser无静默丢弃才通过 |
| extract_summary | glm-5.2、native摘要user、无JSON强制、max_tokens1200 | 非空text；摘要是模型合成而非原文quote；保留真实文本/hash及来源索引，后续SDK裁剪记录 |
| keyword | glm-5.2、native关键词user、JSON object、max_tokens1024 | 仅high_level_keywords/low_level_keywords两列表，字符串非空；空列表合法，保存无图关键词路径；不改词或补预设关键词 |
| query/vlm/base | 禁止 | 意外调用立即记错误，不能返回假空正文 |
| embedding document/query | embedding-3，2048维，batch≤16 | 原52正文/4查询精确缓存命中；新描述/关键词按context+输入hash缓存，未命中才HTTP；顺序/重复/空批/维数/有限非零校验 |

严格JSON校验在native容错parser前执行，是实验协议门；不声称这个门证明内容正确。原生描述没有quote字段，不能替它编造逐条引用。native名称/类型规范化与本版本规则一致，若parser仍跳过记录，记录原/实际计数并失败。非空history属于本次关闭gleaning后的意外调用，失败；hashing_kv只作SDK内参，不发到API。其余未知provider kwargs报协议错误，不静默吞参数。

所有chat请求stream=false、thinking.type=disabled，不传tools或reasoning_effort，不额外加temperature；按实际SDKprompt构建messages，不追加隐含系统指令。结束状态必须stop，恰一assistant choice、无tool_calls，非空reasoning_content标关闭思考未达预期并失败；length或损坏正文保存安全诊断，不缓存为成功/自动改prompt。收到usage先记录，即使后续协议失败也保留。

新Embedding输入本地o200k tokens≤3072、UTF8≤12288 bytes；这是本机保护阈值，不声称供应商tokenizer一致。复用send_batch的标准HTTP/validate_vectors/validate_usage必要机制，独立配置不调用旧整套56输入/5请求限制或改变其CLI。超限文本不擅自截断，由本轮报告说明；SDK辅助描述裁剪在它已发生的位置单独记录。原始片段缺缓存不得补HTTP，直接shared_corpus_mismatch。

| 工程参数 | 本轮推荐值/行为 |
|---|---|
| HTTP超时/响应上限 | 60秒；chat1MiB、Embedding4MiB，超限失败 |
| 并发 | 所有实际HTTP共享asyncio.Semaphore(2)；SDK EXTRACT/KEYWORD各max_async=2，embedding=1，insert=1；同步urllib经asyncio.to_thread，Key不放asdict owner |
| SDK role timeout | 70秒；网络实际60秒，pipeline硬截止仍由父进程监督 |
| 运行总截止 | live3600秒；pilot120、历史build1800、单文档build600、每scope query300秒，启动/IO从总时扣除；不保证达到截止前完成 |
| 防循环数量 | 最多160次chat HTTP、128次Embedding HTTP、2048个新增Embedding输入；全scope/pilot共享计数，SDK重试相同失败request key也不重复发HTTP |
| 自动重试 | 0；同request failed/inflight缓存状态再次调用失败，不借SDK回退重发；错误是不可清除的本轮失败状态 |
| 费用 | 沿用用户取消费用门槛的授权，不设金额阻断；累计实际usage，价格/账单无数据则unknown，不填0或沿用旧标价冒充现价 |

数量和时间是工程停止条件，非费用预算；达到时保留partial与已尝试请求，不扩大限额重跑。父进程超时kill/reap；供应商已开始的处理可能继续，未收到usage不能编造0消耗。活跃运行每60秒以内读取checkpoint给用户有变化的进度；不创建后台自动化。

## 5. 缓存、追踪与SDK错误边界

逐实际请求在发送前持久化intent：request_id、角色/阶段、canonical输入hash、数量、状态attempted、UTC/单调计时；HTTP结束追加终态、HTTP码、response_model/finish_reason、usage、响应hash或固定错误。日志不保存Key/headers/原始供应商错误文本，实际响应含Key即拒绝持久化。仅授权合成材料的成功正文/向量进入Git忽略的data；不存在输入材料时不造示例结果。

应用cache identity包括SDK/prompt/config hash、endpoint/model/维度、角色或Embedding context、完整messages/输入文本与输出参数，不含Key；相同请求只读实际成功缓存。缓存success文件hash与manifest关联，失败和在途不能当success。SDK内部缓存命中可能绕过callback；报告分别列native缓存条目、callback次数、应用缓存命中、HTTP次数，不从callback计数倒推完整SDK命中数。pilot记录不会冒充全库调用。

SDK raw callbacks通过普通闭包引用状态，EXTRACT初始/摘要与KEYWORD显式绑定身份；set_role metadata仅非敏感binding/model/host。Key只有transport持有，不传SDK llm_model_kwargs。本轮禁止直接导入lightrag.llm.zhipu/openai，继续保留runtime安装和未授权进程启动阻断。replay启用完整offline_guard；live transport不使用全局禁止网络的B0 guard，但显式端点及认证请求边界可见。

保留SDK原生异常/回退的固定类别事件计数；callback失败、传输/IO失败即使被SDK捕获，也由worker完成门核对journal失败/inflight/计数和doc_status，强制error。一次独立排障按AGENTS复现→单假设→修源；连续三次失败停下来报告，不在服务失败后改测试或补假向量。

## 6. native图/向量与来源验收

沿用B0完整52/10单元、正文/contexts/input hash/ID/行号与原源校验；B1 doc_status须processed、custom_chunking_func、无skip_kg/硬split/公共正文改变。全库pilot之外，存在实体和关系才说明真正走了图路径；空图报告无图信号，不写图验证成功。

实体/关系/GraphML、辅助Nano矩阵、full_entities/full_relations及entity_chunks/relation_chunks锚点真实保存并新进程读取。每个非空source_id按SDK `<SEP>`拆分，必须属于当前scope映射且正文真实存在，native file_path与这些来源匹配；源码内部无向关系不伪装成有向业务因果。source provenance只能证明抽取来源登记，不能证明描述/关系被原文支持。

配置max_source_ids_per_entity=128、max_source_ids_per_relation=128、max_file_paths=64，覆盖本Mock最大52/11；任何来源省略/占位符要显式失败。辅助VDB每条实际content hash与已成功Embedding/cache对应、矩阵float32且归一化一致，沿用rtol1e-6/atol1e-8；记录中间Embedding输入、最终实体关系数量、最终矩阵数量，不能把中间请求数当节点数。只公共正文向量须与旧cache对应；辅助VDB非旧向量，不虚称完全相同。

保留默认阈值机制但显式参数：JSON=true、entity_extract_max_gleaning=0、max_records=40/max_entities=20、force_llm_summary_on_merge=8、summary_context_size=12000、summary_max_tokens=1200、summary_length_recommended=600、addon_params.language=Chinese、kg_chunk_pick_method=VECTOR、related_chunk_number=5；不改native模板/实体类型guidance，不人为加业务关系。prompt.py/配置进入manifest。共享Embedding batch16、model/维度、C自定义chunk3072/overlap0/heading false和cosine threshold=-1沿用B0；这个负阈值会增加无关图命中，是固定配置的限制而非默许生产设置。

跨文档可能把旧/新同名功能描述合并，时间或否定语义未必保持。因此graph descriptions只存诊断，不直接作为最终正确规则；原文证据继续附角色、源版本和真实位置，上层Agent结合当前需求判断改动/回归。真实资料上的名称冲突、版本有效性和更新一致性仍未验证。

## 7. 查询、排序与共同预算

新进程先audit，然后每题在自己的scope索引跑naive诊断与mix。naive须仍保持B0候选/返回/指标，分数只按float32预定容差比较；意外变化是接线/配置问题，不能用它解释图收益。mix原生top_k=20、chunk_top_k=20、max_total_tokens32768、max_entity_tokens6000/max_relation_tokens6000、rerank=false、disable_user_prompt_prefix=true，不预填关键词、不生成答案。

mix返回native chunks顺序就是实验排名；严格核对chunk_id/content/file_path/范围，映射回原单元。graph元数据与原文独立保存，不加入8000返回正文，不把description当body或替缺失片段补原文。rank从1起，score=null、score_kind=native_order、retrieval_method=graph_mix，不冒充cosine/RRF。扩展pack_evidence允许这一组合，前缀`[graph_mix rank=01 order=native]`补空格至35加换行，总36；旧vector/sparse/hybrid路径逐字保持，公开函数签名不变。

分别报告dense raw、native graph entities/relations/source_ids、native mix chunks与最终selected。native round-robin出口丢失逐片段三路来源字段，因此graph_source_supported/vector_supported只是来源支持诊断，不宣称纯图贡献或精确“哪一路获胜”。如果未加侵入式hook，就把内部未观测的round-robin完整池/细分丢失排名记unknown；不猜测其得分。保留native processing_info、派生描述裁剪/正常WEIGHT回退与预算丢失事件。

所有retrieval完成后才加载原固定assistant_constructed/not_reviewed标签；评价A1、A2参考、B0、B1 Recall@10/20与Coverage@8000、逐条必要原文去留/退化。A2参考读取原已验证结果/评价，hash固定、不重新调参。Q04仍answerability=unknown，不能照抄insufficient标签。工程完成与质量收益分开：工程通过后如质量不提升照实保留，不改标签/语料/预算提高分。

## 8. 影响文件、入口与产物

先搜后写已发现generation_probe/vector_embedding仅固定探针，B0_callbacks仅缓存/禁LLM；不更改其协议。预计新graph_transport.py、graph_callbacks.py、graph_worker.py、graph_probe.py及4对应测试；旧vector_index.py/其测试仅扩展native_order前缀，约10源码/测试文件，超过8但无新服务/依赖；每源码≤500行。graph_worker可调用B0的chunk能力和runtime校验、监督；graph图审计独立，不放宽B0空图验收。已出现第三次重复的固定响应/监督机制优先复用现有helper，不复制三套。

新CLI experiments.graph_probe以`--config`读取本次data目录的运行JSON，上述mode=live/replay、dataset/corpus_run/tasks/vector_run/b0_run/a2_run/runtime_python/runtime_lock/sdk_version、chat_endpoint/chat_model/embedding_endpoint/embedding_model/dimensions、output_root/tokenizer_cache/tokenizer_encoding、candidate_k/共同与native预算、JSON/gleaning/抽取/摘要/关联片段/来源上限、各角色max_tokens、timeout/deadline及数量上限均在JSON显式提供，禁止未知字段和凭证字段。replay可用`--mode replay --graph-run 完整目录`覆盖这两个调度字段，原公开入口不变。完整配置写产物且不含Key；固定值按第4/6/7节校验，不隐式继承SDK env；现存requirements不改。

实施前核对真实document_id为MOCK-CASE-001，Spec中CASE-001是样本简称；pilot据该ID及case_id=TC-01精确选择，不用标题模糊匹配。

产物：summary（最后完成标记）、graph_manifest、unit_mapping、native_storage_audit、native_queries、results/evaluation/report/failure-analysis、provider request intent/终态与成功cache、pilot报告/结构化结果、每scope原生索引。原A/B0目录只读。live失败partial可审计但不能replay为成功；本轮不做自动续跑/恢复服务。

replay核对原源/查询/向量/B0/A2参考hash、SDK/锁/prompt/策略、native完整文件hash与所有成功cache身份；没有Key，完全阻断网络，不重摄取或补建。先原生重载/审计再四题naive/mix，cache miss错误；results除timing外一致、evaluation字节一致才通过。查询可能首次将keyword cache写入SDK，live最终存储快照必须在四题查询/flush/finalize后制作；replay后hash保持。

回退边界：停用新入口即可继续A/B0；保留失败与partial，不自动删除workspace/回滚或覆盖缓存。10倍语料会扩大抽取/描述更新及存储量，当前数量/时间门明确阻断，不声称可扩到真实全库。

## 9. TDD与验收命令

实施先确认新模块缺失的预期红灯，再最小实现。离线fake HTTP/响应只用于错误与协议测试，真实SDK parser/保存重载另行执行；不把替身视为真实服务结果。

- 正常/空抽取、原生JSON schema/规范化/重复/悬空端点/native静默跳过；错误JSON/重复键/截断/意外思考/工具调用/角色/kwargs；原生初始/摘要/关键词三类body和身份，query/vlm禁止。
- 缓存向量顺序/重复/空批/finite/维数/旧正文miss，新描述和关键词真实请求身份；超token/bytes/batch、密钥在响应中、重定向/401/429/5xx/超时/超限响应、usage未知和已知用量保留。
- intent IO失败不发请求、失败/inflight不重试、应用cache与SDK缓存分开、并发2/数量/截止、线程等待与child kill/reap、部分终态unknown、SDK吞错/回退仍失败。
- 真实SDK C与graph source_ID/current scope、图/锚点/VDB保存后新进程核验、公共正文不变/完整长用例、空图/缺来源/范围外/派生文本裁剪诊断；原B0所有测试与全部旧368通过。
- naive同基线、mix native_order/score null/36字符前缀/8000完整证据、旧pack输出不变、标签后置、空结果/预算排除/无答案unknown；完整replay/损坏缓存不补建；报告IO或截止后无complete。

计划验证（本轮未执行）：

```sh
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q experiments tests
.venv/bin/python -m pip check
.venv-lightrag/bin/python -m pip check
git diff --check
```

live/replay的实际argv和每请求角色/usage/截止在实施产物保存，不预填调用次数/图规模/分数。应用构建不适用。验收必须同时满足公共片段/范围与原生图/来源/缓存/失败可观察/无Key重放，指标和估算费用另列；没有真实账单则始终unknown。尚未有实现/接线/本次服务/质量结果，也无本人理解或独立实现登记。

### 本轮实际设计检查

执行`.venv/bin/python data/research/b1-design-20261010/validate_design.py`与`git diff --check`，均退出0：7份文档broken_local_links=0/trailing_whitespace=0，当前代码snapshot/原源码/原85包环境一致，实际独立SDK runtime与B0 manifest完全一致（172源码RECORD身份）；B1源码/测试模块均不存在，新模型调用0。脚本/结果在Git忽略的data，元数据网络访问与无认证HEAD不是模型请求。L1规范/指导入口存在；L2实现/L3接线未完成。功能测试/应用构建本轮不适用，368绿灯为前轮结果未重跑。

**设计阶段下一步（已授权）：用户“继续”确认实施；当前调试状态与唯一下一步见第10节。**

## 10. 2026-10-10部分实施与调试停止（历史）

用户“继续”确认本Spec后开始TDD。预期红灯6failed/30errors（新模块缺失）。graph_transport.py、graph_callbacks.py、graph_worker.py是实质实现，graph_probe.py尚未创建；4新测试文件存在。原vector_index仅增加graph_mix/native_order且score=null的36字符前缀，公开签名与旧分支保持。新前缀测试初始字面量错误写成37字符，在缺模块红灯阶段改为36字符契约的3个空格；保留严格总长度断言，不是放宽预算。

标准HTTP/协议测试实际`19 passed in0.02s`；journal/callback实际`6 passed in0.02s`。缓存文件损坏未被重新检查：1failed→仅保留inflight任务、成功后重新校验磁盘cache→回归通过；原生async parser必须在写success前完成：1failed→await原生校验→6passed。失败响应已知usage保留、intent先写、不重试、并发相同请求去重和全局数量界限有实际离线回归。

真实SDK＋模拟HTTP的同一集成测试连续三次未通过：

1. 复用B0 Callbacks时payload缺dimensions，KeyError；按config明确传入2048维。
2. 注册视觉角色用了vision，固定SDK实际RoleSpec为vlm；已按实际源码修正并同步Spec。
3. build与新进程query断言已经通过（模拟服务、原生图2节点/1边及10完整片段），replay段配置mode=replay而graph_run=None，被完整入口validate_config拒绝：config: invalid_graph_config。

按用户AGENTS调试协议连续3次失败停止进一步源码编辑，不继续尝试修复或新增graph_probe。当前只确认第三次失败触发条件；待验证的假设是父入口的graph_run要求与内部worker直接working_dir/cache_root定位产生校验边界耦合。下一次先核对两层契约，不放宽公共入口的完整缓存检查，不通过skip/放宽断言掩盖失败。尚未修复第三项。

实际失败命令：

```sh
.venv/bin/python -m pytest -q tests/test_graph_worker.py::test_actual_sdk_graph_store_scope_and_reloaded_query_with_fake_service
```

最后输出`1 failed in1.09s`，退出1；日志为data/experiments/b1-probe-evidence/worker-regression-vlm.txt。标准层与缓存命令分别为pytest -q tests/test_graph_transport.py和pytest -q tests/test_graph_callbacks.py，结果19/6 passed。compileall -q experiments tests退出0无输出，仅语法检查，不是功能通过；应用构建不适用。全量测试尚未重跑且新测试仍红，不能声明全部通过或提交。368项是前轮B0结果。

现存62文件快照仅vector_index.py预期变化；旧源/测试/Mock/requirements/.gitignore保持，其余61不变，两环境freeze与实施前一致。新源码130/183/201行，均≤500。没有真实Key落盘/.env修改、安装/升级、真实模型请求、真实图或质量成绩、提交/push。当前Key未注入运行环境，尚未使用已授权真实凭证。模拟响应/向量及其usage只作离线工程测试，不是智谱服务证据。

L1：Spec、3模块、4测试存在，父入口缺失；L2：协议/HTTP/journal/回调/SDK graph worker有实际实现；L3：SDK＋模拟服务的build/query段运行，但replay仍失败、完整CLI/真实小探针/全库对照未接线完成。代码课堂暂停，无本人掌握登记。partial-validation.json保存上述检查，data被Git忽略。

**当时下一步（已完成）：修复父入口/worker配置边界并继续实施；当前唯一下一步见第11节。**

### 继续执行时的配置边界修正

用户再次“继续”后先复现原红灯。公共validate_config签名不变，仍要求replay graph_run非空；提取共享目标/字段/数量校验供父入口和worker使用，内部validate_worker_config不要求父调度字段graph_run，因为job已提供working_dir/cache_root。query worker先要求scope存储目录存在，再由原生audit核对完整正文/图/来源，不创建缺失索引。新增回归同时保持公共入口缺graph_run拒绝与内部原测试回放通过；不改原断言/测试输入。

### 真实服务中发现的向量审计对应关系

首次live run在历史52单元/237实体/305关系和三题查询完成后，单文档矩阵审计报native_vector_mismatch。110次HTTP均成功；同一文本在不同批请求中实际有不同向量，审计vector_pool按文本hash覆盖为任意最后一条响应。41条单文档关系矩阵与此前真实成功响应精确一致，但与被覆盖后选的另一响应不同。修正只保留所有实际成功候选及request ID，要求矩阵匹配其中至少一个真实响应，rtol1e-6/atol1e-8不变；不平均/替换原生向量，不更改检索排名或业务标签。新增回归验证两次相同输入均可追溯。服务向量跨批差异是本次观察，不能归因SDK或宣称提供方绝对确定。

失败run保留。修正审计后在本机data内进行一次明确的工程复核：新结果目录复制原已持久化native和完整成功provider-cache/账本，先只读审计两scope，再完成尚缺Q03查询，按原全部数量/时间限额追加实际请求并累计原110次；不重新抽图/补正文向量、不更换任何输入/参数/模型，不添加自动续跑CLI。复核结果标revalidation且注明原失败run，原summary不覆盖。最终manifest在完整审计/四题查询后制作，再用原公开replay入口无Key验证；不能把原partial目录直接replay为成功。

## 11. 2026-10-10继续执行与实际收尾（当前）

用户再次“继续”恢复已授权实施，未重问方案/模型/Key/预算。先重现原配置红灯；共享约束与父入口/worker边界分离，公共validate_config签名不变且replay仍要求graph_run，query worker要求scope目录存在。原真实SDK＋模拟HTTP测试和新增边界回归7 passed in1.53s；原断言/输入不改。4新模块、5新测试（含单一边界回归）及vector_index前缀完成，约10源码/测试文件，无新依赖/服务。

父入口缺模块6errors预期红灯→实现；首轮2failed/6passed源于worker目录未建立，最小修源mkdir→完整原生SDK/模拟HTTP测试1passed。成功缓存已写但终态提交失败仍会被读取：1failed→要求request terminal=success及response hash一致→回归。向量审计单值覆盖：1failed→保留多个实际成功响应/record ID，原rtol1e-6/atol1e-8不变→42新测试通过。最终410 passed in39.95s（原368保持），无skip/放宽/conftest或旧helper修改。当前4源码140/185/207/227行；现存62快照只有vector_index预期变化，其他61文件不变，两环境freeze一致；无升级/.env/其他仓库/提交/push。

### 实际真实服务与工程复核

Key仅通过关闭回显的stdin临时注入进程环境，不在配置/代码/job/日志/缓存/.env中保存。真实小探针原生解析6实体/5关系，关键词成功；这只证明协议路径，不登记关系正确。首live目录为`data/experiments/b1-lightrag-mix/20261010T092041Z-aac33128`，CLI命令：

```sh
.venv/bin/python -m experiments.graph_probe --config data/experiments/b1-probe-evidence/live-config.json
```

实际exit2，`status=error attempts=110`，category=native_vector_mismatch。历史scope已经写入52单元/237实体/305关系并完成Q01/Q02/Q04；单scope的10单元/53实体/72关系也实际保存processed，但审计器错误选择同文本另一条成功向量。原110次全部HTTP成功、无failed/inflight，原失败summary及所有原生文件/成功cache/账本保留，不改成成功。

修复后执行一次明确本地工程复核，不添加自动续跑入口：`data/experiments/b1-probe-evidence/revalidate.py`新目录复制并记录原native/cache文件hash，按原run ID秒级时间起点扣总3600截止；先校验原失败类型和完整请求终态，重载两scope原生图/向量审计，再查询全部四题。原三题缓存复用，只新增Q03关键词1请求及关键词Embedding1请求，原112累计计数仍受160chat/128embedding/2048新输入限额。未重新抽图/替换原生矩阵、未改变语料/标签/参数或人工修模型输出。

```sh
.venv/bin/python data/experiments/b1-probe-evidence/revalidate.py
```

实际exit0：

```text
status=complete attempts=2 output=/Users/zmw/naiyue-rag/data/experiments/b1-lightrag-mix/20261010T093445Z-04ab215d
```

报告标execution=engineering_revalidation/first_failed_run，原失败目录不覆盖。向量绑定保存匹配的真实request/cache ID，最大误差1.4901161e-8；同文本跨批差异最高观察到约1e-3量级，不把它与float32审计容差混为一谈。完整图/矩阵/锚点/52和10正文/来源范围核对通过；两scope分别237实体/305关系与53实体/72关系，模型描述是派生数据而非原文事实。CLI从零live修复后未再付费重复跑一轮，完整产物来自这次可追溯工程复核。

### 标准入口无Key重放

```sh
env -u NAIYUE_RAG_ZHIPU_API_KEY .venv/bin/python -m experiments.graph_probe --config data/experiments/b1-probe-evidence/live-config.json --mode replay --graph-run data/experiments/b1-lightrag-mix/20261010T093445Z-04ab215d
```

实际exit0：

```text
status=complete attempts=0 output=/Users/zmw/naiyue-rag/data/experiments/b1-lightrag-mix/20261010T093652Z-8142cfdd
```

完整manifest核对源/查询/原向量/基线参考/SDK/锁/prompt/当前adapter/策略及native/provider所有文件hash；无Key、网络阻断、不摄取/补建。results与evaluation逐字节一致，native/provider文件hash保持，新HTTP0。重放账本含历史112请求，不冒充重放新消费。

### 调用、接线与质量

累计真实HTTP112：初始抽取52、描述摘要1、关键词4（chat共57）；document Embedding51、query关键词Embedding4（Embedding共55）。新增Embedding输入705，包含中间描述更新/重复批输入，不能当成最终节点数；原正文/原查询用旧向量。无HTTP失败/在途/未知usage。chat输入104897、输出35760、总140657tokens；Embedding输入/总27725tokens，供应商用量与本地o200k统计分开。未核验现价/账单，估算与真实费用unknown。

| 任务 | A2 Recall20/必要返回 | B0 Recall20/必要返回 | B1 Recall20/必要返回 | B1条/字符 |
|---|---|---|---|---|
| Q01 | 5/8，3/8 | 4/8，2/8 | 4/8，2/8 | 13/7690 |
| Q02 | 1/5，1/5 | 1/5，0/5 | 0/5，0/5 | 15/7631 |
| Q03 | 2/2，2/2 | 2/2，2/2 | 2/2，2/2 | 10/6843 |
| Q04 | N/A，N/A | N/A，N/A | N/A，N/A | 13/7792 |

naive诊断的候选/返回顺序与B0一致，分数在预定容差内；B1 native_order/score null/36字符前缀、原文/版本/定位/完整8000接线。Q01 E02/E04返回，E01/E03候选中但预算排除；E05–E08不在mix前20。Q02原向量候选20的E03没有进入mix前20，其他必要证据也未进入。Q03保持；Q04unknown。原生mix merged35/38/10/37→最终20/20/10/20，详细内部逐路池/归因未观测，不猜排名。

查询返回图metadata的source_id集合覆盖Q01 E06/E08以及Q02 E01/E05/E06/E07，但这些必要原文未进入最终候选；这是登记/证据选择的差别，不证明模型关系正确或纯图贡献。固定当前配置不适合替代A2，无质量提升、Q02退化；不能排除其他图配置或真实材料效果。合成assistant_constructed/not_reviewed，无真实业务/更新/生产/MCP/生成用例或答案/本地CPU Embedding证明。累计原run秒级起点到工程复核848960.518ms含修复/等待/复制/IO，不是性能基准；表中token来自服务真实usage。

L1：4模块/5测试/前缀及入口存在；L2：显式标准HTTP、严格原生协议/native parser门、intent/终态/精确cache、多响应向量匹配、真实SDK图/锚点/范围/监督/评测；L3 main→run/prepare→pilot→EXTRACT/KEYWORD闭包→C chunk/原向量或真实辅助Embedding→graph merge/flush→新进程audit/query→map_native/pack→检索后labels/evaluate→最后summary。标准replay实际走manifest/hash/原生重载/缓存/无网络/评价。代码课堂暂停，未记录本人理解/独立实现或面试能力。

实际验证：pytest -q tests→410 passed in39.95s；compileall -q experiments tests退出0/无输出，仅语法；两环境pip check均No broken requirements found.；git diff --check退出0/无输出。应用构建不适用。final-checks.json与final-green.txt、原失败/复核/replay日志在data/experiments/b1-probe-evidence，Git忽略。

[完整报告](../../data/experiments/b1-lightrag-mix/20261010T093445Z-04ab215d/report.md)、[失败分析](../../data/experiments/b1-lightrag-mix/20261010T093445Z-04ab215d/failure-analysis.md)、[重放](../../data/experiments/b1-lightrag-mix/20261010T093652Z-8142cfdd/report.md)。

**唯一下一步：汇总五组实验并讨论首期技术路线取舍，区分Mock证据与真实材料验证要求；不继续调本次配置掩盖失败，不直接做MCP或完整产品。**
