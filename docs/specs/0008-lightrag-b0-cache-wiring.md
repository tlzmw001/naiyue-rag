# Spec0008：LightRAG公共片段接线与缓存驱动B0

日期：2026-10-10（America/Chicago）。状态：已按用户“继续”实施并完成B0接线/固定对照/重放；B1尚未实施。五组范围已确认；本切片先验证真实SDK存储/naive查询与公共证据兼容性，B1实际抽图/关键词回调在此接线通过后单独形成Spec。代码课堂仍暂停。

## 1. 问题与阶段安排

A1/A2/A3已实跑，当前A3必要返回Q01/Q02从3/8、1/5退到2/8、0/5。B路线要比较LightRAG框架片段检索与图＋片段机制，先确认框架内部实际使用哪些片段、如何调用模型及怎样返回来源；没有接线证据就跑图，不能解释切分/存储/图各自的影响。

推荐本切片：LightRAG1.5.7真实SDK，摄取公共52单元，process_options=C!跳过KG；Embedding callback只读已有56向量，LLM callback直接报unexpected_llm_call，naive查询用aquery_data，完整证据仍按8000字符组装。不是伪造模型返回或实体图，也不是最终生产栈决定。

### B0/B1职责与进入判据

| 阶段 | 本轮范围/后续判据 |
|---|---|
| 本Spec接线/B0 | 固定发布包/独立环境、原11源→52完整片段及单文档10片段、native ID/内容/向量与来源一致、naive真实回调/查询/重载、0模型调用、原固定评测 |
| 后续B1 | 本Spec通过后制定抽图/合并描述/关键词回调Spec，明确角色、原生格式、输入hash缓存、GLM/新增实体关系Embedding、调用/usage/截止及失败处理；保持公共正文与来源映射 |

B1优先延用已确认glm-5.2/embedding-3来源，不再询问型号/Key/费用门槛。原短JSON抽取探针不等于LightRAG原生EXTRACT/KEYWORD兼容；B1还需要实体/关系及高低关键词Embedding，不能承诺只复用原56向量。naive不需要图，但未来若与mix共享已建图索引，建图成本单列为B1摄取开销。

## 2. 版本、许可证与静态证据

