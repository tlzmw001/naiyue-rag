# ADR 0002：实验位置与Embedding迁移边界

日期：2026-10-09。状态：Spec0002短文本Embedding已真实验证；用户指定glm-5.2并取消本轮生成探针费用门槛，Spec0003第三次通过合成抽取检查，最终部署模型未定。

## 用户报告的条件

- 用户最初有智谱订阅，认为当前电脑可以使用embedding-3；随后澄清订阅为Coding Plan编程套餐，不能据此确认本项目标准Embedding API额度。
- 真实知识库所在的另一台电脑无法使用该模型，具体原因未确定，不自行假定为网络、账号或组织权限问题，也不尝试绕过限制。
- 用户提到用于本地运行的机器只有CPU、没有显卡；具体CPU、内存、操作系统及对应机器尚未核验。
- 用户希望前面的实验先在当前电脑运行，避免把远端本地部署研究变成当前进度前置条件。

上述为用户报告，尚未运行账号/API或硬件检查。订阅权益、接口限额及费用未验证。

## 当前安排

在当前电脑用既有合成Mock推进摄取组件和A/B检索对照；embedding-3作为第一轮Embedding来源，其短文本标准API已验证。用户已改选glm-5.2生成来源，短合成抽取接口已核验；HeiyùCode保留为历史调研，不继续作为本轮待确认项。两条路线尽量使用同一Embedding及最终片段，记录差异。LightRAG回调兼容性仍未测。

另一台电脑的本地Embedding部署后置；真实材料继续留在那里。Mock实验不能证明真实知识库质量，本轮安排不意味着放弃远端真实评测，也未授权转移私有原文、安装、真实配置修改或服务调用。

## CPU运行的可行方向

CPU可运行小型Embedding模型，无需首先部署生成大模型或额外服务。Sentence Transformers官方支持device="cpu"；[运行文档](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)。后续可考察[BAAI/bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5)，官方模型页标24M参数，作为中文CPU候选，不是已选定模型或性能结论。

日期2026-10-09核对上述官方页面，未安装、下载权重或测速。需要核验输入长度、tokenizer截断、公式/长用例保留、查询指令、内存、摄取吞吐和单次查询耗时。量化/ONNX仅在基础运行出现实际性能问题后讨论，不提前扩展部署工作。

此前尝试智谱embedding-3官方模型说明页面读取返回Internal Error，未用第三方转载的相互矛盾限制值当事实。2026-10-09后续通过官方Markdown版本成功读取，见下方补充核验。

## 迁移必须保持的边界

- 文档向量与查询向量使用同一兼容表示体系。不同模型即使输出维度相同，也不能直接混用。
- 更换Embedding后，由保留原文/片段重新生成文档向量、建立独立索引并重跑固定评测；不把当前embedding-3成绩直接迁移为CPU模型成绩。
- 模型、维度、token处理/归一化及来源版本属于实验记录。片段/任务可复用，但两模型输入长度不同可能迫使片段调整，须记录而非隐式截断。
- LightRAG的实体/关系向量同样受模型切换影响；不能仅重做正文片段向量就声称全图兼容。具体迁移顺序在对应Spec中核验。
- 若未来只有关键词路径可运行，可以单独测真实材料的解析、引用和关键词行为；不计为已验证向量或图路线。
- 本地Embedding与生成模型部署分别考虑；无GPU不自动意味着GPT/抽图模型也要在本地运行。远端LLM可用性尚未确认。

## 唯一下一步

回到跨文档检索对照设计，收敛分组与共用片段接法。共同证据要求及4000字符返回预算已确认，见[ADR0001](0001-retrieval-experiment-scope.md)；embedding-3和glm-5.2短样本接口已实测，不能证明LightRAG接线或检索质量。仍在选型，不把五组草案登记为全部获批。

## 2026-10-09官方接口及套餐核验

