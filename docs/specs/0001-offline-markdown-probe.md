# Spec 0001：离线Markdown摄取组件实验

日期：2026-10-09。状态：用户以“执行”确认实施，离线切片已完成验证；实际结果见第11节，计划命令不自动视为已运行。

## 1. 目标与范围

在当前电脑，用现有12份合成Markdown直接运行三种现成切分组件，导出片段和诊断报告。回答：普通章节与用例表格保留得怎样，标题/说明是否分离，原文位置能否确认，以及需要哪些业务适配。此次产物是选型实验工具，不声明RAG摄取或检索已完成。

关联决定：[A/B检索候选](../decisions/0001-retrieval-experiment-scope.md)、[当前实验电脑与Embedding迁移](../decisions/0002-experiment-machine-and-embedding.md)。模型/索引/图/MCP/问答/界面/CPU模型部署及真实文档处理不在本切片中。

推荐运行三个候选及两个字符预算；最小可缩减选项仅C0递归切分，不足以完成三候选选型。暂不写专用生产解析器：先观察组件原始行为，再依据失败决定适配。

## 2. 当前数据流及修改原因

现有：合成Markdown → 人工阅读与标准库资产检查 → manifest/source spans。没有产品源码、依赖清单、测试入口或索引。

本切片新增单向流：

```text
Mock原文 + manifest身份/校验信息
             |
             v
读取原文字节、哈希、实际行边界
             |
             v
C0 / C1 / C2 直接切分 → 原始片段内容与组件metadata
             |
             v
原文精确匹配 + 固定结构探针 → 诊断结果
             |
             v
chunks.jsonl + summary.json + report.md
```

表头手写行号有已知偏差；用例存在长物理行和部分前置引用。仅有字符串输出/框架metadata不足以证明内容和定位可用，需要独立检查。

## 3. 输入、参数和依赖

- 运行环境：本仓库已有Python 3.12.14 `.venv`；不读取其他项目环境或任何`.env`。
- 输入根：CLI显式传入`examples/mock-v1`。按manifest列出的12份文件读取，限定其`knowledge/`范围；不递归扫描仓库，不把tasks/README/manifest传给组件。12份中包括模拟本次任务，此处只测切分，不计历史检索。
- manifest只用于文件路径、文档身份/角色/层级及hash校验；expected_pairs不参与切分或生成关系；tasks.json不读、不消费其相关性标签。
- 字符预算：CLI显式传`512 1024`，单位为Python字符数，不是token数；overlap显式传`0`，用于隔离边界现象，不是最终检索参数推荐。
- 输出根：CLI显式传`data/experiments/markdown-probe`，实际每次创建时间戳加UUID的独立子目录，不覆盖任何已有文件。
- 不需要API Key、外部模型账户、MCP或第三方CLI。依赖安装访问PyPI；运行与测试离线。
- Markdown内容只作为文本处理，不执行其中的命令或把文档指令作为操作授权。

直接依赖固定为：`langchain-text-splitters==1.1.3`、`llama-index-core==0.14.25`、`pytest==9.1.1`。2026-10-09实际读取PyPI页面及JSON元数据，版本存在，均标MIT及Python>=3.10，兼容当前解释器声明范围。包组合及传递依赖未安装验证；若解析失败，停止并修订Spec，不能擅自升级。

安装仅在本Spec获确认后执行，限定`.venv`，优先仅接受wheel，不自动编译源码包。`requirements-experiment.txt`记录直接版本，成功安装后以`pip freeze --local`生成`requirements-experiment.lock.txt`记录完整实际环境；后续复现从lock安装。原参考项目只提供机制参考，不复制其源码/setup/Skill。以上三个包作为依赖使用，新增自有代码保持实验职责。

