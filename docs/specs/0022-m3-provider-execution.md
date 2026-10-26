# Spec0022：M3.2 OpenAI兼容Provider与单批Dense执行

日期：2026-10-13。状态：用户“继续吧”确认本Spec与两包增量安装，已完成离线TDD和实际接线：60新增/957全量通过。openai2.54.0/jiter0.17.0已从核hash的本机wheel安装，135既有版本保持。真实模型请求0。承接Spec0020/0021及ADR0005，不接旧快照、不改变已确认总体路线。

## 1. 当前链路与本片目标

当前真实链路为独立EncodingSettings→M2 Document/Chunk→EncodingInput→plan_encoding_batches→normalize_embedding_response。最后一步只有模拟响应，没有SDK执行；timeout/deadline仅加载和校验。

本片接通：已准备的一批EncodingInput→DenseEncoder→OpenAI兼容Provider→原生SDK/有界HTTP响应→严格JSON→既有规范化→ProviderBatchResult及安全请求观察。文档和单项查询走同一路；不写向量库、不启动Agent，不加入Sparse/外层BatchProcessor或真实模型质量评估。

## 2. 参考与依赖依据

参考：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER；只读本机main/f658c5a4011c8b826707a65a3b11ce9301b0626f。OpenAIEmbedding.embed→原生OpenAI.embeddings.create→按data取向量，DenseEncoder另切批；源码入口src/libs/embedding/openai_embedding.py:101、src/ingestion/embedding/dense_encoder.py:66。参考openai>=1.0未锁运行版本，不能宣称我们与它的SDK默认值一致。来源/许可证沿Spec0020记录；本片使用依赖API，独立实现适配，不复制第三方源码。