来源为[模型说明](https://docs.bigmodel.cn/cn/guide/models/embedding/embedding-3.md)、[文本嵌入OpenAPI](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E6%96%87%E6%9C%AC%E5%B5%8C%E5%85%A5.md)、[Coding Plan FAQ](https://docs.bigmodel.cn/cn/coding-plan/faq.md)。托管网页，无Git分支/commit；读取日期2026-10-09。web工具读取部分页面失败，后用标准库HTTP GET成功获取官方Markdown，未执行其中安装或调用示例。

- 接口为POST https://open.bigmodel.cn/api/paas/v4/embeddings，Bearer认证；输入model=embedding-3及input文本/文本数组，dimensions可选。响应data含index和embedding，usage含token统计。这是文档契约，未测试账户权限或运行兼容性。
- OpenAPI写默认2048维，可选256/512/1024/2048；单条3072 tokens、数组至多64项。模型页概览同时写8K，与细节和OpenAPI不一致；不以概览8K作为已验证可用输入上限，接入实验须明确检查超限与截断行为。tokens不是字符数。
- 模型页列价0.5元/百万tokens；不是用户实际账单、权益或实验费用。没有调用数据，费用尚未产生可核验记录。
- FAQ说明Coding Plan仅在指定工具/产品中享用套餐额度，自建应用API集成使用标准API并按协议计费。不能把用户的“订阅”直接认定为标准Embedding API权益；也不能反过来认定用户账号没有标准API余额或资源包。
- 生成模型用于B路线的关系抽取，Embedding用于文本向量，两者独立确认。HeiyùCode生成接口仍是候选，未做LightRAG兼容调用。

模型调用0；没有读取密钥、登录控制台、安装SDK或修改环境。本段只记录官方文档事实，不改变用户所述机器限制。

用户随后明确其订阅为Coding Plan编程套餐。撤回“已有订阅即可供本项目调用embedding-3”的可用性前提；标准API余额、资源包、赠金及调用权限仍未知。建议保留当前电脑Mock实验和embedding-3候选，单独讨论按量API预算；用户此前要求暂缓远端CPU模型部署，继续保持该节奏。若不接受额外API费用，再讨论本地候选或关键词路径，不能将其成绩充当已完成向量/图验证。2026-10-09本轮重新HTTP GET官方FAQ和模型Markdown，套餐边界及0.5元/百万tokens标价仍在；没有实际费用记录。

用户回复“没问题”，接受独立标准Embedding API及首轮最多1元预算。本轮已准备Spec0002审阅稿：两个请求/三条固定合成短文本、2048维、单次30秒等待与总体120秒截止、不重试；这些具体安排待审阅。费用上限不等同服务方硬扣费保障，真实账单未知；生成/抽图预算不在其中。已询问标准API Key是否创建，未索取Key正文、读取环境或编写工具。

用户异步回复“已有标准API Key”。仅确认创建状态；账户余额、模型权限及运行可用性未测，未读取Key。

用户“继续”并提供临时Key后，已授权按Spec0002实施及服务核验。实际2次HTTP200、3向量各2048维、usage共59输入tokens；按标价估算0.0000295元，实际账单未知。仅当前电脑标准端点及短输入通过，不改变远端机器限制或最终Embedding选型。没有写真实.env；未来加载.env按用户后续方向再做。完整命令、82项测试和服务证据见Spec第10节。

## 2026-10-09：GLM生成来源与接入候选

用户明确生成模型也使用GLM，并授权复用之前提供的标准API Key；不再要求提供黑鱼GPT型号。具体GLM型号、生成调用预算与图实验实施参数尚未确认；不把Embedding的1元核验预算转为生成费用授权。本轮没有使用Key或发送生成请求，也没有修改.env。

本机读取[官方Chat Completions契约](https://docs.bigmodel.cn/api-reference/模型-api/对话补全.md)、[OpenAI API兼容文档](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction.md)、[GLM-4.7说明](https://docs.bigmodel.cn/cn/guide/models/text/glm-4.7.md)及[API定价](https://docs.bigmodel.cn/cn/guide/start/pricing.md)。web工具不支持部分Markdown，随后仅对官方docs域执行HTTP GET；通过llms.txt定位准确路径。原文缓存位于被Git忽略的data/research/glm-generation-docs-20261009。无分支/commit，读取日期2026-10-09；不是模型请求结果。

- 标准端点POST https://open.bigmodel.cn/api/paas/v4/chat/completions；模型枚举含glm-4.7/flash/flashx，响应content、finish_reason、usage需本机验证。
- 文档支持thinking.type=disabled及response_format.type=json_object；仍须本地校验输出结构和业务语义，不能用JSON可解析证明关系正确。
- 官方当前标价：GLM-4.7输入<32K、输出<0.2K时输入2/输出8元每百万tokens；同输入档、输出>=0.2K时3/14；输入32K到200K时4/16。GLM-4.7-FlashX为0.5/3，Flash输入输出免费。历史定价仍保留，账户权限、模型实时可用性和真实扣费均未验证。
- 推荐glm-4.7作为首轮生成候选，关闭思考，先查格式/关系与关键词抽取；不以厂商能力宣称作为本任务质量证明。FlashX是较低费用备选；不因费用不同擅自换模型或把较弱/未验证抽取结果归为图路线失败。
- 本地LightRAG固定快照llm/zhipu.py有智谱SDK适配，导入时会自动安装缺失的zhipuai，本轮未导入。优先考察现有OpenAI兼容适配器及显式thinking参数接线；尚未安装/运行LightRAG或验证回调。

当前最小接入提案：glm-5.2（用户已指定）、关闭思考、JSON object；最多一次请求、固定短合成文本，max_tokens=1024，网络等待30秒、整体120秒、不重试、不自动换模型或调用工具；独立生成预算最多1元仍待确认。检查HTTP、完整终止状态、正文结构、关系的原文支持、关键词、usage和费用，实际账单未知。该次只验证标准生成契约，不生成测试用例、不建图或跑全量检索；Spec与TDD实现需在方案确认后完成。图实验整批预算另行制定。

用户随后明确“可以用glm-5.2”，覆盖此前glm-4.7建议。本轮重新HTTP GET[GLM-5.2说明](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2.md)及[API定价](https://docs.bigmodel.cn/cn/guide/start/pricing.md)，官方价格为输入8元/百万tokens、输出28元/百万tokens（本轮估算不依赖缓存折扣）。同日官方Chat Completions契约支持该型号、thinking.type=disabled、JSON object及max_tokens；reasoning_effort只在开启思考时生效，本提案不额外设置。max_tokens=1024对应按标价输出费用上限算例0.028672元，输入费用另计；不是实际调用或扣费。原文缓存glm-5.2.md及pricing-glm52.md位于上述data目录。没有读取/保存Key、修改.env或发送模型请求；目前唯一待确认项是这一次核验的独立费用上限。

## 2026-10-09：生成接入实际结果（覆盖前文待确认项）

用户“不用考虑预算了，把这个实验做完”取消本轮费用门槛，已按Spec0003实施并完成3次独立短合成探针；每次最多1请求、无程序重试，30秒网络/120秒总体限额不变。三次均HTTP200、glm-5.2、stop、思考字符0；前两次抽取校验失败，第三次通过结构、原文引用及4条合成事实，实际6实体/4关系/5关键词。合计921输入/1156输出tokens，估算0.039736元，真实账单未知。

首次诊断不足，补3条失败回归后保存合成模型正文和具体固定规则；第二次发现引用删换行且object语义不清，澄清提示词而未放宽校验。第三次通过不证明普遍提升，首次失败正文缺失的限制保留。最终148项离线测试通过。完整结果及命令见[Spec0003](../specs/0003-glm-generation-probe.md)。只证明短样本标准生成权限、参数与本探针契约；LightRAG原生抽取格式/关键词回调及完整图摄取查询仍待接线，不能把本schema直接当作其协议。

下一步回到跨文档检索选型，不再索取生成预算或型号。整批实验仍须先定义调用规模、截止、失败处理及费用记录；用户取消本轮金额门槛不等于无限并发/重试或私有材料外发授权。