指定Modular参考项目继续为工程参考：[仓库](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER)，main/f658c5a4011c8b826707a65a3b11ce9301b0626f；其所读链为dense/sparse→RRF，不是B路线原生实现。SDK方案依据[HKUDS/LightRAG](https://github.com/HKUDS/LightRAG)公开源码/发布包，本轮未运行第三方setup、API服务、Skill、测试或模型。

此前本地main克隆commit453dce83d6d0354a06e46c8d4029a0895c4e054b的_version为1.5.8；2026-10-10 PyPI /1.5.8/json返回404。不能将旧main源码作为已经发布的1.5.8 wheel，也不能假定与1.5.7相同。

推荐发布版1.5.7：[PyPI](https://pypi.org/project/lightrag-hku/1.5.7/)，MIT，Python≥3.10，pure-Python wheel `lightrag_hku-1.5.7-py3-none-any.whl`，5039835 bytes，SHA256=`895b81d94ca447afc6290c0e049d339f6caed46fbf29e4324f6db987046c6fcb`。官方v1.5.7标签commit=`28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c`；本轮从官方tag下载lightrag.py/pipeline.py/_version.py逐字节对照wheel，三者相同。wheel与旧1.5.8 main多文件不同，以下行号均指解包的1.5.7。

资料仅为读取：`data/research/b-design-20261010`中官方metadata/wheel/hash、14核心模块、tag-wheel-checks和依赖计划；Git忽略，不安装/执行这些文件。runtime以发布wheel及hash为身份，不把三文件对照宣称完整发行重现。

### 追到实际调用

- lightrag.py的initialize_storages/finalize_storages绑定事件循环与存储；EmbeddingFunc→NanoVectorDBStorage._flush_pending_locked最终消费Embedding callback，query也消费它。需要最终flush/重载，不能以upsert返回视为已持久化。
- pipeline.apipeline_enqueue_documents接受ids/file_paths/process_options；显式C调用6参数chunking_func，!在pipeline.py:5418跳过extract，并跳过merge但仍flush片段。ainsert_custom_chunks会写KG，不能将它当本切片无LLM入口。
- 自定义切分输出后，pipeline.py:5323实际调用enforce_chunk_token_limit_before_embedding；回调成功不等于没有后续硬切分。
- utils_pipeline.build_chunks_dict_from_chunking_result保留自定义字段但删_source_span，chunk_id必要时加doc_id前缀，file_path规范化会丢原相对目录。自己保存映射，不能把原生basename当版本/原行号保证。
- lightrag.py:3998的aquery_data强制only_need_context并分派naive→operate.naive_query→_get_vector_context→chunks_vdb.query→process_chunks_unified（重排/前k/token裁剪）→convert_to_user_format。naive没有KEYWORD提取；mix会进入get_keywords_from_query/EXTRACT图链，证据出口不保证无LLM。
- QueryParam没有业务文档scope/exclude字段；范围在构建workspace前约束。graph描述可能融合多源，未来mix也不能只在返回后删doc_id。
- NanoVectorDBStorage.query把__metrics__映射为distance；依赖nano-vectordb0.0.4.3的dbs.py实际先L2 normalize，再矩阵点积，是cosine，数组float32。归一化/精度与原A1实现差异需记录，不声称逐bit相等。
- SDK模块直接load_dotenv(".env")；解析到python-dotenv1.2.4源码确认PYTHON_DOTENV_DISABLED真值会禁止加载。本实验隔离cwd并设置该变量，先用scratch .env哨兵回归验证，不读取/修改项目真实.env。

上述是源码事实。SDK/依赖安装、native存储完整性、回调计数、实际检索质量仍未验证。

## 3. 独立运行环境（审阅后安装）

原.venv及85包/requirements保持；新建`.venv-lightrag`，同Python3.12.14，不借Agent环境。只安装SDK core和pytest，不安装API/服务器/多模态extras，不启动服务。发布wheel安装避免本项目自动执行第三方setup/源码构建。

本轮已用现有pip **dry-run/ignore-installed/only-binary/no-cache**解析：LightRAG1.5.7＋numpy2.5.3/tiktoken0.14.0/setuptools84.0.0/pytest9.1.1，共62条安装记录；含nano-vectordb0.0.4.3、python-dotenv1.2.4、google-genai2.29.0等core的传递依赖。没有安装或改变原环境。完整版本、artifact URL和SHA256在dependency-lock-plan.json，不能把SDK核心19条依赖说成总安装19包。

批准后把该计划生成requirements-lightrag-runtime.txt（直接约束）与requirements-lightrag-runtime.lock.txt（62条精确版本/hash），更新.gitignore只增加新环境忽略项。锁为当前macOS/Python3.12解析结果，不声明Windows可直接用同artifact hash。下载各wheel到data本次目录，逐项hash核验，再安装；原85包版本/freeze/file hashes前后比较。

计划命令（未执行）：

```sh
.venv/bin/python -m venv .venv-lightrag
.venv-lightrag/bin/python -m pip download --only-binary=:all: --require-hashes --no-deps -r requirements-lightrag-runtime.lock.txt -d data/research/b-design-20261010/wheels
.venv-lightrag/bin/python -m pip install --no-index --find-links data/research/b-design-20261010/wheels --only-binary=:all: --no-deps --require-hashes -r requirements-lightrag-runtime.lock.txt
.venv-lightrag/bin/python -m pip check
```

若环境目录已存在，读版本/状态后报告，不能重置/覆盖。任何无wheel、hash/版本不符、依赖冲突都停在环境阶段，不换版本或自动升级。固定PyPI包与runtime.lock的hash计划是审批目标；runtime包不是实际生产方案。

tokenizer固定o200k_base，使用tiktoken0.14.0；其本机源码openai_public.py声明资产为https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken，SHA256=446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d。批准后准备步骤以新runtime运行`python -m experiments.lightrag_runtime --prepare-tokenizer --encoding o200k_base --cache-dir data/runtime/lightrag/o200k-cache`，仅下载该固定资产、最多10MiB并校验hash，按tiktoken缓存键保存及记实际URL/hash。准备后新SDK worker及所有摄取/查询/重放阻断网络，缺词表报missing_tokenizer_asset，不在检索时自动下载。软件/词表准备网络与模型请求/检索网络分开计数；词表不是智谱tokenizer，不能声称3072-token提供方验证。

## 4. 固定输入、范围与映射

沿用examples/mock-v1、tasks.json、公共corpus=`data/experiments/common-evidence-corpus/20261010T021859Z-647de42b`，fingerprint=`65d494952ab388ef3ca80bec1ce024e4e1676255ae2a7a3d80249e403aa8ca7e`；完整向量源=`data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e`。标签不进SDK/切分/模型回调。indexed_text仍make_index_text的context-body-v1，不加源ID/hash/路径文本；原文已有编号/链接保持。

在query.scope/exclude后按真实源范围得到两个不同池：历史11源/52单元和CASE-001源/10单元。各池独立进程/workspace，不通过范围外中转或召回后过滤。Q01/Q02排除的任务原本未在历史池；Q04同历史池，Q03只查询单源workspace。workspace名为规范scope/fingerprint hash，不采用任意用户路径；index/replay manifest包含范围、源/单元/输入hash和SDK/模型/策略。

原11源raw Markdown进入SDK full_docs，自定义chunker按SDK规范化完整输入hash唯一识别原源，并返回该源的公共单元；原source hash另存，不拿规范化输入位置冒充原文。用SDK sanitize_text_for_encoding在入队前确定lookup键，重复规范化全文导致多源歧义就报ambiguous_source_input，不猜源。此为本Mock RAW接线边界，真实同文多源生命周期另议。

native_doc_id=`doc-`＋真实document_id；native_file_path=`native_doc_id.md`只是唯一SDK引用标识，不声称它为原物理文件。native_chunk_id=`native_doc_id`＋`-`＋unit_id；chunk_order_index按原源内公共单元顺序。保存映射native_chunk_id→unit_id/document_id/原source_path/版本/body_span/contexts/input_sha256，旧公开证据字段保持。

callback6参数按本版签名接线，仅返回当前源完整make_index_text内容及tokens/order/id，不按框架大小重新切、不返回虚假_entity，不把复合context+body声称原连续source_span。原52 semantic输入当前全唯一、最长755字符；实际token数及规范化变化在准备后验证，任一模型文本变更/硬split/合并/丢单元即shared_corpus_mismatch。

## 5. callback与SDK生命周期

EmbeddingFunc明确embedding_dim=2048、max_token_size=3072、model_name=embedding-3、send_dimensions=False、supports_asymmetric=True。async callback接受texts/context/额外SDK调度参数，逐输入hash在原缓存中查（document/query分别登记），返回原顺序二维NumPy数组(len(texts),2048)，有限非零；不改文本/前缀/模型/维度、不截断。cache miss或未知context立即失败，不补网络，不用测试向量替代。

LLM callback始终raise unexpected_llm_call；既不是回假空图也不是假生成成功。统计调用角色/数量和异常；任何调用使本切片失败。现有真实Key不读取，父/子进程移除KEY_ENV；B1真实回调另有Spec，不临时切换live。

实际接线采用普通闭包函数转发到callback状态对象，而非把持有NumPy模块/trace的绑定方法直接交给SDK。首个真实SDK测试复现其_build_global_config→dataclasses.asdict→deepcopy绑定方法owner导致`cannot pickle 'module' object`；闭包保持同一个计数对象，避免SDK复制owner状态。原真实存储/回调计数断言作为回归，不修改SDK或测试断言。

SDK选择JsonKVStorage/JsonDocStatusStorage/NanoVectorDBStorage/NetworkXStorage，仅本次data工作目录；max_parallel_insert=1、embedding_func_max_async=1、embedding_batch_num=16、chunk_token_size=3072、chunk_overlap_token_size=0、embedding_chunk_overlap_token_size=0、enable_content_headings=False、rerank_model_func=None、llm_model_name=glm-5.2（仅明确身份，callback禁用），避免SDK再次附标题或不受控并发。tiktoken/库/固定构造参数均进manifest，env参数不作隐藏默认。

在一个持有全生命周期的事件循环中initialize_storages→apipeline_enqueue_documents(ids/file_paths/process_options="C!")→apipeline_process_enqueue_documents→flush/finalize。所有源必须PROCESSED、chunk_method=C/实际custom成功、skip_kg=true，无hard_fallback_split；按真实存储核对52或10个chunk。SDK失败文档不能只靠入口返回值判complete。

先核对text_chunks及doc_status，再退出进程，另新worker初始化原workspace/query。native content必须等于index_text且ID/归属一一对应；词频/原行号由原单位登记，不从basename推断。vdb持久向量必须对应缓存，因依赖float32/L2归一化，按预设rtol=1e-6/atol=1e-8检查归一化向量，不放宽以求通过。entities/relationships图和向量均为空且llm_calls=0。

## 6. 查询、原生预算与完整证据

mode=naive、chunk_top_k=20、top_k=20、enable_rerank=False、disable_user_prompt_prefix=True、max_total_tokens=32768、max_entity_tokens=0、max_relation_tokens=0；实际输入token统计与模板开销确认最坏20单元足够，不以token上限代替8000字符。cosine_better_than_threshold=-1.0显式传入storage kwargs，使本固定集无额外正阈值筛选；非法值或阈值被覆盖失败。

调用aquery_data保留原生chunks顺序；其出口不透传distance，所以另执行同workspace原生chunks_vdb.query记录raw20/distance，用已有query向量传query_embedding作诊断（不新增Embedding API）。ID/内容/顺序与实际aquery_data结果对照，不能按A1分数偷偷改框架排名。query_data正常no_results与SDK/IO/cache error分开，answerability仍unknown。

将native返回chunk_id映射原单元前，必须content逐字匹配索引文本，native截短/未知ID/范围外内容立即失败；不能看到ID就补一段未实际召回的正文。最终候选score取原生distance（cosine点积），rank用原生出口顺序，retrieval_method=vector，附SDK/input/dtype/原生排名信息。复用pack_evidence原36字符vector前缀及完整rendered_text/两换行/8000上限，标签到评价阶段才加载。

同时报raw-vdb前20、SDK去重/token预算后的chunks、最终selected及各阶段丢失，Recall@10/20/必要原文Coverage@8000仍按原定义。输出all score/rank/native_count差异，不预设B0与A1完全相同：float32/L2标准化、tie/native排序、原生token裁剪都是需解释的框架差异。Q04空依据仍unknown，不能从标签复制insufficient。

## 7. 影响文件、CLI与追踪

预计4新模块：lightrag_mapping.py（纯映射/缓存查找）、lightrag_runtime.py（版本/hash/env/词表准备边界）、lightrag_worker.py（SDK async生命周期/回调/存储核验/查询）、lightrag_probe.py（原环境父进程监督/评测/报告）；4对应测试，2 runtime requirements＋.gitignore，约11源码/测试/配置文件，另维护文档；超过8是两个环境及真实SDK子进程边界，非新增服务。每源码≤500行，不改旧公开API或现有A组代码/数据。

父进程CLI在原.venv运行：mode=build/replay、dataset/corpus-run/tasks/vector-run/runtime-python/runtime-lock/sdk-version/output-root、model/endpoint/dimensions（仅缓存身份）、tokenizer-cache/tokenizer-encoding、candidate-k/context预算/原生预算/threshold与截止。replay另需b0-run原完整目录。新SDK worker无.env、无Key、仅本scope白名单源/单元/向量；cwd为新run scratch，设置PYTHON_DOTENV_DISABLED=1/TIKTOKEN_CACHE_DIR/PYTHONPATH项目根，网络与pipmaster运行时安装禁止。

总deadline=180秒，单scope worker timeout=60秒，串行两个scope；父进程从启动开始扣时，超时kill/reap并保留进度，不能假complete。准备安装/词表不计检索耗时，检索scope与回调命中/未知文本hash、LLM/网络尝试、阶段计时、SDK状态/版本/Native存储和源绑定均记录。关键错误用固定分类，不保存Key/原始异常响应；仅授权合成材料进入data报告。

产物summary/index_manifest/unit_mapping/native_storage_audit/native_queries/results/evaluation/report/failure-analysis＋每scope SDK存储，完成标记最后写。replay核验源/单位/缓存/SDK/依赖/策略/files hash及原索引状态，缺失/过期/部分失败不自动补建或发模型调用。原A1重放结果/指标作为基线预检，A2/A3原失败保留。

## 8. TDD、验收与计划命令

安装检查通过后先写失败测试，真实SDK接线必须在新环境执行；原环境全套pytest含子进程集成测试，无skip来绕过SDK缺失。旧337测试继续通过。新增路径：

- 纯映射/原来源/空/重复规范化源/未知native ID/内容不符/角色/范围/版本/输入hash，labels/expected_pairs不能影响索引。
- SDK模块版本/hash正确、dotenv scratch哨兵不加载、runtime自动安装/网络阻断、词表cache缺失可观察；旧环境freeze/资产不变，未创建Web或外部存储。
- 真实C!回调被调用、52/10单元恰好写入、未硬切分/丢字段/内容改写；PROCESSED与持久化后新进程重载；空实体/关系、unexpected LLM/cache miss/IO明确失败。
- Embedding数组形状、空/顺序/重复文本/有限与维度/cache身份、Q03仅10，输入长度/本地词表token预算、dtype误差按预设容差、不改断言求绿。
- raw查询/data出口/映射/前20/8000完整长行、空结果/预算排除/网络/model0、旧评测范围/标签隔离、正常build/replay一致；startup扣时/worker超时/最终报告IO失败不写complete。

计划命令（尚未执行/入口尚未创建）：

```sh
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q experiments tests
.venv/bin/python -m pip check
.venv-lightrag/bin/python -m pip check
git diff --check
.venv/bin/python -m experiments.lightrag_probe --mode build --dataset examples/mock-v1 --corpus-run data/experiments/common-evidence-corpus/20261010T021859Z-647de42b --tasks examples/mock-v1/tasks.json --vector-run data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e --runtime-python .venv-lightrag/bin/python --runtime-lock requirements-lightrag-runtime.lock.txt --sdk-version 1.5.7 --model embedding-3 --endpoint https://open.bigmodel.cn/api/paas/v4/embeddings --dimensions 2048 --output-root data/experiments/b0-lightrag-naive --tokenizer-cache data/runtime/lightrag/o200k-cache --tokenizer-encoding o200k_base --candidate-k 20 --max-context-chars 8000 --max-total-tokens 32768 --cosine-threshold -1.0 --worker-timeout-seconds 60 --deadline-seconds 180
```

同参数replay用实际完整B0目录，输出新目录，不重复摄取；实际query结果除计时一致、评价相等、新模型与LLM/网络0。工程通过不保证B0高于A1；质量下降也保留，token/费用不适用。没有tokenizer/提供方调用数据时不编造token或账单。

## 9. 取舍、限制与下一步

选择发布1.5.7 wheel＋独立环境，减少旧main1.5.8未发布源码构建与原85包冲突；代价为62条新runtime依赖与多进程接线/存储维护。最小替代是继续原A1文件向量，但不能回答框架路径差异；直接live建图增加未知格式/调用量，故先完成缓存接线。

最脆弱前提：1.5.7实际C!管道可以保持52个完整语义单元并允许准确原生来源映射。若后续清洗/硬切分/去重改变它，阶段明确失败并记录，不修补成共享成功或悄悄用更多Embedding。同源生命周期和跨scope实体描述会给B1带来额外成本，真实资料/生产/更新尚未验证。

新环境/SDK存储与原A组独立；停用新CLI即可回到原入口。删除环境/回滚/清workspace另依项目授权，不自动删除/重置。以上为设计阶段取舍；实际安装、工程与检索结果见第10节，无本人学习掌握登记。

### 本轮实际设计验证

2026-10-10：`git diff --check`退出0，无输出；7份本轮指导文档检查：documents_checked=7、broken_local_links=0、trailing_whitespace=0。原experiments源码逐项SHA256对照A3收尾清单全部一致；原环境`pip freeze`与A3 before-freeze.txt逐字一致。`.venv-lightrag`不存在，4个拟新增LightRAG模块均不存在。检查脚本与结果保存于`data/research/b-design-20261010/design-validation.py`、`design-validation.json`；复核命令为`.venv/bin/python data/research/b-design-20261010/design-validation.py`。

L1：Spec及指导入口存在；L2实质SDK实现、L3本项目调用接线尚未完成。功能测试/应用构建本轮不适用，337项绿灯是上一轮A3结果，本轮没有重跑。发布资料/依赖解析使用了网络，但新模型请求为0，SDK摄取/检索均未执行；文档检查不能证明LightRAG功能或检索质量。

**设计阶段下一步（已完成）：用户“继续”授权后按TDD实施B0。当前唯一下一步见第10节。**

## 10. 2026-10-10实际执行与验收

用户“继续”确认具体组件/新环境/缓存B0方案。4新源码/4新测试/2固定requirements及.gitignore新增环境忽略项完成；原17个experiments源码SHA与A3收尾一致，原85包freeze逐字一致。原89资产对pre-A3仅有当时已确认的keyword_index及其测试2个差异，本轮未改变它们；其余87文件保持。真实.env/其他仓库、原公共语料/A1/A2/A3结果未改，无提交/push/服务。

62个wheel全部与批准计划SHA匹配、only-binary/require-hashes/no-index安装；SDK1.5.7及62包版本、SDK172个源码文件RECORD核验实际运行（源码数量以runtime manifest为准）；固定o200k词表准备/hash通过。安装/词表阶段有网络，B0请求阶段阻断网络，未执行第三方setup/自动源码构建。独立requirements只代表此macOS arm64/Python3.12实验环境。

TDD首次6failed/20errors（缺新模块）；首批2failed/17passed复现虚拟路径别名与SDK绑定方法deepcopy→普通闭包/保留传入缓存绝对路径→2passed。父进程把venv Python resolve成基础解释器导致runtime_mismatch→保留venv入口→7passed。失败worker未进入scopes使trace丢计数：1failed→按terminal报告汇总并对超时未报告标unknown→回归通过。JSON序列化异常遗留子进程：1failed→finally kill/reap→6 runtime tests passed。均修源，不改原断言/skip/conftest或旧helper。新增31项/总368 tests passed in31.23s。

实际验证命令（全部退出0）：

```sh
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q experiments tests
.venv/bin/python -m pip check
.venv-lightrag/bin/python -m pip check
git diff --check
```

输出：`368 passed in 31.23s`；compileall及diff检查无输出；两环境`No broken requirements found.`。应用构建不适用，compileall仅语法检查。TDD、安装/hash、最终命令/检查位于`data/research/b-design-20261010/b0-evidence`，完整build/replay argv见final-live-checks.json，data被Git忽略。

实际CLI沿第8节参数执行build（前置`env -u NAIYUE_RAG_ZHIPU_API_KEY`），输出：

```text
status=complete attempts=0 network_attempts=0 output=/Users/zmw/naiyue-rag/data/experiments/b0-lightrag-naive/20261010T082212Z-fae04e9e
```

相同参数改mode=replay、b0-run为该完整目录、output-root=data/experiments/b0-lightrag-replay：

```text
status=complete attempts=0 network_attempts=0 output=/Users/zmw/naiyue-rag/data/experiments/b0-lightrag-replay/20261010T082228Z-90499945
```

结果及evaluation均字节一致，原native14文件hash保持；replay不调用摄取/文档Embedding/切分。两个范围native正文及doc_status分别为11源/52单元和1源/10单元，processed/custom_chunking_func/skip_kg/无hard split、原生正文/ID/归属逐项核对。新进程加载实际float32/L2矩阵，最大归一化误差1.4901161e-8，在预定容差内；图节点/边与实体/关系向量空。缓存文档文本调用52+10、查询3+1，新模型/LLM/网络0。scratch.env哨兵测试确认未加载。全历史与单文档正文token分别6941/2085，可用片段预算31963–31990；raw20/SDK20（单文档10/10），无原生token丢失。

L1：4模块/4测试/2锁文件存在；L2真实映射/缓存/SDK生命周期/存储与版本校验/范围/监督/追踪/评测；L3 main→run→原A1复算→make_payload→run_scope→真实worker initialize→C! chunk闭包/EmbeddingFunc/Nano flush→finalize→新query worker重载/audit→aquery_data naive＋原生raw诊断→map_results/pack→所有检索后labels/evaluate→最后summary。正常、cache miss/未知context、无结果映射、内容/范围错配、存储损坏、失配版本/缓存、超时/序列化/报告IO失败均有明确失败路径和回归。

| 任务 | A1 Recall20/必要返回 | B0 Recall20/必要返回 | B0条/字符 |
|---|---|---|---|
| Q01 | 4/8，2/8 | 4/8，2/8 | 13/7690 |
| Q02 | 1/5，0/5 | 1/5，0/5 | 15/7809 |
| Q03 | 2/2，2/2 | 2/2，2/2 | 10/6843 |
| Q04 | N/A，N/A | N/A，N/A | 13/7792 |

四题候选和返回单元ID顺序均与A1相同，cosine最大差3.8330966e-8，非bit完全相同。Q01 E02/E04返回、E01/E03预算排除、E05–E08未召回；Q02 E03第20但预算排除，其余必要证据未召回；Q03所需排名2/10，首名缺口仍在；Q04unknown。B0保留基线行为，未带来质量提升；不能证明图无用或有效。assistant_constructed/not_reviewed合成标签，无真实业务/更新/生产/CPU本地Embedding或生成/MCP验证。本轮model usage/费用不适用。总2116.797ms含进程启动/校验/IO，不作性能基准。

[主报告](../../data/experiments/b0-lightrag-naive/20261010T082212Z-fae04e9e/report.md)、[逐条失败](../../data/experiments/b0-lightrag-naive/20261010T082212Z-fae04e9e/failure-analysis.md)、[重放](../../data/experiments/b0-lightrag-replay/20261010T082228Z-90499945/report.md)。代码课堂暂停，未登记已讲解/引导理解/独立实现/面试掌握。

**唯一下一步：制定B1原生EXTRACT/KEYWORD/描述合并/新增向量与调用追踪Spec，保持公共证据/既定模型/查询/标签/8000预算，然后审阅实施。**
