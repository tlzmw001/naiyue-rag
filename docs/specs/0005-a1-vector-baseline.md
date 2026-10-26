# Spec0005：A1向量检索基线

日期：2026-10-09（America/Chicago）。状态：用户“继续”已授权并完成A1工程实施、真实调用及零网络重放，实际证据见第10节。接口/工程通过，Q01/Q02检索基线质量不足，未宣布业务验收通过。沿已确认五组范围及公共证据推进，模型继续embedding-3/2048维。

## 1. 目标、当前数据流及推荐

当前Spec0004产物为11历史源/52单元（40正文、12完整用例），没有向量索引或查询。输入固定为common-evidence-corpus/20261010T021859Z-647de42b的sources/units/summary及当前Mock源版本；Q01–Q04使用tasks.json固定query。全阶段合成，不传真实资料。

本切片实现一条可复跑A1：公共单元→标准Embedding→本地文件索引→查询向量→范围内余弦排序→完整证据组装→固定合成标签诊断。用户允许扩大返回上限，助手据实际长度将本轮五组共同上限设为8000字符（用户授权扩大，未逐字指定8000），覆盖此前4000。索引文件实际重新加载后才查询；另有显式replay模式用原文档/查询向量运行，零网络重放，不默认重新发模型请求。

推荐标准库JSON/JSONL保存向量、逐一计算cosine；52个单元足以做精确排序，复用已有数值检查/相似度，无新依赖/服务。参考项目Chroma是另一候选，已有存储/过滤功能，但需新的接入/依赖及分数映射；当前不预装。若后续规模/更新实测暴露文件方案限制，再以证据重选，不把本阶段文件索引当最终生产数据库。

```text
固定公共语料＋源版本核验           固定任务query/范围（不含标签）
             ↓                                ↓
     正文＋语义上下文                     查询文本
             ↓                                ↓
   embedding-3文档向量             embedding-3查询向量
             ↓                                ↓
    文件持久化并重新加载 ───────→ 先限制范围 → cosine排序
                                                ↓
                                      top20候选 → 8000字符组装
                                                ↓
                             保存结果/追踪 → 单独读取标签并评价
```

不加入BM25、关系扩展、重排、LLM改写/回答、LightRAG、MCP、界面或生产更新；不改原实验公开签名、Mock、依赖或真实配置。

## 2. 输入表示、完整性与索引

index_text固定为contexts中的原text按原顺序加body，使用一个换行连接，policy_id=context-body-v1。包括文档标题、章节/维度、列名、来源说明和完整正文；不额外拼入索引登记的unit_id/document_id/文件路径/版本hash或渲染前缀。原文已有文档/需求编号、日期、Markdown链接等按正文保留，所以不能声称输入字符串完全不含编号或路径。此处澄清原文与附加元数据的区别，不改变已实现v1输入、向量或基线。不去重/缩写内部文字、不展开TC引用；同策略用于全部52单元，后续A2/A3/B0/B1复用须记录一致性。

本轮只读测量：52条index_text共11210 Unicode字符，最长755字符/1442 UTF-8字节。查询向量使用tasks.query原字符串，不额外拼入整份新L2，也不让模型抽词/改写。缓存identity包含endpoint/model/dimensions/policy_id/input_sha256，不能跨模型、维度或文本混用；服务未提供权重修订号，provider_revision=unknown，不假称别名固定即可证明长期模型版本不变。

加载语料必须验证summary.status=complete、各单元eligible、唯一unit_id、render_unit一致、body/context span切回当前源、source_sha256、source登记与源范围一致；重算完整语料fingerprint（sources.jsonl与units.jsonl实际字节及固定策略）。源版本改变、伪造位置或内容/ID不符即在付费前失败，不能静默重切或重新生成公共单元。只读dataset用于源核验/身份，不将manifest.expected_pairs等标签交给索引。

新实验接口：load_corpus(corpus_run,dataset)、make_index_text(unit)、load_index(run_dir,expected_fingerprint,config)、search(index,query_vector,scope_ids,exclude_ids,candidate_k)、pack_evidence(candidates,max_context_chars)；查询模块不接收gold标签。新增函数是实验接口，不变更旧公开API，不声明最终HTTP/MCP协议。

