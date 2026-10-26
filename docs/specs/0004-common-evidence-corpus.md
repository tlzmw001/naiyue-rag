# Spec0004：五组检索实验的公共证据单元

日期：2026-10-09。状态：用户“是的继续”已授权按本Spec实施，现已完成离线验证，实际结果见第8节。用户已确认A1/A2/A3/B0/B1分阶段对照；本Spec只确定第一项前置实验：11份历史候选原文→可定位公共证据。不是生产摄取实现，不包括检索或LightRAG安装。

## 1. 当前数据流与原因

已实现的是三类原生切分观察、Embedding短接口及GLM合成抽取探针；尚无公共证据语料。Spec0001中C2原生47片段均exact，完整用例及章节上下文保留，但一整维度多用例在同一片段，最大1339字符；C0 512拆坏长行，1024仍有上下文分离，C1有空白改写及无法定位。上述是这批Mock本机结果，不能外推真实质量。

推荐沿现有C2结果复用llama-index-core==0.14.25的MarkdownNodeParser组织普通正文，增加完整用例行及来源适配。与直接C0递归的取舍：C2本组定位/结构证据更好，仍需自有用例规则；C0可以少用标题组件，但已有长行/上下文缺口。仅选择共用实验片段起点，不选择整套LlamaIndex检索编排。暂不新增Markdown语法依赖或实现通用解析框架。

复用已有load_sources、source_span、map_exact_source、table_cells及new_run_id，不改其公开签名或旧实验行为。先搜索过experiments/tests/Spec，没有公共证据构造/导出入口，新增模块以保持旧组件观察与新适配职责分离。

```text
CLI范围/4000字符上限
          ↓
load_sources校验原文与版本 → 范围筛选
          ↓
C2章节节点 → exact映射 → 普通正文/完整用例适配
          ↓
公共ID＋正文/上下文各自出处 → 单条证据渲染检查
          ↓
sources.jsonl / units.jsonl / summary.json / report.md
```

## 2. 范围、参数和依赖

- 本机现有独立.venv，Python3.12.14及固定83包；不安装/升级/改依赖，不读.env或其他仓库。无网络、API Key、MCP或外部服务依赖。
- 输入examples/mock-v1。只读取manifest.documents的路径/身份/角色/层级/hash；忽略expected_pairs、预期关联/异常标签，不读tasks.json。现有load_sources读取/核验12文件，但排除MOCK-TASK-004后才调用组件或构造证据；历史输出仅11源。
- CLI必须给dataset、exclude-document-id、max-evidence-chars和output-root，无隐藏默认。可重复include-document-id；非空时仅保留列出的已知ID，再应用exclude；未知ID、冲突选择及空范围显式拒绝。例：Q03范围仅MOCK-CASE-001，作为第二个离线范围验收。
- max-evidence-chars本轮4000，单位为Python len的Unicode字符，不是token。普通章节在本切片保持完整，不引入1024硬截断或第二套检索片段策略；超4000的单条证据保留并标blocked，不静默截断。本组Mock预计适合完整章节，但以实际输出为准。
- 本切片支持实际Mock的ATX标题、三反引号围栏、九列单物理行用例、转义竖线及<br>。不转换HTML，不展开引用或执行Markdown命令。其他语法没有通过即不宣称支持。

## 3. 单元构造与公开实验接口

experiments.evidence_units提供build_units(source, max_evidence_chars)→units/diagnostics、render_unit(unit)→str。experiments.corpus_probe提供run(dataset, include_ids, exclude_ids, max_evidence_chars, output_root)及CLI main。这是新增实验接口，非RAG产品API。

普通文档用MarkdownNodeParser.from_defaults(include_metadata=True, include_prev_next_rel=False)，从Document(text=原文)产生标题节点。每个节点须在该版本原文唯一精确匹配，才构造正文范围；组件随机ID不用作公共ID。原文实际标题栈及标题行来自源文件，框架header_path作为观察值，不自动等同完整业务路径。重复正文映射不唯一为ambiguous，禁止选第一个冒充exact。非空输入零节点为错误，空文件记录empty_source。

