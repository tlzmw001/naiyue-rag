# Spec0032：M4.5 基于活动版本的只读文档列表与详情

日期：2026-10-15。状态：**用户已接受，M4.5已实现并完成本地验收**。沿[Spec0031](0031-m4-same-version-activation.md)已验收的版本目录，扩展现有DocumentManager。本片为本机库接口，不新增服务或访问权限模块。

## 1. 价值、当前链路和例子

M4.1–M4.4已经能保存资料包、构建两路索引、激活和重开完整版本。当前DocumentManager只有activate/open_active；没有统一入口回答“这个活动版本有哪些文档、某份文档对应哪些片段”。此片提供后续管理适配所需的可序列化结果，也让更新/显式移除的下一阶段有精确文档身份依据。

示意：活动G1包含L1_Module、历史L2_A及其用例。列表给出文档ID、相对路径、原文版本、字节数和片段数；详情返回其中一份文档的摘要与片段ID。期间激活G2、更新同一L1时，文档逻辑ID不变，但原文hash和片段可能变化。列表和详情必须携带各自所读版本，调用方可用列表revision约束下一次详情，避免把G1列表与G2详情误当一套。

```text
已有摄取：MarkdownLoader → M2文档/片段/关系 → M3成对编码 → BundleStore
已有激活：BundleStore.load + Chroma.audit + BM25.audit → SQLite active
已有open_active：读active → 三类完整审计 → ActiveVersion

本片接线：list_documents / get_document_detail
    → 校验请求
    → IndexCatalog.read（一次选定已提交ActiveVersion，连接随即关闭）
    → 检查可选expected_revision
    → BundleStore.load（同bundle_id，完整来源核验）
    → 对照活动描述的资料包身份/数量/指纹
    → 按Document.id和Chunk.source_ref投影摘要/片段ID
    → 结果DTO + 有界JSON往返
```

只读管理的结果表达已登记快照中的文档事实；不表达Chroma/BM25现在是否健康。响应里的ActiveVersion是版本绑定描述，不是索引健康凭证；调用方不能据此跳过查询入口必要的完整校验。完整两路校验继续走原open_active，行为不变。管理接口不先调用open_active再捕获错误降级；它从入口就不执行两路审计。

## 2. 参考项目的源码事实与差异

来源：[MODULAR-RAG-MCP-SERVER](https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER)，本地`/Users/zmw/MODULAR-RAG-MCP-SERVER`只读，main/`f658c5a4011c8b826707a65a3b11ce9301b0626f`；2026-10-15工作区干净，本轮未查询远端或执行参考项目代码。文件指纹与调用入口在`data/research/spec0032-evidence/source-review.json`。pyproject声明MIT、无独立LICENSE；本片独立实现，不复制第三方代码。

真实源码链：

- Dashboard的`data_browser.py:80`和`ingestion_manager.py:108`调用DataService.list_documents。
- `data_service.py:50–75`装配四存储与DocumentManager；`:99–113`将list结果用asdict转换给UI。
- `document_manager.py:98–141`调用FileIntegrity.list_processed，再逐文档查询Chroma片段数和图片数；`file_integrity.py:399–435`只列status=success的历史，默认按processed_at排序。
- `document_manager.py:143–187`的get_document_detail扫描历史匹配source_hash，再查chunk_ids/image_ids；DataService:115–125暴露此方法。本轮静态搜索中，页面没有调用该详情方法，单元测试有消费者。
- 页面展示片段正文实际走`data_browser.py:113`→DataService.get_chunks:127–153→Chroma.collection.get。不能把这个正文读取行为算到DocumentManager.get_document_detail里。
- `_count_chunks/_get_chunk_ids/_count_images/_get_image_ids:301–334`有异常返回0/[]的分支；本片不能复用这种故障语义。

README/DEV_SPEC是自述：DEV_SPEC:289–290描述列表及包含内容/metadata/图片的详情；实际上述详情DTO只增加片段/图片ID。参考unit tests:218–275用替身验证列表与ID结果，不证明真实四存储一致性；本轮只读这些测试，没有运行它们。

