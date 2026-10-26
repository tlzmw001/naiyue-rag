# Spec0007：A3已有引用与名称配对的文档内检索

日期：2026-10-10（America/Chicago）。用户“是的”已确认并完成本Spec实施与离线对照/重放；工程验证通过，当前A3质量退化，实际结果见第10节。五组总范围已确认，实施使用本Spec的遍历/分文档召回/融合方案；代码课堂仍暂停。

## 1. 问题与固定输入

A2实际必要返回：Q01 3/8、Q02 1/5、Q03 2/2；Q01的E05/E06和Q02的E05/E06/E07未在两路前20，另有融合和预算遗漏。A3考察能否沿已有文档关系找到关联文档，再在这些文档中检索具体原文，改善跨文档证据集合。

A2向量路径已经对范围内全部片段评分，关键词矩阵也包含全部范围内词项；只列出关联文档再按相同全局排名截前20可能仍得相同结果。推荐“关联文档内各取少量相关片段→形成关系路由→与A2融合”；其变化包含文档候选范围、每文档配额和额外融合，不称纯图连边的单变量收益。

固定dataset=`examples/mock-v1`、tasks=`examples/mock-v1/tasks.json`；11历史源/52单元；corpus=`data/experiments/common-evidence-corpus/20261010T021859Z-647de42b`，fingerprint=`65d494952ab388ef3ca80bec1ce024e4e1676255ae2a7a3d80249e403aa8ca7e`。

完整向量源=`data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e`；原A2关键词索引/结果源=`data/experiments/a2-bm25-rrf/20261010T054002Z-99569e55`，不使用只含引用/结果的重放目录作原生索引源。输入context-body-v1、原query、模型/维度、BM25配置、标签、前20及8000预算保持对照约束。

本轮为本机合成材料的离线CLI/库实验，无API入口、账号/Key要求、安装或新增依赖；原56向量与BM25索引只读复用，模型请求0。A3不包括业务规则有效性判断、答案/用例生成、模型抽图、重排、MCP或真实资料适配。

## 2. 实际材料与组件取舍

2026-10-10只读load_corpus及scan_source观察：11源含22处单行内联Markdown引用，20处目标在当前语料，2处目标不在语料（当前导航仍引用本次任务）。3组文件名配对为CASE-001↔L2-001、CASE-002↔L2-002、CASE-L1-001↔L1-001，均已有显式链接支持。没有新增关系索引或质量实验；数量只是当前Mock观察，不作为程序硬编码或真实全库声明。

可直接核对的路径：

- L2_REQ_001_joint_prediction.md第8行→L1_dispatch.md；L1_dispatch.md第17行→L2_REQ_002_strategy_split.md，两个链接可提供拆分需求候选。
- L2_REQ_002_strategy_split_测试用例.md第7行→L1_dispatch.md；反向查“谁引用策略模块”，可取得拆分用例候选。原引用方向仍为用例→模块，遍历反向不变成“模块声明这些用例正确”。
- L1_prediction.md第14/15行分别引用初始需求和命名需求；可经初始需求的反向引用→预测模块→命名需求，两跳到达。
- 初始需求→策略模块→拆分需求→配套用例是3跳；首轮不会把它记成2跳。本Mock用例另有上层链接，可走另一条2跳路径；其他语料是否有这种路径未知。

**推荐组件接法：**现有scan_source/source_span＋标准库相对路径处理及有界队列遍历，JSON/JSONL关系存储；评分继续复用原cosine、jieba/BM25S和已有RRF。只实现项目需要的关系适配，不建立通用Markdown解析或检索框架；网络图数据库不参与本阶段。

依据（静态源码，无相关框架实跑）：

- [Modular](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER)，本机`/Users/zmw/MODULAR-RAG-MCP-SERVER`，main/f658c5a4011c8b826707a65a3b11ce9301b0626f，2026-10-10核对HEAD未变。HybridSearch.search→_fuse_results→fusion.fuse实际消费dense/sparse排名；所读查询链没有本Spec的Markdown引用/名称扩展。A3为本项目新增机制，复杂度不作为参考项目质量证明。
- 已装llama-index-core0.14.25：MarkdownNodeParser.get_nodes_from_node按标题/围栏组织正文，不提取本业务引用边；RecursiveRetriever._query_retrieved_nodes识别IndexNode并根据index_id调用已登记retriever/query_engine，TextNode直接返回，_retrieve_rec的query_engine分支还会查询并构造响应文本。它不能自动读Markdown引用、处理反向链接/名称配对/源行号。
- 同版本AutoMergingRetriever._get_parents_and_merge根据parent_node/child_nodes的已命中比例合并父节点，源函数使用docstore；本材料没有一对一的层级父子关系，正文完整单元与预算也不能无条件替换成父节点。

