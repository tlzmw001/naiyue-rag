# 阶段 Spec

## 2026-10-26：三项优化的7个分片（均已实现/接线/本地验收）

用户要求先依次写Spec、讨论实际决策，再逐片实施，后进一步授权连续完成全部7片；D1/D2/D3均已确认。各片均先红后绿，第7片最终完整2235 passed in437.84s（0:07:17），不自动扩Agent/MCP。下表完整结果为对应片的实际历史运行，不累计推算。

| 顺序 | Spec | 本片交付 | 实施及验收 |
|---|---|---|---|
| 1 | [0044 查询首尾空白与指纹](0044-query-whitespace-normalization.md) | 一致实际查询、原始核验及结果合同 | 已实现/本地验收，历史全量2161通过 |
| 2 | [0045 切分策略身份](0045-chunking-policy-versioning.md) | v1精确重放、旧包可读与策略失效 | 已实现/本地验收，本片全量2178通过 |
| 3 | [0046 中文标点切分](0046-chinese-punctuation-splitting.md) | v2标点规则与固定边界对照 | 已实现/本地验收，本片全量2187通过 |
| 4 | [0047 文档复用计划](0047-document-encoding-reuse-plan.md) | 编码/复用文档集合与失效规则 | 已实现/本地验收，本片全量2196通过 |
| 5 | [0048 编码快照与作业报告](0048-encoding-snapshot-and-job-accounting.md) | 新快照、V2存储、独立本次账务 | 已实现/本地验收，本片全量2220通过 |
| 6 | [0049 正式增量摄取](0049-incremental-document-encoding.md) | 实际只编码变化文档、完整建双索引 | 已实现/本地验收，本片全量2227通过 |
| 7 | [0050 移除与闭环验收](0050-incremental-consumers-and-acceptance.md) | 移除复用、消费者与全量基线对照 | 已实现/本地验收，扩展96及最终全量2235通过 |

每片均需预期红灯、最小实现、定向/全量验证及L1/L2/L3证据。本文以下保留既有Spec状态和历史记录。

## 已有模块Spec

- [Spec0043：本地CrossEncoder（已实现/真实CPU与CLI接线/阶段A本地全量通过）](0043-m6-local-cross-encoder.md)
- [Spec0042：完整证据、预算与独立入口（已接线/真实GLM闭环，验收见Spec）](0042-m6-evidence-and-independent-entry.md)
- [Spec0041：固定候选重排与GLM（已实现/SDK模拟与真实服务证据）](0041-m6-reranking-contract-and-glm.md)

- [Spec0040：M6重排、证据输出与独立使用（两种后端均已确认，分片推进）](0040-m6-reranking-and-evidence-plan.md)
- [Spec0039：M5.5同版本补读与显式引用导航（已实现/接线/M5模块全量通过）](0039-m5-knowledge-reading.md)
- [Spec0038：M5.4双路检索、RRF与统一追踪（已实现/本地验收）](0038-m5-hybrid-search.md)
- [Spec0037：M5.3配置化global/scope统计与Sparse召回（已实现/本地验收）](0037-m5-sparse-retrieval.md)
- [Spec0036：M5.2原生Chroma范围内Dense召回（已实现/本地验收）](0036-m5-dense-retrieval.md)

- [Spec0035：M5.1固定版本、显式范围与问题编码准备（已实现/接线，验证见Spec）](0035-m5-query-preparation.md)
- [Spec0034：M4.7显式文档移除与历史版本保留（已实现/接线及本地验收）](0034-m4-document-removal.md)
- [Spec0033：M4.6重复摄取、文档更新与正式Pipeline（已实现及本地验收）](0033-m4-ingestion-and-updates.md)
- [Spec0032：M4.5活动版本的只读文档列表与详情（已实现及本地验收）](0032-m4-document-management.md)
- [Spec0031：M4.4三类产物同版本激活（已实现及本地验收）](0031-m4-same-version-activation.md)
- [Spec0030：M4.3成对词项→BM25S保存/重开（已实现及验收）](0030-m4-bm25s-storage.md)
- [Spec0029：M4.2正式Chroma与共享.env（已实现及验收）](0029-m4-chroma-index.md)
- [Spec0028：M4路线与已验收的资料包存储](0028-m4-artifact-storage-and-lifecycle.md)

