# Spec0065：nyr启动共享检索服务及CLI覆盖

用户明确要求nyr适配新服务，并检查旧功能CLI空白。延续0060的2执行/20等待、协作取消与调用方重试。

## 当前流与目标流

当前nyr→run_service→create_service→ApplicationRuntime，仍串行业务；新RetrievalService只由库入口消费。
目标nyr→同一认证回环HTTP入口→RetrievalService，chat/query/documents/ingest都复用该实例。
不改变监听边界、Token与进程所有权；跨机器入口仍由后续MCP/网络Spec实现。

## 接线与合同

- create_service默认factory改为RetrievalService，保留runtime_factory测试注入签名；新增registry只读属性供身份摘要使用。
- query通过submit取得QueryHandle，异步等结果并独立监听http.disconnect；断开或ASGI取消时handle.cancel。
- 新增handle.async_result()，shield底层Future，取消等待会请求协作取消；不把Future.cancel误当后台线程退出。
- 保持health完整三字段与protocol=1；configuration_identity加入固定execution_contract标识，拒绝复用旧串行服务。
- 新检索错误映射：timeout504、overloaded429、closed/cleanup/shutdown503、invalid_request400、cancelled409；
  已断开请求直接结束响应，不发晚到成功；旧核心错误映射和证据schema不变。
- 接收请求体用既有service.request_timeout_seconds限制总读取期限，超限408/service_request_timeout；认证和大小预算先行。
- 所有GET/POST仍先显式校验Token、Host和Origin；错误不回显原请求/配置/底层异常。

## CLI与核心功能覆盖

| 已有能力 | CLI接线 |
|---|---|
| 启动常驻服务 | nyr，无需子命令；新RetrievalService长存 |
| 交互/一次查询 | chat/query保留，query补--scope-document-id/--exclude-document-id可重复参数 |
| 文档列表/详情 | documents保留；补document DOCUMENT_ID [--expected-revision N] |
| 显式移除文档 | 补remove DOCUMENT_ID --expected-revision N，复用IngestionPipeline.remove_document |
| 摄取/更新/force | ingest既有参数保持；使用独立writer，不占查询槽位 |
| 队列/后台收尾状态 | 补status→认证GET /v1/status，使用同一共享实例 |
| 本地重排模型准备 | models prepare保持本地显式入口，不启动服务 |
| 无截断审计/容量验收 | 既有nyr-embedding-audit及python -m naiyue_rag.serving.benchmark继续可用，文档明确独立入口 |
| 原文精读/关系导航 | 依赖固定PreparedQuery的库接口，保留原合同，不伪造无查询上下文的CLI包装 |
| Git同步/MCP/回答生成 | 尚未实现，不声明已有CLI |

新增document/remove路由字段闭合校验，只接收document_id与可选/必填expected_revision；未知ID、
revision冲突、移除后再次显式ingest纳回，沿现有核心合同。新增Engine/Service document和remove私有writer接线，
更新互斥共用，不改变已发布文件或全局查询资源。LocalClient放行对应操作，status独立严格读取。
安装smoke复现源目录离线时remove在构造IngestionPipeline阶段错误失败；MarkdownLoader改为首次读取时初始化，
保留loader属性读写与既有调用，不把只读已保存版本的移除绑定到源目录在线。摄取仍在load阶段严格检查源路径。
所有新命令支持--config前后位置；删除必须显式revision，不隐式force，不自动重试。
HTTP审查发现更新等待写锁会占用AnyIO线程池：更新改为非阻塞单writer准入，重复ingest/remove明确409/
retrieval_update_busy，不阻塞线程池等待。查询仍按2执行20等待调度，不因一个更新任务而busy。
LocalClient的query读取等待为retrieval.request_timeout_seconds + service.request_timeout_seconds，
后者作为网络宽限；连接/写入/连接池等待及其他HTTP操作仍使用service值。
不新增配置字段、不改用户配置，避免默认两个180秒的时钟使CLI先断开而收不到504。

## 影响、验收与回退

影响service.py、service_protocol.py、local_client.py、cli.py、serving/service.py/engine.py/scheduler.py，
README、共享服务文档、安装smoke、正式CI和对应测试。跨8文件按本Spec先失败测试。
验收默认HTTP并发/排队、真实TCP断开取消后槽位收尾、超时504与过载429、health/status仍可响应、
部分请求体超时、错误脱敏、旧factory回归、命令映射/范围/详情/移除与再次摄取、真实nyr子进程与最终wheel安装。
旧服务身份不能被新CLI误认为新服务，且不得杀占用者；既有chat退出只停自己创建的实例。
原生全链、全部tests、build、分发审计与pip安装smoke后报告；不升级依赖、不改真实配置、不提交发布。
回退只恢复入口factory与命令接线，保留模型、索引和用户文件；新知识库格式不变。

## 最终实现与本机验收（2026-10-28）

- L1：CLI、HTTP、共享服务与测试文件均存在；新测试加入scripts/run_formal_tests.py。
- L2：共享调度、异步Handle等待/断开取消、严格字段校验、非阻塞更新准入、延迟源加载为真实实现。
- L3：nyr实际子进程→认证HTTP→共享RetrievalService→原生Chroma/BM25/SQLite；最终wheel离源码验收通过。
- 新HTTP/CLI/真实客户端超时、writer准入和离线移除回归均经历预期红灯；相关143 passed in39.09s。
- `.venv/bin/python -m pytest -q tests --tb=short`：`2437 passed in 504.06s (0:08:24)`；日志dist/nyr-shared-final-tests.log。
- `.venv/bin/python -m build --outdir dist/nyr-shared-final`：成功构建wheel/sdist；分发内容审计、Twine严格检查、compileall、两环境pip check及git diff --check通过。
- 在此前全新在线安装全部依赖的隔离环境换装最终wheel，从/tmp以Python -I运行scripts/installed_smoke.py：status=passed、installed_version=0.1.0、native_documents=2、active_revision=3、query_evidence=2、shared_retrieval_queries=10、http_concurrent_queries=10、tcp_disconnect_cancelled=true、cli_management_roundtrip=true、reopened_after_process_crash=true。
- 十条HTTP请求以事件屏障确认2执行/8等待后全部完成；真实TCP断开后对应请求进入收尾，另一查询仍成功。CLI覆盖范围/排除、详情、源离线移除、源恢复重摄取及状态。
- 架构/安全只读复核关闭默认客户端超时竞态和更新阻塞线程池问题，最后无剩余高置信阻断项。

平台macOS26.4 arm64/Python3.12.14；模型为合成本机HTTP服务，model_requests=57、real_vendor_requests=0、weights_downloaded=false。
上述不替代公司Linux真实模型/材料的吞吐和质量验收。当前Ollama未运行；没有本轮真实Ollama并发证据。

最终候选dist/nyr-shared-final，仅本机验证，源码版本仍0.1.0，不能覆盖已发布版本：

- wheel SHA256：10807e8d0748615b581a672becd26fe1f8fbc38d85c232366b32a2e5d6b2d945。
- sdist SHA256：5564829bb2d1d21d9d0167a50618d0f3ef5eb99cf8275055cac5b2bb53409346。

未提交/push/新发布、部署或修改真实配置/知识库。下一步安排新版本或候选交付，再按docs/shared-retrieval.md由用户回传Linux验收。
