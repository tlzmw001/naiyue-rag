# Spec0023：M3.3首片——中文词项、技术标识符与Sparse编码

日期：2026-10-13。状态：用户明确接受词项方案，已完成正式Sparse离线TDD、缓存及M1/M2调用接线：47新增/1004全量通过。承接Spec0021/0022，整体A2双路、BM25S及整次报错方向保持；真实服务/检索质量/BatchProcessor未验收。

## 1. 当前机制与本片价值

当前正式链为M1/M2→EncodingInput→批次计划→DenseEncoder→Provider/SDK→规范化向量与报告。957全量通过为Spec0022上一轮证据；本轮未重跑。关键词路仍在experiments.keyword_index，不能让正式编码反向导入实验。

本片将同一EncodingInput.retrieval_text转换为可追踪词项与TF统计，供后续BM25S消费。Sparse不请求模型、不构建/评分BM25、不写向量索引；doc_length指一条片段的词项总数，不是Markdown字数/行数，也不是整个知识库的文档数。

M3.3按两个实际切片推进：本Spec只落正式Sparse；随后独立BatchProcessor Spec接Dense/Sparse成对结果和整任务报告。Batch仍是唯一分批负责人，按已确认顺序执行Dense→Sparse；任一必要步骤失败停止，不交付部分成功。真实服务、正式QueryEncodingResult及硬截止监督归M3.4，M4负责持久索引与IDF。

## 2. 参考、现有资产与证据

参考URL：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER；本机main/f658c5a4011c8b826707a65a3b11ce9301b0626f。只读核验src/ingestion/embedding/sparse_encoder.py、batch_processor.py、src/core/query_engine/query_processor.py以及本项目experiments/keyword_index.py/对应测试。未运行第三方setup/Skill或完整pipeline/服务。

- 参考SparseEncoder._tokenize实际是jieba.lcut→过滤标点→可选小写→全局min_term_length（默认2），encode产生chunk_id/Counter/doc_length/unique_terms。它的描述文字提到whitespace，不替代实际jieba源码。
- QueryProcessor也用jieba.lcut，但另有停用词、min_keyword_length=1及max_keywords=20；这不是本片自动复制的参数。正式文档与查询共用同一词项策略，后续M5另负责意图/改写/过滤。
- 参考BatchProcessor按批Dense→Sparse，异常捕获后继续；本项目沿已确认整次失败策略，不沿用其部分成功行为。
- 现有A2独立jieba.Tokenizer、搜索模式/HMM=False、完整ASCII标识符/小写、query去重，cache目录必须新建。检索质量历史证据不迁移为新72Chunk已通过。
- 本机jieba0.42.1（MIT）/bm25s0.3.13已安装，无新依赖。使用库API和自身薄适配，不复制参考源码进产品。探针仅抽取参考两个方法并注入本机真实jieba实例，禁止网络，不是参考整体测试。

### 合成探针的真实观察

输入：开关 关 开关 TC-01 cvr_ltv route=1 threshold=0.5。

| 路线 | 实际词项 |
|---|---|
| 参考默认 | 开关、开关、tc、01、cvr、ltv、route、threshold、0.5 |
| 已有A2 | 开关、关、开关、tc-01、cvr_ltv、route、1、threshold、0、5 |
| 推荐候选 | 开关、开关、tc-01、cvr_ltv、route、1、threshold、0.5 |

“人工智能”在参考精准模式中是一个词；A2/候选搜索模式还产出“人工”“智能”，因此三词均参与TF和长度。不能把doc_length定义成唯一词数，也不能假称词项彼此不重叠。

候选另保留0、0.5、0.50、-1、+2、1e-3、v1.2、module.path；不保留单独下划线。数值按文字保留，0.50不自动变成0.5，不做数学等价、单位转换或业务判断。该差异只证明机制，未测召回/排序优劣。

## 3. 已确认词项合同

