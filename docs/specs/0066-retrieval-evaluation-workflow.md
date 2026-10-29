# Spec0066：批量跑题、人工证据积累与离线检索评分

状态：用户已授权切片A实施并发布0.2.0，A已实现/接线/本机验证；B/C仅设计，尚无产品命令。2026-10-28用户确认先跑题并人工看结果，从结果逐渐积累证据集，再以Recall@K等指标支持模型/参数对比。
本文规定完整演进合同；本次交付切片A，B/C按明确的依赖顺序接入，不以本设计宣称已有自动评分或真实质量结论。

## 1. 当前事实与选择

当前nyr query经ManagedConnection/LocalClient→认证回环HTTP→共享RetrievalService→RetrievalPipeline→ResponseBuilder。
服务固定模型配置，每次查询绑定一个活动版本。最终JSON已有完整片段、来源SHA/正文位置、Dense/Sparse/RRF排名、重排分数、预算排除项与观察数据。
现有serving.benchmark是并发/耗时验收；validation.retrieval_smoke沿旧多文件配置且限四道未审核合成题，不能直接承担本次用户题集。
先搜后复用：新命令复用现有连接、查询、版本和证据合同；旧smoke保留，正式功能不依赖experiments。

选择标准库JSON/CSV/Markdown文件与现有CLI；不引入评测框架、数据库、新服务、模型裁判或新依赖。
已有本机认证和模型凭据沿统一配置使用，不索取新账户/Key。设计验证不依赖当前模型服务在线；实施使用受控本机模型替身。
公司真实材料和目标机端点由用户执行验收，不假定本机可访问。

```text
questions.jsonl → nyr eval run → 现有共享检索服务
                         ↓              ↓
                  运行记录/人工报告 ← 最终证据
                         ↓
                   人工选取并核对原文 → gold.jsonl
                         ↓
               nyr eval score（离线）→ 指标/逐题对照
```

## 2. 切片A：先跑题、保存结果、人工看

切片A命令（已接线并通过本机安装验收，公开交付见0.2.0 Release）：

```sh
nyr eval run --config config-a.yaml --questions questions.jsonl --output runs/model-a
nyr eval run --config config-b.yaml --questions questions.jsonl --output runs/model-b
```

每次只运行一份配置；模型切换、准备权重和建库仍由已有流程显式完成，不自动更换模型/摄取/调参。
不同Embedding使用独立有效storage_root，材料固定；并行启动多套服务时端口不同。不把expected_revision当历史版本选择。

### 题集合同

UTF-8 JSONL，每个非空行一题；允许空白行。每题闭合字段：

| 字段 | 类型/规则 | 用途 |
|---|---|---|
| id | 非空ASCII字母数字/下划线/短横线，1–64字符，整集唯一 | 跨运行关联 |
| query | 非空字符串，原文保留；UTF-8可编码 | 实际查询 |
| reference_notes | 可选字符串 | 人工已知原文位置或待核对依据，仅报告展示 |
| checkpoints | 可选字符串数组 | 人工检查要点，仅报告展示 |
| scope_document_ids | 可选合法文档ID数组，不重复 | 复用现有范围语义 |
| exclude_document_ids | 可选合法文档ID数组，不重复 | 复用现有排除语义 |

重复JSON键、NaN、未知字段、重复ID、类型错误拒绝；所有题先完整校验，再创建输出和连接服务。
CLI提供--max-questions（默认1000）、--max-input-bytes（默认16777216），均为正整数；每题实际查询请求还须符合既有service.max_request_bytes。
缺省/空列表的范围语义沿核心；reference_notes/checkpoints永远不进入HTTP请求、Embedding或重排输入。
保存原题集字节摘要；每题另存仅含实际查询及过滤条件的request_sha256，提示说明变化不改变实际请求身份。

### 执行和失败

