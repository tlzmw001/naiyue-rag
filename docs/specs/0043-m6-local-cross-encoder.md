# Spec0043：M6.3 本地 CrossEncoder 后端

2026-10-15，用户已明确本轮同时完成两类后端，先 GLM 闭环；本片在 GLM 验收后实施。2026-10-16用户已确认单环境兼容方案，继续实施；已完成当前本地工程边界验收，实际推理/测试结果见本Spec实施节。

## 调用链与选择

参考 main/f658c5a4011c8b826707a65a3b11ce9301b0626f：CoreReranker→RerankerFactory→CrossEncoderReranker→sentence_transformers.CrossEncoder→predict(query, passage)。沿用此实现方式，不另造推理框架。我们已有 CoreReranker.score 合同，新的 CrossEncoderReranker.score 复用同一完整候选/ID/整次失败检查；query CLI 通过 rerank_backend=cross_encoder 选择，本地不使用 LLM Key。

参考示例 ms-marco-MiniLM-L6-v2 标注 English。本次 CPU 工程验证选择同一作者多语言模型 cross-encoder/mmarco-mMiniLMv2-L12-H384-v1；官方卡 https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 标记15语言、Apache-2.0、使用同一 CrossEncoder.predict，并非最佳业务模型结论。BGE-v2-m3 保留后续质量/长文本对照候选，不同时下载多套权重。模型 Hub commit、文件哈希、字节量和日期在下载后记录，并以本地 naiyue-model.json manifest在加载前逐项核对大小/哈希/身份；只读安全权重，不执行远程代码，不读取私人 Hub token。

## 配置与实际执行

新增 CrossEncoderSettings(model_id,model_revision,model_path,device,batch_size,max_pair_tokens,max_model_bytes)，严格 YAML；model_path 相对 YAML 解为绝对路径。运行时只加载指定本地目录，local_files_only=True、trust_remote_code=False、token=False，缺失文件明确 rerank_model_unavailable，不自动联网下载。model_id/revision 作为实验身份记录，与下载 manifest 绑定。

先对每一对完整 query+passage 按真实 tokenizer 计算含特殊 token 的长度（truncation=False）。任一超过 max_pair_tokens，整次在 predict 前报 rerank_input_limit；不得用 predict 默认截断掩盖丢失用例。显式 CPU/batch_size/max_length，原始浮点分数映回原候选，数量/标量/有限数检查。与 LLM 共用排序合同，但分数域不可横向比较。

模型加载和预测错误只报安全 code；无候选结果/HTTP请求/费用伪报；本地 report attempted_requests=0、usage=None、elapsed 实测。不把同步 timeout 字段当作能中断 PyTorch：本片不新增虚假硬截止，真实验证用子进程监督，超过300秒终止并记录未知完成状态。

## 依赖与边界

已核对 PyPI 一手元数据：sentence-transformers 6.1.0、transformers 5.20.0、torch 2.14.1；新增 CPU 推理依赖采用独立 requirements-reranking.txt 固定主依赖；先以当前全部137个安装版本作 constraints 执行 pip --dry-run，确认不升级/替换已有包后再安装，记录新增锁定集合、pip check 和实际接口源码。若解析需改变既有版本，停止并讨论具体冲突。

新增依赖只装本项目 .venv、权重只存本项目被忽略的 data/models；不改实际 .env、其他仓库/全局环境，无第三方 setup/Skill 执行。GLM 和关闭基线不要求本地模型包可导入；本地后端懒加载，不拖慢其余入口。

## 影响与验收

新增 core/cross_encoder_settings.py、reranking/cross_encoder.py、requirements-reranking.txt、可迁移示例、测试；接入 app 中已预留分支并去除未实现说明。现有 CoreReranker/ResponseBuilder 合同保持。先红灯验证 tokenizer 完整长度/错误/非有限数/成对顺序，再真实安装版本源码核验，真实本地权重 CPU 推理及同候选三路比较。原生验证阻断 socket，证明推理阶段零联网；下载与推理分账。

固定标签：合成样本由助手构造、未人工审核，文档级及片段级指标分开；按问题必要证据集合做 Recall@k，空标注不伪造分母或无答案检测。将召回池、关闭重排、GLM 和本地重排分别评价，失败保留，不因某个分数改善宣布业务通过。

回退：显式 none 或 llm 可继续使用原流程；失败不隐式回退，不删除模型、旧索引或旧代码。完整模块结束时做全量回归与文档收束，然后按已定阶段进入系统学习。