保持A2的中文搜索模式/HMM=False、内置jieba词典；中文最小词长独立配置，2为首个候选，可设1对照。“开关”通常已是整词，不需要先拆成两个字再拼回；单独的“关”在2规则下被过滤，可能造成短业务词漏召回，后续用失败样本决定调整，不提前加入单字白名单。

ASCII按词法片段保留字母/数字/下划线、内嵌连字符/点号，数字前正负号保留；至少含一个ASCII字母或数字。小写可配置，默认对照选true。数字/标识符不套中文最小长度，单字符0/1等保留；单独标点与下划线过滤。政策版本固定zh-search-ascii-lexical-v2，变规则须变身份；它是A2的业务适配候选，不声称更先进或更有效。

不引入停用词/关键词前20上限/用户词典/语言模型扩词/数值归一化。Sparse只读retrieval_text，不能把document_prefix/query_prefix加入BM25词项。参数修改不能原地重用不匹配的旧索引。

### 具体输入输出

EncodingInput保留item_id、kind、两文本/hash、model_space_id/representation_id及原文来源。本片不会修改这些字段。

SparseRecord含item_id、kind、retrieval_text_sha256、tokens、term_frequencies、doc_length、unique_terms、tokenizer_id。以上例：tokens长度8，开关的TF=2，其余6词TF各1；doc_length=8、unique_terms=7。tokens保留出现顺序/重复，查询terms按首次出现顺序去重。空词项正常返回tokens=[]、TF={}、两个长度0，不补占位词，不据此判业务无答案。

## 4. 配置、身份与jieba缓存

新增独立SparseEncodingSettings/load_sparse_encoding_settings，复用read_yaml_mapping的64KiB/严格UTF8/重复键/alias/merge拒绝；不修改既有EncodingSettings schema、公开API或实验SparseSettings，不添加兼容包装。单独YAML只含五个必填字段：

| 字段 | 含义与验收配置 |
|---|---|
| min_chinese_term_length | 正整数排除bool，探针用2及1对照 |
| lowercase | 严格bool，首个对照true |
| cache_dir | 本项目调用方提供的本地目录；YAML相对路径按配置文件目录解析，直接构造用绝对路径；拒绝不明确路径/符号链接边界 |
| max_terms_per_input | 正整数，生成词项计数的资源上限；验收配置10000，仅为实验保护，不称最佳参数 |
| max_resource_bytes | 正整数，读取安装词典/cache资源的字节上限；验收配置32MiB，当前词典5,071,852bytes、cache9,254,935bytes，非通用最优默认 |

所有值显式提供，无隐式.env/目录/模型回退。逐输入字节/数量界限继续用EncodingSettings。词项通过jieba.cut_for_search生成器消费并检查上限；超限整项失败，不截断返回。

tokenizer_id=jieba版本+内置词典SHA256+policy/search/HMM=False+中文长度/小写等语义参数的规范JSON摘要。cache目录/运行上限不改变词项身份；retrieval_text_sha256独立绑定实际文本。改变Dense模型/前缀不自动改变tokenizer_id，Sparse不能被无关模型配置扰动。

缓存沿jieba真实initialize，不自己实现其DAG/前缀词典。需复用实例状态与可验证磁盘cache，避免A2每次要求全新目录：

1. 根据安装词典hash、jieba版本、Python主次版本及marshal格式计算cache命名空间，和词项策略身份分开。
2. 首建独占命名空间，实际初始化jieba，检查cache产生及大小，记录cache SHA/词典SHA/版本身份的严格小型metadata；必要写失败不能凭initialized=true报成功。jieba内部会捕获cache读写错误，因此须检查外部产物。
3. 复用前核metadata/实际cache大小及hash，不仅依赖mtime或库内部回退；不完整/不匹配/损坏/符号链接明确失败，不自动删除、覆盖或修复既有cache。
4. metadata以新建临时文件→同目录原子替换写入，失败路径可观察；不会把源文档/词项写进缓存。单实例顺序使用，不承诺并发首建/跨版本缓存兼容。

