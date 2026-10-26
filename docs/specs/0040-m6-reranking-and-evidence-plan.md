# Spec0040：M6重排、证据输出与独立使用边界（阶段边界与验收）

日期2026-10-15。状态：参考源码与本机依赖已核对；用户已确认本轮完成两种后端，先用GLM闭环；已按Spec0041–0043实施并完成当前本地工程验收，详细证据见各片及handoff。不得据此登记M6已完成。

## 1. 已有数据流与本阶段目标

M1–M4保存Markdown原文/实际位置/完整用例/显式关系及同版本双索引；M5已经从任意合规新问题走固定快照、一次成对编码、Dense/Sparse/RRF，并提供受控原文补读和已有引用导航。当前融合结果是含内部编码信息的HybridResult，不能直接作为最终工具证据。

M6使`HybridResult → 可配置启用/关闭的重排 → 上下文预算 → 结构化证据/引用`闭合。之后提供实际库装配和可重复命令、小型固定合成样本/关闭重排基线；系统学习在阶段A完成后开始。Agent、MCP、UI和完整评测平台仍为阶段C，问答生成是证据上的独立适配层，不成为本片前置。

## 2. 参考与一条实际调用链

参考 https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER ，本机`/Users/zmw/MODULAR-RAG-MCP-SERVER`，main / `f658c5a4011c8b826707a65a3b11ce9301b0626f`，2026-10-15只读核对：

`QueryKnowledgeHubTool → HybridSearch → CoreReranker.rerank → RerankerFactory → none/LLMReranker/CrossEncoderReranker → CitationGenerator → ResponseBuilder → MCP响应`。

- 当前YAML重排enabled=false/provider=none，示例model为cross-encoder/ms-marco-MiniLM-L-6-v2，top_k5；不能因有实现文件就声称该默认链启用重排。
- LLM分支：完整候选文本与ID拼入prompt→LLMFactory生成client.chat→JSON数组passage_id/score→映回候选。当前JSON校验/未知ID映射较宽、错误可包含响应片段；CoreReranker可回退原序。这里按既定安全错误、范围/来源和无隐式降级约定加强，不照搬宽松接受。
- CrossEncoder分支：导入sentence_transformers.CrossEncoder、加载配置模型→构造(query,passage)对→model.predict→分数排序；timeout字段本身不证明预测能强制中断，不复制虚假硬截止。
- CitationGenerator提取source_path/page与可选metadata，snippet默认200字符；ResponseBuilder直接依赖MCP类型并渲染Markdown/引用/图像。我们当前Markdown核心保留完整用例、实际行/字符定位和版本，核心证据不依赖MCP，协议转换留后续适配层。

本机importlib.find_spec实查：openai可用；sentence_transformers、transformers、torch均缺失。没有安装依赖、下载模型或运行参考实现。

## 3. 外部模型材料与待决策

2026-10-15读取[参考MiniLM官方模型卡](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2)：标记English，MS MARCO任务；参考带L-6的URL会重定向到该正式ID，不应未经中文对照直接当本知识库最佳模型。[BGE官方模型卡](https://huggingface.co/BAAI/bge-reranker-v2-m3)列出中文/英文和多语言候选，是后续本地选型来源；这里没有验证其本机速度、容量或用户材料质量，不引用GPU benchmark冒充CPU性能。

用户已明确选择：本轮同时完成 LLM 与本地 CrossEncoder，先 GLM 闭环。该决策覆盖两类实现与验证，不重复提问后端节奏。GLM 首片见 [Spec0041](0041-m6-reranking-contract-and-glm.md)；本地依赖与模型来源在该片实施前单独写清。

## 4. 两种路线共同遵守的核心合同

后续切片在实际实施前补齐确定Spec，不一次创建所有Provider/占位插件。

- CoreReranker只消费固定HybridResult候选；关闭时保留RRF顺序作为对照，启用时只调整已有ID的排序/分数，不允许注入新文档、改写原文或生成用例。top_k沿参考5并可配置，不能混淆融合池与最终证据数量。
- ID/数量/重复/有限分数/原模型输出完整性显式校验；LLM原始响应不进日志，调用用量由实际API报告取得，缺失为unknown；不编造费用/Token。分数不是答案可信度。
- 候选与问题是数据，系统提示和工具授权独立；不执行材料指令。完整候选尤其用例行不静默截断，超输入预算在模型前失败或由显式配置确定的完整候选选择处理，策略需写入实施Spec。
- 不新增隐式错误回退；若后续允许回退，必须配置并在结果说明是否执行及原因，关闭重排基线不称为“模型重排成功”。原问题编码报告与本次重排请求分账。
- 证据包含文档ID、片段ID、source_path、原文hash、活动索引版本、实际SourceSpan、完整正文/必要上下文、各路排名/分数及重排信息。引用标记能映回具体证据与原文，不依赖手写行号或模型编造引用。
- context_text预算与完整返回JSON预算分别配置；完整用例/证据原子选择，预算遗漏明确记录。空命中/预算无法容纳/执行失败分开，answerability未知保持未知，不能由“返回非空”断言知识足够。
- ResponseBuilder输出核心DTO，MCP/Agent再消费；不把内部向量、原始模型响应或凭证送入最终知识上下文。

## 5. 验证与收束判据

先红灯、最小实现、定向回归；使用实际SDK MockTransport验证配置→客户端→响应解析→候选ID绑定，而不是仅测试假排序函数。每个新依赖/模型能力单独核对实际版本与来源，不能自动升级现有锁版本。

真实模型验证另明确配置模型、公开/合成材料、请求上限和截止时间，Key仅通过本项目授权入口加载且不打印；当前M5真实请求0不能当M6服务证据。核心程序需能在重排关闭配置下独立运行/评测，并保留启用对照及失败归因。

固定样本明确标注单位、分母/算法、标签来源和未人工审阅状态；检索与最终证据预算/引用分别计量，不把一次回答或单测全绿当业务质量通过。真实资料在另一机器，仍提供可迁移命令，未知结果不补写成功。

M6验收后阶段A才能登记独立RAG核心闭环；本Spec初稿时仅M5范围接线，实施结果见各片验收节；不预填生产成熟度或本人掌握。后续实施文件/接口/正常异常分支及回退边界按选定切片再展开。

2026-10-16阶段收束：两后端及完整证据/独立使用当前本地边界通过，当前完整全量2151 passed in404.22s。阶段A退出，进入阶段B准备；真实资料/生产能力/本人掌握另验。