1. 输出目录必须不存在；拒绝覆盖、符号链接目标及知识库/索引根下的输出。新建目录0700、所有文件/临时文件0600（Windows沿系统ACL），不写知识库/真实配置。
2. 加载配置/模型表并计算现有身份摘要；通过ManagedConnection复用常驻服务，无服务时沿原所有权规则启动临时实例。
3. health核身份后documents读取active及source_path/source_sha256清单；无活动版本明确拒绝，不自动摄取。
4. 冻结本批active，顺序执行题目，每次query传同一expected_revision；结果active必须与初始完整描述相等。
5. 每题记录真实客户端端到端耗时和服务已有阶段观察；首题冷启动/缓存影响保留，不把这一轮当稳定性能基准。
6. 单题模型失败/超时保留固定安全错误码，继续下一题，不自动重试；后续查询仍受真实服务槽位/期限约束。
7. revision冲突、结果版本不符、服务身份变化/不可用、输出IO失败立即结束本批；保留已有结果及未执行题ID。
8. Ctrl+C停止后续请求、关闭客户端，取消传播沿现有断开合同；返回130。取消不表示后台已实际退出。
9. 每完成一题追加结果并flush/fsync；meta以临时文件+原子替换更新。报告完成后最后提交终态，报告失败标aborted。进程被强杀后可能遗留最后半行，离线读取报告损坏/未完成，禁止静默忽略或宣称完成。
10. 完整执行且无请求错误返回0（空证据是有效执行）；有请求错误/版本变化/输入或IO错误返回2。质量结论不影响run退出码。

### 运行产物

| 文件 | 内容 |
|---|---|
| run.json | schema_version=1、包版本、起止时间、运行状态running/completed/partial/aborted、题集摘要、题ID/request摘要、服务身份、完整active、按来源路径排序的文件SHA清单、脱敏配置、计数、未执行题 |
| results.jsonl | 每题id、request_sha256、执行状态、耗时、原query/范围、成功时原schema2响应或失败时安全错误码 |
| report.md | 模型/版本说明，逐题问题、人工提示、原文证据、来源/位置、排名、预算排除、耗时、错误；不作自动好坏判断 |
| review.csv | id、request_sha256、judgment、notes；后两列空白，人工填足够/部分/无帮助/不确定及说明 |

run状态completed表示无请求错误；partial表示请求有失败但跑完；aborted表示中途终止。无输入数据不生成假题/假分数。
配置只导出白名单：选中模型逻辑ID、实际模型名/版本/维度、表示和切分参数、检索/重排/证据预算、模型及服务期限。
不导出api_key/api_key_env、access_token、完整models.json、环境变量值或带凭据的URL；不保存向量、原始模型响应或提示词。
题目和返回原文只进入用户指定的结果文件，终端/日志仅进度、题ID、路径和安全错误码。
Markdown中的用户内容作转义并以安全引用/文本展示；CSV处理公式前缀，保留原始文本于JSON结果。现有目录拒绝覆盖，离线工具不改人工填写文件。

第一片仅保存stage=final_evidence，按evidence数组次序形成连续的评估排名；原字段rank保留为来源重排排名，避免预算排除后排名有缺口。
记录rank_limit=min(hybrid.fusion_top_k,rerank.top_k)与实际返回数；返回少于上限是合法结果，不补条目。
本片不声称有Dense/Fusion完整候选，不能从最终证据推算上游Recall@20。

## 3. 切片B：候选依据变成可审核证据集

拟新增离线命令，不访问模型或服务：

```sh
nyr eval evidence --config config-a.yaml --runs runs/model-a runs/model-b --output evidence/v1
```

按题目id+request_sha256合并已保存结果的候选依据，来源材料清单必须相同；输出目录必须不存在，生成candidates.jsonl、待人工编辑的gold.jsonl及source-snapshots目录。
candidates记录来源/正文位置/quote、出现的run和排名；gold每题review_status=pending、answerable=null、required_units为空，未审核项不伪装有效标签。
本命令的config只用于找到本地资料包，读取首个run记录的明确bundle_id，核对其来源清单与所有run一致；不连接HTTP、不解析Key、不依赖当前活动版本或源目录在线。
资料包缺失/校验失败即停止。将包内文档按原UTF-8字节写入source-snapshots，以SHA命名文件，manifest.json映射来源路径/SHA/大小；不自动覆盖结果。
同一来源SHA及字符区间去重，不按分数判断业务正确，不自动将候选放进required_units。人可删掉无关项、选取更小的原文范围、补充未被任何模型召回的依据。
输出不含伪造的reviewed状态；题目整体review.csv判断不自动转换为Gold。