库初始化日志仅涉及安装词典和cache状态；本项目报告/异常不携原文、词项、Key或供应商异常。故障注入必须检查可观察性，禁止把jieba静默fallback当成功。需要调整具体日志接线时先更新Spec，不新增通用日志系统。

实施前源码接线补充：内置词典有界读取后用不可变bytes快照绑定身份；一个jieba.Tokenizer薄子类只覆盖get_dict_file，首建返回快照流、复用时拒绝重建，initialize/DAG/搜索算法完全沿库。库没有allow_rebuild参数，缓存读取故障会走该方法，因此这个边界有实际消费者。cache首次与复用均有界读并核marshal结构，不以initialized=true代替产物验证；实际词典total与FREQ数值之和不完全一致，不编造该校验。

jieba缓存写失败会logger.exception输出原异常；只在本实例initialize调用期间给jieba命名logger添加安全Filter，改固定消息并移除异常/栈文本，finally恢复Filter，不改级别/handler或全局日志策略。原文从未交给日志。这个局部日志适配仅服务已确认的初始化失败分支，不做通用回调框架。配置及派生资源均核符号链接边界，有界资源读取；metadata限制复用现有64KiB常量，拒绝重复键/额外字段。

## 5. 接口与调用地图

```text
独立Sparse配置 → 本机词典/cache核验 → 独立jieba实例/策略身份
M2 → 已有EncodingInput → SparseEncoder.encode_batch
                           → 既有输入/批次重校验
                           → retrieval_text → 词法片段/中文搜索词
                           → 过滤/小写 → Counter → SparseRecord
query EncodingInput → 同一分词策略 → query_terms稳定去重
后续BatchProcessor → 逐批Dense/Sparse → item_id和各自文本hash核对
```

- SparseEncoder(encoding_settings,sparse_settings)：初始化自己的jieba实例和身份，不使用全局jieba.add_word/lcut状态。词典/cache失败构造报固定EncodingError，后续调用不伪装为空词项。
- encode_batch(inputs)：复用plan_encoding_batches/validate_input_profile，要求恰好一批；逐项重新核hash/模型与表示合同，仅对retrieval_text分词，返回与输入对应的SparseRecord列表。空批/多批是接口误用，完整空任务由后续BatchProcessor返回正常空结果。
- query_terms(query_input)：要求kind=query，调用同一词项路径，再稳定去重；其tokenizer_id来自同一Encoder，未来QueryEncodingResult接入时不另造查询分词器。
- SparseRecord.to_dict/from_dict：严格字段/类型/hash/长度/TF与Counter一致性，消费时重校验，可变列表/dict独立复制，不信任Python注解。

正常/纯标点/被过滤完三种情况分别测试；纯标点与被过滤完返回合法空词项。配置、来源篡改、cache IO、词项超限或库执行异常是失败；固定code安全日志，无关键空catch，无自动降路。

## 6. 文件、验收、回退

拟新增core/sparse_encoding_settings.py、core/sparse_types.py、encoding/sparse_tokenizer.py、encoding/sparse_encoder.py；修改实际包导出，新增对应配置/词项/接线测试。预计共9个源码/测试文件，按职责保持单文件≤500；无新服务、依赖、真实运行配置、数据库或其他仓库修改。独立配置因旧SparseSettings属于快照/BM25评分，不混合职责。

TDD覆盖：严格配置/相对目录/身份；开关/关、重复词、搜索重叠、TC-01/cvr_ltv、小数/正负号/点号名、标点、query去重；前缀不入Sparse、hash/来源/跨配置篡改、词项预算/空批；首次cache/同目录复用、损坏/缺metadata/IO/符号链接失败；JSON往返/复制/TF与长度一致。真实M1/M2→编码输入→本机jieba/Sparse，12Mock所有记录与ID/hash核对，模型请求0。故障注入前确认预期红灯，再实现，不放宽既有断言。

验证目标pytest→全量pytest→compileall/pip check/diff检查；回读实际tokens/TF，不冒称检索效果。直接使用已有jieba，无模型Key/外部API/新CLI。应用构建未设立；语法检查单列。不清理失败缓存、不回滚或删除旧实验；本片尚不写索引，停用新入口即可保留原资产。