用例文档仍由C2组织章节；有合法表格时，一条九列物理行生成一个test_case单元，原行包括全部字段，不做单元格展开或改写。上下文包含原文文档标题、维度标题、表头及同维度表格前的来源/覆盖块引用，每一段独立保留span。其他叙述按原文范围生成text单元；不得再生成包含这些用例行的整维度正文造成重复。表头/分隔行不作为独立检索正文；结构上下文由单元引用保留。

源码中TC-ID/前提引用保留原样；TC-02不继承TC-01步骤和预期。本切片不推导关系。仅将解析后的九个列值作为case_fields观察字段；若现有table_cells不能可靠处理某种行内竖线，记录unsupported_structure，不擅自新建通用解析库。

单位字段固定为schema_version=1、unit_id、document_id、source_path、source_sha256、role、semantic_level、directory_level、kind(text/test_case)、heading_path、body、body_span、contexts、case_id、case_fields、component_metadata、rendered_text、rendered_characters、eligible、diagnostics。component_metadata保留实际C2 metadata作为观察值；text的case_id=null/case_fields=[]；contexts每项含context_kind（document_title/section_heading/dimension/columns/source_note）、text和span，不能把拼接上下文冒充连续原文。

实现前细化：ID数组序列化使用ensure_ascii=False、separators=(',', ':')、UTF-8；表格分隔行须与九列匹配。text从已唯一定位的C2节点内实际范围取连续原文，边界strip时同步调整offset；不对内部空白换行做转换。检测到不支持围栏时该源不调用C2并记录blocked，避免坏结构被误切；其他结构错误保留可确认单元并阻断总体成功。

span为已有source_span结构：start_char/end_char半开Unicode字符区间、line_start/line_end一基闭区间、source_sha256；每项source.text[start:end]==所标正文/上下文。字段变化同步检查单元构造、渲染、JSONL、汇总和测试。公共ID为unit-加sha256(document_id、source_sha256、kind、start、end按固定JSON数组序列化)；同源版本/位置重复运行稳定，版本变化ID也变，不使用正文hash独立合并不同位置。

render_unit固定依次输出元数据行、各contexts和body，使用换行连接：元数据行含unit_id/document_id、source_path、source_sha256、正文L起止；每个上下文用[context_kind L起止]前缀后接原text，正文用[body]前缀后接原body。所有文字/前缀/换行计入rendered_characters，转义换行在JSON中存储不改变实际字符串len。正文与上下文位置分别可核验；仅重叠的同span上下文去重，不跨证据删除来源。字符超限时eligible=false并记录single_evidence_over_budget，仍导出原文；成功状态不能含超限/不支持或无法定位单元。

## 4. 输出、失败与追踪

每次独立时间戳UUID目录，独占创建，不覆盖任何结果。sources.jsonl保存选中源身份/版本/实际行数/字符数，不含排除源或标签；units.jsonl保存实际完整单元。summary含运行ID、参数、Python/组件版本、源hash、实际文件/单元/用例数、最大渲染长度、eligible数、诊断及耗时；report展示真实摘要、代表性用例/上下文出处、失准手写行号警告、结构/超限/映射失败和限制。summary最后写入，记录整体status与CLI退出码。

- 输入缺失、UTF-8错误、hash不符、ID/路径越界：沿已有校验明确失败，退出2；不改源文件、无空catch。错误只记录类别/本机公开源相对路径，不引入凭证或任意环境值。
- 标题像代码内容时不当标题；未闭合/不支持围栏、错误列数、缺表头/维度、重复case_id、非单物理行等记录unsupported_structure，不把表格错误当正常叙述。
- 映射ambiguous/unmapped、未支持格式或单证据超限：导出可确定的单元和所有诊断，整体blocked、退出2，不把缺失部分填为空成功。手写范围失准只作warning，不作为原文定位/切分依据，当前故意L999-L1005须可见但不阻断实际位置正确的单元。
- 参数非法/未知或空范围拒绝；合法空源与组件异常分开。组件异常不自动换LC/C0；意外网络访问测试即失败。
- 输出目录冲突/无权限/写失败报output_error、退出2，不覆盖/删除/重试既有产物。相同输入重复运行单元内容/ID/诊断稳定，运行目录/耗时不同正常。

最脆弱前提是C2原生内容可映射到源版本；失败就保留诊断并修订方案，不通过放宽exact断言掩盖。此离线阶段不留下外部状态；回滚边界为停止使用新入口并保留结果，不自动删除文件/回退Git。