| 方面 | 参考事实 | 本项目推荐及理由 |
|---|---|---|
| 入口职责 | DocumentManager list/detail，DataService转换给上层 | 沿用现有DocumentManager扩展，不另建管理服务或框架 |
| 文档集合 | 成功摄取历史，可按collection筛 | 当前StorageSettings已绑定一个KB，只读该KB当前active资料包；不把其他候选或旧索引目录混入列表 |
| 身份 | 详情用source_hash匹配 | 用已有稳定document_id；source_sha256单独表示修订。同字节不同路径不合并 |
| 片段事实 | 按doc_hash到Chroma计数/取ID | 来源于完整核验的规范资料包，以Chunk.source_ref精确分组；不猜ID前缀归属 |
| 完整性与后端状态 | 辅助统计故障可被表示为空 | 目录/资料包失败必须报错；两路健康审计不在管理读取中执行，也不新增healthy字段 |
| 字段 | 图片计数、处理时间来自相应存储 | 当前Markdown主线不增加图片字段；没有已存处理时间就不生成或从文件mtime猜时间 |
| 内容 | 详情仅ID，正文走另一个入口 | 本片详情返回摘要和ID；全文/Chunk正文、关系导航与精读工具按后续场景切片 |

核心取舍：推荐元目录+资料包的只读路径，可以在不初始化检索SDK的前提下查看快照。另一条最直接的办法是每次调用open_active再投影，会要求两路健康才能查看文档，还会执行额外原生IO；若用户明确要求“文档可见就必须证明两路可用”，再采用该合同，不能实现后静默更换。

## 3. 既有资产与本片范围

实际源字段：MarkdownLoader:80–83保存Document.id及metadata中的knowledge_base_id、source_path、source_sha256、size_bytes、line_starts。标题、L0/L1/L2、文档角色不属于这组必有文档字段，本片不补猜分类。

实际身份：document_id是`doc-`+SHA256([KB,规范相对路径])；M2当前片段ID仍为`unit-`+64位hash，不得在管理层改名。Chunk.source_ref指向Document.id；start_offset/end_offset和body_span绑定原文。BundleStore.load重做来源、M2结果、关系及编码绑定校验，允许源目录后来变化而旧快照仍然可读。

复用IndexCatalog.read、BundleStore.load、ActiveVersion、StorageSettings及StorageError。只扩展列表/详情及三个小DTO；不增加SQLite表、源文件扫描、索引写入、列表缓存、回调、读会话管理或旧接口包装。open_active/activate签名和语义保持。

不包含文档更新/删除/清理、摄取前跳过、增量Embedding、检索范围评分、全文精读、关系扩展、collection统计、UI/HTTP/MCP、Agent或权限控制。不会把只读浏览当查询正确、引用有效或完整M4生产验收。

## 4. 新接口与结果合同

已有DocumentManager构造签名保持；新增：

- `list_documents(*, expected_revision=None) -> DocumentList`。
- `get_document_detail(document_id, *, expected_revision=None) -> DocumentDetail`。

expected_revision=None表示使用本次选定的活动版本；显式值必须为非bool整数，范围0..MAX_REVISION，0代表未激活。合法document_id必须匹配`doc-[0-9a-f]{64}`；只收逻辑ID，不收路径、source_hash、bundle_id或任意ActiveVersion作为选择器。请求先校验，非法请求不读取目录或初始化存储。

从storage公开导出三个结果类型，均严格字段/类型校验，防御性复制、repr不展示源路径、to_dict/from_dict可JSON往返：

| DTO | 精确字段 |
|---|---|
| DocumentInfo | document_id、source_path、source_sha256、size_bytes、chunk_count |
| DocumentList | active: ActiveVersion或None；documents: list[DocumentInfo] |
| DocumentDetail | active: ActiveVersion或None；document: DocumentInfo或None；chunk_ids: list[str] |

字段来源：

