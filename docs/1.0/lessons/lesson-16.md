# Lesson 16：阶段B·2.4 结构规则与语义分块

日期：2026-10-21，第2章共6节。目标：准确命名当前方案，理解基于Embedding的语义分块如何决定边界，并区分源码事实、说明用数值与实际模型结果。

## 当前方案的准确描述

当前采用结构感知＋业务规则＋递归字符切分：MarkdownLoader保留原文；markdown_structure识别标题、代码、表格/用例及定位；DocumentChunker保护原子单元、对text使用RecursiveCharacterTextSplitter；ChunkRefiner按规则准备检索视图，MetadataEnricher提取已有元信息；BatchProcessor在这些片段已经确定后生成检索表示。

它利用作者编排的标题及业务结构间接保留含义，但没有在切分前调用Embedding/LLM来判断主题边界。“语义分块”有宽泛说法，本节用窄义“由模型表示或模型判断决定语义边界”，不把所有照顾语义的规则混称成已实现此算法。

## 一个四句小例子

S1：订单基础金额等于单价乘数量。
S2：移除折扣后，基础金额公式保持不变。
S3：日志文件保留七天。
S4：超过保留期限的日志自动清理。

若同一标题下连续书写四句，当前递归切分由已配置分隔符和长度决定；加入中文句号只增加可用语法边界，不自动判断S2和S3之间是主题变化。若作者已拆成“计费规则/日志规则”两个章节，结构规则便能利用这一信号，但不证明所有标题都可靠。

## 一类Embedding语义分块算法

先分句→可选把相邻句组成窗口→为每个句/窗口编码→比较相邻表示差异→在差异明显处设断点→拼回片段。Embedding可先理解为文字的一组可比较数字，内部原理到第3章，余弦计算到第5章。

本机源码对照：llama-index-core 0.14.25的node_parser/text/semantic_splitter.py::SemanticSplitterNodeParser。build_semantic_nodes_from_documents依次调用sentence_splitter、_build_sentence_groups、embed_model.get_text_embedding_batch、_calculate_distances_between_sentence_groups、_build_node_chunks。默认buffer_size=1在当前循环实现中包含前一句＋当前句＋后一句，不是只取当前句。源码说明与实际行为以循环为准。

距离由1-similarity计算，再取当前文档相邻距离的百分位作为断点阈值；默认95，严格大于阈值的地方切开。95不是相似度0.95或业务正确率95%。此实现的分句和分组本身也需要适配语言，不默认能正确处理任意中文表格。

## 数字机制演示（手工数值，不是模型输出）

人为给四句之间的三个距离设为[0.10,0.80,0.15]，表达S2/S3之间差异较大。纯本机np.percentile计算95分位为0.735，只有第二个距离超过阈值，因此在S2之后分为[S1,S2]和[S3,S4]。

本次执行输出：manually_assigned_distances=[0.1,0.8,0.15]；percentile95=0.735；break_after_sentence_numbers=[2]。这只验证相对阈值和断点机制，不证明实际Embedding会给出这些距离、会找到此主题边界或改善检索。

百分位是相对当前距离分布的规则；大差异可能来自术语、异常描述、否定/反例，不保证恰好是应分开的业务主题。语义分块也可能切断条件与结果、公式与解释或跨句依赖，且不自动满足检索长度上限。

## 两类分块的比较与组合边界

| 维度 | 当前结构/规则/递归 | Embedding语义分块 |
|---|---|---|
| 边界信号 | 标题、代码围栏、表格、列名、分隔符和长度 | 相邻表示变化及阈值 |
| 切分时模型请求 | 当前没有 | 需要Embedding；也有其他LLM判断方案 |
| 适配前提 | 文档结构与业务规则可用 | 分句、模型、窗口与阈值需适配 |
| 可解释性 | 可追到具体规则/位置 | 可追到句组、分数和阈值，但分数不是业务证明 |
| 典型风险 | 无标题、多主题长段、结构声明不可靠 | 模型差异、阈值漂移、依赖切断、长块 |

两类机制可组合，例如先保护表格/代码，再对普通长段试验语义边界，最后约束长度并绑定原文；这只是机制说明，没有批准或实施新路线。当前没有语义分块主链消费者，不因本机装有LlamaIndex就声称已经接线。

分块后Embedding服务检索；分块时Embedding服务边界判断，是两个用途和数据单位。句组向量不一定等于最终检索Chunk向量，不能默认复用或声称只需原来的同一批调用。模型费用/耗时本节没有测量。

## 中文标点优化记录

按用户要求写入docs/future-work.md：中文“。”“，”独立字面量分隔符，保留标点和位置、验证长度/重叠、固定对照与处理身份失效。状态尚未实现，只记录；不新增中文分词或语义模型方案，不把此优化当主题识别算法。

## 实际代码阅读与已有调试入口

- ingestion/markdown_structure.py::scan_document：结构信号和原文区域，见Lesson14已有Debug Test。
- ingestion/document_chunker.py::split_document：text递归，其他保护单元，见Lesson15实际框架走读。
- ingestion/chunk_preparation.py::ChunkRefiner.transform：规则生成retrieval_view，原始chunk.text保持；名字Refiner不代表已调用LLM。
- 本机llama_index/core/node_parser/text/semantic_splitter.py仅只读研究，无实例化默认Embedding或运行模型。项目没有语义分块Debug Test；不能借其他算法的绿灯宣称它已验证。

## 证据与学习状态

本节为概念＋当前代码/已安装框架源码对照，运行了上述人工距离的纯数值演示；未运行真实Embedding/LLM、未改源码/依赖/.env/运行配置、未重跑功能测试。文档检查用git diff --check，不当功能验证。

2.4已讲解；用户理解、本人调试/复写/独立实现待评估。下一节2.5：用例表格的识别、列名/字段、整行与上下文保护，沿当前真实代码和测试学习。