现有LlamaIndex递归检索可作为后续统一retriever API的候选，但本轮仍需自己登记业务边和来源；现在改成IndexNode/StorageContext会增大接线范围，并改变实验内部对象。原小型适配能继续使用已测评分内核并保留固定单元。最小替代是只沿直接引用或只返回关联文档ID；它不验证当前需要的两跳正文与旧用例补充。本Spec推荐有界两跳，框架重选留给真实材料/规模的证据。

## 3. 数据流与资源参数

```text
固定源/位置/版本 ─ scan_source/内联引用/文件名 ─ 关系索引保存→重载
原向量与BM25缓存 ─ 原A2重算并比原结果 ────────┐
                                             ↓
                           A2前5片段→最多3个非L0种子文档
                                             ↓
                查询范围内正向/反向引用与配对→最多2跳→最多8关联文档
                                             ↓
               各文档cosine前4＋原全范围BM25前4→局部RRF→各取4
                                             ↓
                      最多32单元→关系路由前20→与A2前20再RRF
                                             ↓
                        最终前20→完整8000证据→标签评价/追踪
```

参数经CLI显式提供，本次批准值为seed_k=5、max_seed_documents=3、max_hops=2、max_related_documents=8、per_document_k=4、relation_k=20、candidate_k=20、rrf_k=60、max_context_chars=8000、deadline_seconds=180、max_graph_nodes=64、max_edge_visits=128。布尔/非正/越界参数拒绝；首轮不是自动调参器。图节点超过64在建索引前失败，遍历超128边时明确resource_error，不静默截成成功；关联文档/片段数量配额的截断另记录。

所有基线/候选、关系路由、最终合并与预算的变化均可追踪；关系元信息仅为实验诊断，不拼进context_text。后续Agent适配若返回路径文字，必须重新把实际文字纳入预算。

## 4. 关系来源与缓存契约

只给构造器corpus.sources/registry与位置映射，不给tasks、evidence_units标签或manifest.expected_pairs。原load_corpus可继续核验manifest文档身份；配对不读取其中的答案配对。关系数据是线索，不是文档中的指令、操作授权、功能依赖/替代或规则有效性的证明。

### Markdown引用

使用已测scan_source的物理行/fenced/heading状态。支持一行内普通`[label](relative.md)`，包含表头块引用和导航表格；单反引号内代码及围栏内容不建边，图片/外部URL不建文档边。参考式链接、跨行/嵌套括号或复杂转义不猜解析：有可疑形式时登记unsupported_reference警告，原文保持。scan_source的blocked结构诊断使关系构造失败；原失准表头行号只作已有warning，不定位目标正文。

实施边界澄清：多反引号/未闭合行内代码所在行不解析引用并记unsupported_reference；剔除完整普通链接/图片后，残留`](`或参考式链接符号同样记录警告，防止跨行断裂引用静默消失。缓存load重推导来源事实只作完整性校验，失败报错，返回原缓存记录，不替换/保存为重建成功。A2基线复现的评分耗时另记录；关系阶段每题全范围BM25仅评分一次。

缓存字段类型核验使用规范JSON表示比较并拒绝非整数记录数；不能用Python字典值相等代替类型完整性（True==1、False==0会误接受布尔行号/字符位置）。该规则由伪造缓存且更新文件hash的失败回归确认，保持原索引 schema/源位置定义。

路径相对引用所在文档目录计算；UTF-8百分号解码一次，拒绝非法/残余百分号、绝对/Windows驱动/协议相对路径。resolve后必须在dataset/knowledge根内，并与当前registry中的规范relative_path精确对应；不扫描任意目标文件。越界/符号链接逃逸为可观察的blocked_target警告，无边、无读目标；根内但未索引的目标记target_not_indexed，无边、无中转。`#fragment`保留并记fragment_unresolved，只建文档级边，不声称章节锚点已验证；纯本文件锚点不触发扩展。