官方说明：[OpenAI Python SDK](https://developers.openai.com/api/reference/python)。当前在线说明已采用HTTPX2，不能直接当成所选2.x源码事实。实际核验PyPI发布wheel的源码与METADATA：

| 选项 | 实际依赖事实 | 推荐 |
|---|---|---|
| openai 3.29.0 | 基础依赖httpx2>=2.12.0,<3 | 本片不引入新的HTTP栈；这不是模型质量取舍 |
| openai 2.54.0 | 基础依赖httpx>=0.23.0,<1、jiter>=0.10.0,<1，其余由当前环境满足 | 固定2.54.0，复用已装httpx0.28.1，先完成最小协议适配 |

以当前135个分发的精确版本作为constraints，pip --dry-run --only-binary=:all:确认只新增两包，无升级/替换：

| 包 | 固定版本 | 本机wheel SHA256 |
|---|---|---|
| openai（Apache许可证） | 2.54.0 | 89089789197ccdb87f173a03145ed1598d00795220c93e96cf712b1cbf5e5f2b |
| jiter（MIT） | 0.17.0 | 61aed66ee042b3b49ef85fdf75714234d055d89d8496ac1c6e47f89e7a30d5e4 |

wheel下载并核hash，只解包到ignored data/research/spec0022-evidence/isolated供子进程探针使用，没有运行setup/build或安装主.venv。jiter轮子为CPython3.12/macOS arm64；该hash与兼容性证据不自动适用于另一台Windows/CPU机器。后续正式依赖文件注明本机增量锁的适用范围，不把两条增量依赖说成完整项目锁。

## 3. 已核验机制与必要适配

| 机制 | 固定SDK源码/离线实测 | 本片实施要求 |
|---|---|---|
| 重试 | _constants.py默认2；401/429/500/ReadTimeout在max_retries=0时均只有一次模拟传输 | 显式0；HTTPTransport也retries=0，不引入外层重试 |
| 格式与维度 | resources/embeddings.py未指定格式时补base64；显式float不走隐式base64转换 | encoding_format=float；request_dimensions=null时完全不发，提供时按配置发，禁止按模型名前缀猜 |
| 响应读取 | 成功streaming入口不读正文；_base_client.py:1143–1147错误分支先response.read再造异常 | 限额必须在传输字节流层覆盖成功与错误响应，不能仅在成功入口iter_bytes累计 |
| 关闭 | response上下文退出关闭响应，但HTTP client仍开；sdk.close关闭所持HTTP client | Provider拥有并复用一个客户端，显式close/context manager；每请求响应独立关闭，异常同样关闭 |
| 超时 | 默认600秒/read，connect5秒；显式7秒已出现在HTTPX四类timeout扩展 | 配置timeout与remaining_seconds取较小值，禁止默认600秒 |
| 环境 | 显式Key/base_url仍会继承组织、项目、自定义headers | Key/base_url显式注入；用公开参数/Omit去掉组织/项目headers，不继承管理员凭证；首版拒绝存在OPENAI_CUSTOM_HEADERS的隐式注入，报固定码，不读取/输出其值 |
| 日志 | _base_client.py:518–533的DEBUG Request options实际含合成输入，内置敏感header filter不保护正文 | 本片不修改全局日志。构造/请求前检查相关SDK/HTTP日志是否会输出原始DEBUG/INFO；不安全配置明确拒绝后才允许网络。SDK导入前也核OPENAI_LOG，避免其自动改变日志配置。用敏感哨兵测试，生产入口只记录固定码/安全数字 |

代理/重定向显式trust_env=False、follow_redirects=False，302失败而非追随。若真实端点必须经代理，到服务验证时再配置明确代理；不从其他仓库读取配置。

### 有界读取的最小实现

Provider的HTTPX transport包装只服务SDK这一真实消费者：委托一次handle_request，核响应headers，再包装SyncByteStream。不是通用插件系统，不增加回调注册/ContextVar。

1. 请求Accept-Encoding: identity；首版收到非identity Content-Encoding明确失败并关闭响应，避免压缩体积与解压体积界限混淆。
2. 已声明Content-Length超过max_response_bytes可提前拒绝；缺失/不准确时仍按实际流累计。限额约束所有成功/错误正文，不信任header代替实际计数。
3. 先累计当前网络块大小，再判断限额，超限不追加到应用缓存，立即关闭。应用累计正文有界；不能声称底层从未收到一个越界网络块。
4. 正常成功正文从SDK streaming response取bytes；严格UTF8及JSON，重复键/非标准NaN/Infinity拒绝，不用SDK的宽松Pydantic对象来替代原响应合同。异常正文只允许SDK在同一字节界限内消费，不序列化供应商正文或异常链。
5. 流、响应和客户端关闭失败必须给出安全错误，不能空catch；已有执行错误为主错误，关闭错误作为固定诊断，不覆盖它。

本机仅验证了流边界原型在200/500均停止并关闭，尚未实现产品transport、压缩/header/JSON规则。这些是后续TDD验收项，不登记为已完成。

## 4. 拟接口与职责

- OpenAICompatibleEmbedding(settings, *, api_key)：只接受本项目独立配置和显式非空凭证；初始化失败无网络。embed(texts, *, timeout_seconds)单次请求，返回(payload, request_report)；不分批/分块/写库。作为内部边界仍核文本与数量/字节预算，不仅信任Dense调用。
- DenseEncoder(settings, provider)：核两者模型/表示配置一致；encode_batch(inputs, *, remaining_seconds)使用既有输入重校验与计划，要求恰好一批，然后调用Provider并normalize_embedding_response(source_kind=service)，返回(result, request_report)。空/多批/非法剩余时限拒绝且请求0；整个空文档任务由后续BatchProcessor正常处理。
- 每请求report采用明确白名单dict：attempted_requests、http_status或null、response_bytes（已观察）、elapsed_seconds（单调耗时）、error_code、response_close_error_code及client_close_error_code（后三项固定码或null）；成功tokens仍来自ProviderBatchResult.usage，未知不补0。没有响应的网络错误不编HTTP终态。
- 新EmbeddingExecutionError继承EncodingError并附白名单report，既有EncodingError签名/错误合同不变。正常返回与失败报告都不包含Key、URL、正文、词项、向量全文或原始exception。
- 暂不建立只有一项的Provider注册表/插件工厂。现有provider枚举只有已实现openai_compatible；有第二个后端或明确选择消费者时再建立工厂。这是沿参考职责分期接线，不更换LangChain底座。

Dense不再内切批。上层后续BatchProcessor是唯一分批和整任务请求预算负责人，传递remaining_seconds；M5查询同样先准备单项输入。此次不新增旧retrieve_once兼容回调。

本片Provider为同步、顺序复用的单客户端，拒绝同时/重入使用同一个实例，不声明线程安全或并行能力。HTTP传输对象每请求显式绑定report/deadline，流拿到该请求的数据，不使用全局上下文或回调。测试通过monkeypatch HTTPTransport构造注入MockTransport，不新增产品transport参数或替身Provider。

timeout是网络等待约束；请求前/流块间/返回前检查剩余deadline只能形成协作截止，不能中断任意阻塞同步调用或证明任务硬截止。真正整体硬截止沿现有worker监督经验留整任务切片。SDK2.54.0没有因超时自动安全取消远端计算的证明。

## 5. 分支与验收

| 分支 | 预期 |
|---|---|
| 文档/查询单批、逆序index、合法model/dim | 真SDK+模拟HTTP→结果ID/hash/vector按输入对应；报告单请求、usage分别已知/未知 |
| 空/多批/篡改输入/超限/时限耗尽/不安全环境日志配置 | 固定错误，网络调用0 |
| dimensions提供或null | 实际HTTP请求正文分别存在/不存在该字段；float格式显式 |
| 401/429/500/302/网络超时 | 整次失败，无重试/跳转/换模型/单路降级；错误report安全 |
| 大成功/大错误正文、缺失或虚假Content-Length | 同一实际字节界限生效，响应关闭，不把错误响应留给SDK无限read |
| gzip等非identity编码/非法UTF8/重复键/坏JSON | 明确报错且关闭；不静默解压或降级 |
| 重复/缺失index、NaN/零向量/错维度/别名不符 | 复用原规范化断言，服务响应不成为可用结果 |
| 已关闭Provider/close故障/正常上下文退出 | 无请求或明确故障诊断；原执行错误不被关闭故障替换 |

故障由httpx.MockTransport/SyncByteStream注入，使用真实固定SDK，禁止socket网络并使用合成Key/内容。mock服务响应里的source_kind=service只表示经过协议入口，验证报告仍明确mock，不称真实服务通过。不加平行SDK替身框架，不依赖sleep极紧窗口。

拟影响文件：encoding/openai_embedding.py、bounded_transport.py、dense_encoder.py、execution_report.py、encoding/__init__.py及正式包导出、core/errors.py（增加独立子类）、两份编码增量依赖清单与对应Provider/Dense测试。execution_report仅供初始化/请求/关闭/Dense预检三个以上真实分支复用白名单报告及安全抛错，不是事件系统；Dense与Provider核所有执行配置一致，避免runtime界限不一致。每个源码文件≤500行，既有输入/结果字段及序列化合同不变；如发现必须变字段，先修Spec再同步消费者/测试。

安装前按仓库AGENTS“修改环境前确认”取得两包增量授权；之后确认缺Provider/Dense为预期红灯，再最小实现。验证目标测试、全量pytest、compileall、pip check、git diff --check及135包版本保持。无需新UI/服务/配置/.env/数据库。应用构建未设立；compileall只算语法检查。

回退边界：此时无索引写入或激活，不动旧实验/真实缓存；关闭Provider即可停止新执行路径。依赖卸载、删除或Git回滚仍按仓库权限确认，不自动执行。

## 6. 本轮准备证据

```sh
.venv/bin/python -m pip install --dry-run --only-binary=:all: \
  --constraint data/research/spec0022-evidence/constraints.txt \
  --report data/research/spec0022-evidence/dependency-plan.json \
  --cache-dir data/research/spec0022-evidence/pip-cache openai==2.54.0
# Would install jiter-0.17.0 openai-2.54.0
.venv/bin/python data/research/spec0022-evidence/probe.py
# {"sdk_version":"2.54.0","checks_passed":21,"network_attempts":0,"model_requests":0}
.venv/bin/python -m pytest -q tests/test_encoding_settings.py tests/test_encoding_inputs.py tests/test_encoding_validation.py --tb=short
# 56 passed in 0.29s
```

probe-results.json逐项保留成功延迟读、四种HTTP错误提前读/单请求、超时单请求、格式、关闭、环境headers、DEBUG正文以及有界流原型。wheel-verification.json/dependency-plan.json保留实际版本/来源/hash；网络下载曾出现TLS错误，改pip download取得jiter并再次核hash，没有关闭TLS校验。源码解包和原型仅调研，未进正式包。收尾pip check输出No broken requirements found，git diff --check退出0；validation.json比对135包精确版本未变，openai/jiter仍未安装。应用构建不适用，本轮无产品源码修改。全量897为Spec0021上一轮证据，本轮没有重跑全量；没有新产品功能红/绿灯、服务请求或用户独立掌握证据。

上节是准备时证据；实际实施状态与下一步以第7节为准。

## 7. 实际实施与验收

### TDD与差异

先写两份测试，确认缺Provider/Dense模块导致2个collection errors。实现后49/55通过，6项失败来自新测试注入：真实时钟消耗使timeout小于初始预算、直接改logger.level未更新Python日志缓存。保留所有断言，改固定生产边界时钟及setLevel注入后55项通过。不改生产时限语义/已有conftest/旧断言。

收尾补5项关键分支，初始化资源关闭和意外规范化异常报告预期红灯。修源：HTTPClient构造失败时关闭已创建transport；Dense意外Exception转换固定embedding_encoding_failed并保留报告。初始化测试单独运行须先导入真实SDK，再替换Client构造，否则提前触发SDK类定义失败；修故障入口后原断言保持、两个回归可独立通过。最终60项通过，无skip/放宽。

Provider的timeout_seconds限制本次可用时间窗，网络timeout再取剩余窗与runtime.timeout_seconds的较小值；Dense扣除预检耗时，规范化后再核deadline。这是协作截止，不能中断任意阻塞同步调用。单元测试只把三个生产边界的time对象替换为同一固定时钟，无sleep；SDK/框架时钟不改。wiring_probe用真实单调时钟，但mock耗时不当服务延迟。

非阻塞Lock拒绝同实例重入/同时执行，close同样核锁，不宣称并行编码。BoundedTransport.begin直接交report/deadline给流。KeyboardInterrupt原样传播，关闭失败只记固定诊断，不覆盖原异常；无headers则http_status=null，真正委托传输时才记attempted_requests=1。

### 实际命令与输出

```sh
.venv/bin/python -m pip install --no-index --no-deps --require-hashes --find-links data/research/spec0022-evidence -r data/research/spec0022-evidence/install.lock.txt
# Successfully installed jiter-0.17.0 openai-2.54.0
.venv/bin/python -m pytest -q tests/test_openai_embedding.py tests/test_dense_encoder.py --tb=short
# 60 passed in 0.39s
.venv/bin/python -m pytest -q tests --tb=short
# 957 passed in 57.82s
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0；应用构建未设立，这只是语法检查
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0
.venv/bin/python data/research/spec0022-evidence/wiring_probe.py
# 12文档→72Chunk（12完整用例）→72输入→36模拟HTTP批→72向量；另1查询向量
# mock_http_requests=37，actual_network_attempts=0，model_requests=0
# unknown_usage_requests=37，client_closed=true，retrieval_quality=not_evaluated
```

probe实际读取前片合成独立YAML，加载12Mock并调用正式M2/M3输入/计划、Provider、Dense、规范化和序列化；真SDK由MockTransport返回逆序index。逐批核ID/hash/vector顺序、wire float/dimensions省略、timeout与关闭。演示脚本外层循环不是产品BatchProcessor；37次mock调用不是37真实请求。source_kind=service只表示协议入口，报告明确mock；usage全部未知，无token/cost/真实延迟/质量结论。

implementation-validation.json记录135既有包不变、仅增2包至137；114既有源码/测试/样本hash保持，只改3既有源码（包导出与错误子类）。4新增实现模块、2测试/2依赖清单真实存在，源码均≤500。不改旧实验/断言/向量、真实.env/YAML或其他仓库，未提交/push。

L1存在：4编码模块、新错误子类、两个测试/依赖清单。L2实质：真SDK请求、字节/JSON/向量校验、安全report/错误映射、协作deadline及生命周期。L3接线：独立YAML→M1/M2→输入→Dense→Provider→SDK→MockTransport→规范化→结果/报告；文档/查询均覆盖，正式导入仍不加载experiments。

剩余：真实服务/资料/检索评测、硬截止监督、Sparse/外层成对结果及M4索引未验收。只支持同步OpenAI兼容协议，压缩响应拒绝，不称Azure/Ollama/Claude Embedding已支持。日志不安全则拒绝网络，不修改全局日志。

唯一下一步：按M3.3制定Sparse词项与批次完整性Spec，先落实中文最小词长候选和标识符/数字规则，再接正式Sparse与成对结果。真实服务留M3.4，不复用旧临时Key或预算授权。

### 教学与Debug Test入口

职责/数据流已说明；本人完整走读、复述、独立实现/追问能力未评估，不创建Lesson8完成记录。按project-learning延续模块分支图。

| tests/中的精确节点 | 输入/分支/预期 | 断点、栈帧与观察 |
|---|---|---|
| test_dense_encoder.py::test_actual_dense_path_preserves_source_and_reorders_indices[query] | 两问题、逆序index→输入顺序恢复，1请求/已知usage | DenseEncoder.encode_batch:17→Provider.embed；测试帧先看items，Provider返回后Dense帧才有payload/report，规范化后才有result。WATCH [i.item_id for i in inputs]、[r['index'] for r in payload['data']]、result.input_ids/result.vectors |
| 同函数[document] | 真实M2输入→原文span/hash保持 | F5到Dense边界，只投影items[0].source_span、embedding_text[:80] |
| test_openai_embedding.py::test_actual_byte_limit_covers_success_and_error[absent-500] | 三块×32bytes，上限48→第二块停止/关闭，HTTP500保留、错误码too_large | _BoundedBody.__iter__中report['response_bytes']从32→64，第二块未缓存；_fail抛→Provider捕获→安全异常，pytest预期捕获所以绿 |
| test_openai_embedding.py::test_http_failure_single_attempt_safe_report[429] | 429→1请求，无重试/泄漏 | Provider except分支；最终caught.value只看code/report |
| test_openai_embedding.py::test_response_close_failure_observed_without_masking_http_failure[500] | Body.close抛OSError→HTTP500仍主错误、关闭诊断明确 | 故障Body.close、捕获_close_response；WATCH http_status/error_code/response_close_error_code |
| test_openai_embedding.py::test_initialization_failure_closes_created_transport | Client构造失败→transport关闭、请求0 | SDK先真实导入；fail_client及Provider初始化except，看resource选择transport |

VS Code Test Explorer选节点Debug Test，用F10/F11/Shift+F11；未学SDK内部可F5到本项目边界。HTTPTransport构造被换成MockTransport，SDK/编码实现不替换；时间仅在确定性测试模拟。不要重新调用embed/close看返回值，result/report在返回后才产生。精确节点见test-nodes.txt。
