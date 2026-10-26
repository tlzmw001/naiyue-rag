# Spec0017：M2第一切片——Markdown结构与可定位Chunk

状态：用户在参数化与术语澄清后授权实施，本片已实现/接线并验收：目标测试组85通过（含46既有配置测试），新增39，全量747通过。M0追踪及M1 Loader课堂暂挂，不作为开发门槛。本片产出带真实来源的Chunk，旧A2缓存保持，未重建索引。实际证据见第7节。

## 1. 当前与参考调用链

当前产品链止于MarkdownLoader→Document，metadata含库ID/相对路径/字节hash/行起点。旧实验evidence_units.build_units使用LlamaIndex MarkdownNodeParser章节节点→全局字符串定位→完整用例适配→旧unit；限定九列表头、TC编号和围栏形式，依赖manifest的role/层级。该逻辑有实验/基线消费者，不能直接移植为通用能力或删除。

参考URL：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER；本地main固定commit f658c5a4011c8b826707a65a3b11ce9301b0626f，只读核源码与配置，未刷新远程/运行参考服务或复制源码。

真实链：IngestionPipeline→DocumentChunker→SplitterFactory→RecursiveSplitter→LangChain RecursiveCharacterTextSplitter；片段字符串转Chunk并继承metadata/生成ID，随后ChunkRefiner→MetadataEnricher→编码。参考Chunker创建Chunk时未提供start/end/source_ref位置字段；Refiner直接改变chunk.text，规则含去HTML标签/压缩空白；Enricher规则提取title/summary/tags，配置可使用LLM并有fallback。

config/settings.yaml显式chunk_size=1000、chunk_overlap=200、splitter=recursive；refiner/enricher.use_llm=true。这些是配置事实，不当质量优选或全部服务验证。

本机已有markdown-it-py4.2.0、langchain-text-splitters1.1.3、llama-index-core0.14.25。读取已装TextSplitter源码：create_documents(add_start_index)使用find启发式定位，_join_docs可能strip；不能只相信该索引而不核原文切片。

本轮独立合成探针：按参考1000/200及相同separators切1060字符用例行，4个片段中无完整行；MarkdownIt(commonmark)+table的heading/table/tr_open提供行map，CRLF示例表格行可定位。仅机制探针，不是组件全面选型/真实文档或检索质量通过。

## 2. M2模块地图与首片范围

M2分三个可验收切片：

1. 本Spec：结构解析、正文与完整用例/代码/表格边界、标题上下文、真实位置→公共Chunk及诊断。
2. 规则ChunkRefiner/MetadataEnricher：清洗产物与原始证据分开、角色/层级/标题/来源元数据有出处，具体转换另写Spec，不复制会破坏br/源码的规则。
3. 文档级显式引用/需求用例配对与固定结构评测：只记录原文声明的关系，不推断业务依赖/现行有效性；关系导航由M5/M7消费。

模型Refiner/摘要/标签增强继续归M9独立对照；框架错误不静默改用另一切分路线。首片不建空Factory/Refiner/Enricher、用LLM、扩图谱、改索引、接Agent/权限或修改真实配置。

推荐首片：markdown-it-py识别Markdown结构及行区间→用M1原始line_starts映射回原文→普通正文复用参考Recursive及实际配置的长度/重叠→完整用例行与代码/一般表格保护→M0 Chunk/SourceSpan。不自行实现递归切分算法，不因结构相似就重用整个旧实验流程。参考1000/200仅作为可复现实验起点，不固定为产品默认或最佳值；300等重叠值同样可参与实验。

## 3. 输入输出与接口

配置接线沿参考：拟DocumentChunker(settings)，从实际Settings.ingestion读取chunk_size/chunk_overlap（字符，不是token），不在Python构造或缺省分支补1000/200等数值。split_document(document)返回(chunks, diagnostics)，chunks为list[Chunk]；空/纯空白文档返回[]及信息诊断，非空内容不能静默变零片段。不新增或修改Document/Chunk公开签名；本类尚未创建，此处修订的是待实施接口。

