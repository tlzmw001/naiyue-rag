# 知识库Agent底座建议（待具体选型确认）

日期：2026-10-10。用户询问Agent底座怎样建设。本轮首切片仍为Spec0010的单次A2查询；底座方案是建议，不据此安装依赖或启动Agent。

## 当前事实与来源

- RAG环境实际元数据：langchain未安装、langgraph未安装、langchain-core1.6.9。仅有core不等于可调用create_agent。
- 只读测试Agent的AGENTS/requirements及`agent_runtime._create_runtime_agent`调用：其既定路线为Python＋create_agent＋middleware；传model/tools/system_prompt/response_format/context_schema/state_schema/checkpointer，装配工具/模型/控制观察。没有读取或借用该仓库虚拟环境、.env或凭证，没有修改该项目。
- 静态读取PyPI官方LangChain1.4.2 wheel并核SHA256，缓存factory.py/types.py/METADATA/来源到Git忽略的data/research/agent-foundation-20261010。该发布包要求core>=1.6.3,<2及langgraph>=1.2.11,<1.3；元数据范围匹配不证明完整依赖解析或运行通过。未安装/导入该wheel。
- 沿factory源码：create_agent→装配ToolNode与middleware handlers→StateGraph(state/context schemas)→model/tools及before_model/after_model等节点→条件边→compile。框架管理工具循环与状态更新，不自动证明我们的证据支持、授权、预算或停止策略正确。
- 一手文档：[Agents](https://docs.langchain.com/oss/python/langchain/agents)、[Middleware](https://docs.langchain.com/oss/python/langchain/middleware/overview)、[LangGraph workflows/agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)。网页是当前模式依据，不混成已安装版本测试或真实GLM工具调用证据。

## 推荐与候选

| 方案 | 取舍 |
|---|---|
| Python＋LangChain create_agent＋专用middleware（当前首选） | 复用标准模型/工具循环和已熟悉知识；知识库Agent独立状态，RAG保持框架无关。需要验证自检回跳、工具批次预算与真实模型协议，不搬主Agent整个runtime |
| 原生LangGraph StateGraph | plan/search/read/assess/finalize节点与边可更明确控制；需要自己装配模型/工具/消息/错误状态，代码与教学范围更大。若create_agent的hooks难以可靠表达查证状态/强制验证，再考虑 |
| 自写while工具循环 | 控制直接，但需承担ToolMessage配对、异常/取消/并发、结构化输出和状态恢复；当前没有需要重造通用harness的证据 |

create_agent本身构建LangGraph图，前两项是使用层级选择，不是互斥技术。推荐基于本知识库需求及学习/维护成本，不因测试Agent选择就强制沿用全部组件。

## 最小底座职责

1. 单独任务实例/消息历史，只传知识目标、必要材料及受控证据引用，不fork整个主会话。
2. 工具围绕搜索、文档预览/关系、原文补读；当前retrieve_once是第一可用下层能力，其他工具按切片建。无测试执行、文件改写、任意Shell权限。
3. 状态保存待确认问题、发现及Evidence ID、缺口/冲突、实际调用/读取量和终态；中间大量正文存受控外部记录，结果有预算。
4. middleware/应用验证负责预算/截止/重复动作、引用身份/版本/位置，以及最终结果门禁；Self-RAG语义相关/支持/效用判断是可评测的模型输出，不拿prompt自评当程序保证。
5. `model→tools→model`过程中有工具请求才执行受控工具；准备结束时检查交接是否合约，缺依据可继续查证或返回部分/需输入。检索循环下层不负责主任务/现场根因。
6. 最小事件与错误终态可关联检索调用，不默认引入LangSmith托管/另一个Web或长期聊天系统。需要持久任务/恢复后再定checkpoint。

同轮工具可能形成批次，预算不能仅before_model检查一次；执行边界必须可靠计数/预留。当前A2Snapshot为串行兼容层，不能未经验证并发共享。同步/异步hooks、取消与调用链分别验收，不能从async函数签名推出所有IO非阻塞。

## 最小验证与反对条件

在独立本项目环境另Spec固定SDK/客户端版本，先假模型做搜索→补读→证据自检→结束/部分/失败的完整状态流，再用公开/合成材料核对GLM的bind_tools、实际ToolMessage循环与结构化输出。原JSON生成探针不证明这些能力。工具与结果校验不能被供应商默认error回填掩盖。

测试跨任务不串历史、预算/多工具批次/重复动作/取消、证据错ID/版本或不支持、失败/部分终态、A2调用真正接线。先比较最小create_agent接法能否可靠实现边界，必要时与StateGraph最小对照；不先复制测试Agent的多模型回退、审批、压缩、会话/UI整套运行层。

若hooks导致证据门禁或状态转换难以理解/验证，或知识流程需要强制每个节点独立输出、暂停恢复，则改用原生StateGraph。若真实模型工具协议受阻，先定位供应商/客户端能力，不以安装框架证明可用。没有实测延迟/质量或具体依赖安装批准。