依赖预检结果：6.1.0 要求 huggingface-hub<2 而现有为2.2.0，pip dry-run exit1，未安装或替换包。已向用户提问独立 .venv-rerank（相同源码和 CLI）或当前环境调整兼容版本；此环境选择待真实答复，不能自动选项。等待期间只完成无安装依赖的后端合同和确定性测试。

本地合同验收：`pytest -q tests/test_cross_encoder_reranker.py --tb=short`首次13项因模块缺失红灯→13 passed in0.12s；真实包/权重尚未安装，不能当作本地推理通过。反向依赖静态核对：原tokenizers要求hub>=0.16.4,<3，当前主要冲突是新增sentence-transformers的hub上界；未据此擅自降级。

兼容候选已只读求解成功（仍未安装）：保持其他现有包固定，候选需将hub2.2.0调整至1.33.0，新增sentence-transformers6.1.0/transformers5.20.0/torch2.14.1及其必要依赖共10包。完整pip plan见data/research/spec0043-evidence/compatible-candidate-plan.json。两种环境方案均已有可审阅候选，等待用户选其一才实施。

## 2026-10-16 已确认的实施修订

用户在了解版本影响后明确“好的就这么做”：使用当前本项目 .venv，将 huggingface-hub 2.2.0 调整为1.33.0，安装已求解的10项新增依赖，其余136项原有包保持版本。不再创建第二环境或重复询问此选择。早先“待环境答复”为历史状态，已被本节替代。

安装前保存当前137包快照；requirements-reranking.txt固定已审阅的11项变更集合，并用136项原版本constraints约束安装。先执行pip check与本片合同测试，发现构建/依赖失败先修复再继续。实际模型下载只取固定Hub commit 1427fd652930e4ba29e8149678df786c240d8825 下的模型卡、配置、tokenizer和safetensors；不执行仓库脚本、不下载pickle权重。文件身份/大小/hash保存在模型manifest。

CPU验证先原生加载/完整pair长度检查/真实predict，再用前轮四份HybridResult缓存比较关闭重排、已保存真实GLM与本地CrossEncoder；固定候选与标签不变，阻断socket，新真实模型API请求0。随后以模拟Embedding/原生本机索引验证app后端选择，避免为接线证明再次调用服务。推理验证由独立子进程300秒监督。完整模块退出执行当前全部测试，而非把历史全量与新增数相加冒充新运行。

已安装6.1.0源码核对发现：CrossEncoder.__init__(max_length=...)会先覆盖processor.model_max_length；因此先加载自然上限，核对配置不超过它，再设置公开max_seq_length，避免自我比较。新增回归先确认DID NOT RAISE红灯；此次修正不改输入超限报错策略。

依赖全链路同步：旧Chroma增量lock仍固定hub2.2导致真实verify_runtime门禁报runtime_mismatch；先复现，再仅同步该项至本次已下载1.33 wheel的真实SHA256。其余48项不变，新增reranking增量hash lock记录11项；不放宽runtime校验或修改旧测试。

可迁移接线补充：新增validation.prepare_local_model显式命令，从CrossEncoderSettings取得模型ID/commit/目录/总字节上限，只下载四项必需安全文件和已有的三项可选tokenizer/模型卡文件，token=False；按Hub该commit的LFS SHA256或git blob SHA1校验，再保存本地SHA256 manifest。已有合法manifest只审计复用，未知非空目录拒绝覆盖；失败保留部分文件，不自动删除。核心查询仍只离线加载，不自动下载。该命令供新机器复现，避免依赖本机data里的临时脚本。新增正常/篡改/限额/失败与复用测试，不调整旧测试基础设施。

## 实施与验证（2026-10-16）

### 安装与锁文件

实际命令：

```bash
.venv/bin/python -m pip install -r requirements-reranking.txt -c data/research/spec0043-evidence/compatible-candidate-constraints.txt --report data/research/spec0043-evidence/install-report.json
.venv/bin/python -m pip check
```

安装exit0；pip check输出`No broken requirements found.`。前后实际metadata对比：原137包只有huggingface_hub2.2.0→1.33.0，其余136包版本保持，新增加10包，总147。基础/Chroma/编码/reranking四锁共146唯一pin，冲突0、实际安装不匹配0（pip本身不在运行锁内）。安装轮/哈希来自实际pip report，未猜测wheel值。

同步Chroma旧锁前，真实verify_runtime因已装hub与旧锁不一致拒绝；同步该一行后原门禁通过，旧test_chroma_probe.py为6 passed in2.11s。没有放宽版本/原生SDK审计或修改旧测试断言。