- document_id=Document.id；source_path/source_sha256/size_bytes=已核原文metadata对应字段，字节数不能用len(text)替代。
- chunk_count=当前资料包内source_ref等于该Document.id的Chunk数量，不能从文件名/目录层级/旧回执或ID字符串前缀猜。
- 列表按(source_path,document_id)升序，使用现有规范POSIX相对路径及Python字符串顺序，不依赖原文读取/编码批次顺序或本机locale。
- 详情chunk_ids按该文档Chunk的(start_offset,end_offset,id)升序；保留已有unit-ID，不改写、不重切分。
- active始终复用本次所选目录绑定；有active时，source信息必须与该bundle绑定。返回对象不持有活数据库连接、SDK对象或对内部对象的可变引用。

DTO约束：source_path沿现有资料包相对Markdown路径合同，source_sha256为64位小写hash，size_bytes/chunk_count为非bool非负整数。DocumentList无重复ID/路径，条目数和片段数之和分别等于active.version.document_count/chunk_count；按已有KB+路径公式核对每个document_id。DocumentDetail.document存在时，chunk_ids唯一、语法合法且长度等于chunk_count，文档身份属于active的KB。未知/缺字段、bool冒充整数、重复ID、计数或状态矛盾均不能序列化成正常结果。

空态精确区分：

| 状态 | 列表 | 详情 |
|---|---|---|
| 未激活 | active=None，documents=[] | active=None，document=None，chunk_ids=[] |
| 合法活动空库 | active有值，documents=[] | active有值，document=None，chunk_ids=[] |
| 活动库中找不到合法ID | 正常列表 | active有值，document=None，chunk_ids=[] |
| 存在空白Markdown | 真实条目，size_bytes/片段数可为0 | document有值，chunk_ids可为空 |
| 目录/资料包坏了 | 抛安全错误 | 抛安全错误，不能伪装成未找到 |

不返回原文、向量、词项、完整Chunk、任意metadata、图片占位数、假时间、假标题或假分类。缺失的文档由None表达，不生成一个全空的DocumentInfo。

## 5. 一次读取的分支与跨调用一致性

1. 校验可选revision和文档ID，复用当前配置检查。
2. IndexCatalog.read仅调用一次，获得完整已提交ActiveVersion或None；无活动revision按0处理。坏目录照常抛固定错误。
3. 若传入expected_revision且不等于本次revision，抛既有catalog_revision_conflict；不再加载资料包。
4. 无active直接返回对应空态，不创建目录、资料包或SQLite文件。
5. BundleStore.load(active.version.bundle_id)一次；核对KB、文档/片段数量、source_fingerprint、model_space_id、representation_id、tokenizer_id、dimensions，与活动描述不符报catalog_identity_mismatch。
6. 使用这一个bundle投影；任何Chunk.source_ref无法对应文档、出现重复/矛盾或输出超过资源限额，整次失败，不返回部分列表。
7. 返回有界DTO；即使第2步之后另一个调用激活G2，本次仍返回G1的数据和G1的active，不重新读取latest。

列表→详情的调用约定：列表返回revision=1，调用方将1作为详情expected_revision。若详情选定版本时已是revision=2，明确冲突，由调用方刷新列表；不自动在历史版本中搜索同名文档。未传guard时详情可读取新的当前版本，但响应携带其真实revision，不能贴上旧列表的版本标签。

这只是乐观读取约束，不持锁直到用户点开详情，也不新增跨调用状态。当前新接口只浏览当前active；已取得旧ActiveVersion的低层资料包读取能力不变，不把历史浏览扩成本片新API。

可在DocumentManager增加一个供两个新方法使用的私有读取边界，统一“选一次版本、revision门禁、同包校验”。理由是两条管理路径共享同一个快照合同；不让它承接activate或open_active的完整控制/两路执行链。DTO及纯投影放同一document_views模块，保持IO与投影职责清楚，不建通用注册层。

## 6. 错误、只读与资源约束