## 5. TDD与验收

先写新测试并确认入口/构造缺失的预期红灯，依赖/测试收集正常后才实现。正常与异常均使用合成夹具、现有Mock，测试内部阻断socket，不修改conftest。修复带回归，不放宽断言或skip。

| 核验 | 明确条件 |
|---|---|
| 普通章节 | 公式围栏＋时序说明同单元；标题正文原样可回查；节点0/重复/改空白分别可观察；围栏中的#不是标题 |
| 用例 | 12条实际Mock用例各有唯一完整行、九字段、原维度/表头及可用来源说明；<br>/转义竖线及部分前提引用原样；不产生整表重复正文 |
| 定位与版本 | UTF-8中文、LF/CRLF、源char/行号一致；源hash不符拒绝；全部输出span切回源文一致；L999-L1005只为warning |
| 范围与标签 | 正常输出11源且无MOCK-TASK-004；Q03仅MOCK-CASE-001；替换/删除tasks或expected_pairs不改变单元，未知ID/路径逃逸/空范围拒绝 |
| 字符预算 | 元数据/上下文/换行计入len；超限完整保留、eligible=false且blocked，不能静默切行 |
| IO/接线 | CLI→真实已安装C2→适配→JSONL/报告；原12源hash不变；重复ID稳定、输出不覆盖；注入读写错误可观察，socket阻断下通过 |

## 6. 影响文件与计划命令

共11个文件：新增experiments/evidence_units.py、experiments/corpus_probe.py、tests/test_evidence_units.py、tests/test_corpus_probe.py；维护本Spec、README、docs/specs/README、handoff、future-work、learning-roadmap及ADR0001的实际切片状态。文件超过8个是一个前置实验的源码/测试/实际入口记录，未新增服务；每源码文件≤500行，若职责需调整先更新Spec。旧实验/测试/锁文件及真实配置不改。

以下为获确认后的计划，不是本轮执行结果：

```sh
.venv/bin/python -m pytest -q tests
.venv/bin/python -m experiments.corpus_probe --dataset examples/mock-v1 --exclude-document-id MOCK-TASK-004 --max-evidence-chars 4000 --output-root data/experiments/common-evidence-corpus
.venv/bin/python -m experiments.corpus_probe --dataset examples/mock-v1 --include-document-id MOCK-CASE-001 --exclude-document-id MOCK-TASK-004 --max-evidence-chars 4000 --output-root data/experiments/common-evidence-scoped
.venv/bin/python -m compileall -q experiments tests
.venv/bin/python -m pip check
git diff --check
```

没有应用构建，compileall是语法检查。收尾贴红灯、完整测试结果、CLI实际状态/数目/报告路径、所有span及原输入hash核验；L1文件存在/L2实质/L3真实调用分别给证据。不得预填单元总数、通过数或引用质量为成功。

## 7. 教学与后续边界

用户目前先选型、不看代码；本阶段结果用于讨论片段实际长什么样，不自动安排课堂或记本人理解/独立实现。公共单元完成后，唯一下一步是A1向量基线Spec，沿已授权embedding-3来源接线；A2/A3/B0/B1仍在已确认总范围内分阶段制定，LightRAG安装/回调/原生格式/存储片段一致性另有验收，不能由本阶段声称通过。

