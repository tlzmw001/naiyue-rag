# LlamaIndex：组件型知识库路线的静态源码深验

- 候选：github-0759；仓库 https://github.com/run-llama/llama_index
- 调研日期：2026-10-09；分支 main；commit `6dd2f3cdd9ce7ff927ea8d46ccee08875bb00f95`（见 `raw/clone-snapshots.json`）。
- core 版本：0.14.25；file-reader 版本：0.7.0；Python >=3.10,<4；MIT（`clones/llama-index/LICENSE`）。本轮仅阅读，不复用代码。
- 终态：partial_borrow；可组合使用或借鉴组件。没有安装、运行第三方代码、真实模型、服务或本机测试；deep_verified 表示静态实现深验，live_verified=false。

## 它解决什么问题

提供把文档转换成节点、索引和检索结果，再可选交给 LLM 合成答案的 Python 组件。不是预装了本项目业务规则的完整测试知识库。README/官方仓库文档给出组合使用方式；下文机制均来自固定 commit 源码。

首要借鉴点是 Document/Node/NodeWithScore 分离、可显式选择 transformations、retriever 与 query_engine 分离、metadata 过滤、缓存与 docstore 去重各司其职。是否采用框架仍需以本项目小样本实验决定。

## 摄取真实调用链与两种 Markdown 入口

所有相对源码路径均以 `clones/llama-index/` 为根，core 下源码前缀 `llama-index-core/llama_index/core/`，reader 前缀 `llama-index-integrations/readers/llama-index-readers-file/llama_index/readers/file/`。

1. `readers/file/base.py:92-112` 的默认扩展名映射没有 `.md`；`SimpleDirectoryReader.load_file:634-644` 对没有专门 reader 的文件读原文，创建 `Document(text=data, metadata=metadata)`。`file_metadata` 可注入项目、模块、文档角色和业务版本；`filename_as_id=True` 可设路径为 ID，默认 False。
2. **显式原文 Document + MarkdownNodeParser**：`node_parser/file/markdown.py:48-107` 按 ATX `#` 标题切分，遇到三反引号围栏切换代码块状态，避免其中的 `#` 被当标题。每个片段保留本节标题和正文；`109-125` 构造 TextNode，metadata 的 `header_path` 是父级标题路径，本节标题仍在正文中。这条路线适合我们保留原文定位的实验。
3. **显式 MarkdownReader**：reader `markdown/base.py:25-37,39-101,117-150` 默认 remove_hyperlinks/remove_images=True，清理空白行、去 HTML 标签并按标题重组文本，最后每节成为 Document，metadata 来自 extra_info。该 Reader 不直接产生原文件行号或原文字符区间；后续 NodeParser 的字符定位也只对重组后的 Document 生效。不要误称它和原文 Document 路径具有同样可追溯性。
4. `node_parser/node_utils.py:25-26,29-73` 默认节点 ID 为 UUID，SOURCE relationship 指向原 Document。`node_parser/interface.py:84-155,157-177` 后处理继承 parent metadata、构建前后关系，并在 parent_doc.text 里 find 片段正文，设置 start_char_idx/end_char_idx。找不到时这些字段仍可为 None；没有自动 line_start/line_end。`schema.py:782-787` 也定义为 Optional。
5. `ingestion/pipeline.py:345-368,428-432` 支持显式 transformations；未提供时默认 SentenceSplitter + Settings.embed_model，**默认并非 MarkdownNodeParser**。`run:539-663` 先准备输入、筛去重复/未变文档，依次转换，再写有 embedding 的节点到 vector_store，最后更新 docstore，返回 nodes。
6. `indices/base.py:88-129` 的 `VectorStoreIndex.from_documents` 是另一条入口：取 transformations，run_transformations 后构造 index；并非自动建立有 docstore 去重语义的 IngestionPipeline。可先由 pipeline 只产 nodes，再交 `VectorStoreIndex(nodes, embed_model=...)`，也可由含 Embedding 的 pipeline 写支持存正文的后端后 `from_vector_store`。两条路线的持久化、更新语义要明确选择，不能假设一条快捷调用自动包含另一条。
7. `indices/vector_store/base.py:126-148,219-245` -> `indices/utils.py:170-203` 对没有 embedding 的节点取 MetadataMode.EMBED 内容，批量调用 embed_model，再 vector_store.add；已带 embedding 的节点复用。若后端不存正文，index/docstore 保存去掉 embedding 的节点，供检索回填。

