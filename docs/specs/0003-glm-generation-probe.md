# Spec 0003：GLM-5.2短文本生成接入核验

日期：2026-10-09。状态：已实施；用户要求“不要考虑预算，把这个实验做完”，共3次独立探针，前两次校验失败、修正后第三次结构及合成事实通过，详见第9/10节。此为选型实验，不是图谱或RAG产品实现。

## 1. 当前数据流与修改原因

已有Markdown组件实验及Embedding标准API探针；82项离线测试的前次结果见Spec0002。Embedding CLI走配置→父进程监督→worker→两次HTTP→响应校验→相似度→报告。它不能验证生成权限、输出结构或LightRAG模型回调。

本次新增独立生成探针：配置→父进程监督→worker→一次标准Chat Completions→usage/结束状态/JSON结构校验→合成事实检查→报告。复用已有ProbeError、NoRedirect、new_run_id；不改Embedding公开接口，不抽取仅一次的新抽象，不安装或升级依赖。

## 2. 授权与范围

用户指定glm-5.2、授权复用此前标准API Key，现已明确取消本轮费用预算确认。保留最多一次请求、max_tokens至多1024、网络等待至多30秒、整体截止至多120秒、不重试、不自动换模型的既定范围。费用仅记录，不以未批准的金额门槛阻止实施。

只发送固定合成文本和查询。不读真实知识库/.env/其他仓库凭证，不导入会自动安装依赖的第三方适配器。不建图、不索引、不生成用例、不实现MCP或最终问答，不将成功外推为LightRAG接线/跨文档质量。

## 3. 固定输入、输出与事实检查

合成来源R1三行：

```text
派生分由概率原始值与价值原始值相乘得到。
新需求取消派生分校准。
基础分继续校准。
```

查询：这次派生分校准改动需要回归哪些基础分行为？

请求JSON object，返回且仅返回entities、relations、keywords三字段。

- entities：1到20条，字段name/quote；名称唯一且出现在来源，quote必须是来源的非空连续子串并包含name。
- relations：0到20条，字段subject/predicate/object/quote；端点须为已列实体，quote为来源连续子串且包含两端名称。predicate只允许computed_from、calibration_removed、calibration_retained，提示词明确定义它们。
- keywords：1到10条非空字符串，去重；是否覆盖派生分/基础分/校准另作诊断，不由可解析JSON推断质量。
- 拒绝重复JSON键、非对象顶层、额外/缺少字段、空字符串、非法引用或悬空端点。schema为本探针契约，不声称兼容LightRAG原生抽取格式。

助手合成的固定事实标签为：派生分computed_from概率原始值；派生分computed_from价值原始值；派生分calibration_removed校准；基础分calibration_retained校准。每条quote须落在对应事实的那一行。逐条列matched/missing/unsupported及关键词覆盖，不作为人工标注或通用抽图评测。结构合法但事实遗漏/错配时仍保存实际输出和失败诊断，不自动重试或改标签。

## 4. 配置与外部契约

独立CLI experiments.generation_probe。所有运行参数由CLI传入，密钥只从NAIYUE_RAG_ZHIPU_API_KEY读取，不自动加载.env，不接受Key命令行参数。

```text
endpoint=https://open.bigmodel.cn/api/paas/v4/chat/completions
model=glm-5.2
max_tokens=1024
timeout_seconds=30
deadline_seconds=120
max_requests=1
input_price_cny_per_million=8
output_price_cny_per_million=28
output_root=data/experiments/glm-generation-probe
```

endpoint/model有本次授权目标校验，常量是允许范围而非默认请求地址。整数限额不接受bool；价格有限且非负。构造system/user消息、thinking.type=disabled、response_format.type=json_object、stream=false；不传tools或reasoning_effort。输入仅固定样本，无任意文件入口。

标准HTTP Bearer认证、不转发重定向、无自动重试。只读最多1MiB响应，超限明确失败。模型字段须与请求一致，choices恰为一个index=0的assistant消息，无工具调用；finish_reason=stop、非空content才解析抽取结果。记录reasoning字符数，非空时标记关闭思考未达预期，不把它拼入JSON正文。

usage必须含prompt_tokens/completion_tokens/total_tokens的非负整数，total=prompt+completion；缺失/异常为usage_unknown，费用不填0。成功收到用量但正文/模型/结束状态错误时仍保留已知用量和费用。估算=(prompt×8+completion×28)/1000000，参数价格写入报告，真实供应商账单始终未知，除非有账单证据。

## 5. 状态、失败与追踪

summary含公开config、合成source/query及hash、attempt_count、HTTP、model、finish_reason、reasoning字符数、usage、estimated_cost_cny、provider_billed_cost_cny=null、extraction、quality_checks、sanitized_error、elapsed_ms。

