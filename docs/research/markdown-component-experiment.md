# Markdown摄取组件：选型实验候选

日期：2026-10-09。状态：实验设计建议，具体组件尚未选定、未安装或运行。A/B路线范围已获确认，见[ADR 0001](../decisions/0001-retrieval-experiment-scope.md)。

## 输入与共同要求

使用[Mock v1](../../examples/mock-v1/README.md)的12份合成Markdown。输入已是Markdown，不需要为此引入PDF转换；读取原始文件并保留版本和位置，之后才生成索引表示。

对普通章节核验标题、正文、公式、代码块、链接及原文定位；对用例核验一行一用例、九个列义、所属维度/覆盖说明、`<br>`及转义竖线、部分前置引用。格式不支持或内容超限时须明确报告，不静默丢弃。

## 候选与事实边界

| 候选 | 已读到的真实机制 | 本例待验证的问题 |
|---|---|---|
| C0：参考项目的递归字符切分 | Modular配置接线到LangChain RecursiveCharacterTextSplitter，按分隔符和字符长度递归 | 普通段落是否合适；长用例是否被拆散；标题/表头是否与正文分离 |
| C1：LangChain标题分组，长普通章节再递归切分 | 官方文档显示MarkdownHeaderTextSplitter按指定标题分组、携带标题metadata，可接递归切分；默认处理会移除部分空白与换行 | 标题范围是否正确，原文位置如何映射；用例表格仍需专用规则 |
| C2：LlamaIndex MarkdownNodeParser | 固定源码get_nodes_from_node扫描标题、反引号代码围栏并构造节点；_build_node_from_split写header_path | 节点长度、标题路径、代码及表格保留；不会仅因使用此解析器就自动变成一行一用例 |

来源：[Modular固定源码](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER/blob/f658c5a4011c8b826707a65a3b11ce9301b0626f/src/libs/splitter/recursive_splitter.py)，main/f658c5a4011c8b826707a65a3b11ce9301b0626f；[LangChain标题切分文档](https://docs.langchain.com/oss/python/integrations/splitters/markdown_header_metadata_splitter)和[递归切分文档](https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter)，2026-10-09读取、网页不绑定包版本；[LlamaIndex固定源码](https://github.com/run-llama/llama_index/blob/6dd2f3cdd9ce7ff927ea8d46ccee08875bb00f95/llama-index-core/llama_index/core/node_parser/file/markdown.py)，main/6dd2f3cdd9ce7ff927ea8d46ccee08875bb00f95。

这是静态源码/文档事实，不是本机解析测试结果。LC标题文档此前读取失败，本轮已成功读取；仅更新这项证据，不假称此前已核验。

## 建议怎样比较

1. 先运行现成组件，导出实际片段内容和metadata，暴露各自原始行为；不先修饰输出或隐藏失败。
2. 根据真实输出判断所需适配。普通章节复用通用组件；用例候选单位为完整行，加列名、维度/来源说明。这些附加上下文各自保留出处，不冒充连续原文。TC-02对TC-01的引用保留并按文档范围解释，不自动继承全部字段。
3. 保留原文位置映射，手写L999-L1005作为错误探针。只设strip_headers=False仍不保证字节/空白与原文一致，不能直接用变换后行号做原文定位。
4. 比较组件及必要适配的实际效果/代码量/依赖，避免因为框架提供节点或Document对象就采用其整套编排。

具体Markdown语法解析器、参数与超限策略在Spec中定稿；不预定全部自写或单用正则处理任意Markdown。拟议的离线组件检查不需要模型调用，不能替代后续检索质量实验。

## A/B共享片段的接线核验

LightRAG固定commit 453dce83d6d0354a06e46c8d4029a0895c4e054b中有两条可继续验证的入口：

- `ainsert_custom_chunks`（lightrag.py:2394起）接受字符串片段；同文档相同内容去重，path在2439取空值并规范化，2781–2784组装存储字段，没有逐片段原始行号参数。其注释标为旧接口，已有文档是增量patch而非替换。不能因接受片段就承诺完整证据或更新契约。
- `chunking_func`及pipeline显式C策略（pipeline.py:5245、5318起）实际调用自定义切分回调，之后仍有校验/Embedding长度限制等处理。可用入队/处理接口指定process_options，暂不需要REST服务；是否保持相同片段及位置映射仍需测试。

补充发现：ainsert注释说固定F，但未传process_options的入队行为产生空选项（pipeline.py:1004–1006），解析后chunking_explicit=false。pipeline.py:5500–5545此分支可调用自定义chunking_func；因此“SDK一律绕过自定义切分”的结论过强。默认实现是固定token，显式F/R/V/P会绕过回调；实验应显式核对所用分支，并把实际传入/最终存储片段对照输出。[LightRAG固定源码](https://github.com/HKUDS/LightRAG/blob/453dce83d6d0354a06e46c8d4029a0895c4e054b/lightrag/lightrag.py#L838)。

若A/B无法共享完全相同的最终片段，报告切分差异，评价整体路线；不能将全部差异归因于图。上述均为静态接线证据，未运行回调或摄取。

## 待明确的下一项条件

确认本独立工程可配置的LLM与Embedding能力，后续再定接口/模型及预算。不要读取Agent凭证或默认其聊天网关支持Embedding；不需要用户在聊天中提供密钥。之后形成可审阅的实验Spec，按离线摄取检查、基础检索、图对照分别推进。