有向edge字段：schema_version=1、edge_id、kind=markdown_link、from_document_id/to_document_id、两端source_sha256、quote（完整原链接）、source_span（实际字符/行及源hash）、raw_target、canonical_target、heading_path。edge_id按种类/两端ID与版本/原字符范围及规范目标hash生成。引用所在原文必须能按span逐字切回；目标版本来自当前已核验源。重复原文不同位置为不同来源记录；同位置同边去重。

### 名称配对

只识别historical_test_cases文件stem的精确`_测试用例`后缀，NFC规范化、区分大小写，去后缀后与当前registry中唯一同stem的module/historical_requirement匹配；跨L1/L2目录也适用。不按相似标题、前缀近似、日期或模块词猜配对。无匹配/多个匹配/角色不合分别记missing_pair/ambiguous_pair/invalid_pair_role，不生成虚假用例。

配对edge统一从用例→来源文档，kind=filename_pair；source_span/quote为null，derivation记录filename-suffix-v1、两份真实relative_path/版本及stem。文件名关系不伪造原文引语。若同一文档明确的“对应需求/对应模块”表头链接与命名候选冲突，登记pair_conflict并停用名称边，显式链接仍是原文事实。其他上层/通用引用不自动视为配对冲突。

当前Mock格式中表头范围为首次二级或更深标题之前；正文中格式相同的引用继续作为普通链接，不能覆盖文件名配对。该边界有失败回归，不外推所有真实文档的元信息布局。

### 保存重载

新关系目录含edges.jsonl、diagnostics.jsonl、relation_manifest.json；manifest最后写，含complete/schema、语料fingerprint、关系/解析策略、scope节点表（ID/path/role/level/hash）、文件hash和记录数。只使用本项目固定文件名。加载检查文件hash、唯一ID、登记节点/版本、原文span、配对推导及所有策略；缺失/部分/损坏/源变更明确relation_cache_mismatch，无隐式重建。只在独立新UUID目录build；replay读取原完整A3关系索引，在新目录写引用/结果，不复制为新原始缓存。

边的遍历方向另外记录forward/reverse；反向和文件名配对不生成伪造的原文反向quote。两个方向都保留原edge_id和实际出处。当前3对配对均与显式引用重复，报告不能把全部收益归因于名称匹配。

## 5. 范围、种子与遍历

先复用validate_scope，允许节点为query.scope_ids或当前全语料，减exclude_ids；种子、边两端、中转及目标都限制在此集合。范围外节点不能作桥梁后再过滤。所有单元范围继续遵守原查询约束，本次任务不参与历史关系索引或中转，当前L1仍按当前导航标记。

种子取A2前5候选片段（不是已选返回），跳过L0，按排名去重文档，再取最多3个；不看标签，不按角色强制需求/用例各一。L0可以是关系目标与正文候选，但作为遍历终点，不能作为种子或中转扩散整个系统。

有界广度遍历正/反向Markdown与配对，所有边都计1跳；最多2跳，不给名称边免费额外一跳。环/自引用/重复目标不重复扩张。可同样到达的目标择最小(hop,seed_rank,target_document_id,edge_id序列,方向序列)路径，保持稳定；路径存种子片段/文档、每条实际边与遍历方向、hop_count。原种子文档不列入补充文档，避免无边也重排同文档的隐含变化。

待到达节点按上述路径优先序处理（先广度，再种子排名/稳定ID）；非种子文档被接受时立即占8个配额之一，超出者明确document_limit_excluded且不入扩张队列。不是先遍历所有节点后才截8，因此不能通过已经截断的文档到达更多目标。重复/更差路径不重新占配额，每个节点至多扩张一次；L0到达后只登记目标。无种子/无合法关系/无可补充文档时，原样回到A2候选与组装，不凭图空结果判无答案。Q03只允许CASE-001，其他文档不能中转，因此本轮该题不扩展到需求或模块；文本TC-02引用TC-01的部分条件不属于本轮文档边机制，不自动继承用例内容。

## 6. 文档内筛选与融合

扩展命中文档不等于全文相关。每个补充文档继续使用原缓存query向量，调用现有vector_index.search限于该文档，取4，分数为原cosine。BM25仍用原query范围的N/df/avgdl与原分词，取得全范围匹配分数后，仅筛选此文档并取4；不为每文档重建BM25统计或换Embedding输入。合法关联文档若没有可用单元，记录empty_document并返回空列表，不制造片段或将此情况报成IO失败。

