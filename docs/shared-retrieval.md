# 团队共享检索模块

该模块以长期存活的Python对象提供并发检索，供后续Agent/MCP入口复用。
`nyr`已通过本机认证HTTP入口调用同一模块。可用Python库或CLI；远程MCP尚未部署。

## nyr常驻入口与命令覆盖

第一个终端运行`nyr --config /absolute/path/config.yaml`保持服务常驻；其他终端使用相同配置运行
`nyr chat`、`nyr query`、`nyr documents`、`nyr status`。客户端退出不关闭它连接的已有服务。
未发现服务时，单次命令/chat仍可自动启动临时实例并在自己退出时清理；共享使用应先显式运行nyr。

| 能力 | 命令 |
|---|---|
| 查看已发布文档及revision | nyr documents |
| 查看文档元数据详情 | nyr document ID [--expected-revision N] |
| 显式摄取/更新 | nyr ingest --expected-revision N [--force] |
| 移除活动版本文档 | nyr remove ID --expected-revision N |
| 单次查询与范围过滤 | nyr query TEXT [--scope-document-id ID] [--exclude-document-id ID] [--expected-revision N] |
| 连续终端检索 | nyr chat |
| 执行/排队/取消后收尾状态 | nyr status |
| 显式本地重排模型准备 | nyr models prepare MODEL_ID |
| 本地Embedding输入审计 | nyr-embedding-audit --config PATH [--probe] |
| 容量聚合验收 | python -m naiyue_rag.serving.benchmark --config PATH |

ID取自documents输出；范围/排除参数可重复。文档移除保留原文件和历史版本；再次显式摄取可能纳回原材料。
源目录离线仍能查询、查看元数据、移除已入库文档；重新摄取需要材料目录在线。
同一时间只执行一项摄取/移除，额外更新立即返回retrieval_update_busy；不阻塞线程池或停止在线查询。
详情是既有DocumentManager元数据，不是原文精读。固定查询上下文的原文行读取/关系导航保留Python接口，
没有伪造无上下文CLI；Git同步、MCP、回答生成也不宣称已提供命令。

## 使用

```python
from naiyue_rag import load_application_settings
from naiyue_rag.serving import RetrievalService, RetrievalError

settings = load_application_settings('/absolute/path/config.yaml')
with RetrievalService(settings) as service:
    # 对已摄取知识库发起请求；复用同一个service处理多个用户的调用。
    first = service.submit('查询问题一')
    second = service.submit('查询问题二')
    result = first.result()
    other = second.result()
```

`service.query(...)`是提交并等待的便捷入口；调用参数支持现有scope/exclude_document_ids及expected_revision。
submit会复制并校验输入范围，结果保持原schema2证据结构。服务、查询Handle或异常均不自动发送外部消息。
`ingest(expected_revision=...)`走独立写入流程，`documents()`查看已发布版本；更新期间可以查询旧版本。
一次请求绑定一个版本；发布成功后新开始执行的请求使用新版本，已有请求仍使用它固定的旧版本。

## 配置

```yaml
retrieval:
  max_concurrent_queries: 2
  max_queued_queries: 20
  request_timeout_seconds: 180
  shutdown_timeout_seconds: 10
```

- 同时执行默认2；等待最多20，不包括执行中的请求。空闲服务可接收十条同时提交的正常请求，超容量明确报retrieval_overloaded。
- 请求期限为秒，覆盖排队与执行。`submit/query(timeout_seconds=...)`只覆盖本次请求，默认使用上述配置。
- 旧配置没有retrieval节时使用这些默认值；配置在服务创建时固定，更改需重建服务。
- `service.request_timeout_seconds`控制HTTP连接/写入/池等待及服务端收取请求体的期限；query客户端读取等待为
  `retrieval.request_timeout_seconds + service.request_timeout_seconds`，预留配置的网络宽限以接收服务端超时结果。
  其他HTTP操作和health仍用各自已有等待设置；不修改真实配置文件。
- 每槽位使用独立模型客户端，共享同版本已校验资源。并发数增加不保证CPU模型吞吐增加，需实测。

## 取消、超时和关闭

`handle.cancel()`请求协作取消；`handle.result()`抛RetrievalError，code为retrieval_cancelled或retrieval_timeout。
服务不重试，调用方可重新提交。`handle.result(timeout=...)`遵循Future语义，仅限制本次等待，不更改服务作业期限；
需要改变作业期限应在submit时传timeout_seconds。等待超时也可由调用方显式cancel。

`handle.status()`报告state、backend_finished和排队/执行/总耗时；`wait_backend(timeout)`等待后台实际退出。
调用方超时或取消后，后台可能仍在完成一个底层调用；槽位直到真正退出才归还。
`service.status()`报告executing、queued、draining；executing包含已分配但尚未进入函数的执行槽位。
HTTP连接断开或ASGI取消会调用对应handle.cancel，不会提前释放槽位；服务不发送晚到的成功响应。
HTTP查询超时返回504/retrieval_timeout，队列满429/retrieval_overloaded；nyr输出安全错误码与配置提示。
升级后如仍有旧服务占用端口，执行合同身份不同会明确拒绝连接；先退出原服务再运行新版nyr，不自动杀进程。
请求的对外终态只产生一次，晚到的成功不会覆盖超时，也不会启动隐式重试。

close停止接收新请求/更新，取消等待任务并请求执行任务收尾。关闭期限耗尽返回retrieval_shutdown_timeout；
调用方保留服务对象，待后台退出后可再次close。其他关闭失败返回retrieval_cleanup_failed，保留待清理资源。
底层原生调用永久阻塞时第一版不强杀线程，仍需人工重启；返回timeout本身不意味着工作已终止。

## Linux实际材料验收

先安装包含本模块的候选包，使用已有模型与已摄取的知识库；以下命令不会主动摄取或Git同步。
输入一条已知能命中的实际问题，问题不回显，不写入汇总报告。分别在新进程中测2路和4路：

```sh
python -m naiyue_rag.serving.benchmark --config /absolute/path/config.yaml --requests 10 --concurrency 2
python -m naiyue_rag.serving.benchmark --config /absolute/path/config.yaml --requests 10 --concurrency 4
```

报告包含受理/完成数、错误码计数、排队/执行/总耗时p50/p95、版本和客户端进程峰值RSS。
客户端RSS不包含独立Ollama服务；Windows无resource计数时为null。observed_reserved_slots是采样到的已分配槽位，
不是底层模型推理并行度；两条真实执行重叠由事件同步的原生测试证明。
首次查询包含冷加载，全部请求均在该批次提交，不把样本混为稳定线上p95。
验收通过至少要求admitted=completed=10、errors为空、revision符合预期；耗时目标以真实材料结果再确定。

未来Git同步：固定远端commit后准备候选材料，完成索引/校验才发布，失败继续服务旧版本。
仓库、分支、凭据和周期由后续Git同步Spec定义。MCP/Agent入口持有同一服务实例，不在每次工具调用时新建。
