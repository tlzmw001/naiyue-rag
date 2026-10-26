# Spec0041：M6.1 固定候选重排与 GLM 接线

日期：2026-10-15。用户已确认两种后端本轮完成，先 GLM 闭环；本片实现中，未经运行不得登记通过。承接 Spec0040；本地 CrossEncoder 在共用合同稳定后另片接入，无需再次确认已定范围。

## 当前链与修改原因

M5：QueryPipeline.prepare → Dense/Sparse → RRFFusion → HybridResult。后者保存同版完整 Chunk、各路排名、编码报告及追踪，目前没有真实重排消费者。新增 CoreReranker 消费该结果，仅重新排序已有候选并取 top_k；随后 M6.2 ResponseBuilder 消费它，不依赖 Agent/MCP。

参考：Jerry-ai-dev/MODULAR-RAG-MCP-SERVER，main/f658c5a4011c8b826707a65a3b11ce9301b0626f，2026-10-15。实际 CoreReranker→LLMReranker→LLM.chat→JSON passage_id/score→映回候选，及 CrossEncoder→predict 的调用链已读。沿用编排/后端分离、top_k=5 示例、完整候选、可关闭基线。差异：不隐式回退；拒绝缺失/重复/未知 ID、不有限数与伪造正文；原始模型响应不进错误。配置参数没有最佳性声明。

## 接口及数据

- RerankSettings(enabled, top_k, max_candidates, max_input_characters)，严格 YAML，所有上限必填；关闭也遵守 top_k，保持 RRF 原序。
- LLMRerankSettings(model, base_url, timeout_seconds, deadline_seconds, max_response_bytes, max_output_tokens, temperature, extra_body)，严格 YAML。extra_body 只允许 thinking.type（enabled/disabled），不能覆盖 model/messages/stream 等主参数。OpenAI SDK 2.54.0 已安装，不新增依赖；GLM 示例 glm-5.2/标准 endpoint/thinking disabled，模型不硬编码在生产函数。
- CoreReranker(settings, backend=None).rerank(hybrid) → RerankResult。backend.score(query,candidates) → (scores, report)，scores 为所有输入 passage_id/score 一一对应的完整集合。公共接口新增，不改旧签名。
- 候选文本复用已验证 Chunk 的 contexts 与 retrieval_view.text；保持整行用例和必要标题。query 使用 prepared.encoding.input.retrieval_text，不用加前缀的 embedding_text。输入数量/整个问题与候选字符总量超限在调用前失败，不截断、不悄悄缩小池。
- RerankResult 保存 defensive copy 的 HybridResult、设置、provider/model、全部候选分数、排序后 top_k 的 rank/chunk_id/score 及闭合报告。相同分数按原 RRF 次序稳定排序；跨后端不比较绝对分值，分数不代表可信度。
- 关闭/空结果不调用后端，分别记录 disabled/empty；启用一个候选仍调用后端，行为一致。LLM 一个批次、一次请求、零重试。
- 结果不改变存储；只持有原固定快照，期间 active 变化不重新选择版本。最终原文与引用由后续 ResponseBuilder 绑定。

## 执行/失败与用量

LLM 使用 SDK chat.completions.with_streaming_response.create(stream=False) 的有界原始 HTTP 读取，所有 HTTP 状态的响应字节均限额，禁止重定向、环境 proxy/凭证/头混入；关键 close 失败可见且保留主错误。复用凭证解析 resolve_api_key，不修改真实 .env。按职责分开 rerank 报告；已有 embedding 报告保存在原 HybridResult 或错误的安全 observation 中。

HTTP/IO/解析/结束原因非 stop/未知 ID/数量不全/重复/有限数验证失败：RerankError，整次无结果；错误仅闭合 code 和报告，不包含 query/candidate/prompt/响应/Key。usage 缺失为 None；有 usage 时严格非负整数及 total=prompt+completion，服务返回 token 明确分账，不估价。即使 content 错误也尽可能先保留有效已知 usage。不得将程序解析成功视为检索业务质量通过。

计时以 monotonic 实测，HTTP 超时取 timeout 与剩余 deadline 的较小值；流读前后检查 deadline。这是同步 IO 的有界超时检查，不声称能强杀任意阻塞代码；端到端真实服务验收由独立子进程监督总时限。

输入与错误码/报告解析有真实消费者才提取；HTTP 边界此次是第二份相同机制但错误域不同，暂保留本片局部实现，避免为一次接入改变已验收的 embedding 公共合同。

## 影响与验证

新增 core/rerank_settings.py、core/rerank_results.py、reranking/{core,llm,transport,report,bootstrap}.py、小型包入口及两个示例 YAML；root 新增公开导出。新测试 test_reranking.py、test_llm_reranker.py；后续原生完整闭环测试与 M6.2 共同验证。旧查询/存储/实验接口、真实配置、依赖与文件均不删除或改写。

TDD：配置/关闭/空/固定 ID 完整排序和别名隔离；真实 SDK MockTransport 的 URL/模型/extra_body/限额/HTTP/坏 JSON/结束原因/usage/关闭/安全日志；HybridSearch→CoreReranker 接线和原编码次数不变。测试为合成材料，默认禁止外网。

本片真实模型请求为 0。M6 核心闭环就绪后监督验证：只用本项目合成 Markdown，embedding-3 建库与查询及 glm-5.2 重排合计最多 12 次 HTTP、每次模型 deadline≤60秒、总进程 deadline 300秒；遇明确失败保留报告、不自动重复请求或扩大预算。真实 .env 仅授权解析器在内存加载指定 Key，不打印/保存其内容。该计划沿用既有模型/材料授权；本地依赖/权重与 CPU 验证另片记录。

回退边界：新入口不被旧查询调用，禁用重排直接保留原序；不回滚存储、不改旧测试。切片完成后才追加实测命令/输出和限制。

## 实施证据（2026-10-15）

- Core 合同预期红灯25项（新模块/导出缺失），最小实现后25 passed in14.67s。
- LLM 首轮25项预期红灯、5项配置用例已绿；真实 openai2.54.0 + MockTransport 接线与 Core 联合55 passed in16.00s。涵盖实际 URL/模型/完整输入/stream=false/thinking/timeout、HTTP302/401/429/500零重试、坏JSON/结束原因/ID与usage、安全字节/关闭/超时分支，不是虚构HTTP成功。
- `python -m pytest -q tests/test_reranking.py tests/test_llm_reranker.py tests/test_evidence_response.py tests/test_core_app.py tests/test_hybrid_search.py tests/test_knowledge_reader.py --tb=short`：119 passed in52.66s；后续示例路径回归使 app 测试为6项，均通过。
- 实际 L3 消费为 RetrievalPipeline/独立 app：一份 HybridResult→CoreReranker→LLMReranker SDK→严格分数映射→ResponseBuilder；新查询只编码一次，固定原快照，不额外召回。
- 服务验收在0042闭环执行，见下片真实报告：glm-5.2 首闭环1请求/1795tokens，四题同池对照4请求/7027tokens；Embedding另账。本片初期“真实请求0”为设计边界，后续验收有以上实际请求，不继续宣称0。
- 原始红灯/绿灯见 data/research/spec0041-evidence/；模型包未升级，未改真实 .env/旧测试/索引格式，无参考程序执行或代码复制。CrossEncoder仍为下一片，其未验证不由GLM成功替代。
