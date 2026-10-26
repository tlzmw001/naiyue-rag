# 托管服务的一手文档深验

2026-10-09，仅文档/API契约核对。没有供应商账号开通、文件上传、付费调用或服务结果；live_verified=false。完整HTML捕获在raw/web/preselection，宿主页面片段在official-usage.web-response.txt和hosted-service-evidence.web-response.txt。

## Gemini File Search

官方文档 https://ai.google.dev/gemini-api/docs/file-search 给出创建store、upload/import、轮询operation、在Gemini调用中使用file_search和读取annotations的路径。服务负责切分/向量化/索引，支持chunking_config和metadata_filter；引用是模型输出中的file_citation，文档说可能包含引用，并未保证每个答案都有完整原文定位。调用示例可以获得，SDK开源不代表该检索后端开源。当前所读入口依赖供应商模型工具；未证明独立端点可直接返回我们要求的稳定chunk ID、版本、Markdown行范围和全部召回证据。

适合快速体验托管知识问答或用作对照；开发与运维负担较少，检索内部和原文映射控制有限。文档有索引embedding和模型输入输出计费说明，本轮没有实测token或费用，也没有判断用户资料能否外发。文档列出与其他内置grounding工具组合的限制，这是正式限制，不是本机发生故障。

## Azure AI Search knowledge base retrieve

官方文档 https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-retrieve 给出SDK/API/MCP访问；retrieve响应由提取内容或合成答案、activity和references构成，文档明确不同API版本能力不同。知识源范围、metadata filter、include_references、最终文档数/输出预算等有显式入口。所读示例包含稳定和preview版本；不能把preview特性概括为所有版本已具备。

这一契约可借鉴给Agent提供证据的工具设计。采用服务需要Azure检索资源、知识源/索引、鉴权和相应模型配置，部署维护与费用前提高于本地小库；文档响应不证明本业务质量。文档说明权限变更在preview检索结果中可能存在传播时间，必须验证范围更新而不能将metadata过滤当作完整业务权限证明。

二者都可以作为托管路线参考。是否满足本项目公开契约、数据边界、成本与中文材料质量，必须另有授权材料和受控实验；本轮只给partial_borrow，不给生产或质量成熟性结论。