请求发出前emit检查点，累计attempt_count=1；父进程用余下总时间等待，启动后重新扣除耗时，超时kill并回收worker。中断/超时的已尝试请求不冒充未调用，未收到usage的费用未知；不能保证终止供应商已经开始的处理。

错误分类可观察：preflight/HTTP/transport/response/usage/extraction/deadline/worker/output；只保存类别和HTTP码，不记录Key、原始错误响应、异常文本、child stderr。收到的响应若包含实际Key，拒绝持久化。worker意外异常通过安全错误信封报告，不空catch。正常无关系返回合法空列表并显示遗漏，空正文是明确失败。

每次在新目录独占写report.md，最后写summary.json作为报告完成标记；IO失败明确报错，既有结果不覆盖。status=complete表示接口/结构流程完成，quality_checks.passed另行表示该合成探针是否通过。CLI完整流程返回0，协议/IO/截止失败返回2。

## 6. 影响文件与TDD

新增本Spec、experiments/generation_probe.py、tests/test_generation_probe.py；更新README、Spec目录、ADR0002、handoff、future-work、learning-roadmap及project-plan的当前模型状态。data下保存红/绿日志和真实结果，受现有Git忽略规则保护。不改依赖、其他实验、真实配置或源文档。

先写离线失败测试，确认模块缺失红灯；再最小实现。测试阻断真实socket并用假凭证/HTTP/子进程替身，覆盖目标/限额、请求body/header、重定向、错误码/超时/损坏/超限响应、严格schema/来源、事实遗漏、usage未知及已知用量保留、单次无重试、父进程截止/启动耗时、IO冲突、CLI接线。测试失败修源码，不放宽断言或skip。真实抽取正确性作为实际报告诊断，不在离线测试预填真实成功。

## 7. 验收与计划命令

```sh
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q experiments tests
.venv/bin/python -m pip check
git diff --check
.venv/bin/python -m experiments.generation_probe --endpoint https://open.bigmodel.cn/api/paas/v4/chat/completions --model glm-5.2 --max-tokens 1024 --timeout-seconds 30 --deadline-seconds 120 --max-requests 1 --input-price-cny-per-million 8 --output-price-cny-per-million 28 --output-root data/experiments/glm-generation-probe
```

无应用构建，compileall只是语法检查。验证全部既有测试、12份Mock源及Embedding/依赖文件hash未变、源码≤500行、输出不含凭证；L1文件存在、L2实现、L3真实CLI到HTTP和报告分别给证据。失败不伪造成功、不自动超额重试；真实服务失败也保留可复现的安全报告。

## 8. 来源、限制与回滚