存储schema_version=1：index_manifest.json含语料fingerprint、原输入hash、endpoint/model/dimensions/policy、源ID集合/摄取排除ID、unit_count、向量文件hash及完成状态；index_vectors.jsonl每条含unit_id/input_sha256/vector；query_vectors.json每条含task_id/query_sha256/vector。原公共单元作为只读源登记引用，load_index须校验文件hash、唯一映射、2048维、有限数和非零范数，再与源单元绑定。只有全部52文档及4查询向量验证/保存后写index_manifest完成标记，不把部分文件当缓存可用。

## 3. 模型客户端与资源范围

沿用专用进程环境变量NAIYUE_RAG_ZHIPU_API_KEY；live复用已授权来源，隐藏输入/进程环境传递，不写.env、不接受Key命令行参数。replay不需要Key，不读取.env，也不静默补网络。费用按实际usage记录，不设置新的金额确认门槛；实际供应商账单未知。

本轮所有运行参数由CLI显式提供：endpoint标准/embeddings、model=embedding-3、dimensions=2048、batch_size=16、max_inputs=56、max_requests=5、单次timeout=30秒、总deadline=180秒、max_response_bytes=4194304、max_input_utf8_bytes=3072、unit_price_cny_per_million=0.5、candidate_k=20、max_context_chars=8000。整数拒绝bool、负/零/超限，价格须有限非负；endpoint/model是批准目标校验而非隐藏默认。先校验全部输入/任务/长度/范围及所需批次数，超过56输入/5请求在付费前拒绝。

52文档按固定单元顺序四批（16/16/16/4），4查询一批，总计最多5请求。无自动重试/换模型/降级/并发。现有send_embedding只允许2条且每条200字符，不能复用来发送本组；保持原函数不变，新建本次受限批量客户端，复用ProbeError/NoRedirect/validate_vectors/validate_usage/cosine及new_run_id。

新客户端只构造model/dimensions/input，Bearer认证、拒绝重定向；响应最多读4MiB＋1，拒绝超限、重复JSON键、原始或解码后含实际Key的响应。校验返回model、data数量/index唯一且可乱序重排、精确维度、数值有限/非零范数和usage。先保留已知usage，再检查向量，不能因坏向量抹掉已产生用量。错误只记固定分类/HTTP码，不保存原始错误响应、异常消息或凭证。

监督父进程启动worker并扣除启动时间，用余下deadline等待；发请求前emit无密钥检查点，记录attempt_count/阶段/输入hash/已知usage。超时kill并回收worker，保留已尝试次数/已知费用，未收到usage为unknown；终止进程不保证取消服务端已开始的处理。失败保留该新目录产物，但本切片不实现断点续跑，replay只接受完整已验证缓存，禁止隐式补调用。

2026-10-09重新HTTP GET官方嵌入OpenAPI确认embedding-3单条3072 tokens、数组最多64项、可选2048维；缓存data/research/a1-design-20261009/embedding-api.md。UTF-8字节检查是应用保护，不是模型tokenizer或3072-token证明；服务逐条token数/静默截断行为仍未知，不安装未验证tokenizer、不给超限文本偷偷截短。本组最长1442字节只说明固定输入小，不外推长文档支持。

## 4. 查询、范围与分数

任务输入仅task_id、query、可选scope_document_ids和historical_search_exclude_document_ids；先提取这些白名单字段，金标签单独交给评价模块。Q01/Q02固定查询，不将本次需求加入历史候选；当前L1仍标当前导航。Q03只允许MOCK-CASE-001的10个单元，过滤在任何cosine排序前执行，可复用各自独立的文档向量而不做全库排名后过滤。

无scope字段表示已批准索引全部源；显式空scope/未知scope ID为错误，不能变成全库。exclude ID必须在源ID或该索引已登记的摄取排除ID中，当前任务已排除可合法再次声明；未知/错误ID拒绝。查询空白、向量无效、索引不兼容失败，不返回空成功。

用旧cosine计算原始[-1,1]相似度，按(-score,unit_id)稳定排序、截取min(candidate_k,范围内单元数)。source/ID映射必须来自当前索引，不能凭模型编造。原始cosine不是概率/业务相关性判断，也不按不同框架的分数直接比较。候选返回rank/score/unit_id及源身份，保留匹配范围与实际候选数供追踪。

## 5. 8000字符组装与输出契约

按候选原排名依次考虑，完整加入一条；放不下则记录budget_excluded并继续检查后面的候选，不截断、缩写、按金标签优先，也不自动补引用。相同unit_id只返回一次；不同单元的上下文仍按Spec0004格式保留，不在此阶段跨单元删共同标题。