### 单变量质量对照安排

本轮探针保留P0旧A2、P1只过滤中文短词、P2只改ASCII词法、P3组合候选。旧A2实现/缓存不改；不为产品增加旧模式兼容。M4/M5接评分后，用同一组原文/切片/查询/范围/Embedding/返回预算逐项对照，记录召回与排序失败；本片TF检查通过不能代替该质量验收。

## 7. 当前证据与下一步

```sh
.venv/bin/python data/research/spec0023-evidence/token_policy_probe.py
# samples=3，policy_comparisons=4（P0–P3；参考另列）
# assertions_passed=2，model_requests=0，network=blocked，retrieval_quality=not_evaluated
```

token-policy-probe.json含固定参考commit/源码hash、真实jieba版本/资源大小与词项差异。上述两断言只是两条合成预期，不是新增产品测试或正式模块验收。未写Sparse产品源码、改依赖/真实配置/索引/模型/提交/push。L1：Spec/探针存在；L2：已核词项机制；L3：正式Sparse尚未接线。学习仅机制已说明，本人调试/复写/独立掌握未评估。

上节为设计/探针时记录；实施状态与唯一下一步以第8节为准。

## 8. 实际实施与验证

### 实现与红绿灯

新增四模块：core/sparse_encoding_settings.py、core/sparse_types.py、encoding/sparse_tokenizer.py、encoding/sparse_encoder.py；两包导出增加正式入口，既有EncodingSettings和实验接口不变。SparseRecord严格核token列表/Counter/两长度/hash/角色，to_dict再次校验并独立复制，未知字段拒绝；配置五字段实际加载/消费，无空模块。

先写三份测试，确认缺正式配置/Encoder导致3个collection errors。最小实现45/46通过，剩余测试把marshal.load全局故障同时注入了内存校验和jieba文件读取，提前触发sparse_cache_invalid。将故障限定到实际jieba.cache文件读取，所有原断言保持；目标分支单独通过，不重建、不改mtime、不泄漏原异常。没有放宽断言/skip/改旧tests或conftest。

随后补路径检查PermissionError回归，复现原异常逸出；单一修复_check_path，IO检查失败也记录固定sparse_resource_path_invalid。最终47新增/1004全量通过。初始化日志Filter仅在initialize期间添加，finally恢复；level/handler不改。cache读失败通过get_dict_file禁止fallback重建，写失败检查实际产物，metadata原子写失败不标完成。坏/缺/不匹配缓存不覆盖、不自动修复。

配置相对cache路径按YAML目录解析，直接构造要求绝对路径；缓存及资源路径所有祖先禁止符号链接，macOS的/tmp别名需使用其真实路径或配置文件目录下相对路径。该规则是资源边界，不是文档ACL。现有词典/cache是安装公开词典产物，metadata/hash用于一致性检查，不称密码学授权/不可信外部缓存安全加载。首建失败可留下未完成目录，重用明确失败；本片不删除或自动修复。

### 实际命令与输出

```sh
.venv/bin/python -m pytest -q tests/test_sparse_encoding_settings.py tests/test_sparse_encoder.py tests/test_sparse_wiring.py --tb=short
# 47 passed in 15.43s
.venv/bin/python -m pytest -q tests --tb=short
# 1004 passed in 78.06s (0:01:18)
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0；应用构建未设立，只记语法检查
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0
.venv/bin/python data/research/spec0023-evidence/wiring_probe.py
# documents=12，chunks=72，complete_cases=12，sparse_records=72
# token_occurrences=3405，empty_term_records=0，json_roundtrip_records=72
# query_terms=[开关,关闭,0.5,cvr_ltv]，cache_files_unchanged_on_reuse=true
# network_attempts=0，model_requests=0，retrieval_quality=not_evaluated
```