## 文档更新、缓存和版本

- `ingestion/pipeline.py:58-110` 将整批节点的 MetadataMode.ALL 内容与 transformation.to_dict 组合计算 hash；缓存命中跳过转换。这是 transformation 结果缓存，不是业务版本历史。
- `469-507` 的 upsert 用 ref_doc_id 或 id_ 查旧 hash：不变跳过；改变先删旧 docstore/ref_doc 和向量，再重跑。只有给出稳定 document ID 才能可靠识别“同一文档改变”；重新生成 UUID 会变成新文档。
- `568-601`：docstore 与 vector_store 同时提供才有 upsert/delete 语义；只有 docstore 时警告并退化成 duplicates_only。`650-660` 先写 vector_store 后更新 docstore；`376-426` persist/load 只明确持久化 cache/docstore，后端向量持久化另管。
- 风险（静态设计推断）：旧向量删除发生在转换之前，转换/远程写入失败可能造成不完整更新；此链未提供跨 docstore/vector_store 原子事务或保留所有历史版本。需要针对真实选中存储后端做失败注入及恢复测试，不能用源码阅读宣布实际故障。
- `tests/ingestion/test_pipeline.py:172-236` 检查内容和 metadata 改变；`378-401` 检查 transformation 抛错后新文档未加入 docstore。本轮只读这些测试，未执行，不据此声称我们本机已通过。

## 检索、范围和证据接口

`VectorStoreIndex.as_retriever`（`indices/vector_store/base.py:112-124`）返回 VectorIndexRetriever；`retrievers/retriever.py:42-73` 接收 filters、doc_ids/node_ids、top_k。`104-115` 对 query 调 embed_model；`130-144` 把 filters 等传入 VectorStoreQuery；`227-246` 调后端 query、从 docstore 回填正文，再经 `212-225` 转成 NodeWithScore。

`vector_stores/simple.py:244-315` 在相似度计算前按 metadata 和 node_ids 过滤，遍历存储向量再算 top_k；metadata 未存的旧库无法过滤时抛错。**这证明本机简单后端支持预过滤**，不证明所有第三方数据库具有完全相同的过滤能力。参数 doc_ids 虽传下去，该 simple 路径展示的是 node_ids 与 metadata 过滤，不能只因接口存在就断言此后端支持所有参数。

本项目可把 project/module/version/doc_role 注入 Document.metadata（`schema.py:275-301`，Reader extra_info 及 NodeParser metadata 合并已接线），通过 metadata filters 限范围，再将 NodeWithScore 转换成自己的 Evidence 契约。默认 metadata 还会进入 embedding/LLM 文本；可用 excluded_embed_metadata_keys/excluded_llm_metadata_keys 选择控制哪些参与模型输入。业务版本和权威性并没有由字段名字自动产生。

**本轮所追的 reader → node parser → vector retriever → synthesizer 链中，未发现自动执行“当前需求是正确性依据，旧用例只是历史参考”的业务规则。**我们需自行设计文档角色、有效版本与证据展示规则，并评测“旧用例与新需求冲突”案例。该判断限于已读调用链，不声称全库没有任何可扩展机制。

证据出口建议核验 `retriever.retrieve(...)` 的 NodeWithScore；包含节点 ID、ref_doc_id/source relationship、metadata、正文和可空 score。原文件行号、业务版本、检索路径名称和可审计 trace_id 仍需我们的适配层定义。检索接口本身不生成答案，不自动把有排名的候选断言为足够回答。

## 大模型到底怎样接线

