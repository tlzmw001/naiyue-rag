# Spec0026：M3真实服务验收与受监督执行设计

日期：2026-10-14。状态：已按用户授权完成离线TDD与本次最多2次POST的真实小样本验收，结果见第9节。沿已确认M3路线，保留Spec0021–0025接口；本片新增的是独立验收入口的执行边界和随后的小样本服务验证，不把验收工具扩为生产任务调度框架。

## 1. 当前事实与为什么要改

当前BatchProcessor/QueryEncoder在同步阶段前后检查单调时间；Provider限制单请求超时、响应字节、重试为0，但阻塞IO/Sparse初始化或处理不能靠调用后的检查即时中断。上一片1167通过是离线历史证据，本轮未重跑全量。

固定参考：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER，本机main/f658c5a4011c8b826707a65a3b11ce9301b0626f。2026-10-14对已核BatchProcessor/OpenAIEmbedding调用链搜索subprocess/Popen/deadline没有命中；这只描述该调用链，不断言整个参考项目没有其他监督机制。

本项目旧experiments/embedding_probe.py:211–254与vector_embedding.py:141–176用Popen→communicate(timeout)→kill→读检查点，已有实质机制。新入口不导入实验：借鉴父子进程/安全检查点，解决旧全环境继承、终止后无超时communicate、stdout/stderr无长度边界及现有M3报告消费差异。

选择标准库Popen.communicate监督，stdout/stderr指向DEVNULL；安全检查点只写有界、本项目私有run目录的JSONL。相比读取双PIPE并维护线程/selector，文件检查点无需额外后台队列，父进程只在退出/终止后读，终止时仍可取得完整前缀；用于低频验收，不承诺在线高吞吐。控制性检查点写失败须停止下一请求，不套用可选查询trace写失败仍保留结果的策略。

## 2. 一条完整执行链

```text
本机CLI：严格读取独立Encoding/Sparse配置、两合成文件
  → M1/M2准备两document EncodingInput + 新query，先核全部计划/原文hash
  → 无Key/非法配置/输出路径/总请求超限：失败，0子进程/0请求
  → 新建私有run目录/检查点文件，开始监督时钟
  → Popen固定本项目worker，stdin只传有界配置/合成输入，Key只进专用子环境
      worker：构造Provider/真实Dense/Sparse
      → 私有ObservedDense（监督检查点适配）
      → BatchProcessor一次文档批请求 → QueryEncoder一次查询请求
      → 结果严格重校验/JSON往返/身份一致检查 → 关闭Provider → final
  → 正常：父进程读/校验检查点，返回完整验收报告
  → 超时/worker退出异常：kill（仍在运行时）→限定时间wait→读有效检查点前缀
      → 失败验收报告，无部分编码结果，未知请求/usage明确标出
```

父子进程都不写索引/激活数据。源准备/配置读取发生在监督开始前，耗时单列；120秒监督覆盖Popen后导入、SDK/jieba初始化、文档/查询编码、客户端关闭。回收另限5秒，调度/文件系统异常另报，不能宣称绝对实时或整个摄取服务已具120秒硬截止。

终止本地worker不等于取消服务端任务、撤回请求或退款。当前Provider无重试、worker不启动后代，最多两次Dense调用全局控制；进程组/分布式取消不在该验收工具范围。

## 3. 明确的运行参数提案

全部由独立配置/显式CLI参数传入；以下为本轮验收值，不是检索最优参数或模型通用限制。