- [Spec0027：项目.env凭证与模型配置装配](0027-project-dotenv-credentials.md)

- [Spec0026：受监督执行与真实服务验收](0026-m3-supervised-service-check.md)
- [Spec0025：正式查询成对编码](0025-m3-query-encoding.md)

- [Spec0024：成对批次编码、整次失败与用量报告](0024-m3-paired-batch-encoding.md)
- [Spec0023：M3.3 Sparse词项、缓存与编码验收](0023-m3-sparse-encoding.md)
- [Spec0022：M3.2 Provider／Dense执行与验收](0022-m3-provider-execution.md)
- [Spec0021：M3.1独立配置与输入／响应校验](0021-m3-input-and-validation.md)
- [Spec0020：M3编码链路与分片规范（设计稿，待实施）](0020-m3-encoding.md)
- [Spec0019：M2显式引用与需求／用例配对](0019-m2-explicit-document-relations.md)
- [Spec0018：M2规则文本准备与元数据](0018-m2-rule-preparation.md)
- [Spec0017：M2结构与可定位Chunk](0017-m2-source-bound-chunking.md)
- [Spec0016：M1通用Markdown原文加载](0016-m1-markdown-loading.md)

最新已实施：[Spec0015：M0统一最小查询追踪](0015-m0-minimal-tracing.md)，63新增/660总测试。TraceContext及显式JSONL收集真实接线，旧七阶段/证据保持；写失败保留结果并明确标失败，双失败原异常保持。M0三基础片对当前查询消费者已验收，下一课追踪失败控制流，然后准备M1加载Spec。Lesson7路径题引导后回答正确。

最新已实施：[Spec0014：M0 YAML配置加载与资源装配](0014-m0-settings-loading.md)，56新增/597总测试通过。内部共享全库默认、新入口真实读取并装配当前A2、旧四题精确保持；无新依赖或真实运行配置修改。下一步配置装配小课，M0统一最小追踪仍待。QueryRequest题引导后回答正确，见Lesson6；旧阶段叙述按时间保留。

用户已认可[模块主线M0–M9](../project-plan.md)，参考为默认骨架。[Spec0013：M0公共数据契约](0013-m0-core-contracts.md)首片已完成：当时48新增/541总测试，11源/52片段往返、旧四题精确兼容与真实消费者验证；错误身份保持、无新依赖。QueryRequest课已收尾，配置片当前状态见上；M0最小追踪待，整体未完成。[Spec0012](0012-live-query-embedding-preparation.md)继续暂停，归M3/M5。

最新已实施：[Spec0011：沿Modular接入Chroma](0011-chroma-reference-alignment.md)。37新增/493总测试、原生52条写入/重复写/另进程重载/范围与来源/模型身份通过；49增量wheel固定hash、原86版本不变。正式四题Dense排序与A2证据顺序一致；参考fusion10另组减少Q01/Q02覆盖。五节局部代码课已记录；当前是本机合成缓存接线，作为M4存储模块的可复用资产，不是大库/真实材料/完整产品Agent或动态Embedding通过。

此前已实施：[Spec0010：可调用的一次A2查询与证据契约](0010-callable-a2-query-preparation.md)。总体目标由[ADR0004](../decisions/0004-knowledge-agent-goal-and-boundaries.md)确认；新入口真实复用已测检索函数，46预期红灯→46新增绿灯/456总测试；原四题真实缓存逐字段与A2一致。真实新问题Embedding和Agent循环/模型自检未实施。下文保留此前实验的设计/实施记录，Spec0009已收尾，不能把中间失败段当最新状态。

已按用户“执行”完成[Spec 0001：离线Markdown摄取组件实验](0001-offline-markdown-probe.md)，实际红灯、34项测试、60配置对照和限制写入规范末尾。此为离线组件实验，不是完整RAG实现；设计变更先更新Spec，按实际证据标注状态。

[Spec 0002：标准Embedding API接入核验](0002-embedding-api-probe.md)已按用户“继续”及临时Key授权执行：48项新增测试、共82项离线测试通过；2次真实Embedding请求成功，共59输入tokens。具体结果、费用估算及边界见规范末尾；不包含知识库检索、抽图或生产功能。