- 新增document_invalid_request、document_integrity_failed、document_limit_exceeded三个固定StorageError码；非法API/DTO输入用第一个，内部投影不一致用第二个，输出超限用第三个。
- 目录错误、catalog_revision_conflict/catalog_identity_mismatch及资料包错误沿既有安全码传播，不输出底层原异常、原文、源路径或凭证。
- 不调用Chroma/BM25的audit/build/get、不调用open_active，不读取原始Markdown目录、不做Dense/Sparse编码/模型请求、不解析.env。坏索引本身不会阻止查看已核的文档快照；这不是吞掉索引错误，两路检查没有被执行。需要检查两路时明确调用原open_active，其失败合同保持。
- 不增加运行参数，沿StorageSettings的max_documents/max_chunks/max_file_bytes/max_bundle_bytes/max_manifest_bytes。输入加载仍受已有资料包限额；整个返回的规范UTF-8 JSON（无末尾LF）受max_bundle_bytes约束，利用已有有界JSON工具，超限不截断。
- 首片完整返回一个KB的有界列表，不加入分页/模糊搜索或偷偷限前100条。数量超过配置上限明确失败。
- 必要读取/SQLite关闭失败仍显式可观察；目录缺失返回空态不创建，正常读取不补写缓存、修复索引、改指针、增revision或写追踪文件。

最脆弱前提是已保存快照可被完整读取。BundleStore.load目前会读完整编码载荷并重做M2校验，列表并非只读几行manifest；这会增加IO/CPU/内存。首片复用现有严格校验，不承诺比参考逐文档计数更快，也不为猜测的规模问题新增轻量目录副本。若后续实测成为瓶颈，由独立Spec设计可信摘要/缓存并保持版本绑定，不能为提速放松现有检查。

## 7. 影响文件与TDD计划

预计7个源码/测试文件，加必要阶段文档后总影响超过8个文件；核心实现仍限定下表。无新依赖、SDK版本变更、配置/环境文件修改、服务或真实模型账户需求：

| 文件 | 改动 |
|---|---|
| naiyue_rag/storage/document_views.py（新） | 三DTO、精确字段/状态/身份及JSON往返、同包纯投影；不执行IO |
| naiyue_rag/storage/document_manager.py | 新增两个公共方法与管理读取边界，已有两方法不变 |
| naiyue_rag/storage/__init__.py | 导出三个结果类型 |
| naiyue_rag/core/errors.py | 追加三个闭集码 |
| tests/test_document_views.py（新） | DTO严格性/深复制/状态/排序/计数/来源版本 |
| tests/test_document_management.py（新） | 真实资料包/元目录读取、revision/错误/限额/无副作用 |
| tests/test_document_management_wiring.py（新） | 真实组件构建激活→新进程仅管理读取→结果消费与字节/mtime不变 |

先搜已有实现：本轮静态搜索正式包没有DocumentInfo/DocumentList/DocumentDetail或list/detail方法；扩展现有DocumentManager。新模块因DTO/纯投影职责独立而新增；不搬迁/重写已有激活代码，不修改旧测试基础设施。源码均≤500行。正式包不导入experiments。

先确认预期红灯，再最小实现，覆盖：

1. 正常DTO往返、未知/缺字段、非法doc/hash/path、bool/负计数、重复文档/片段、None状态不一致、跨KB逻辑ID、深复制与安全repr。
2. 列表排序、不同原文大小、空白文档、合法零片段库、同字节不同路径的两个文档、当前Chunk.source_ref计数与unit-ID详情顺序；无猜标题/角色/处理时间。
3. 未激活与未知合法ID分别返回第4节空态；非法ID/expected_revision在读目录前失败，目录不被创建；超界revision拒绝。
4. 目录坏、schema错误、SQLite读取/关闭失败、包缺失/hash错、活动描述与包数量/来源/三身份/维度不符均抛安全错误，不返回[]/None掩盖故障。
5. 两个管理方法都只读一次catalog；选定G1后注入G2激活，本次仍为G1；列表G1→新详情传expected=1而当前2时冲突，且不加载bundle；未加guard的详情明确返回2。
6. 同路径L1修订保留document_id、hash/片段更新，历史L2_A及旧用例仍在G2；未激活候选和旧版本不混入列表。改变/移走测试源文件后仍从保存快照读，禁用MarkdownLoader现场加载。
7. 故意损坏两路marker或禁止SDK初始化后，文档快照仍可读；单独调用open_active仍失败。证明职责不同，不能用try/except吞掉已执行的两路失败。
8. 输出JSON和配置数量限额有明确红灯，无部分列表/截断。新DTO/序列化字段与管理调用同步检查，日志不出现合成敏感正文/路径/Key/异常。
9. 真实M1/M2/M3+Embedding SDK MockTransport、真Sparse/Chroma/BM25完成激活作为准备；另一独立进程管理读取正常/零/全空/混合场景，返回ID与保存资料对应，详情ID可按已有底层入口回取原完整用例。
10. 管理读取进程阻断网络、编码、原始源文件访问、.env读取和两路SDK执行；确认没有导入原生chromadb，目录/资料包/索引所有已有文件字节和mtime、active revision不变，无新文件。