当前keyword_index.search只返回前20，不能用它把已被全局截掉的片段补回来。新增score_all(index,query,tokenizer)作为已验证词项/有限正分数的完整范围评分接口；现有search签名保持，只从score_all结果切前k，旧结果字段、分数与顺序精确不变。A3每题只评分一次全范围，其他候选只是筛选，不新增模型请求。缓存范围/空词/OOV/有限数/实际词项命中规则继续生效。

各文档两路按局部排名重新编号、用原rank_fusion.fuse(k60)取4，标准字段仍绑定原完整单元。最大片段池8×4=32，按(-doc_local_rrf_score,unit_id)排关系路由前20；保留local_dense_rank/cosine、local_sparse_rank/原BM25分数、doc_local_rrf_score、best_path。局部RRF分数是排名启发式，不是跨文档概率或业务正确性；同分ID排序可能造成文档偏向，须在报告可见，不按gold纠正。

关系路由的片段可以已出现在A2候选中；其重复只能分别在两个路由贡献一次。最后按A2排名与关系路由排名等权RRF(k60)合并，最多40唯一单元→前20。新增combine_routes契约验证两个路由的唯一ID、连续排名、有限分数及所有canonical正文/位置/版本；同分按unit_id，不把原RRF/BM25/cosine数值直接相加，不增加跳数奖励或角色权重。

只有A2一路时直接保留其原候选/分数；关系路由存在时，最终候选retrieval_method=hybrid、score_kind=rrf、retrieval_stage=relation_augmented，retrieval_info含a2_rank/a2_rrf_score、relation_rank/doc_rrf_score、各路contribution、原A2信息及best_path；缺路字段null。路径只是来自引用/命名的候选依据，摘要不替代正文覆盖。

复用pack_evidence原签名及hybrid的36字符前缀、完整rendered_text/两换行/8000预算，正文不截断、去重、放不下记录并继续。本阶段context_text与A2计量一致，路径JSON只在实验诊断中保存；answerability仍unknown。

## 7. 编排、影响文件与产物

预计新增experiments/relation_index.py（解析/存储/范围遍历）、relation_retrieval.py（按文档筛选/关系路由/最终合并）、relation_probe.py（CLI、基线校验、追踪/评测/报告），扩展keyword_index的score_all。新增3对应测试并补原test_keyword_index，共约8源码/测试文件，另维护现有指导文档。每源码≤500行；不改旧公开签名、依赖/真实环境、源文件、旧A1/A2结果。最后融合为本业务两路适配；暂不把原仅dense/sparse的fuse泛化为检索框架。

新CLI mode=build/replay仅控制关系索引，replay另需relation-run；a2-run必须指向完整原A2 build。还有dataset/corpus-run/tasks/vector-run/endpoint/model/dimensions/output-root、原BM25/分词/backend参数及第3节参数、relation-policy=explicit-doc-v1。所有目标/资源从CLI提供，不硬编码Mock ID或文件名答案。

run先校验语料/原向量/查询hash/原A2完整状态；复用Tokenizer和assemble_keywords的replay加载原BM25，在新输出写关键词引用。直接调用原search/keyword_search/fuse/pack重算A2，原结果除计时字段外精确相等，尚不读labels；不调用会提前评测的旧hybrid_probe.run。之后build/load关系索引，扩展与A3召回；所有检索完成后才load_labels/evaluate并精确比原A2评价。任何基线差异停止，不改旧结果或缓存补成功。

输出关系原始文件/引用、seeds/遍历诊断、related_documents、document_limit_excluded、各文档原始召回/局部融合、关系路由/截断、两路union、最终候选/selected/budget_excluded、各阶段计时和绑定hash。results.jsonl按task嵌套A2/relation_route/A3；evaluation.json分别用原evaluate，另记在何阶段失去必要正文。gold只进评价/失败分析；未标注不自动当无关。

summary/report/failure-analysis记录基线一致性、来源/版本、配置、模型attempt_count=0、网络实测次数（未观测为null）、状态/固定错误分类与调用阶段。CLI暂时阻断并计数socket连接/DNS，finally恢复；单线程观察边界与A2一致，不作为多线程网络防护。阶段检查deadline；报告/输出后、最终summary前再检查，超时/IO/关系错误不写complete。无自动重试/补网络。关系无命中是正常empty，坏索引/源/配置是error。