实际probe读取前片合成Embedding YAML和本轮合成Sparse YAML（相对cache_dir），串接真实Loader/M2/输入准备/计划/Sparse/jieba；逐条核item_id及retrieval_text_sha256、TF/长度与JSON往返，重构Encoder复用同一cache并比文件hash/查询词项。probe外层for不是产品BatchProcessor；原文/完整用例保持。3405是该raw/layout/分块参数下的词项出现次数，不是词汇量、模型token数或质量指标。labeled_case路径也有独立接线测试。

implementation-validation.json记录137分发版本不变/新增依赖0；121既有源码/测试/样本hash保持，只改两份现有包导出。新增源码均≤500行，无其他仓库/.env/真实运行YAML/旧实验/向量/提交/push变化。模拟IO仅测试所有者的临时文件；元数据和序列化字段已同步检查生产者/实际消费者/测试，当前无DB映射，后续M4必须消费相同字段。

### L1/L2/L3与教学入口

L1：四模块/三测试/公开导出存在；L2：严格配置/身份、真实搜索词法、可核cache与失败、TF/长度/序列化/稳定查询去重均实质实现；L3：独立YAML→M1/M2→EncodingInput→Sparse→真实jieba→记录/查询词项，当前无模型、BM25评分或持久索引。只有get_dict_file是薄适配，分词/DAG/initialize沿库；不宣称整个M3或生产验收完成。

| 精确测试节点（tests/） | 触发分支与预期 | Debug Test断点与WATCH |
|---|---|---|
| test_sparse_encoder.py::test_real_terms_tf_query_dedup_prefix_and_roundtrip | 正常输入8词/7唯一词，query前缀不入Sparse，稳定去重 | SparseEncoder.encode_batch→SparseTokenizer.tokenize；Encoder帧看item.retrieval_text，tokenize返回后tokens才产生，append后records才含结果；WATCH tokens、dict(Counter(tokens))、records[0].doc_length |
| test_sparse_encoder.py::test_configured_minimum_and_lowercase_share_cache_but_not_token_identity | min1/lowercase=false→保留关/TC-01，cache复用/策略ID变化 | 初始化与tokenize过滤分支，看settings.min_chinese_term_length、identity和tokenizer_id；Cache目录同、策略ID不同 |
| test_sparse_encoder.py::test_empty_terms_are_valid_not_execution_failures[\u5173] | 输入“关”，min2过滤后tokens=[]/TF={}/两长度0 | tokenize中文过滤分支→SparseRecord构造，不抛异常；pytest节点按默认转义列出，不是业务无答案判定 |
| test_sparse_encoder.py::test_cache_read_failure_cannot_fallback_rebuild | 实际marshal文件读取抛OSError→禁止重建，文件不变 | 测试fail(handle)在真正缓存文件触发；jieba.initialize内部先捕获→_DictionaryBoundTokenizer.get_dict_file抛固定码；预期异常被pytest捕获所以绿 |
| test_sparse_encoder.py::test_swallowed_cache_write_failure_is_observable_and_safe | marshal.dump抛错，库仍可initialized→本项目检查产物报错 | 断点测试fail、_read_resource；看engine.initialized与cache路径是否存在，日志只固定码，Filter最后移除 |
| test_sparse_wiring.py::test_m1_m2_to_real_sparse_binds_ids_hashes_and_preserves_originals[raw] | 12Mock/72记录，ID/hash和完整原文对应 | F5到SparseEncoder.encode_batch，F10/F11/Shift+F11；测试帧看inputs/chunks，返回后records，对少量字段投影 |

VS Code Test Explorer选择Debug Test，不重新执行有状态初始化或分词来观察返回值。正常测试是真jieba；异常测试仅在标注的IO/词法函数注入故障，未替换正式业务链。基础Python略过，Counter/生成器需要时沿本代码展开。机制/职责与数据结构已说明；本人代码走读/复述/独立调试或实现仍未评估，不预填Lesson8完成记录。

唯一下一步：制定BatchProcessor成对编码Spec，明确整体预检/单一分批、Dense→Sparse的ID/hash核对、空任务和中途失败的安全用量报告；实现继续沿已确认整次失败，不重选分词/A2/模型。
