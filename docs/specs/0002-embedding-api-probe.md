# Spec 0002：标准Embedding API接入核验

日期：2026-10-09。状态：用户“继续”并提供临时Key已授权按本Spec实施及受限服务核验，已完成并验证；1元Embedding预算已确认。临时Key只通过本次进程认证提供，不写真实.env。不把这份规范视为最终模型或框架选择。

## 1. 当前状态与问题

现有数据流为Mock Markdown → C0/C1/C2离线组件 → 片段及结构报告。没有向量、索引或查询执行；现有34项测试只验证离线工具。

用户已确认Q01需要五类历史参考，第一轮固定返回预算内优先减少关键证据遗漏。拟比较单路向量、关键词融合、已有关系及LightRAG图路线。向量实验需要先确认标准Embedding接口的账户权限与请求/响应契约。

用户购买的是Coding Plan；官方FAQ不支持将它直接当作本项目标准API额度。标准余额/赠金/资源包及Key权限未知。不得读其他仓库配置或通过Coding端点替代标准Embedding接口。

## 2. 本次边界与取舍

本次只做两个标准Embedding请求、响应校验和本地相似度演示。合成短文本与历史Mock没有敏感原文；不摄取整个知识库、不选择向量数据库、不抽图、不生成回答、不运行MCP。

优先使用Python标准库HTTP发送JSON，避免为一次协议核验安装供应商SDK。官方SDK是后续适配候选；本次通过不证明SDK、LangChain/LlamaIndex或LightRAG回调接线通过。沿现有experiments包增加一个工具，不建立生产Embedding抽象接口，不升级依赖。

## 3. 固定输入与数据流

工具内只定义以下明确合成样本，不接受任意原文件或私有文档输入：

- S1：联合预测一次返回多个基础值，派生分使用原始预测值计算。
- S2：存储密钥轮换时保留旧密钥，等待迁移完成后停止使用。
- Q：一次预测取得多个结果时，派生分如何计算？

```text
CLI参数＋专用环境变量 → 本地参数/预算检查
                            ↓
            请求1：S1/S2批量向量 → 严格响应校验
                            ↓
            请求2：Q查询向量 → 严格响应校验
                            ↓
           本地余弦计算 → 向量/用量/错误摘要
```

每次请求最多2条，每条不超过200个Unicode字符。字符限制用于固定小样本范围，不冒充token计数或证明模型最大输入长度。

## 4. 请求配置与凭证

命令行显式提供endpoint、model、dimensions、timeout-seconds、deadline-seconds、max-requests、budget-cny、unit-price-cny-per-million、output-root；参数不从其他工程或隐式模型默认值获取。

首轮审阅值：

| 参数 | 值 |
|---|---|
| endpoint | https://open.bigmodel.cn/api/paas/v4/embeddings |
| model | embedding-3 |
| dimensions | 2048；先保持官方默认维度，不做维度效果比较 |
| timeout-seconds | 30；单次网络等待限制 |
| deadline-seconds | 120；从验证进程启动开始的墙钟截止 |
| max-requests | 2；所有尝试均计数，不自动重试 |
| budget-cny | 1.00；用户已确认的首轮Embedding总预算 |
| unit-price-cny-per-million | 0.5；执行前重新核对官方标价 |
| output-root | data/experiments/embedding-api-probe |

凭证只从用户为本项目提供的环境变量NAIYUE_RAG_ZHIPU_API_KEY读取。工具不读.env；本规范不授权写真实.env或其他环境配置文件。Key不进命令行参数、报告、Git或错误正文。缺少Key在任何网络请求前失败。

本次目标只允许表内已审阅的标准HTTPS端点，拒绝userinfo/query/fragment及自动重定向，避免Bearer凭证转发到其他地址。执行阶段不将环境中的代理认证/连接信息写日志。

## 5. 预算与截止

请求前先增加attempt_count，失败和超时也占请求次数；任一请求失败立即停止，不发送下一次，不自动重试。拒绝增大本文的次数、样本范围或执行截止。

按官方单条3072-token限制和3条输入计算，标价下预算估算上界为9216 × 0.5 / 1000000 = 0.004608元。它依赖官方输入限制、标价及按输入token计费，不能当作实际账单或供应商费用的程序硬保证。实际输入是固定短文本；不得以这个上界放宽到长文档。