本Spec不读取任务答案标签、不计算检索成绩、不建立索引/图、不调用Embedding/GLM、不实现问答、重排、MCP/服务/界面，不迁移真实材料。参考机制来源为已装包源码及[官方MarkdownNodeParser](https://developers.llamaindex.ai/python/framework-api-reference/node_parsers/markdown/)，读取2026-10-09；官方当前页不能代替固定0.14.25本机源码/实测。无第三方代码复制，直接使用现有MIT包API。完整基线见Spec0001第11节。

## 8. 实际实施与验证

本地America/Chicago日期2026-10-09；结果ID使用UTC，目录前缀20261010不是另一轮输入版本。按Spec新增两份源码及两份测试、同步7份指导文件；旧工具公开签名/实现、依赖锁、Mock和真实环境配置未改。未提交/push或修改其他仓库。

### TDD与实际命令

两份新测试先正确收集，因evidence_units/corpus_probe模块缺失报43 errors in 0.16s、退出1；最小实现首次运行43 passed in 0.56s、退出0。然后执行全套：

```text
.venv/bin/python -m pytest -q tests
191 passed in 0.61s                 [exit 0]

.venv/bin/python -m experiments.corpus_probe --dataset examples/mock-v1 --exclude-document-id MOCK-TASK-004 --max-evidence-chars 4000 --output-root data/experiments/common-evidence-corpus
status=complete sources=11 units=52 cases=12 blocked=0
output=.../20261010T021859Z-647de42b  [exit 0]

.venv/bin/python -m experiments.corpus_probe --dataset examples/mock-v1 --include-document-id MOCK-CASE-001 --exclude-document-id MOCK-TASK-004 --max-evidence-chars 4000 --output-root data/experiments/common-evidence-scoped
status=complete sources=1 units=10 cases=7 blocked=0
output=.../20261010T021859Z-4821b020  [exit 0]

.venv/bin/python -m compileall -q experiments tests
无输出                              [exit 0]
.venv/bin/python -m pip check
No broken requirements found.       [exit 0]
git diff --check
无输出                              [exit 0]
```

以上CLI为本轮实际执行，不是测试替身输出。原148测试保留全部通过，新43项覆盖真实已装C2、正文/上下文、CRLF、转义、部分引用、各结构/映射/组件失败、空源、预算、范围、标签隔离与IO；不修改conftest、断言或skip。构建不适用，compileall只是语法检查。

预期红灯完整日志为data/experiments/corpus-probe-evidence/red.txt；绿灯/CLI工具输出摘要为green-summary.txt（摘要不是重建的完整pytest日志）；独立源检查及最终命令/源码hash在source-checks.json、final-validation.json。data受现有Git忽略规则保护。

### 内容、定位与离线证据

历史范围52单元=40 text＋12 test_case，全部eligible，最大单条rendered_characters=1104。12条用例逐一匹配实际完整物理行，最长正文571字符，含表头/维度/说明后1104字符；原表格分隔行不单独进入检索正文。186处正文/上下文span独立切回源文及版本hash/行号一致；另按全源非空白字符覆盖核验，无遗漏（明确排除仅作表格结构的用例分隔行）。不以位置正确宣布检索业务质量通过。

1条warning保留：MOCK-L2-001第10行[251,261)的L999-L1005为stale_header_line_range；实际公式单元仍定位第19–30行并包含计算公式/时序说明。TC-02正文第20行/[1036,1230)共194字符，独立上下文为标题第1行、维度第11行、表头第17行、说明第13–15行，整体727字符；没有继承TC-01的测试步骤或预期。

27份既有Mock/原实验/原测试/依赖文件hash全部不变。源码行数：evidence_units216、corpus_probe132、test_evidence_units169、test_corpus_probe149，均≤500。

为验证离线契约，另在新进程中先阻断socket.connect/connect_ex，再以runpy执行同一CLI参数、独立输出根common-evidence-offline-guard：complete sources=11 units=52 cases=12 blocked=0，network_attempts=0、退出0，结果目录20261010T022027Z-763e25d8。其units.jsonl与原历史范围输出完全一致。模型客户端没有接入，Embedding/生成调用0；模型tokens/费用不适用。

### L1/L2/L3与已知限制

- L1文件存在：两份源码/测试、规范及三套实跑sources/units/summary/report存在，入口文档已同步。
- L2真实实现：构造/渲染/位置与结构校验、范围、异常、预算及独占落盘有实现与43新测试；没有占位模块。
- L3调用接线：实际CLI→run→build_units→旧split_candidate的已装MarkdownNodeParser→适配→渲染/字符检查→JSONL和report→最后summary；CLI实际排除本次任务，单文档范围只构造该源。网络阻断/源映射另有独立证据。

支持范围仍限本Spec合成语法；未核验真实资料、多种表格/围栏/复杂Markdown或生产更新。4000是单条可返回性检查，本阶段没有多条查询组装、召回、无答案识别或检索评测。LightRAG共享片段/索引/图未接线，五组未运行。用户目前暂停代码课堂，不登记讲解、引导理解、独立实现或面试掌握。唯一下一步A1向量基线Spec，不重问五组/模型/片段方案。