在现有统一Settings中新增可选IngestionSettings分组，仅包含chunk_size/chunk_overlap，允许从YAML提供任意合法值。旧快照配置未提供该组时ingestion=None，继续兼容；创建Chunker时缺该组明确失败，无隐式参数回退。若提供该组，两字段均必填、未知字段拒绝，chunk_size为非bool正整数，chunk_overlap为非bool非负整数且小于chunk_size。原to_snapshot_config仍仅输出旧12字段，避免把摄取参数错传给查询资源。实施只改schema/加载代码与测试临时YAML，不改真实运行配置。

内部结构扫描使用MarkdownIt的token.map行范围（0基、右开）和M1实际行起点获得原文字符区间。解析器内部规范化视图不覆盖Document.text；标题与其他上下文引用真实原文及SourceSpan。只有标题的文档仍保留可定位标题片段。

Chunk.text必须逐字符等于Document.text[start_offset:end_offset]；source_ref=Document.id，source_path/source_sha256/knowledge_base_id继承。metadata含body_span、kind、heading_path、contexts、chunk_index、component_metadata及诊断。不把全文line_starts重复复制到每片段。ID沿已用原文身份机制：unit-加SHA256([document_id,source_sha256,kind,start,end]规范JSON)，原文版本或区间变化换ID，不改变既有unit资产。

component_metadata记录实际parser/splitter版本、实际chunk_size/chunk_overlap、结构保护策略及规范化配置指纹；参数变化须能从产物区分。重复文本不靠全局find猜所属章节。正文片段在其原始结构区间内定位，核范围、原文相等与顺序；组件返回不可定位片段明确失败，不补虚假offset。旧C2/A2结果保留为历史对照；新参数不得以旧向量或不同候选池冒充同条件实验。

## 4. 主要分支与业务适配

| 内容/情况 | 拟处理 |
|---|---|
| L0/L1/L2普通正文 | 标题上下文保留；普通内容在结构区域内按Recursive参数细分 |
| 用例文档 | 依据用户命名/标题规则识别测试用例材料，记录识别依据；历史/当前有效性不由名称判断 |
| 合法用例表格 | 一条物理源码行一个完整Chunk，附维度标题/列名/来源说明；br、转义管道、公式/步骤/预期原样保留 |
| 用例列数/编号 | 不限定九列或TC前缀；识别用例名称/标题、前提/前置条件、测试步骤、预期结果等既知列名；无业务编号保留null，不生成假TC |
| 一般表格 | 保留表格结构为保护块，不把每行都假称测试用例 |
| 围栏/代码 | 使用解析器识别，内部#不当章节；原代码保护为完整块 |
| 原子块超过chunk_size | 仍保留完整块，标记oversize诊断，不截断；它能否编码由M3模型实际输入上限判断 |
| 用例表头无法识别 | 保留为完整一般表格并给未分类诊断，不拆成半用例或猜列义 |
| 行列不一致/原文不匹配/组件失败 | 明确ChunkingError，不返回部分成功片段或默换路线 |
| 空文档/空白 | 正常零片段，信息诊断；不创建非空SourceSpan或填示例数据 |

标题/用例字段识别只做结构标签，列文本与原行仍为原始证据。表头手写行号不作定位依据；仅能检测明确越界等机械问题，不宣称合法行号就语义相关。完整代码块和表格超过目标长度是已知边界，不把它们隐藏或无限递归拆小。

原文hash/line_starts与Document.text不一致时在切分前拒绝，防止可变Document的源绑定被破坏。输入参数拒绝bool/非法尺寸，overlap要求0≤overlap<chunk_size。错误日志只固定stage=chunking/code，不含原文、路径、组件原异常；无网络、写文件或自动重试。

## 5. 影响文件与验收

拟10源码/测试文件（参数配置接线增加2项，超过8项但仍同一切片、无新增服务）：ingestion/markdown_structure.py、ingestion/document_chunker.py、ingestion/__init__.py、core/errors.py、包__init__.py、tests/test_markdown_structure.py、tests/test_document_chunker.py、tests/test_chunking_wiring.py，加core/settings.py及tests/test_settings.py。后者只新增配置组的测试，保留原断言/helpers；不通过修改旧测试来容忍不兼容行为。核心新模块不导入experiments，无依赖升级、Mock/锁/缓存修改，单文件≤500行。