每条输出为检索前缀＋原unit.rendered_text，前缀格式固定为[vector rank=两位编号 cosine=带符号八位小数]及换行，长36字符。条间用两个换行；元数据、正文/上下文/定位、排名/分数及所有换行均计入context_text的Python len，总长≤8000。原排名保留，跳过后不改成新的相似度排名。超过上限的条目完整留在内部追踪，不能计作已返回。

内部result含task_id/query/范围/index_id、candidates、selected（带document_id/unit_id/source/版本/body_span/contexts/body/rank/score/retrieval_method）、budget_excluded、context_text/context_characters、耗时、status与answerability。只有context_text是本实验模拟交给上层的证据视图，候选/诊断/评价不附给Agent；本轮是CLI实验，不是完整MCP JSON计数契约。将来适配层若另返字段/JSON结构须把实际返还文字计入并重验，不能沿用本实验8000字符结论。

正常有候选可组装为retrieved；范围内无可用候选为empty；有候选但无完整条目能放入为no_evidence_fits，区别于服务/索引error。answerability始终unknown：A1不实现无答案阈值或生成判断，不把Q04的预期标签复制成运行状态。

### 已发现的预算上限

只读格式核验发现Q01的E01–E08在现有单元中各有一份完整正文对应；原完整渲染5055＋连接14=5069字符。加入上述实际检索前缀后共5357字符；在此前4000上限下最多6/8，该历史分析保留。用户允许扩大后，本轮改8000，可完整容纳8/8并留2643字符；Q02全部必要材料3443字符、Q03为1905字符，可容纳5/5与2/2。这是离线格式可容纳性，不是实际召回或返回质量。

8000不是按任务标签选取证据的规则；组装仍按相似度排名，背景/无关候选可能占预算，所以能容纳必要材料不保证实际返回8/8。报告继续分开候选/返回/预算遗漏，不以降低断言或改标签修饰效果。全52单元加检索信息/连接共27551字符，最长20条共13406字符，8000仍会限制候选返回；不是把整个Mock塞给上层。五组使用同一8000以保持对照公平，旧4000报告不回写或直接与8000分数混比。紧凑输出/多轮检索不加入本轮。

## 6. 固定评测与失败分类

检索结束后才读取candidate_required_evidence/background/irrelevant与evidence_units源版本标签；工具可在付费前验证标签hash/范围是否有效，但不将它们传给表示/召回/组装。源行范围转换为当前源字符范围；标签与公共单元用实际body_span映射，不靠标题或文件名命中。

片段级Recall@10/20：必要标签范围中至少一个非空白原文字符与unit.body_span相交，则该unit计入相关公共单元集合；top-k相关单元数÷该相关集合数。本组Q01/Q02/Q03实际对应8/5/2个相关单元。背景标签另报；未标注内容不自动判为无关，明确干扰MOCK-NOISE-005命中/返回单独计数。

原文单元Coverage@8000：实际selected正文span的并集完整覆盖某必要标签范围内所有非空白字符才算1（纯空白间隙不造成假遗漏）；完整命中必要标签数÷必要标签数。上下文/图摘要/仅ID不替代必要正文。分别记录not_recalled（top20候选未完整覆盖）、budget_excluded（top20已完整覆盖但selected未覆盖），避免双计。结果必须记录实际max_context_chars，不将不同返回上限的覆盖率作为同条件分数。

Q04必要集合为空，两个指标分母为0均null/not_applicable，不填0或1；报告实际候选/返回材料与独立标注expected_status=insufficient_evidence，系统answerability=unknown，不宣称无答案识别通过。检索质量可低或Coverage为0，完整运行仍可complete/退出0，因为基线用于揭示失败；工具结构/范围/IO/服务失败则退出2，不能伪装质量分数。

标签继续assistant_constructed_synthetic_candidates，用户只确认Q01五类相关性，未逐行审阅全部范围或其他任务；4题无统计代表性/独立留出证据。未实现模型评分/人工已审标注/MRR/nDCG/答案评测，不预填真实召回成绩。

## 7. 产物、缓存与失败

每次新UUID目录，不覆盖旧产物。正常输出index_vectors.jsonl/query_vectors.json/index_manifest.json、results.jsonl、evaluation.json、report.md、summary.json；summary最后为全流程完成标记。原向量及索引位于被Git忽略data，源码不含凭证；现场CLI使用隐藏输入→进程环境→finally清理，不展示Key。