| 参数 | 本轮值与原因 |
|---|---|
| provider/base_url/model | openai_compatible；https://open.bigmodel.cn/api/paas/v4/；embedding-3；沿已定模型核新SDK链 |
| expected_dimensions/request_dimensions | 2048/null，核默认输出，不发送自定义维度 |
| model_revision/allowed_response_models | null/[embedding-3]，未知revision不伪造，未声明别名明确失败 |
| document_text_mode/text_layout | raw/contexts_then_view，沿当前正式输入机制 |
| document_prefix/query_prefix | 空/空，本轮不引入训练前缀假设，语义效果另评 |
| batch_size/max_inputs/max_requests | 2/2/2；两个文档输入合批1次+问题1次；监督适配全局限2次 |
| max_input_utf8_bytes/max_batch_input_utf8_bytes | 4096/8192，应用资源保护，不能当3072 tokens计数证明 |
| timeout_seconds/deadline_seconds | 30/120；单请求SDK超时与父进程整体监督分开 |
| max_response_bytes | 262144，单请求安全读取上限，超限明确失败 |
| Sparse | min_chinese_term_length=2、lowercase=true、max_terms_per_input=10000、max_resource_bytes=33554432；模板cache_dir=./cache，按实际执行配置文件目录解析 |
| cleanup_seconds | 5，终止后wait仍限时，回收失败写worker_reap_timeout，不无限等待 |
| max_checkpoint_bytes/max_checkpoint_records | 65536/16，写入前和父进程读取均限制，不积累原stdout/stderr |
| key-env | NAIYUE_RAG_ZHIPU_API_KEY，仅当前项目注入；父进程用Spec0027的resolve_api_key读取指定项目.env/命名环境变量，不使用旧聊天Key |
| output_dir | 显式位于本项目data/validation的新run目录，目录0700/文件0600；已存在拒绝，不覆盖/清空 |

样本为两份新、公开合成Markdown：feature_x=1启用/0关闭；threshold=0.5边界/缺参报错。问题：“feature_x=1且threshold=0.5时应关注哪些边界？”只验协议和工程合同，不让本轮调用解答它或评价召回。

本轮离线准备探针实际得到2文件/2Chunk、合计171原文字节、最大Chunk46字符，模型0；稍后创建examples中的相同固定材料。父进程预检固定两输入及一问题，不通过截断材料凑预算。

## 4. 官方接口核验与限制