成功响应读取usage；缺失或异常usage标为unknown并停止后续请求。已知usage按标价计算estimated_cost_cny，与provider_billed_cost_cny分开；后者没有账单时为null。异常响应是否计费也记unknown，不填0。预算总账从本次记录开始，后续全量Mock实验须扣除已用及预留未知费用后再定Spec。

网络工作在子进程中执行，由父进程按120秒总截止监督；到期终止本工具的网络子进程并记deadline_exceeded，服务端是否已处理/计费记unknown。不能把socket timeout当成整个程序墙钟截止，也不认为终止客户端能撤销服务端请求。

## 6. 响应验收与输出

200响应必须是可解析JSON，model与请求相符；data数量等于输入数量，index唯一且完整覆盖0..n-1，按index对应输入而非假定返回顺序。每个embedding长度2048，元素为有限数值（拒绝bool/NaN/Infinity），向量范数非0。

usage至少含非负整数prompt_tokens与total_tokens，total_tokens不小于prompt_tokens；若有completion_tokens也校验非负整数。缺少或异常用量保持实际向量诊断，但整体状态非complete，不再发送后续请求。

使用同一模型/维度的Q与S1/S2向量算余弦，保留实际分数；不要求相关样本分数必须更高，不用一对算例证明检索质量。

每次创建唯一结果目录，独占写summary.json及report.md，已有目录不覆盖。summary记录schema_version、模型/端点公开配置、合成输入ID及hash、attempt_count、阶段/HTTP状态、耗时、维度/范数诊断、usage、估算费用/未知实际费用、余弦分数和sanitized_error。没有向量或分数的阶段字段用null，不补假数据。不保存原始响应、完整向量、Authorization、异常正文或用户凭证。

工具正常完成全部响应检查及报告写入返回0；参数、权限、余额、限流、网络、响应、用量、预算、截止或落盘错误返回2，并在stderr输出阶段及安全错误类别。HTTP失败可记录状态码，不打印供应商原始正文。

## 7. 影响文件与TDD

拟新增experiments/embedding_probe.py和tests/test_embedding_probe.py；拟更新README.md、docs/handoff.md、docs/specs/README.md与本文实际验证章节。沿已有实验入口，不改现有公开函数签名、依赖清单或锁文件。仅两个实现/测试文件，单文件均不超过500行。

先写离线失败测试，确认缺少实现导致预期红灯，再实现最小工具。测试全部阻断实际网络，通过可控HTTP/子进程替身验证以下路径；替身在本测试文件中，不修改conftest或全局测试设施：

- 正常批次、乱序index重新对应、查询向量与余弦、独立结果目录。
- 缺Key/错误端点/非法参数/输入超范围在网络前失败。
- 非200、超时、损坏JSON、数量/重复index/维度/数值/范数错误明确失败，不重试。
- 缺usage/错误usage、预算不足、请求上限、总截止均停止后续请求；无未知数据造假。
- 落盘冲突/权限错误不覆盖、不吞错；秘密不会出现在stdout/stderr/输出文件。
- 完整CLI路径与父子进程监督接线；截止测试使用可控替身，不依赖紧时间窗口。

## 8. 计划验证命令与判定

以下保留实施前的验证计划；本轮实际执行结果见第10节：

```sh
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q experiments tests
.venv/bin/python -m pip check
git diff --check
```

服务执行命令计划如下，执行前须完成实现、离线绿灯和用户提供专用环境变量；本规范不读取或写入真实配置。本轮已按该参数执行，结果见第10节：

```sh
.venv/bin/python -m experiments.embedding_probe --endpoint https://open.bigmodel.cn/api/paas/v4/embeddings --model embedding-3 --dimensions 2048 --timeout-seconds 30 --deadline-seconds 120 --max-requests 2 --budget-cny 1 --unit-price-cny-per-million 0.5 --output-root data/experiments/embedding-api-probe
```

实际收尾记录TDD红灯、全部测试、syntax/pip/diff检查、原始安全日志与真实服务结果；L1文件存在、L2实现、L3两次请求与报告链分别核验。compileall只是语法检查，没有应用构建，不冒充build。服务受凭证或账户限制时如实报失败/未验证，不放宽响应断言。