人工正式gold.jsonl每题字段：schema_version=1、id、request_sha256、review_status(pending/reviewed)、answerable(bool/null)、required_units。
required_units是一组必需业务依据，每项unit_id唯一，alternatives为一组等价出处；每个出处有source_path/source_sha256/start_char/end_char/quote。
字符坐标沿核心保留原始换行的UTF-8解码文本，区间左闭右开；quote须是该区间原文，行号只作可读辅助，不作为身份。缺条件的片段不能仅因词相似标为等价。
一个unit可以有多份等价出处，命中任一份即可；各unit之间是必须覆盖的不同业务要点。
reviewed表示人工已审核这组必要依据和已知等价出处，仍允许日后修订；每次评分记录整份gold文件摘要，不声称穷举了所有可能正确表述。
未审核/缺标签保持未评分。answerable=false必须由人工核对资料，不能由检索空结果推断；此类题的Recall/MRR为null，不纳入正例分母。
本片提供字段说明和真实产物生成的待审核草稿，不向用户目录写示例业务答案。

## 4. 切片C：离线评分与调参对照

```sh
nyr eval score --run runs/model-a --gold evidence/v1/gold.jsonl --k 1 3 5 --output scores/model-a
nyr eval score --run runs/model-b --gold evidence/v1/gold.jsonl --k 1 3 5 --output scores/model-b
```

仅读结果/gold，不连接模型、不需要启动nyr服务；cli在加载运行配置前分流离线子命令，避免默认配置初始化/Key依赖。
参数K为正整数且不超过已记录rank_limit；超出明确拒绝，不补足候选。若合法K内实际结果不足K，按实际返回结果计算，不把空槽当正确命中。
输入run/results需完整一致，输出目录不存在；材料清单/题请求不符、来源SHA变化、重复gold或越界坐标拒绝，不拿别题/旧材料标签评分。
草稿/pending题、缺标签题与人工无答案题分别计数，未评分项不默认为0。某道已审核正例的请求失败按0计入主指标，同时单列运行失败；aborted运行拒绝汇总，防止漏执行题抬分。

匹配单位为必需业务依据，不是固定chunk_id：前K个返回项body_span及contexts的来源区间，在同source_path/SHA下求并集；完整覆盖某个等价出处才算该unit命中，部分重叠不算命中。
同unit多次命中只计一次；Gold坐标/quote与gold.jsonl旁的source-snapshots核验，逐文件核原UTF-8字节SHA，再用解码文本核坐标和quote。
结果中的body/contexts也必须与该快照对应区间一致，不能仅相信文件中声称的SHA和坐标。缺快照、路径逃逸或不匹配明确失败。
来源快照不复制运行配置/密钥，不读变化中的远端工作区；新补Gold可直接引用同一完整来源快照，未召回的资料也可人工加入。

| 指标 | 确定口径 |
|---|---|
| Hit@K | 前K条完整覆盖至少一个必需unit为1，否则0 |
| Recall@K | 完整覆盖的不同必需unit数/该题必需unit总数；报告注明required-evidence-unit coverage |
| MRR@K | 首次完整覆盖任一unit所需的最小前缀排名r，取1/r；K内无命中为0 |
| Complete@K | 全部必需unit均覆盖为1，否则0 |
| 最终证据覆盖率 | final_evidence阶段全部实际返回项的unit覆盖比例 |

前缀联合覆盖的MRR注明evidence-prefix口径，不与传统单片段相关性MRR混称；输出逐题值及同一已审核正例集合上的宏平均。
score.json记录gold摘要/题集摘要/stage/K/分母/未评分计数/请求失败数/指标定义；score.md与per-question.csv提供可读明细。
不同运行对照必须使用同份gold和相同请求/材料，报告样本范围；不把新增标签前后的分数直接归因于模型变化。
nDCG需要分级相关性标签，不在本轮实现；无答案识别准确率需独立分类合同，本轮不从answerability=unknown伪造。

## 5. 上游阶段诊断的扩展边界

最脆弱假设：最终交付证据足以支持首轮人工选型；它不足以定位所有上游漏召回原因。
因此A产物明确stage及排名深度，C先评分final_evidence；需要Dense/Fusion/Rerank指标时，增加专门诊断切片捕获对应完整候选及来源。
诊断须复用一次RetrievalPipeline的真实中间结果，不重跑来拼凑同一请求；只导出排名/来源/文本，排除QueryEncodingResult中的向量。
该扩展在用户需要上游定位时单独定API，不属于本轮A/B/C实施，不提前改线上query签名/响应大小或默认吞吐。

## 6. 文件范围与实施顺序

整体涉及超过8个文件，但不新增服务。切片边界如下，各源码文件不超过500行：