只使用测试临时目录和公开/合成材料，不修改真实.env或现有索引。复用已有M4.4真实构建测试入口作准备，不复制整套测试框架。管理读取的新进程与准备/回取验证进程分开，避免用已加载SDK掩盖隐式依赖。

拟验证命令：新增三个测试文件定向运行，随后M4.4三测试文件回归和tests全量；再compileall/pip check/git diff --check与新文件链接/白空检查。独立应用构建不适用；实际命令/输出和红灯记录在实施后填写，不能预写通过数。

## 8. 完成与回退边界

L1：DTO/两个方法/导出/安全码存在。L2：实际目录只读/同包来源检查与投影，无占位、无隐式SDK。L3：正式新方法在独立进程消费已激活的真实三件套，结果携带准确版本，片段ID能对应完整来源；旧activate/open_active消费者保持。

回退只需停止调用新管理入口，旧激活/存储格式未变，不需要数据迁移或重建。没有待删除的旧管理实现；旧实验消费者仍保留。首次实现若需要扩大到schema、配置、公开旧签名或新服务，先修订Spec讨论。

本片不验证检索/问答质量，不给出原生索引健康、真实资料规模、性能或生产并发承诺。完整课堂继续暂挂；只记录本轮职责/选择已说明，不记录本人独立掌握。

## 9. 设计轮验证与当时下一步（历史）

本轮只读参考及当前源码，并重跑已有M4.4测试；结果与来源指纹在`data/research/spec0032-evidence/`。上一轮1532全量是历史验收，本轮不将它当M4.5已通过。新方法/新DTO/新测试尚未存在；本轮没有生产代码、依赖、配置、真实.env、既有索引或其他仓库修改，无删除/提交/push。

实际命令：`.venv/bin/python -m pytest -q tests/test_index_versions.py tests/test_document_manager.py tests/test_document_manager_wiring.py --tb=short` → **89 passed in19.10s**，仅证明已有M4.4回归。compileall exit0，pip check输出No broken requirements found.，git diff --check exit0；本轮修改文档另检查链接/尾部空白。与上一轮快照核对的164项源码/测试/配置资产相同、137项安装包名称/版本相同。独立应用构建不适用，不将文档检查当功能测试。

唯一下一步：确认本Spec推荐的“管理读取只校验元目录+规范资料包，结果携带活动版本、可选revision约束；两路健康继续open_active”的合同后，按第7节TDD实现M4.5。


## 10. M4.5实施与验收（2026-10-15）

用户明确接受本Spec后，按第7节完成7个源码/测试文件。DocumentManager新增两个方法，_document_bundle仅共用管理快照边界，_document_response用既有规范JSON限额；原构造/activate/open_active没有改动。document_views为三严格DTO与纯投影，独立于SDK/Agent/UI；错误码/导出同步，无新存储格式或配置。

### 10.1 红灯与测试编写修正

先运行新增DTO/管理测试，缺少DocumentInfo等正式导出导致ImportError，退出2，记录red-formal.txt；实现后首组79 passed in5.97s。补上同字节不同路径与真实接线后，最终新增结果见下表。

原生接线首轮4失败：新测试把“禁止执行分词/初始化检索SDK”误写成“jieba也必须未导入”。独立最小探针证实旧正式包导入本来就会导入jieba；Spec第6节只禁止分词执行，第7节只明确要求chromadb未导入。将该新测试校正为禁止jieba.Tokenizer.initialize，继续阻断SparseTokenizer.tokenize并保留Chroma/BM25/OpenAI未导入断言；未修改分词生产模块，也未放宽业务断言。下一轮3失败/1通过，原因是新消费测试错误访问Chunk.body_span；核对真实Chunk合同后改为metadata['body_span']['source_sha256']，保留同一来源hash相等断言。两个问题均为新测试误设，非生产修复；原始输出保留wiring-first.txt/wiring-second.txt，不计为业务失败或伪造成功。