先预期红灯→最小实现，结构/正常/异常均有独立确定性测试。覆盖L0/L1/L2、标题跳级/重复正文、BOM/三类换行、代码内标题、四列/九列/额外列、无编号与不同编号、br/转义管道、长完整用例、一般表格、缺列/坏行、空与过长、组件故障与原文绑定。所有body/context按真实SourceSpan回读相等，序列化与source_ref一致；无新文档角色/历史真伪臆测。

配置临时YAML→load_settings→Settings.ingestion→DocumentChunker→真实Splitter参数必须接线；改变size/overlap的确定性长正文样本须观察到边界/重叠变化，不能只断言对象字段赋值。缺组/非法值在切分前失败，旧快照字段映射与原配置测试保持。M1 Loader→结构扫描→成熟Splitter→公共Chunk/SourceSpan真实消费。固定结构样本保留完整行与上下文；原子块在不同长度设置下仍保持完整，oversize诊断依据实际chunk_size。普通片段边界允许因新策略变化，不能要求新结果等同旧章节C2；已有A2测试/索引保持。新结构标签不是人工业务金标准，不发模型。

计划命令尚未执行：

```sh
.venv/bin/python -m pytest -q tests/test_markdown_structure.py tests/test_document_chunker.py tests/test_chunking_wiring.py tests/test_settings.py
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q naiyue_rag experiments tests
.venv/bin/python -m pip check
git diff --check
```

L1检查10文件；L2真实结构/切分/源绑定/诊断及参数加载；L3由实际配置与Loader文档经新主链得到可定位Chunk且JSON往返，参数变化真正到达组件。构建不适用，compileall仅语法。无索引迁移或删除，旧入口继续运行；M3实际编码时必须使用新片段策略身份，不能挪旧向量当新片段。

### 参数实验与结论边界

实现后首轮仅做固定合成结构样本的可重复结构对照：固定parser/原子保护/语料，先固定overlap=200比较size=500/1000/1500，再固定size=1000比较overlap=0/100/200/300。这些只是第一组候选，不写成内置枚举或默认最优；实验参数与每份结果一起记录。全部组合仍须满足合法参数约束，不能同时改变模型、召回或预算来解释切分影响。

结构阶段评价单位明确：每个原文/上下文span的逐字符回读一致性；标注合成用例行的完整保留数/标注行总数；固定正文的非空白字符是否被正文及上下文区间覆盖；片段数量、正文及渲染上下文长度、原子块超长数、区间重复覆盖率与诊断。标签是合成结构标签，不能当用户人工业务金标准。

这些对照只能筛掉结构破坏/无法定位的参数组合，不能选出最佳检索参数。M3–M5用相同固定问题/标签、真实重新编码索引、相同召回与上下文预算，再比较证据召回/排序/最终覆盖、延迟及实际可观测用量。真实资料在另一机器，最终值还需该资料验证，不由参考配置或单个探针下结论。

## 6. 待确认与唯一下一步

推荐沿上述“成熟结构解析＋参考Recursive正文＋原子用例/代码/表格保护”组合。原子块超长保持完整并显式诊断，LLM清洗不在首片；参考参数不是最优结论。本机探针尚不能证明真实远端结构全部适配；实现通过后仍需固定结构集和远端真实验证。

用户已认可思想并要求参数化，后续按本修订方案实施/验证；不再把参考数值当最佳或要求重新确认总体路线。暂停的课堂不强制补齐，不提前生成M2后两片空模块。

## 7. 实际实施与验收

按10源码/测试文件范围完成Settings可选IngestionSettings→DocumentChunker(settings)→MarkdownIt结构/原文区间→真实Recursive→公共Chunk/SourceSpan。原配置组必填规则/快照12字段不变；旧配置ingestion=None，创建Chunker必须显式配置。版本、实际参数、保护策略及config_sha256随片段记录。结构模块201行、chunker74、settings197，新测试44/208/41；所有源码/测试≤500，无新依赖/模型/真实配置修改。