2026-10-14读取官方[Embedding API](https://docs.bigmodel.cn/api-reference/模型-api/文本嵌入.md)和[Embedding-3说明](https://docs.bigmodel.cn/cn/guide/models/embedding/embedding-3.md)，URL/日期/SHA缓存data/research/spec0026-evidence/official-sources.json。

官方文本写默认2048维、单条3072 tokens/数组不超过64条；本轮只2条/1条、使用默认2048。API维度枚举与文档部分示例不完全一致，本轮不据例子选768或任意维度。

当前Provider显式发送encoding_format=float，官方本轮请求schema未列该字段。新SDK→真实智谱端点的兼容性需要实测；不先悄悄移除参数或放宽结果断言。若端点拒绝或返回模型别名/usage不兼容，保留固定失败证据，形成单一修复提案后再实施；不自动增加第三次请求。

官网文档GET成功不证明Key/模型账户/计费/Embedding POST可用。2026-10-14仅检查当前进程命名环境变量是否存在，结果false；没有读取.env/旧Key或第三方环境。标准API Key是唯一外部凭证依赖，Coding Plan不当Embedding额度。随后用户明确要求根.env加载，Spec0027已实施该能力；本段存在性false仍为设计时观察，不代表之后配置不能生效。

## 5. 检查点、观察与新增适配的必要性

新入口只新增一个私有ObservedDense适配，实际调用方是验收worker的BatchProcessor/QueryEncoder。它持有真实DenseEncoder/settings，并原样转调encode_batch；不实现另一套Embedding，也不改原函数签名。

当前核心只在整个任务返回时交报告；父进程终止发生在Sparse阻塞时，已经完成的Dense用量无法由最终结果取得。因此需要在Dense边界有安全检查点。直接给核心加回调会改公开签名，跨职责共享整条任务流程也不合适。这个适配只服务监督验收，后续生产任务若需要监督应独立Spec，不默认复用本工具承诺。

- Dense前：检查全局剩余请求预算，先持久写request_reserved，记录序号/文档或查询阶段/输入数量与指纹。这里是调用预留，不叫已发HTTP。
- Dense成功：核合法ProviderBatchResult/配置别名和request_report，再写request_observed，保存真实请求次数/HTTP状态/合法usage；无正文/词项/向量/URL/Key。
- Dense异常：合法EmbeddingExecutionError.report写观察，usage按当前M3失败合同未知；未知异常/非法report保留未确认调用，不补0。
- Sparse/配对/最终失败：核心EncodingJobError报告另作阶段证据，与已有观察核对，不把同一请求重复加总。
- 客户端关闭：worker显式finally关闭；正常路径关闭失败使验收失败，已有主错误与关闭错误各保留固定码，不能覆盖主错误。

检查点用单worker顺序JSONL、递增seq及run_id，协议类型闭集：worker_started、task_started、request_reserved、request_observed、task_result、cleanup、final。各事件字段严格校验、未知键拒绝；输入只摘要，合法响应model须在声明别名内。每次有界序列化后追加/flush/fsync，未完成写不能进入下一调用。

父进程拒绝乱序、重复序号/观察、身份漂移、越预算、完整行畸形和final后追加。kill造成末行未完成时保留此前完整合法行，并明确checkpoint_truncated；协议失败保留此前观察但整体失败，不能从坏内容补字段。最后final必须与exit code/计划/任务终态/关闭状态对应。

监督报告另于核心EncodingReport：status=complete/failed；terminal_stage/error_code；worker_exit_code/kill_requested/reaped/cleanup_error；reserved_dense_calls/observed_dense_calls/attempted_requests_known_sum/attempted_requests（有未知调用则null）；已知usage小计、未知调用数/总体usage状态；源准备与监督耗时、配置/输入身份、doc/query核心报告与验证摘要。

总请求/usage以request_observed账目为主，task_result只交叉检查。已经预留却没观察的调用不直接计为HTTP1；账单未知、不按字符估算或均摊。未启动worker/请求时0是实际事实；服务端未返回的HTTP状态留null。硬终止失败不交付部分向量，只保留安全观察。

## 6. IO、环境与权限

示例YAML是待批准的运行模板；本轮执行会把两个已严格校验的模板原样复制到新run目录（0600），再用现有load_encoding_settings/load_sparse_encoding_settings读取副本。Sparse模板cache_dir=./cache因此位于新run/cache，不在examples下建缓存、不修改原模板；绝对cache路径语义保持，但本轮固定采用相对模板。源准备前对模板做严格分组/字段校验，生成执行配置和输出目录是获确认后的本片操作。

父进程在显式项目根用resolve_api_key(project_root,key_env)解析凭证，命名环境变量存在则优先，否则只读该根.env。只把所选Key注入子环境，不复制整个.env，也不让worker搜索凭证文件。

父进程用固定sys.executable和本项目模块参数列表启动，不接受任意命令/拼接shell。stdin有界且不含Key；子环境仅必要运行变量白名单与本次显式Key，不能dict(os.environ)复制所有账号变量。Provider继续显式Key/URL、trust_env=false/no retries/no redirects；父进程先检查会改变SDK日志/headers的环境条件，不能通过丢变量悄悄绕过既有guard。

stdout/stderr均DEVNULL，原异常/调试正文不写文件。关键失败通过检查点及父报告固定码显式可见；没有final的异常退出报worker_failed。所有路径只接受本项目明确源/配置和data/validation输出，拒绝路径穿越/symlink/非新目录；目录/检查点创建、追加、读取、关闭和报告保存失败均须可观察。

这是本机离线CLI/库级验证工具，没有HTTP/MCP入口。检查点是监督控制与必要证据，不能降成可选日志；M0可选追踪持久化行为不改变。清理只终止本次启动的worker，绝不删除run产物/原材料/缓存/索引；不复制其他项目凭证/环境，不修改真实.env。

## 7. 文件范围、测试与两阶段验收

预计10个源码/测试/样本文件，超过8文件但没有新依赖或服务：

1. validation/__init__.py：独立验收包，无顶层正式API/实验兼容重导出。
2. validation/encoding_check.py：配置/预算预检、CLI及父监督。
3. validation/check_report.py：安全检查点/监督报告协议与核对。
4. validation/encoding_worker.py：真实组件装配、ObservedDense与检查点写入、资源关闭。
5–6. tests/test_encoding_check.py、test_encoding_check_wiring.py。
7–10. examples/encoding-check/feature.md、threshold.md、encoding.example.yaml、sparse.example.yaml。

源码单文件≤500；接近上限时按职责拆分且先更新Spec。不改Provider/Dense/Sparse/Batch/Query公开签名，不增加框架/注册/ContextVar，不复用旧实验入口，不删旧资产。

第一阶段离线TDD：父监督正常、启动失败、总预算预检0请求、无Key、未知/缺失观察、Dense后Sparse阻塞、非法/超限/截断检查点、错误exit/final、kill/wait失败、客户端关闭失败、日志Key哨兵、父/子关键IO失败；真实M1/M2/SDK MockTransport/Sparse链验文档/查询三类身份。确定性Popen替身测超时/预算，另用就绪握手的真实阻塞子进程验证终止/回收，避免sleep50ms一类紧时间断言。既有tests全量、compileall、pip check、diff及旧资产hash保持。

第二阶段真实服务：标准Key就绪且本Spec调用边界获确认后，只用固定2合成文档/1问题、最多2次POST、整体监督120秒。不重试/换模型/额外探针；成功验2条文档向量+1条问题向量均2048/有限非零/ID-hash正确、正常Sparse/JSON/身份与关闭，usage能取得则真实记录，否则明确未知。失败保留错误/最后安全观察；任何第三次调用需新的具体授权。

现有CLI入口（完整实际执行命令见第9节）：

`python -m naiyue_rag.validation.encoding_check --encoding-settings <独立配置> --sparse-settings <独立配置> --output-dir <全新本项目data/validation目录> --project-root . --key-env NAIYUE_RAG_ZHIPU_API_KEY --cleanup-seconds 5 --max-checkpoint-bytes 65536 --max-checkpoint-records 16`

本轮不接生成模型/LLM问答、M4数据库/索引或M5召回，不把三个向量成功当RAG质量通过。回退是停用该验收入口，保存错误证据；无索引/数据回滚。

## 8. 设计阶段证据与当时待确认项（历史）

实际两份合成样本的M1/M2准备得到2Chunk/171原文字节，模型0。实际运行既有：

`.venv/bin/python -m pytest -q tests/test_embedding_probe.py::test_deadline_kills_child_and_keeps_attempt_unknown tests/test_vector_embedding.py::test_deadline_kills_worker_and_preserves_attempt --tb=short`

输出2 passed in0.26s。这两项使用Popen替身，只证明旧监督分支，不证明新runner/真实子进程已终止。当前只有Spec及官网缓存/样本准备探针存在，新10文件/执行入口尚未实施，未重跑全量，构建不适用。

待确认是本片新增的父worker/必要检查点设计及新服务验收边界（最多2次POST、120秒+5秒回收）；embedding模型、串行成对编码和整次失败等已定路线不重选。真实阶段还需本项目.env或命名环境变量中的标准API Key；设计时当前进程缺失，Spec0027已提供文件加载能力；不在文档填Key或回用聊天临时凭证。唯一下一步：确认该具体Spec后先连续完成离线实现；凭证就绪时按同一已确认边界完成真实验收。

### 实施接口澄清

run_check(encoding_settings_path,sparse_settings_path,output_dir,*,project_root,key_env,cleanup_seconds,max_checkpoint_bytes,max_checkpoint_records)为验收模块入口，前置配置/路径/凭证失败抛固定CheckError且不启动worker，执行后返回安全监督dict。CLI将前置错误转成固定失败JSON。worker stdin描述符额外限16384字节；监督时钟含启动，超时后kill+wait均限定。父进程只负责本次直接子进程，不杀进程组。报告保存失败同时返回persistence_error，不掩盖原主要执行错误。

实施补充：固定合成材料按文件名/原文SHA核对，拒绝被替换的正文，避免该验收工具上传其他材料。Sparse缓存限定本次run内；通用Sparse加载器的绝对路径语义未改。全量回归暴露根.env.example已缺失（test_only_root_example_is_unignored：FileNotFoundError），恢复既有Spec0027约定的空模板，不读取/修改真实.env，也不放宽旧断言。

## 9. 实施与验收记录（2026-10-14）

用户确认Key已填本项目.env并要求继续，沿第3节具体边界执行，无额外模型请求。已形成10个源码/测试/样本文件及恢复的空.env.example；core编码API、既有源码/测试和依赖版本保持。必要检查点失败停止后续编码，不交付部分向量。空模板恢复是全量真实失败后的最小修复，不修改真实.env或旧断言。

### 离线TDD与工程证据

- 首个红灯：test_encoding_check缺validation模块，ModuleNotFoundError（data/research/spec0026-evidence/red-implementation-tests.txt）。随后父监督与协议19通过，补真实SDK MockTransport/jieba链、调用后Sparse失败、关闭/IO/截断/协议/预算/未知观察与隔离worker等，共55 passed in6.31s。
- 测试替身修正说明：单问题Sparse替身只返回一条query记录，不适用两document批，改用既有按输入ID/kind返回的批次Sparse替身；已知Sparse失败用EncodingError(sparse_encoding_failed)注入，未知OSError另保留独立测试并期待既有encoding_stage_failed。未放宽生产断言或修改旧测试基础设施。
- 完整Mock链发现父进程先判exit!=0会遮蔽合法失败final，修为校验final/exit对应后保留具体失败码；非法final/exit配对仍失败。固定样本被替换时新增预检失败回归，文件名/原文SHA与指定合成集一致才允许子进程。
- 首次全量：1 failed,1265 passed in89.17s，唯一失败test_only_root_example_is_unignored因根.env.example缺失。恢复空模板后该原测试1 passed in0.14s；再次全量1266 passed in89.33s，见full-tests-after-template.txt，首次失败输出保留。
- compileall退出0；pip check输出No broken requirements found.；git diff --check退出0；git check-ignore .env输出.env。记录static-verification.json。111既有资产SHA/安装包freeze均保持（implementation-preservation.json）；当前新增源文件最大186行。
- 真实阻塞子进程测试以pipe就绪握手确认进入Sparse，再注入父超时分支，实际kill/wait并核对进程已退出，保留之前1次Dense/7个合成tokens；超时触发是测试注入，不声称等到了真实120秒或发真实模型请求。服务返回/账单与此合成usage分开。

```zsh
.venv/bin/python -m pytest -q tests/test_encoding_check.py tests/test_encoding_check_wiring.py --tb=short
.venv/bin/python -m pytest -q tests --tb=short
.venv/bin/python -m compileall -q naiyue_rag tests
.venv/bin/python -m pip check
git diff --check
```

### 实际服务命令与结果

以下为本次已执行记录；output-dir已存在，工具拒绝覆盖。重新执行模型验证属于新的请求，不能复用本轮2次限额。

```zsh
.venv/bin/python -m naiyue_rag.validation.encoding_check --encoding-settings /Users/zmw/naiyue-rag/examples/encoding-check/encoding.example.yaml --sparse-settings /Users/zmw/naiyue-rag/examples/encoding-check/sparse.example.yaml --output-dir /Users/zmw/naiyue-rag/data/validation/20261014-spec0026-01 --project-root /Users/zmw/naiyue-rag --key-env NAIYUE_RAG_ZHIPU_API_KEY --cleanup-seconds 5 --max-checkpoint-bytes 65536 --max-checkpoint-records 16
```

- CLI退出0，run_id=4cb009b7743d4eb7af29ab45846925dd，status=complete，监督耗时1.8621365419821814秒；并未触发真实超时。worker exit0、reaped=true、kill_requested=false；11条合法检查点、无协议/截断/关闭错误。
- 两次真实HTTP200，source_kind均service、返回model均embedding-3；文档响应51843字节/调用耗时0.58597秒，查询25947字节/0.29824秒。encoding_format=float在此次服务请求被接受，无参数移除、重试或第三次POST。
- 两文档输入+一查询输入严格成对/JSON往返，三条向量均2048维，有限非零校验与ID/各自hash核验通过。model_space_id、representation_id、tokenizer_id在文档与查询之间一致；原向量只在worker内验证，检查点/报告不保存向量/正文/词项/Key/URL/供应商body。
- 服务返回usage文档70/query21，共prompt_tokens=total_tokens=91；两次usage状态known、未知请求0。真实账单/费用无数据，billing_cost=null，不按价格推算。
- 安全报告及配置副本在data/validation/20261014-spec0026-01/，CLI副本在data/research/spec0026-evidence/live-cli-report.json。两者内容一致；.env仍Git忽略，仅选定Key从父进程专用子环境注入，未读取/复制其他仓库环境。

L1：validation包、样本和两测试文件存在。L2：Popen/有界必要JSONL/严格Ledger/真实组件装配均为实质实现。L3：CLI预检→worker→BatchProcessor和QueryEncoder→ObservedDense→DenseEncoder→真实SDK服务、Sparse及DTO→关闭→父报告已跑通；不是只有组件各自测试。

范围限制：只完成本模块小样本协议/工程接线，不代表检索、跨文档业务或问答质量通过；无索引写入、真实业务材料、CPU本地Embedding性能或生产任务调度验收。课堂仍暂挂，本人独立能力未评估。唯一下一步：对照参考项目梳理M4存储/索引生命周期与现有Chroma资产，先给出M3成对记录如何持久化/激活/查询消费的Spec，再按确认范围实现。