2026-10-09官方[GLM-5.2](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2.md)、[接口](https://docs.bigmodel.cn/api-reference/模型-api/对话补全.md)、[定价](https://docs.bigmodel.cn/cn/guide/start/pricing.md)及[兼容说明](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction.md)，原文缓存见ADR0002。无第三方代码复用。

停止使用新探针即可，无索引/数据库迁移，不自动删除任何产物；实际服务费用不可回滚。一次合成关系与关键词结果不能证明全库抽取质量、版本判断、LightRAG格式/SDK接线、CPU部署或业务用例质量。用户仍要求先选型，不在本轮安排代码课堂或登记独立实现。

## 9. 首次实测后的可观测性修正

首次真实请求HTTP200、模型glm-5.2、finish_reason=stop、思考字符0，但invalid_extraction。原实现没有保存失败正文或具体规则，不能定位原因；该限制是探针缺口，不能据此否定模型/图路线。

按用户“把实验做完”的授权连续处理：先写失败回归，修正诊断，再人工发起一次新的独立探针（每次仍最多1请求、30秒网络/120秒总截止，不在程序内重试）。保留首次结果，不放宽契约、不换模型、不改事实标签。若连续三次实测失败则按项目调试规则报告阻塞。

summary新增completion_content，schema_version升至2：仅当完成响应信封检查、失败发生在抽取校验时，保存不超过20000字符的模型正文；本探针输入固定为合成文本，不接受私有文件。成功结果也保存同一正文，报告单独展示。仍不保存原始HTTP响应、错误响应、思考内容或凭证。解析HTTP JSON后再次检测解码后的实际Key，防止JSON转义绕过原始字节检查。错误类别附固定规则代码（JSON/top_fields/count/entity/name/entity_quote/relation/endpoint_predicate/relation_quote/quote_endpoint/keywords），不序列化异常消息。字段同步检查worker、checkpoint、父进程、JSON、报告和测试。

第二次HTTP200，invalid_extraction_relation_quote。实际正文将第二、三行删除换行后拼成quote，并将两条校准关系object均设为“新需求”。原提示只解释predicate，没有明确校准关系的object语义；因此作单一提示词修正：校准类subject为被校准对象、object为来源原词“校准”（须列为实体），quote逐字复制并保留原换行，不拼接改写。其余输入、schema、标签、模型和限额不变；写提示词回归红灯后修正，进行第三次且最后一次独立探针。对照只用于观察同一示例，不用前后一次差别宣称普遍质量提升。

## 10. 实际实施与验证（2026-10-09）

### TDD与本机验证

新增测试最初因模块缺失报59 errors（退出1，0.26秒）；实现及追加IO/监督测试后144 passed。可观测性修正3 failed/62 deselected→修源码147 passed；提示词定义1 failed/65 deselected→改提示词148 passed。最终新增66项、原有82项均通过；不改变已有断言、skip或依赖。原始初始红/绿与最终日志在data/experiments/generation-probe-evidence；两次回归红灯另保存实际工具输出摘要，非完整重建日志。

实际命令逐条执行并检查退出码，最终结果：

```text
.venv/bin/python -m pytest -q tests
148 passed in 0.47s                       [exit 0]
.venv/bin/python -m compileall -q experiments tests
无输出                                   [exit 0]
.venv/bin/python -m pip check
No broken requirements found.            [exit 0]
git diff --check
无输出                                   [exit 0]
```

应用构建不适用；compileall仅语法检查。15份固定输入/原Embedding源码和测试/依赖锁文件hash未变，generation_probe.py 374行、test_generation_probe.py 406行；本项目源码/文档/测试与本轮报告/日志凭证模式检查为0匹配。data结果、证据目录和.venv均由git check-ignore确认忽略。未修改.env或其他仓库、没有提交/push。

### 实际服务结果

第7节生成命令的全部参数由CLI传入；实际使用getpass隐藏输入→临时进程环境→main(args)→run→supervise→worker→一次HTTP→校验→落盘，finally清除该进程环境变量。Key不在argv、源码、报告或日志；每次都新建结果目录，无程序自动重试。三次均glm-5.2、HTTP200、finish_reason=stop、reasoning字符0：

| 次数/结果目录 | 校验结果 | prompt/completion/total tokens | 总耗时ms | 标价估算元 | CLI退出 |
|---|---|---|---|---|---|
| 20261009T173808Z-69235f0e | invalid_extraction；初始未保留失败正文/规则，不能归因 | 292/385/677 | 3646.580 | 0.013116 | 2 |
| 20261009T174004Z-dcd99ca1 | invalid_extraction_relation_quote；具体正文见第9节 | 292/347/639 | 3504.931 | 0.012052 | 2 |
| 20261009T174048Z-fca28a76 | complete；结构/原文引用通过，quality_checks.passed=true | 337/424/761 | 5523.972 | 0.014568 | 0 |

合计3请求、921输入/1156输出/2077总tokens；估算(921×8+1156×28)/1000000=0.039736元，不使用缓存优惠；provider_billed_cost_cny=null。耗时包含本地进程及报告开销，非纯服务端延迟；不是规模或性能基准。

最终6实体/4关系/5关键词，required_relation_count=matched_relation_count=4，missing_relations/unsupported_relations/missing_keywords均空。正确提取两条computed_from及派生分calibration_removed、基础分calibration_retained，quote均为来源原文。此为助手合成固定标签，不是用户人工标注、模型评分或真实业务质量结果。单次改提示词后成功不证明统计稳定性。

实际报告保存在data/experiments/glm-generation-probe各结果目录的report.md/summary.json；本机可看[最终报告](../../data/experiments/glm-generation-probe/20261009T174048Z-fca28a76/report.md)。初次schema_version=1；后两次为2，新增completion_content。保留两次失败，不回写/覆盖历史。

### L1/L2/L3与边界

- L1存在：新Spec、生成源码、66项测试及三套真实结果文件存在；README/规划/ADR/交接/待办/学习入口已同步。
- L2实质：严格JSON/原文/用量检查、事实诊断、单次HTTP、进程截止、安全错误、文件冲突和真实报告有实现与离线验证；不是空模块。
- L3接线：实际main(args)使用用户指定端点/型号/参数，经worker发POST收到模型/usage/正文，真实结果进入校验并保存；第3次CLI退出0，合成事实通过。测试另验证请求header/body、异常和父进程截止，不以测试替身冒充服务结果。

尚未安装/运行LightRAG、创建图或向量索引、跨文档召回、MCP、最终问答或用例生成；未读远端真实资料，CPU适配/稳定性/实际账单未知。用户暂停代码课堂；只记录实现和实测，不记录引导理解/独立实现。唯一下一步回到跨文档检索实验分组与共享片段接法的设计。