| 切片 | 主要文件 | 交付/验证 |
|---|---|---|
| A | cli.py；新增validation/evaluation_inputs.py、evaluation_run.py、evaluation_report.py；test_evaluation_inputs.py、test_evaluation_run.py、test_evaluation_cli.py；installed_smoke.py、run_formal_tests.py；README/使用说明 | 严格输入→真实nyr连接→逐题结果/报告/空白人工表 |
| B | 新增validation/evaluation_evidence.py及对应测试；CLI/使用说明 | 多run候选归并、人工状态、同版本只读原文快照、明确Gold schema |
| C | 新增validation/evaluation_score.py及对应测试；CLI/正式测试清单/使用说明 | 离线匹配/指标/错误及分母/调参对照 |

新增职责独立模块是为隔离输入校验、带副作用的跑题和纯离线报告/评分，沿现有validation包，无需改pyproject包发现或加新依赖。
不会直接复用旧smoke的受限标签校验，也不修改旧测试来让新合同通过。正式编码前各片补充其精确测试表，不重选已定方向。

## 7. 验收与回退

- A：正常题/空证据/中文和多行题、非法JSON/重复ID/未知字段、提示不泄露到请求、scope、版本冲突、模型超时后继续、服务失联、Ctrl+C、输出IO失败/拒绝覆盖、Markdown/CSV安全展示、配置凭据不入产物。
- B：不同模型同材料归并、重复出处、等价依据/多必需unit、人工补充原文、pending不可变reviewed、来源快照/hash/坐标不符、结果排名不自动变成标准答案。
- C：手算固定例子的Hit/Recall/MRR/Complete、并集覆盖/部分覆盖/重复命中/等价出处、空标签与无答案null、失败正例为0、超深K拒绝、材料/请求不符、离线断网/无Key/无默认配置IO。
- 安装验收增加一份合成题集跑真实nyr子进程、原生索引和受控模型端点，检查产物可读及凭据缺席；公司真实质量由用户另验，不自动发送材料到新模型。
- 实施验证命令：`.venv/bin/python -m pytest -q tests --tb=short`、`.venv/bin/python scripts/run_formal_tests.py`、`.venv/bin/python -m build --outdir dist/evaluation-candidate`、分发审计/Twine/pip check及离源码安装smoke；`git diff --check`。
- A新增测试先红后绿；最终测试/构建/安装结果完成后追加，不借用Spec0065的2437通过作为本功能验证。
- 回退撤新增CLI/validation接线即可，既有索引格式和query协议不变，已生成题集/评审/证据文件保留；本次用户已明确授权0.2.0提交/push/标签发布，真实配置/材料/旧结果不变。

下一步：完成A的完整回归和0.2.0发布门禁后交付用户运行；B/C后续实施，用户题集可只有id/query。

## 8. A最终本机证据（2026-10-29）

- 新增37项评测回归，包含私有权限、路径归一化、认证/资源变化停止、报告写入失败和外围中断；按对应预期红灯修复。架构/安全复核无剩余高置信阻断。
- `.venv/bin/python -m pytest -q tests --tb=short`：2474 passed in530.13s。
- `.venv/bin/python scripts/run_formal_tests.py`：1803 passed in469.54s。
- 最终wheel/sdist成功构建，分发内容审计、Twine严格检查、compileall、两环境pip check、git diff --check通过；新增源码均不超过500行，无新依赖。
- 在隔离依赖环境安装最终wheel，离源码Python -I运行installed_smoke：installed_version=0.2.0、status=passed、evaluation_questions=2、http_concurrent_queries=10、shared_retrieval_queries=10、tcp_disconnect_cancelled=true、cli_management_roundtrip=true。
- 平台macOS26.4 arm64/Python3.12.14；原生Chroma/BM25/SQLite及合成本机HTTP模型，真实厂商请求0、权重下载false，不当作公司Linux模型/资料质量证明。
- 本地最终候选dist/release-0.2.0-final：wheel SHA256=5efb0482d7c2992ac013a88042382de2fa4271415c4e00ffb1ece713e4eba341；sdist SHA256=b5eeb4a2daa2dd422fb560c6cf1c71e0b559bd9cb581c7dc8b28093f1c409534。
- 公开制品由标签流水线重新构建，公开SHA须与该次受测CI制品核对，不混用本地候选摘要。0.2.0发布还须同提交分支CI、标签流水线、公开安装和同标签模型附件验证，实时结果以GitHub/PyPI为准。