### 固定权重与实际版本源码

下载模型：cross-encoder/mmarco-mMiniLMv2-L12-H384-v1，commit1427fd652930e4ba29e8149678df786c240d8825；7文件492748252字节/48.757秒，卡片Apache-2.0，实际LFS SHA256/git blob与固定commit核对后记录本地SHA256。无pickle/远程代码。data/research/spec0043-evidence/model-source.json、download-summary.json保存来源；权重在examples/core-demo/data/models，受Git忽略。准备入口对合法已有模型返回unchanged，不重下。

实读安装6.1.0的cross_encoder/model.py、base/model.py、base/modules/transformer.py，源码hash见installed-source.json。自然容量检查回归：首次1项因未报错红灯，修正先读取自然max_length、再设置公开max_seq_length后14 passed in0.66s。

### 原生CPU与同候选池对照

实际监督命令`.venv/bin/python /tmp/naiyue-local-rerank-check.py`，源码快照保存native-03/runner.py。300秒父进程监督，HF/Transformers离线参数与socket阻断；CoreReranker→真实CrossEncoder.predict→CPU Transformer.forward→ResponseBuilder。模型参数设备全部cpu。

首次native-01/02未通过完整性观测断言，原因是6.1直接调用底层forward方法，绕过了PyTorch __call__ hook，观测数组为空；不代表模型没有执行。沿实际源码追到调用处，将**验证脚本**的观测挂到真实bound forward，并继续调用原函数、保留同一完整token计数断言，native-03通过。未修改生产得分、正文、标签或放宽断言。一次中间脚本输出目录重名未启动worker，另存新目录后继续，原失败产物保留。

native-03实际：模型加载2.992秒，整个四题重放7.686秒，Python网络尝试0、模型API0，最大pair150tokens，预检token数与实际forward attention_mask计数逐批一致。每题本地重排分别0.172/0.164/0.134/0.136秒（已加载模型，本机单次测量，不是跨机器性能承诺）。本轮不新增GLM/Embedding服务请求，复用前轮实际候选与GLM缓存，不重新调参。

| 问题 | 候选池必要片段 | 关闭重排Recall@5 | 保存的真实GLM | 本地CPU | 本地预算后 |
|---|---:|---:|---:|---:|---:|
| Q1跨文档回归 | 3/3 | 1/3 | 3/3 | 2/3 | 2/3 |
| Q2旧用例预期 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| Q3日志规则 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| Q4无依据问题 | null | null | null | null | null |

标签仍assistant_constructed/not_reviewed_by_user。Q4仍unknown，不称已识别无答案。Q1漏项是L1保留规则：RRF8→本地10，GLM4；相关历史需求RRF3→本地2，旧用例RRF9→本地3。候选池已有完整原文，失败定位到重排/top_k；不据此宣称模型内部原因、完整业务质量或本地模型总体优劣。failure-analysis.json保留该负向证据。

### 实际CLI接线与确定性错误

`.venv/bin/python /tmp/naiyue-native-cli-check.py`：严格YAML→app.query→QueryEncoder→真实Chroma/BM25/RRF→真实本地CPU→最终5条证据，与固定缓存本地重放的context_text/活动版本完全相同。Embedding只用MockTransport返回**相同问题已有的真实向量**，模拟SDK请求1、新外部模型请求0、Python网络尝试0；不是新Embedding服务调用。安全合成Key仅在该子进程env注入，真实.env不改。

新增tests/test_cross_encoder_app.py通过真实本地适配器/模型文件审计与原生存储，重型模型和Embedding HTTP为模拟，覆盖normal/failure/empty三分支及配置实际消费。模型准备6项红灯→通过；准备+本地合同20 passed in0.57s，本地片合计23 passed in12.96s。另一次安装后相关76 passed in28.24s。

本片公开入口包括显式prepare_local_model、两种app配置和CPU重排库入口。model_manifest校验失败/缺文件/超限/预测异常整次报错；关闭基线明确none，不自动切换后端。源代码不超过500行，没有新增Agent、MCP或问答层。

当前最终全量`.venv/bin/python -m pytest -q tests --tb=short`：**2151 passed in404.22s（0:06:44）**，包括现有全部测试与本片10项新增；完整原始输出full-suite.txt。compileall exit0、pip check无破损依赖、git diff --check exit0，源码最大266行。M1–M6阶段A当前本地工程边界通过，下一步为阶段B第1章。真实资料、Windows/Linux部署、本地Embedding、生产容量/可靠性仍未验；个人掌握无新增证据。