## 9. 回滚与局限

产物仅新增实验工具和被Git忽略的独立结果目录，无索引/数据库/服务状态迁移；停止使用即可，不默认删除已有文件。已发生的服务费用不能回滚。

通过只说明本机指定模型/配置的短文本接口契约可用；不证明3072/8K边界、长用例保留、真实语料召回、CPU部署、SDK/框架接线或最终模型选型。官方8K概览与3072细节矛盾继续保留，不自行宣称已解。

来源：[模型与套餐核验](../decisions/0002-experiment-machine-and-embedding.md#2026-10-09官方接口及套餐核验)。生成模型/LightRAG调用预算独立讨论；本次1元不授权其调用。

## 10. 实际实施与验证（2026-10-09）

已新增[接入工具](../../experiments/embedding_probe.py)与[离线测试](../../tests/test_embedding_probe.py)。复用现有new_run_id，没有依赖升级、真实配置改动或生产RAG模块。临时Key通过关闭终端回显的getpass传入专用进程环境变量，核验后移除；未保存凭证文件。

TDD原始日志在被Git忽略的data/experiments/embedding-probe-evidence：

- 47项正常收集；缺少模块的预期红灯47 errors、退出1（red.txt）。
- 最小实现首次全量80 passed/1 failed：报告科学计数法显示；保留原断言，cost-format-red.txt复现后单点修金额显示，随后81 passed（green-1.txt）。
- 截止回归startup-deadline-red.txt：启动耗时未扣除，实际119秒/预期116秒；只修启动后重新计算剩余时间，未放宽断言。
- `.venv/bin/python -m pytest -q tests` → **82 passed in 0.54s**、退出0（green-accepted.txt）；新增48项，原34项全部通过。新测试阻断真实socket，没有改conftest、skip或放宽断言。
- `.venv/bin/python -m compileall -q experiments tests` → 退出0；`.venv/bin/python -m pip check` → `No broken requirements found.`；`git diff --check` → 退出0。没有应用构建，compileall仅语法核验。源码338行/测试337行。

服务前重新读取官方模型Markdown，仍列0.5元/百万tokens及单条3072-token细节。按第8节参数，通过getpass临时进程注入只运行一次：

```text
status=complete attempts=2 output=/Users/zmw/naiyue-rag/data/experiments/embedding-api-probe/20261009T155624Z-a4387149
```

[实际报告](../../data/experiments/embedding-api-probe/20261009T155624Z-a4387149/report.md)与同目录summary保存逐请求结果：

| 请求 | 合成输入 | HTTP | 向量 | prompt / total tokens | 网络及响应校验耗时ms |
|---|---|---|---|---|---|
| 1 | S1、S2 | 200 | 各2048维 | 42 / 42 | 316.240 |
| 2 | Q | 200 | 2048维 | 17 / 17 | 280.346 |

全部通过模型、index、维度、有限数值、非零范数及usage校验。整体674.615ms含子进程开销，仅是单次短文本核验，不是性能基准。输入tokens共59，估算59×0.5/1000000=**0.0000295元**；供应商账单未提供，provider_billed_cost_cny=null。预算的按标价估算余量0.9999705元不是账号实际余额。实际模型调用2次，无重试；没有生成、抽图或重排调用。

实际余弦Q→S1=0.7255652010829075、Q→S2=0.430525329087215，使用真实向量计算；没有预填结果或用该排序作测试硬断言。三级证据：L1工具/测试文件存在；L2真实HTTP、校验、预算/截止监督与落盘实现；L3完整CLI→父进程→worker→两个POST→余弦→报告，见attempt_count=2及HTTP200/usage。

限制：只验证指定2048维短文本契约；没有验证3072/8K超限、长用例、实际账单、其他维度、SDK/框架/LightRAG回调、CPU模型或知识库召回。`.env`加载未实现。本轮没有提交/push，不记录用户独立实现或技术理解通过。

唯一下一步：回到A/B跨文档检索实验，确定共用证据单元与返回预算；图路线生成接口/预算仍独立确认。不自动开始新切片或增加本轮模型请求。