[Spec 0003：GLM-5.2生成接入核验](0003-glm-generation-probe.md)已执行：66项新增测试、总计148项通过。3次独立真实请求，前两次失败保留，补诊断/澄清提示词后第三次结构与4条合成事实通过。合计921输入/1156输出tokens，估算0.039736元；真实账单未知。未运行LightRAG或全库关系抽取。

[Spec0004：公共证据单元](0004-common-evidence-corpus.md)已按“是的继续”实施：43项新增测试、总计191项通过；11历史源→52单元/12完整用例，186处来源位置核对，最大渲染1104字符；单文档范围1源/10单元/7用例。离线socket阻断实跑0网络尝试，1条手写行号warning保留。尚未索引、检索或接LightRAG，不作为最终生产解析选型。

[Spec0005：A1向量基线](0005-a1-vector-baseline.md)已按“继续”实施：60新增/251总测试通过，真实5请求/56向量各2048维/7472输入tokens，估算0.003736元。Q01前20召回4/8→最终2/8，Q02为1/5→0/5，Q03为2/2→2/2但首名非所需用例，Q04系统unknown。无Key且阻断网络的重放结果一致。保留真实质量失败，不以接口/测试成功宣布选型通过。

[Spec0006：A2关键词＋RRF对照](0006-a2-bm25-rrf.md)已按用户“可以”实施：jieba0.42.1＋BM25S0.3.13，原83包不升级；43项新增/294总测试通过。原向量缓存＋范围内BM25→等权RRF(k60)→完整8000返回，移除Key/阻断网络实跑和重放0请求/0网络，评价字节一致。Q01必要覆盖2/8→3/8、Q02 0/5→1/5、Q03保持2/2；BM25部分命中被RRF排出前20，结果不作为完整质量通过。下一步A3已有关系扩展Spec。

[Spec0007：A3已有引用与名称配对](0007-a3-explicit-relations.md)已按“是的”实施，43新增/337总测试通过；23边/3诊断、查询范围内2跳/L0终点/分文档检索与再融合实际接线，0模型/网络重放一致。Q01必要返回3/8→2/8，Q02 1/5→0/5，Q03与A2精确相等；当前配置质量退化，保留负向证据。下一步B0/B1 LightRAG接线/共享片段Spec，不由工程通过宣称有效或继续调参数掩盖失败。

[Spec0008：LightRAG公共片段接线/B0](0008-lightrag-b0-cache-wiring.md)已按“继续”实施：固定发布1.5.7/独立62依赖、原源C!自定义公共52/独立scope10、缓存Embedding/禁LLM、真实native存储/新进程重载/naive出口/完整8000已验证。31新增/368总测试通过，移除Key的build/replay0模型/0网络、结果/评价字节一致。四题候选/返回单元顺序和指标与A1相同，最大cosine差3.8331e-8；B1原生抽图/关键词尚未运行。唯一下一步B1 Spec，不把B0工程通过宣称图质量通过。

[Spec0009：B1原生模型图与mix](0009-lightrag-b1-model-graph.md)为设计审阅：固定1.5.7、标准HTTP适配（不导入自动安装/重试的智谱适配器）、原生JSON/gleaning0、EXTRACT初始/摘要/KEYWORD分账、原始向量精确缓存与新描述/关键词Embedding、两scope来源/图持久化、native_order原文证据与完整8000对照。先小探针通过再完整B1/无Key重放；未安装/改代码/发模型请求，368绿灯是B0前轮未重跑。

Spec0009已按“继续”进入部分实现，3模块/4测试、标准HTTP19/缓存6 passed；真实SDK＋模拟HTTP集成连续三次未通过，当前replay mode缺graph_run触发完整配置校验。按AGENTS停止源码调试，父入口/真实小探针/全库/无Key重放未完成，新模型请求0。唯一下一步修配置边界并让原失败测试通过，不把前轮368或局部绿灯当本轮完成。

Spec0009现已实际收尾：4模块/5测试/原前缀接线，410 passed in39.95s；真实小探针/两scope图与四题已验证。首live审计单值覆盖bug失败保留，修复后完整产物标engineering_revalidation，仅追加Q03两请求，累计112 HTTP/用量；标准无Keyreplay attempts0、结果/评价字节相同。B1 Q01同B0、Q02召回退化，保留失败与源绑定证据，唯一下一步五组首期路线取舍。