## 8. 验收与执行命令（设计，尚未运行）

新增测试先确认红灯，再最小实现；原294测试全部保留并通过。必验：

- 正向/反向引用、2跳、配对L1/L2、命名缺失/歧义/冲突；围栏/行内代码/图片/外部链接不建边；相对路径/百分号/锚点、损坏引用、越界/符号链接、根内未索引目标；真实span/源版本切回。
- 环/自引用/重复边/多路径稳定性、L0终点、不以范围外桥接、空种子/空关系、2跳与3跳区分、节点/边/文档/单文档配额上限可观察。
- 关系索引保存重载、坏hash/字段/部分完成/位置/名称推导/源更新拒绝，IO失败不标complete；构造不消费expected_pairs或任务标签。
- score_all与原search前20精确一致；新增低全局排名匹配可在文档内候选出现；BM25统计不受目标文档筛选改变；模型/OOV/空范围/非法分数与无答案状态明确。
- 文档内检索/局部RRF/路由排序/两路合并与tie；错误ID/正文/位置拒绝，单路回到原A2、重复只贡献一次；完整长用例/36前缀/8000及预算遗漏，路径不伪造正文支持。
- 原A2重算/评价一致；gold在全部检索后消费，Q03无越界且无关系路由时A2/A3精确一致；CLI无Key/网络阻断、build/replay结果与评价一致、截止/输出失败不写假完成。

计划命令：

```sh
.venv/bin/python -m pytest -q tests/test_relation_index.py tests/test_relation_retrieval.py tests/test_relation_probe.py tests/test_keyword_index.py
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q experiments tests
.venv/bin/python -m pip check
git diff --check
.venv/bin/python -m experiments.relation_probe --mode build --dataset examples/mock-v1 --corpus-run data/experiments/common-evidence-corpus/20261010T021859Z-647de42b --tasks examples/mock-v1/tasks.json --vector-run data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e --a2-run data/experiments/a2-bm25-rrf/20261010T054002Z-99569e55 --endpoint https://open.bigmodel.cn/api/paas/v4/embeddings --model embedding-3 --dimensions 2048 --output-root data/experiments/a3-explicit-relations --candidate-k 20 --rrf-k 60 --bm25-k1 1.5 --bm25-b 0.75 --bm25-method lucene --tokenizer-policy zh-search-ascii-ident-v1 --backend numpy --relation-policy explicit-doc-v1 --seed-k 5 --max-seed-documents 3 --max-hops 2 --max-related-documents 8 --per-document-k 4 --relation-k 20 --max-graph-nodes 64 --max-edge-visits 128 --max-context-chars 8000 --deadline-seconds 180
```

实施后在移除Key的新进程执行上述CLI，再将实际build目录作relation-run，mode=replay、output-root=data/experiments/a3-relations-replay；其余参数相同，网络尝试必须实测0，排名/路径/返回除计时与运行引用外一致，评价相等。现阶段没有这条CLI入口，不把计划命令写成已执行。

片段级Recall@10/20与必要原文Coverage@8000复用原定义/源span，Q01/Q02/Q03相关单元分母8/5/2。另报必要正文在关联文档发现、文档内配额、路由截断、最终融合和预算各阶段的去留；比较是否新返回、原已返回是否丢失、干扰是否增多、补充召回成本。若收益仅来自配额/再融合，按事实说明；3组名称边已有显式链接，不能独立归因名称配对。Q04无相关正文，指标N/A、系统unknown，不以图连通识别证据充分。

不设强制质量提升断言，不为通过改标签/种子/权重/预算。工程验收与质量判定分开；结果差就保留。标签仍assistant_constructed/not_reviewed，用户只确认Q01类别相关性；真实材料/统计显著性/大规模更新尚无证据。

## 9. 限制、恢复边界与下一步

最脆弱前提：相关文档能由前5片段中的种子在2跳内到达，而且每文档前4能包含所需正文。若链接缺失/模块导航陈旧/种子错误、配额让摘要压过正文，A3仍可能失败；记录每阶段候选与路径，不自动加跳数、模型抽取、停用词或重排。图连通性只是候选来源，旧用例仍不自动作为新预期，当前L1不冒充历史快照。