replay-run必须显式给完整原目录，校验语料、模型参数、文件hash、查询字符串hash后重新加载文档/查询向量，不发模型请求；字段/文本变更必须报cache_mismatch，不能偷用旧向量或隐式联网。评价标签修订只影响评价，不改变query/hash或排名；再评测仍记录新标签源。分别记本次新增请求/usage/费用（replay为0）与原缓存调用信息（真实账单仍unknown），不重复计费。

输入/范围/配置/标签源无效在网络前失败；HTTP401/429/5xx、超时/重定向/坏JSON/向量/未知usage明确分类，不自动重试。已知费用=(本次已知prompt_tokens×配置单价)/1e6；任何已尝试请求用量未知，则总费用unknown并另存已知小计，不填0。只写错误分类/HTTP码/阶段，不记录原始错误响应、child stderr或异常字符串。

IO失败/目录冲突/缓存损坏/读取源变更均可观察，输出部分文件不等于完成；失败不生成完整索引或假评测。方向不合适可停止使用本入口、保留源与已有结果；不自动删除/回滚。服务费用无法回滚。语料10倍超过本轮输入/请求上限会在付费前阻断，不能推断本机查询吞吐或全库性能。

## 8. TDD、影响文件与验证

预计17文件：新experiments/vector_index.py（语料/索引加载、排序和组装）、vector_eval.py（查询白名单/标签映射与指标）、vector_embedding.py（受限批次HTTP及worker/监督）、vector_probe.py（CLI/调度/报告）；各一份tests/test_vector_*.py，另增tests/vector_fixtures.py共用显式配置/假响应，避免第三次重复，不改conftest。维护本Spec、README、Spec目录、handoff、future-work、learning-roadmap、project-plan及ADR0003。超过8文件用于网络/检索/评测职责和测试分离，无新服务，每源码≤500行；调整职责前更新Spec，不创建空模块。

实施前接口细化：corpus包含units/sources/registry/fingerprint/excluded_ids；write_index负责独占保存及最后索引标记，load_index从调用方配置指定语料绑定，不读取缓存自带的任意源路径。search返回candidates/compared_count，pack_evidence返回selected/budget_excluded/context_text等。向量worker只在stdout发送安全检查点/状态，完整向量写入独立结果目录。replay由CLI另外要求原summary.status=complete，不能把只有索引完成但全流程失败的目录作为完整重放。以上新增实验字段同步JSON/加载/调用/测试。

截止回归发现：初版只监督模型worker，worker完成后超时仍能继续查询。先用受控时钟复现1 failed，再补总体截止在网络后/索引重载后、逐题查询及评测前后检查；失败时保留已知调用和费用，评测为null，允许写安全失败报告以保留证据。另核验worker启动耗时扣除及结果写入失败无完成标记，不修改原断言。

先正确收集新测试，确认缺模块/新行为红灯，再最小实现；旧191项全部保留通过，不改旧测试基础设施/断言/skip。离线测试阻断socket并用假HTTP/worker与二维手算向量，不冒充真实2048服务输出。

| 核验 | 核心路径 |
|---|---|
| 语料/表示 | 源hash/span/渲染/唯一ID/eligible校验；正文和语义上下文进入实际请求，opaque ID/hash不进；标签改变不改变文本/排序 |
| 网络/资源 | 16/16/16/4＋4请求body真实接线；响应乱序、缺/重复index、维度、bool/NaN/零范数、未知usage、HTTP/超时/重定向/损坏/超限/Key回显可观察；无重试；deadline保留部分用量 |
| 排序/范围 | 手算cosine、同分稳定顺序；过滤先于每次相似度调用；Q03只比较10单元；空query/未知或空范围拒绝、空候选与error分开 |
| 预算/标签 | 完整长行及上下文不截；前缀/分隔符计数，超限跳过但留追踪；Recall/完整与部分Coverage/背景/未标注/Q04分母0分类；原文版本不符阻断 |
| 持久化/重放 | 实际保存后重新load；篡改向量hash/顺序/身份/查询拒绝；replay在socket阻断且无Key时完全复现排名/返回/指标，本次请求0 |
| IO/安全 | 路径范围/JSONL读取失败、无权限和输出冲突；部分文件不冒充完成；凭证不在请求日志/源码/报告/Git；12源及原实验/锁hash不变 |

以下命令为获确认后的计划，本轮未执行：