来源：[PyPI LC包](https://pypi.org/project/langchain-text-splitters/1.1.3/)、[LlamaIndex包](https://pypi.org/project/llama-index-core/0.14.25/)、[pytest包](https://pypi.org/project/pytest/9.1.1/)，源码/切分边界见[摄取比较](../research/markdown-component-experiment.md)。已核对注册站点可读，未验证安装成功。

## 4. 三个候选的固定调用方式

| ID | 组件及明确参数 | 输出处理 |
|---|---|---|
| C0 | LC RecursiveCharacterTextSplitter；chunk_size分别512/1024；overlap=0；length_function=len；非正则；分隔符按参考顺序：双换行、换行、英文句点空格/叹号空格/问号空格/分号空格/逗号空格、空格、空串；其余使用固定包默认值并记录 | split_text读取整个文档，保留输出字符串，不补标题/表头 |
| C1 | LC MarkdownHeaderTextSplitter；标题#、##、###；metadata名称h1/h2/h3；strip_headers=False；return_each_line=False。随后对各标题组调用与C0相同递归组件，分别512/1024 | 保留page_content及metadata；不把组装结果称为原文，不修表格行 |
| C2 | LlamaIndex MarkdownNodeParser.from_defaults；include_metadata=True；include_prev_next_rel=False；Document.text为原文，get_nodes_from_documents | 保留node文本及metadata；只运行一次原生标题切分，不做二次长度切分 |

共5种配置×12份文档=60条文档实验结果，片段数由组件实际输出决定，不预填。C2不遵守字符上限，其最大/超限长度用于描述，不能称为相同预算的检索质量对照。

本次采用发布包，LlamaIndex版本与已调研main声明版本一致仍不证明文件相同。实施时查看安装包中的必要函数位置并记录真实路径/包版本；出现行为差异记录，不改第三方组件使它满足我们的预期。

## 5. 实验内部接口与输出字段

这是实验工具的内部约定，不是公开RAG API。

| 入口 | 输入与返回 | 职责 |
|---|---|---|
| load_sources | dataset_root → SourceSnapshot列表 | 校验manifest与路径、读UTF-8原文字节，构造源位置 |
| split_candidate | SourceSnapshot、candidate、size、overlap → ChunkObservation列表 | 只调用对应组件，保留实际输出 |
| map_exact_source | 原文与片段文本 → mapping状态及候选SourceSpan列表 | 精确查找原文出处，不模糊猜位置 |
| inspect_document | 原文、片段列表 → ProbeObservation列表 | 检查固定结构探针和定位，不改变候选输出 |
| run/main | CLI参数 → 三种报告；退出码 | 调度、计时、写输出；错误明确返回 |

SourceSnapshot字段：document_id、relative_path（以knowledge为根）、role、semantic_level、directory_level、source_sha256、text及实际行起始字符索引。原始字节hash后UTF-8解码，不更改换行/空白；CRLF按一个实际行结束处理，不误计为两行。

ChunkObservation字段：candidate、variant、document_id、ordinal（0起）、chunk_text、native_metadata（实际组件字段）、character_count、mapping_status、source_spans。ordinal只是实验顺序，不是稳定产品chunk ID；来源身份来自manifest，不声称已实现自动元数据提取。

SourceSpan字段：start_char、end_char（解码文本中的半开字符区间，非字节offset）；line_start、line_end（实际原文件1起、包含端点）；source_sha256。源行范围只是显示定位，精确区间仍保留字符offset。

映射规则：唯一完全相同子串为exact；多处为ambiguous，保留所有匹配，不默认选第一处；无完全匹配为unmapped，source_spans为空。允许诊断发现框架改空白后无法精确匹配；不得用手写行号或归一化字符串强行补准确位置。不把unmapped输出当可直接投产证据。

ProbeObservation字段：probe_id、scope（文档/用例/块）、status（pass/fail/not_applicable）、expected_text（实际源探针文本，纯合成输入）、expected_source_spans、observed_chunk_ordinals、reason。未支持或不足以判断须显式说明，不能靠空值标为pass。

summary.json含schema_version=1、状态、运行ID、Python/依赖版本、全部参数、语料文件/hash列表、60个文档配置结果、耗时及诊断计数。chunks.jsonl一行一个ChunkObservation。report.md逐候选展示代表性成功/失败与实际片段；原文示例仅来自合成材料。没有token/费用/Recall字段或虚构数据。

elapsed_ms只作此次实验观察，包含不同首次初始化影响，不宣称组件性能排名。重复运行比较固定输入/参数/片段内容及诊断结果，忽略运行ID、计时与框架随机ID。

## 6. 固定结构探针与计算方法

探针是结构要求，由源Markdown独立识别；不是检索相关性金标准，不借用tasks.json预期证据。

| 探针 | 检查单位与判据 |
|---|---|
| 完整用例行 | 12条源用例行各自完整文字是否包含于至少一个输出片段；跨片段拼接不算完整；统计完整行数/12 |
| 列义与维度 | 对每条完整行，检查同一片段是否同时含其源表头及最近测试维度标题；native_metadata单独列出，不冒充正文保留。分开计数完整行、行+表头、行+表头+维度 |
| 来源/覆盖说明 | 检查用例所属维度的源块引用是否随同完整行出现在同一片段；缺少说明列为缺口，不自动复制补齐 |
| 内联元素 | 对含<br>、公式/行内代码、转义竖线的原文探针，逐个检查原始串是否完整出现；报告来源行和对应片段，不只统计全库符号总数 |
| 围栏代码块 | 每个源围栏块含开始/正文/结束是否完整保留于一个片段；拆分或残缺分别说明 |
| 链接 | 每个源Markdown相对链接是否原样保留于至少一个片段；不以修改路径后的链接充数，不扩展关联文档 |
| 位置 | 统计exact/ambiguous/unmapped片段；所有exact区间必须从原文切回完全相同文本；false exact必须为0 |
| 手写行号 | 001源表头L999-L1005与实际文件行数冲突必须作为source warning显示；不得把它填入SourceSpan |
| 部分前置引用 | 001用例TC-02的“沿用TC-01指定条件”原文是否保留；不展开继承，不推断完整业务依赖 |

探针识别器只覆盖本Mock及测试夹具的明确语法：ATX标题、三反引号围栏、块引用、单物理行管道表格、Markdown相对文件链接；匹配源表格行时尊重转义竖线，九列之外/多行表格等报unsupported_structure。不能称为完整Markdown语法解析器。L0/L1/L2正文表格不当测试用例表格；源用例判别依据角色historical_test_cases。

未知语法报告能力边界，不根据目录级别把L1来源用例误判需求。第三方片段发生规范化时诊断可失败，不给模糊匹配或改变探针来制造通过。

## 7. 正常、异常与空结果

- 正常：校验12份输入 → 对5种配置依次处理 → 记录实际片段/诊断 → 创建独立输出目录写报告。按文档/candidate/variant输出阶段进度，不打印正文。
- manifest缺失、hash不符、UTF-8错误、路径逃逸或源读取失败：不继续组件调用，stderr含阶段/相对路径/错误类型，退出2，无成功报告。
- 参数size非正、overlap<0或overlap>=最小size：拒绝并退出2。
- 输入目录外路径/绝对文件路径/符号链接逃逸：resolve后校验knowledge根范围，拒绝；来源身份不能允许覆盖输出路径。
- 合法空Markdown：测试夹具记录empty_source、0片段、探针not_applicable；非空文件却0片段记录组件错误。
- 组件导入/调用错误或意外网络访问：记录该配置error，不用其他组件伪装其结果；完成能执行的配置后总状态error、退出2。输出失败项reason，不声称三候选完整通过。
- 探针fail但组件正常：实验命令可退出0，因为已得到有效诊断；summary必须保留fail计数。退出0不能解释成知识库结构验收全通过。
- 输出IO失败/已存在目标子目录：明确报错退出2；不覆盖、删除、重试写成功。数据规模仅Mock，不实现自动重试/并发/服务。

依赖安装网络失败或wheel不可用立即停止，报告错误；不自动使用镜像、源码构建、升级或换工具。若语料扩大10倍，仍顺序按文档处理并记录耗时；本切片不承诺全库吞吐。

## 8. TDD与验收

先写下列测试，运行确认因实验入口/检查器未实现而红灯；确认测试收集正确，不能把缺pytest/依赖算成预期红灯。随后最小实现，连续完成已确认范围。

| 测试组 | 核心断言 |
|---|---|
| source/位置 | UTF-8中文、LF/CRLF、字符offset与实际行；重复子串ambiguous；改空白unmapped；hash变化被识别；失准表头不污染位置 |
| source/失败 | 缺文件、非法编码、输入路径逃逸、输出目录冲突、无写权限（用明确注入OSError，避免root权限影响）均可观察 |
| diagnostics | 完整九列表格行pass；把同一行步骤/预期拆成两片后fail；丢表头/维度/来源说明分别fail；转义竖线不误计列；部分引用原样保留而不自动展开 |
| 空与异常 | 空文件0片段；非空0片段error；抛异常不能变成空成功；不支持语法显式提示；错误报告字段/CLI退出码一致 |
| 组件接线 | 实际C0/C1/C2均执行，记录包版本/参数；5配置×12文件=60；不伪造片段；报告的source字段能反查原文 |
| 离线保证 | 在测试内部用pytest monkeypatch阻断socket连接，组件运行若访问网络立即失败；这是验证离线契约，不修改conftest/共享基础设施 |
| IO与序列化 | 报告JSON/JSONL可读、Markdown包含实际fail；输入文件hash前后相同；重复运行固定内容及诊断一致；不覆盖前一运行 |

测试夹具新增小型合成Markdown，覆盖重复段落、CRLF（测试动态生成字节）、含标题样式内容的围栏、非法九列表格及空文件；不更改Mock正文或manifest，使既有基线保持。

验收分两层：实验工具必须所有测试通过、无虚假exact位置、输入无修改、无运行网络调用、报告接线完整；候选组件的结构探针允许fail，必须给出处和实际输出，并以失败证据提出下一项适配建议。三候选原始行为没有统一“全绿”业务门槛，也没有据此选定最终框架。

## 9. 影响文件与拟议命令

实施新增8份文件，更新3份指导文档，共11份；不新增服务。文件数量用于一个实验切片的依赖、工具与测试分离，每个源码文件<=500行；超过需先修订Spec，不能堆入大文件。

| 文件 | 职责 |
|---|---|
| requirements-experiment.txt | 三个直接依赖固定版本 |
| requirements-experiment.lock.txt | 安装后实际完整依赖快照 |
| experiments/__init__.py | 使实验CLI可通过python -m执行，仅包标识，不声明业务能力 |
| experiments/markdown_probe.py | 参数、输入校验、三候选调用、位置映射、调度与报告写入 |
| experiments/markdown_checks.py | 独立结构探针及诊断 |
| tests/test_markdown_probe.py | 读取/定位/接线/错误/重复运行测试 |
| tests/test_markdown_checks.py | 结构保留与故障探针测试 |
| tests/fixtures/markdown_edge_cases.md | 小型合成结构夹具 |
| README.md、docs/handoff.md、docs/1.0/learning-roadmap.md | 实际命令、证据状态及真实代码阅读入口 |

以下命令仅为获确认后的执行计划，本轮没有运行：

```sh
.venv/bin/python -m pip install --only-binary=:all: --no-cache-dir -r requirements-experiment.txt
.venv/bin/python -m pip check
.venv/bin/python -m pip freeze --local > requirements-experiment.lock.txt
.venv/bin/python -m pytest -q tests
.venv/bin/python -m experiments.markdown_probe --dataset examples/mock-v1 --sizes 512 1024 --overlap 0 --output-root data/experiments/markdown-probe
.venv/bin/python -m compileall -q experiments tests
git diff --check
```

本仓库尚无应用构建，compileall是语法检查，不能叫应用构建通过。收尾贴实际红灯、测试数/结果、CLI摘要、输出路径、代表性失败片段；pip/测试/CLI失败均明确报告。实验启动后不逐步重复询问已确认范围。

## 10. 回滚、学习及后续边界

新增内容位于experiments/tests/依赖文件和data实验产物，不更新知识库/索引/服务。若方向不合适，可保留原Mock及已记录结果，停止使用该实验入口；删除、回退文件或重建环境须按用户授权范围执行。不得为回滚本切片清空仓库或其他项目。

最脆弱前提：Mock能代表真实文档关键结构。若真实材料存在不同语法/长度分布，则这些实验结论只覆盖Mock，需要补远端结构测试及真实评测。接口/位置能力保持显式未满足状态，避免提前依赖其为产品契约。

本轮已讲解机制；实施后的课堂先读load_sources→split_candidate→map_exact_source→inspect_document，用TC-02及其源行走一遍。用户复述/改探针的结果另记lesson；不因批准Spec就记录理解或独立实现通过。

本Spec获实施确认后，连续完成上述离线切片。智谱Embedding-3、HeiyùCode生成调用、LightRAG对照均作为后续独立Spec/切片处理；当前切片没有模型费用预算或调用授权。

## 11. 实际实施与验证证据

- 三直接依赖按固定版本安装成功，pip check输出`No broken requirements found.`；完整freeze记录83包，未升级其他项目依赖或读取凭证。
- 初始测试正常收集32项，首次执行`32 errors in 0.13s`，原因为实验模块尚不存在。保存[红灯输出](../../data/experiments/markdown-probe-evidence/red.txt)。最小实现后32项通过。
- 自查发现文档ID被误判行号范围，以及维度组合检查未要求表头；各自先复现回归红灯再修源代码，未放宽测试，最终`34 passed in 0.42s`，见[绿灯输出](../../data/experiments/markdown-probe-evidence/green-accepted.txt)。
- CLI实际执行正常，60条文档配置结果、195片段；结构探针404 pass、76 fail。5项fail为同一合成失准手写行号在五配置中重复提醒，其余为组件结构缺口；不是76个独立缺陷或检索业务失败率。
- [最终报告](../../data/experiments/markdown-probe/20261009T145752Z-1c71c3e4/report.md)、[完整片段](../../data/experiments/markdown-probe/20261009T145752Z-1c71c3e4/chunks.jsonl)、[结构结果](../../data/experiments/markdown-probe/20261009T145752Z-1c71c3e4/summary.json)。data被Git忽略，最终报告与前面的检查器修正前结果分开保留，不覆盖输入。
- 测试含socket连接被阻断时的三组件实际运行、独立两次结果一致、输入12文档hash未变、所有映射区间切回原文一致。无模型调用/模型下载/真实材料访问。
- compileall与git diff --check均退出0。compileall只证明语法，没有应用构建可声明。

| 配置 | 片段 | exact / ambiguous / unmapped | 完整行 | 行+表头 | 行+表头+维度 | 行+来源说明 |
|---|---|---|---|---|---|---|
| C0/512 | 33 | 32 / 1 / 0 | 11/12 | 6/12 | 1/12 | 1/12 |
| C0/1024 | 18 | 18 / 0 / 0 | 12/12 | 10/12 | 7/12 | 7/12 |
| C1/512 | 51 | 6 / 0 / 45 | 11/12 | 5/12 | 5/12 | 5/12 |
| C1/1024 | 46 | 1 / 0 / 45 | 12/12 | 10/12 | 10/12 | 10/12 |
| C2/native | 47 | 47 / 0 / 0 | 12/12 | 12/12 | 12/12 | 12/12 |

C2最大节点1339字符，整张维度表可能共处一节点，尚未满足一用例一检索单元或模型token限制。C1安装源码`markdown.py:107,122`使用两个空格加换行聚合段落，实际输出空白变化解释了无法精确匹配；并非正文必然丢失。C0/512的表头内容在第17–18和29–30行重复，因此保留两个候选位置而不猜一个。

教学算例实际调用map_exact_source：001用例TC-02原行194字符，源字符区间[1036,1230)，实际第20行。函数只证明片段位置；半条用例同样能exact定位，完整性由结构探针另查。

当前未提交Git，代码版本用sha256记录：markdown_probe.py=`ff191b167dc6f82981b314b55f63b9d692c4c034f5dee4494b0d4aeea66a08ed`；markdown_checks.py=`bface709d4207dfd93944397e7a43f157db8b9dddb153f6447eb3d7c3e898815`。安装源码LC1.1.3/character.py:110与markdown.py:134，以及LlamaIndex0.14.25/file/markdown.py:48已读取核对。

存在/实质/接线：两个脚本真实实现读取、切分、诊断及序列化；CLI调用run→load_sources/split_candidate/inspect_document→写三报告；运行60配置及195片段证明实验接线。RAG索引/检索、语义效果、真实资料与远端CPU兼容均未验证。用户理解与独立实现证据尚未收集。