已读框架/参考源码与当前Mock结构；关系索引/召回/接线/测试和质量均尚未实现或运行。无新增模型请求，无课堂掌握/独立实现登记。现有A1/A2和缓存保持可用；所有新输出独立目录，停用relation_probe可继续旧入口，解除/删除/回滚需另按项目授权，不自动清目录/reset/卸载。

上述为设计阶段下一步，已经用户确认并完成；当前下一步以第10节为准。

### 本轮实际设计检查

git diff --check实际退出0、无输出；标准库脚本检查本轮7份文档（跳过围栏/行内代码中的语法示例），输出documents_checked=7、broken_local_links=0、trailing_whitespace=0、a3_spec_exists=True、a3_source_modules_present=[]。这是文档验证，不是功能/性能/质量通过。L1规范文件存在，L2 A3实现与L3接线尚无。294项测试为A2上一轮结果，本轮未重跑；当前设计切片功能测试/应用构建不适用。未改依赖、真实配置、源码/测试/原样本或运行缓存，未提交/push；原源观察与SDK源码静态读取不冒充新的RAG实验成绩。

## 10. 2026-10-10实际实施与负向结果

### TDD与环境

3新源码/3新测试及keyword_index.score_all/test_keyword_index必要扩展已完成，约8源码/测试文件。现有search签名与结果保持；复用原评分内核、scan_source/来源映射、RRF和预算。依赖/真实.env/其他仓库无变更，85包freeze与实施前逐字一致；未提交/push。

预期红灯1 failed、18 passed、37模块缺失errors→索引/召回47 passed、CLI接线9 passed。补损坏引用/多反引号边界，2 failed→修源2 passed；缓存bool冒充整数位置，2 failed→规范JSON类型比较修源2 passed；正文对应字段冒充表头，1 failed→限制首次二级标题前修源1 passed。全部旧断言保留，无skip/放宽，无conftest或旧共享helper修改。新测试复用旧测试中的纯合成A1/A2缓存准备函数，没有伪造服务或成功结果。

```text
.venv/bin/python -m pytest -q tests
337 passed in 14.79s                        [exit 0]
.venv/bin/python -m compileall -q experiments tests
无输出                                     [exit 0，仅语法]
.venv/bin/python -m pip check
No broken requirements found.              [exit 0]
git diff --check
无输出                                     [exit 0]
```

新增43项，原294项继续通过；应用构建不适用。[红灯](../../data/experiments/a3-probe-evidence/red.txt)、[解析回归红灯](../../data/experiments/a3-probe-evidence/parser-red.txt)、[类型回归红灯](../../data/experiments/a3-probe-evidence/cache-types-red.txt)、[表头回归红灯](../../data/experiments/a3-probe-evidence/header-red.txt)、[最终绿灯](../../data/experiments/a3-probe-evidence/final-green.txt)均保留，失败没有覆盖成成功。

实施前89份原资产hash保存；除keyword_index与其测试两份预期变化，其余87份原源码/测试/Mock/tasks/requirements/公共语料/完整A1/A2缓存和结果hash不变。新源码≤500行。环境无升级/安装，既有失败基线可继续运行。

### 实际命令、产物与接线

第8节完整build CLI已在移除Key的新进程实际执行；最终replay只改mode、output-root并加relation-run指向下述原完整build，所有检索/范围/模型/预算参数相同。完整实际argv及比较断言见[final-live-replay-checks](../../data/experiments/a3-probe-evidence/final-live-replay-checks.json)：

```text
build: status=complete attempts=0 network_attempts=0 [exit 0]
data/experiments/a3-explicit-relations/20261010T071448Z-f02434ac
replay: status=complete attempts=0 network_attempts=0 [exit 0]
data/experiments/a3-relations-replay/20261010T071448Z-eeebb96b
results_equal_except_timings=True; evaluation_bytes_equal=True
q03_a2_a3_exact_equal=True; environment_unchanged=True
```

L1：3模块、score_all及对应测试/规范存在。L2：真实相对引用/名称依据、持久关系/原文校验、范围遍历、局部检索/RRF、最终合并/完整预算与失败追踪，非占位。L3：relation_probe.main→run→load_corpus/load_index/Tokenizer/assemble_keywords(replay)→baseline_recompute原A1/A2结果一致→relation build/write/load→expand→build_route(score_all/vector search/局部fuse)→combine_routes/pack→全部检索后load_labels/check_evaluation→报告/结果→最后summary。