- `settings.py:34-76` 延迟解析 Settings.llm/Settings.embed_model；两个 setter 可显式传独立实例。
- `embeddings/utils.py:42-76` 默认尝试 OpenAIEmbedding 插件并验证 key，缺包/缺 key 明确报错；`llms/utils.py:40-71` 默认尝试 OpenAI LLM 插件并验证 key。仅 core 并不自动提供这些插件。IS_TESTING 会走 Mock 实现，测试结果不能作真实服务证明。
- `VectorStoreIndex.__init__:70-72` 使用显式 embed_model，否则 Settings.embed_model；查询 retriever 默认复用 index 的同一 embedding model。摄取及查询必须一致，其维度、模型配置与索引版本要由项目约定。
- `query_engine/retriever_query_engine.py:37-48,63-131` 接收 llm/response_synthesizer/node_postprocessors；默认 Settings.llm 和 COMPACT synthesizer。`160-168,203-215` 查询先检索及后处理，再 synthesize。`response_synthesizers/factory.py:107-123` 选择 CompactAndRefine，`compact_and_refine.py:49-74` 按 prompt budget 整理片段，`refine.py:88-110` 调 llm.predict 或 structured_predict。
- 因此可以让 Agent 使用纯 retriever 证据，再由 Agent 自己生成；独立知识库问答则另接 query_engine/我们自己的生成层。无需为检索工具强行初始化聊天 LLM。OpenAI 兼容网关的 embedding/LLM 仍须分开确认支持的端点与模型；本轮没有调用你的模型网关。

## 评测与追踪接线

`evaluation/retrieval/evaluator.py:16-50` 调 retriever.aretrieve，提取 node_id/text，与 expected_ids 进行评测。`metrics.py:29-78` 默认 hit_rate 是是否命中任意一条相关 ID；不等于完整证据 Recall@k；空 retrieved_ids/expected_ids 直接 ValueError，故无答案样本的标注/评分要另设计。固定片段级标签需要稳定节点 ID 和冻结切分版本，不能每次重生成随机 ID 后直接比较。

NodeParser、index build、retriever 和 synthesize 源码含 callback events / instrumentation spans（如 interface.py:173-177、indices/base.py:111、retriever.py:103、response_synthesizers/base.py:240-273），能作为追踪扩展点；这不证明已接持久日志、成本汇总、隐私过滤或项目级失败追踪。真实服务 token/费用未知。

## 依赖、运维、学习取舍

core `pyproject.toml:37-40,57-89` 依赖 Pydantic、NumPy、NLTK、tiktoken、HTTP/async 库、workflows 等；reader 包 `pyproject.toml:31-34,72-80` 还包括 pandas、pypdf 等多格式依赖。仅 Markdown 可以先保留原文并用 core node parser，避免因为文件 reader 打包形态而安装全部多格式能力；是否采用仍待实验。

优点是已有文档/节点/检索/问答组件可组合、模型和后端可替换，省适配工程。代价是理解全局 Settings 的延迟默认、transform/cache/docstore/vector_store 多处状态、配置对元数据模型输入的影响及后端差异。本项目自主学习的首切片可自行实现可定位 Markdown 片段和 Evidence 契约，用框架作为后续对照或适配候选。不能从源码深验推导中文需求/用例检索效果、可拒答能力或生产可靠性。

## 一手文档与复核入口

仓库固定 commit 文档已读：

- `docs/src/content/docs/framework/module_guides/loading/ingestion_pipeline/index.md`：显式 transformations、向量库、缓存和持久化示例。
- `docs/src/content/docs/framework/module_guides/loading/documents_and_nodes/usage_documents.md`：metadata、稳定 doc ID、排除 embedding/LLM metadata 的使用方式。
- `docs/src/content/docs/framework/module_guides/indexing/vector_store_index.mdx`：from_documents、nodes、in-memory 默认与向量后端。
- `docs/src/content/docs/framework/getting_started/starter_example.mdx`：模型配置和 OpenAI compatible LLM/Embedding 各自适配器。

公开定位前缀：`https://github.com/run-llama/llama_index/blob/6dd2f3cdd9ce7ff927ea8d46ccee08875bb00f95/`；后接上述完整 repo 路径和 `#L行号` 即固定版本证据。浅 clone 未展开完整 commit/Issue 历史，没有认定实际失败经验。

本轮只做静态验证：L1 源码/测试文件存在，L2 所读入口有实质实现，L3 上述配置和核心调用存在源码接线。它们均属参考项目静态证据；本机运行验证、真实服务结果和业务质量未验证。构建/运行测试不适用（本轮授权为只读研究，不安装或执行第三方代码）。