### 10.2 实际验证

| 实际命令 | 本轮输出 |
|---|---|
| `.venv/bin/python -m pytest -q tests/test_document_views.py tests/test_document_management.py tests/test_document_management_wiring.py --tb=short` | **84 passed in 14.86s** |
| `.venv/bin/python -m pytest -q tests/test_index_versions.py tests/test_document_manager.py tests/test_document_manager_wiring.py --tb=short` | **89 passed in 20.31s** |
| `.venv/bin/python -m pytest -q tests --tb=short` | **1616 passed in 148.35s** |

输出分别在data/research/spec0032-evidence/new-tests.txt、m44-regression.txt、all-tests.txt。compileall、pip check、diff/新文件白空和文档链接的最终结果见同目录implementation-verification.json。项目无独立应用打包构建入口，该项不适用；compileall不冒充安装包构建。没有真实模型POST或业务质量评测。

### 10.3 三级接线及边界证据

- L1存在：storage公开导出DocumentInfo/DocumentList/DocumentDetail，DocumentManager两个公共方法和3个闭集StorageError码存在。
- L2实质：请求前置校验、一次目录/资料包读取、revision门禁、KB/数量/指纹/三身份/维度绑定、按source_ref分组/位置排序、严格DTO与有界输出均有确定性测试。未激活/活动空/空白/未知ID与损坏分开；真实目录/包错误不伪装空值。无占位实现。
- L3接线：test_native_activation_metadata_read_and_id_consumer复用原真实M1/M2/M3+SDK MockTransport/真Sparse/Chroma/BM25构建激活；独立进程调用正式管理入口，第三进程消费返回的active/文档ID/片段ID，经Chroma.get_by_ids核对原完整用例及来源hash。正常、零片段、全空词项、混合四分支通过。
- 管理进程实际阻断socket连接、源目录/.env打开、编码/分词初始化、两路audit/build/get和open_active；确认chromadb/bm25s/openai未导入。准备后移走现场源目录，仍从已保存快照读取。读取前后存储全文件集合、字节和mtime_ns、active外部对照文件均不变；详情回取在另一进程验证，不把Chroma维护写算入管理只读承诺。
- test_activation_during_read_does_not_mix_versions在两入口选G1后实际激活修订G2，本次仍为G1，下一次未guard列表读取G2；guard冲突先于bundle加载。同路径L1身份稳定/hash变化，历史L2与用例保留；同字节不同路径不合并。
- test_broken_index_does_not_hide_document_snapshot故障注入两路marker损坏，新接口仍能读取源快照，原open_active仍抛错；未执行后端后捕获降级。结果ActiveVersion仅绑定快照，不证明索引健康。

### 10.4 资产、学习和唯一下一步

实施前231项资产与137个安装包名称/版本快照已保存；实施后仅3既有源码修改（document_manager、storage导出、errors），新增1源码/3测试及必要阶段文档，既有测试和配置未改，安装包版本一致，源码最大266行。对document_manager移除本片新增import/末尾方法后重算hash，与实施前相同，证明原方法原文保持。证据implementation-assets.json；最终文档核验另见implementation-verification.json。未修改真实.env、旧索引、其他仓库，无删除/提交/push。旧chroma_store/a2_snapshot/keyword_index/vector_index仍有实验/回归消费者，当前新管理方法没有替代其职责，不扩大清理。

完整课堂继续暂挂；本轮只说明读取边界和验收，未登记本人代码走读、独立调试/实现或面试能力。BundleStore仍完整加载编码并重核M2，未声明轻量目录读取或容量/性能改进；真实知识库/生产并发/断电、文档更新/删除、M5召回及业务质量均不由本片证明。

唯一下一步：对照参考FileIntegrity/Pipeline与现有正式入口，先制定M4.6重复摄取与文档更新的Spec：明确源版本判定、重建/激活失败边界及历史L2保留，再确认实施范围。