原23条边（20原文引用＋3名称依据）、3诊断（2未索引目标＋1旧手写行范围warning）实际保存重载一致；类型、出处和配对推导校验通过。反向遍历保留原edge方向/来源，L0只作终点，种子文档不做补充目标。原A2结果及评价精确一致。

| 任务 | 种子文档数 | 关联文档数 | 边访问数 | 文档内汇总片段 | 关系路由截断数 |
|---|---:|---:|---:|---:|---:|
| Q01 | 3 | 7 | 29 | 26 | 6 |
| Q02 | 2 | 8 | 29 | 29 | 9 |
| Q03 | 1 | 0 | 0 | 0 | 0 |
| Q04 | 3 | 7 | 38 | 25 | 5 |

Q03不能经范围外需求/模块中转，A3全部候选、分数、context_text与A2精确一致；不是把必要标签复制成结果。索引replay只读原关系/关键词缓存，在新目录保存引用与输出。CLI实际连接/DNS计数0，库未观测时保持null；模型请求0、tokens/本轮费用不适用。

本轮总管线386.114ms，原A2复算55.631ms，包含本地校验/词典/原生加载/关系校验/召回/序列化/报告；不是生产规模、纯检索延迟或CPU Embedding部署基准。

### 质量结果：当前配置退化

| 任务 | 原A2 Recall20/必要返回 | 关系路由 Recall20/必要返回 | A3 Recall20/必要返回 | A3条/字符 |
|---|---|---|---|---|
| Q01 | 5/8，3/8 | 3/8，3/8 | 5/8，2/8 | 15/7935 |
| Q02 | 1/5，1/5 | 1/5，1/5 | 0/5，0/5 | 15/7765 |
| Q03 | 2/2，2/2 | 0/2，0/2（空路由） | 2/2，2/2 | 10/6843 |
| Q04 | N/A，N/A | N/A，N/A | N/A，N/A | 15/7951 |

Q01关联找到了拆分需求、拆分用例和命名需求：E05进入文档内rank4，却在关系路由rank22被截；E06/E07分别关系rank10/8、最终rank19/5，新返回。原已返回E01公式变rank18预算排除、E02旧校准rank21最终融合排除、E04旧用例rank16预算排除；E08命名关系rank9→最终17又被预算排除。原返回集合E01/E02/E04变成E06/E07；同为前20召回5/8并不意味着保持了需要的证据组合。

Q02 E05/E07在关系rank22/25被截，E06关系15→最终25被二次融合排除；原唯一返回E03旧用例被推到最终23，丢失。因此关系路由能单独返回E06，但最终A3必要返回0/5。Q03保持原结果，首名仍不是两条必要用例；Q04没有GPU依据，三个系统仍unknown。

事实支持“已有关系能定位遗漏所在文档”；不支持采用当前配额/局部排名/等权二次RRF组合作为A2替代。路径、文档内配额、路由前20、最终前20与预算是不同失败阶段，当前数据不能把收益/退化归因纯边机制。没有为改善结果调参数、模型、种子、gold或预算；三名称配对本来已有显式链接，不单独归因其收益。

[实际报告](../../data/experiments/a3-explicit-relations/20261010T071448Z-f02434ac/report.md)、[逐条失败分析](../../data/experiments/a3-explicit-relations/20261010T071448Z-f02434ac/failure-analysis.md)、[重放报告](../../data/experiments/a3-relations-replay/20261010T071448Z-eeebb96b/report.md)。全部为固定合成集，标签assistant_constructed/not_reviewed，无真实业务/生产/无答案识别证明；data被Git忽略，克隆不提供缓存。

代码课堂暂停，无本人阅读/练习/独立实现/面试掌握登记。当前保留A2作比较基线，保留A3负向配置；真实材料、模型抽图/图检索、重排、答案、MCP未验证。

**唯一下一步：制定B0/B1的LightRAG接线与共享片段Spec，核对固定版本、公共52单元的原生接法、Embedding/GLM回调、来源映射及抽图/关键词调用分账；先设计，不自动安装或跑B。** 五组/模型/Key与既有预算不重问，当前A3不继续调参掩盖失败。