TDD实际过程：初次新测试有一处漏括号，修正测试语法后才确认3收集错误为预期缺结构模块/Chunker。最小实现78通过，另3参数化用例失败源于新超长测试输入正好40字符且配置40；源代码“超过才超长”正确，明确说明后只将新测试配置改为30，全部原断言保留，81通过。未以改代码虚报超长或放宽断言掩盖问题。随后新增损坏表格与空表格回归红灯→分别修结构分支→83；补恰好等于上限不超长及重复业务编号不合并→85目标组。既有tests/test_settings.py全部原内容作为前缀保持，只追加11配置测试，无旧断言/helper/skip修改。

实际最终命令与结果：

```sh
.venv/bin/python -m pytest -q tests/test_markdown_structure.py tests/test_document_chunker.py tests/test_chunking_wiring.py tests/test_settings.py
# 85 passed in 0.27s（46既有配置+39新增）
.venv/bin/python -m pytest -q tests
# 747 passed in 57.05s
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0，无输出，语法检查；打包构建不适用
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0，无输出
```

L1：10文件存在。L2：真实组件结构map、同区域递归定位回读、完整原子块、配置加载/校验/指纹、诊断及安全异常，非占位。L3：临时YAML经load_settings把73/11实传给真实LC Splitter，M1目录加载→结构→Chunk→JSON往返；现有12份结构Mock全部12条用例行原样保留。四列/七列/九列、无编号、不限定TC、重复业务编号分别独立Chunk，source_ref/正文/context回读一致。

规则细节：用例表格保留原表头和分隔行为上下文；空表格保留一般表格，不生成用例。用例材料中不被解析为合法表格/代码的表格形状行明确invalid_table，不悄然走正文切分；未知合法表头保留整体一般表格并诊断。无标题/特殊历史状态臆造；名称/标题仅结构分类依据，不证明当前业务有效性。

参数实验脚本保存为忽略目录中的data/research/spec0017-evidence/parameter_probe.py（验收重放材料，不是另一个产品实现），以原生产入口执行。命令：

```sh
PYTHONPATH=. .venv/bin/python data/research/spec0017-evidence/parameter_probe.py
```

实际15文档=12既有结构Mock+3临时合成文档；标签为脚本从明确合成用例行构造，13条，并非人工业务金标准。6组唯一参数全部13/13完整、非空白字符缺失0、正文与上下文span回读一致：

| size / overlap | chunks | 已核span | 原子块超长数 | 正文区间重复覆盖比例 |
|---|---:|---:|---:|---:|
| 500 / 200 | 101 | 334 | 3 | 0.175600 |
| 1000 / 200 | 88 | 295 | 2 | 0.069379 |
| 1500 / 200 | 85 | 286 | 1 | 0.040860 |
| 1000 / 0 | 87 | 292 | 2 | 0.000000 |
| 1000 / 100 | 87 | 292 | 2 | 0.030961 |
| 1000 / 300 | 89 | 298 | 2 | 0.113320 |

比例=(各正文区间长度之和−每文档正文区间并集长度之和)/各正文区间长度之和；上下文重复不计此分母。覆盖检查统计正文和上下文区间并集是否覆盖原文全部非空白字符；逐span检查包含实际空白原文。上下文长度仅各context文本之和，不是最终ResponseBuilder/模型提示词长度。参数产物parameter-inputs.json/parameter-results.json带输入hash/实际config指纹，retrieval_quality=not_evaluated、service_usage=null；未选最佳参数。

保护记录data/research/spec0017-evidence：154既有代码/测试/Mock/锁/基线hash、135已装版本保持；5允许修改旧文件另存前状态，source-checks记录10文件hash/行数，新模块实验导入0。无旧索引迁移、原文改写、真实.env/YAML/其他仓库/服务/提交/push变化。

限制：当前仅结构与位置，可包含短标题片段及完整超长块；原子块能否Embedding仍须M3按真实模型限制处理。名称/标题识别为启发式，真实私有材料/跨机器行为未验证；普通片段不同于旧C2，新向量未建立，未宣称检索收益。规则清洗、丰富元数据、文档级引用/配对为M2后续片。新Chunk.to_dict有效；旧to_legacy_unit仅用于完整旧unit元数据的桥接，新首片不假称已有全部旧20字段或进入旧索引。

当前暂停课未登记掌握，新代码未本人调试/复写。唯一下一步：准备M2第二切片规则Refiner/MetadataEnricher，先明确派生文本与原文合同，不要求补课再开发。