```sh
.venv/bin/python -m pytest -q tests
.venv/bin/python -m experiments.vector_probe --mode live --dataset examples/mock-v1 --corpus-run data/experiments/common-evidence-corpus/20261010T021859Z-647de42b --tasks examples/mock-v1/tasks.json --endpoint https://open.bigmodel.cn/api/paas/v4/embeddings --model embedding-3 --dimensions 2048 --batch-size 16 --max-inputs 56 --max-requests 5 --timeout-seconds 30 --deadline-seconds 180 --max-response-bytes 4194304 --max-input-utf8-bytes 3072 --unit-price-cny-per-million 0.5 --candidate-k 20 --max-context-chars 8000 --output-root data/experiments/a1-vector-baseline
.venv/bin/python -m compileall -q experiments tests
.venv/bin/python -m pip check
git diff --check
```

replay使用同一CLI完整参数，改mode=replay并显式添加--replay-run实际成功目录，输出新目录；成功目录ID由实际运行产生，不能预造。真实调用使用已授权Key，不写.env；本轮无GLM请求/依赖安装。收尾给实际命令/测试输出/请求和usage/费用/索引重载/逐题候选与预算失败/重放一致性、L1/L2/L3及限制。无应用构建，compileall仅语法检查；缺业务阈值不是隐含通过，基线不声明业务质量验收。

## 9. 来源与唯一下一步

Modular固定main/f658c5a4011c8b826707a65a3b11ce9301b0626f，读取2026-10-09：dense_retriever.py:141将query交给embed、:150将向量/filters交给vector_store.query；chroma_store.py:128创建cosine collection，:263–265将distance映射为1-distance/2。因此参考分数尺度与本Spec原始cosine不同，不拿绝对值跨组比较，不运行其setup/Skill或复制代码。[Dense源码](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/core/query_engine/dense_retriever.py)。

官方[Embedding OpenAPI](https://docs.bigmodel.cn/api-reference/模型-api/文本嵌入.md)本轮web读取失败后标准库HTTP GET成功，内容缓存在data；这是文档而非新的服务调用。标准接口已用短样本真实核验，长本组/16条批次尚待实施验证。新代码复用本仓库自己的检查器，不复制第三方实现。

实施后唯一下一步依据A1逐题失败分析制定A2（BM25＋RRF）Spec；五组范围/模型/片段不重问。不提前跑A2/A3/B0/B1或给用户登记代码理解；仍处选型实验，代码课堂暂停。

## 10. 实际实施与验证

本地日期2026-10-09，结果ID为UTC 20261010。4份源码/4测试＋vector_fixtures已创建并实际调用；额外测试夹具原因见第8节，无conftest/旧测试/原工具/锁文件修改。原始Mock和语料保持，未修改真实.env/其他仓库、提交/push或安装依赖。

### TDD和本机命令

新测试正确收集后因缺少4模块报57 errors in 0.19s、退出1（完整red.txt）；最小实现57 passed in 0.48s。发现worker结束后未检查总体截止，受控时钟回归1 failed→只补父流程截止检查，并加启动耗时/写入失败验证。最终60项新增、旧191项全部通过：

```text
.venv/bin/python -m pytest -q tests
251 passed in 1.35s                        [exit 0]
.venv/bin/python -m compileall -q experiments tests
无输出                                    [exit 0]
.venv/bin/python -m pip check
No broken requirements found.             [exit 0]
git diff --check
无输出                                    [exit 0]
```

构建不适用，compileall只为语法检查。最终源码行数vector_index230、vector_eval107、vector_embedding174、vector_probe143；四测试112/85/142/110及共享夹具25，均≤500。31份原始Mock/旧工具/旧测试/依赖hash未变；未放宽断言或skip。红/绿、截止回归、源码hash与独立检查保存data/experiments/a1-probe-evidence，受Git忽略保护。

### 真实标准API与索引重载

第8节完整live命令的实际全部参数经main(args)执行；临时Key通过getpass隐藏输入→进程环境→worker，finally清除，不在argv/源码/报告。结果：

```text
status=complete attempts=5
output=.../a1-vector-baseline/20261010T031953Z-52cfda4e   [exit 0]
```

实际5次HTTP200，文档16/16/16/4、查询4；分别prompt/total tokens=2004/2945/2014/360/149，completion均0。合计7472输入/总tokens，按配置0.5元/百万估算0.003736元，provider_billed_cost_cny=null；不是实际扣费/余额。整体2310.834ms包括本地预检、进程、HTTP、IO、排序与评测，不是服务端纯延迟或规模性能排名。没有自动重试、模型切换或GLM调用。

落盘52文档＋4查询向量，独立加载检查56条均精确2048维、有限值/非零范数；index_manifest文件hash/语料fingerprint/文本映射实际校验。所有52实际文档请求input_hash与context-body-v1文本相符；未追加索引ID/版本hash，11段原文自带Doc ID仍在正文，说明原文与附加元数据应区分。公共单元/源版本/模型表示未改变。

### 实际四题基线与失败

指标单位、标签源、分母和计算见第6节；下表为真实向量运行，不是fake测试向量或模型评分。固定标签仍assistant_constructed_synthetic_candidates、not_reviewed，用户只确认Q01类别相关性。

| 任务 | Recall@10 | Recall@20 | Coverage@8000 | 选中条数 | 字符 | 结果解释 |
|---|---|---|---|---:|---:|---|
| Q01 | 2/8=0.25 | 4/8=0.50 | 2/8=0.25 | 13 | 7690 | 召回缺口及排名/预算缺口并存 |
| Q02 | 0/5=0 | 1/5=0.20 | 0/5=0 | 15 | 7809 | 仅E03进入前20，最终仍排除 |
| Q03 | 2/2=1 | 2/2=1 | 2/2=1 | 10 | 6843 | 范围先过滤为10单元，找齐但排名不理想 |
| Q04 | null/N/A | null/N/A | null/N/A | 13 | 7792 | 无所问GPU阈值依据，系统unknown，未实现无答案判断 |

Q01实际返回E02历史校准正文和E04旧校准用例；E01原始公式rank19/score0.49686830、E03一次预测用例rank14/0.51570041进入候选，却被完整预算组装排除。E05拆分rank27、E06异常rank25、E07旧冲突用例rank36、E08字段映射rank29，均不在top20。Q02 E03 rank20/0.44203577被排除，E01/E05/E06/E07分别25/31/40/36。Q03所需TC-02 rank2、TC-01 rank10，rank1是TC-05；不能以覆盖2/2说明排序质量已通过。

前列包含摘要、维度说明和导航；它们可能有背景价值，未标注不自动为无关，但没有完整覆盖任务必要正文。Q01/Q02明确干扰文档候选/返回均0，不等于返回全部相关。Q04不从期望标签拷贝insufficient_evidence为系统结果。没有调预算/输入/过滤摘要/标签/模型以追求高分，A1保留为失败基线；不能根据四题断言Embedding模型普遍无效。

[实际报告](../../data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e/report.md)含所有候选/返回正文/请求；[简短失败分析](../../data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e/failure-analysis.md)用保存向量查看全范围必要排名，没有新增模型调用。

### 显式零网络重放

使用第8节完整参数，改mode=replay，添加--replay-run data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e，输出根data/experiments/a1-vector-replay。在新进程中先移除专用Key、阻断socket.connect/connect_ex，再runpy执行实际CLI：

```text
status=complete attempts=0
output=.../a1-vector-replay/20261010T032159Z-45d42d2f
network_attempts=0                        [exit 0]
```

排名、候选/返回正文、8000预算内容除elapsed字段外完全相同；evaluation.json全相同。本次新增请求/用量/估算费为0，原缓存调用5次及估算0.003736另列，不重复计费。[重放报告](../../data/experiments/a1-vector-replay/20261010T032159Z-45d42d2f/report.md)。重放目录不复制向量，不作为新的向量缓存源；需要完整原live目录。

### L1/L2/L3与限制

- L1：源码/测试/两套真实结果/索引与报告存在，README/Spec/ADR/规划/学习入口已同步。
- L2：有真实文件向量、源绑定、先范围后cosine、完整组装、字段/用量/截止/缓存/IO检查及60项新测试，无空模块或伪造结果。
- L3：实际main→预检→worker 5次HTTP→write_index→load_index重新加载→4题search/pack→独立标签评价→结果/报告/summary；独立进程重放证实存储被消费。Q03只比较MOCK-CASE-001的10单元，各返回范围和charlen≤8000实际检查。

本轮全部合成，未验证真实知识库/CPU模型/更新或生产规模；64条批次/3072-token超限与静默截断未知，provider权重修订号/实际账单未知，cache hash不是外部恶意文件认证。没有答案/引用校验、无答案判据、BM25/RRF/关系扩展/重排/LightRAG/MCP。功能实现/工程验证与业务质量分开，用户暂停代码课堂，没有理解/练习/独立实现/面试掌握记录。唯一下一步依据这份失败基线制定A2对照Spec，不重写A1。
