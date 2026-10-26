# Spec0016：M1第一切片——通用Markdown原文加载

状态：用户接受首期身份规则及方案后已按本Spec实施/接线，48新增/708总测试通过。用户要求“先进行M1”，追踪课堂暂挂，不作为开发门槛。沿已确认M0–M9路线，普通Markdown已可进入公共Document；旧Mock/索引资产保持，不声称新文档已可检索。实际验收见第7节。

## 1. 当前链路与参考事实

现有experiments.markdown_probe.load_sources依赖manifest：显式Mock ID/角色/层级/预期hash→读knowledge目录文件→原字节SHA256/UTF-8文本/line_starts→旧source字典。vector_index.load_corpus另强制synthetic/naiyue-rag-mock-v1。现有A2公开资源因此不能加载任意真实资料。

参考URL：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER；本地main固定commit f658c5a4011c8b826707a65a3b11ce9301b0626f，工作区干净，当前只读，未刷新远程或运行参考服务。

- BaseLoader.load(file_path)→Document，Loader不负责分块。
- 当前IngestionPipeline实际使用PdfLoader/MarkItDown→Markdown；本地src/libs/loader未见通用Markdown Loader。
- PdfLoader的doc_id为doc_加内容hash前16位；SQLiteIntegrityChecker按完整file_hash登记/should_skip。
- pipeline.run先检查hash/skip，再load、chunk、编码、写存储，最后mark_success；此顺序不等于多存储原子事务保证。

本片沿Loader→Document接口及字节hash机制；原文件本身已经Markdown，不转换/清洗正文，也不引入PDF依赖或额外解析框架。保留既有原文位置规则与公共Document。通用切分/表格处理在M2；完整索引/成功登记消费者在M4接线。

## 2. 目标与最小数据流

```mermaid
flowchart LR
    A["显式知识库根目录及固定knowledge_base_id"] --> B["扫描普通.md文件，排序"]
    B --> C["MarkdownLoader.load"]
    C --> D["库内路径检查与限额读取"]
    D --> E["同一字节计算hash并UTF-8解码"]
    E --> F["公共Document及实际行起点"]
    F --> G["load_all返回文档列表，后续M2消费"]
```

公开库入口拟为MarkdownLoader(knowledge_base_root, knowledge_base_id, max_file_bytes)，load(relative_path)→Document，load_all()→list[Document]。三个构造参数由调用方提供，不默认扫描工作目录，不创建/修改运行YAML/.env。知识库根目录是导入范围，不是人员权限清单。

本片不需要manifest、synthetic标记、人工ID或预填hash；不添加空BaseLoader/Factory或完整摄取框架。只有一种格式，先实现具体Loader；其他格式有实际消费者时再决定公共抽象。

## 3. 已确认文档身份与版本

已确认逻辑Document.id=doc-加SHA256(JSON数组[knowledge_base_id, 规范相对路径]的UTF-8字节)。绝对根目录不参与ID；同库/同相对路径改内容时ID不变，source_sha256变化。同内容不同路径保留两份来源，不按hash合并历史需求/用例。

此身份方式与参考内容hash ID不同，原因是本业务须区分同一路径修订和不同历史来源；M1计划已要求身份/版本分开。当前不维护跨改名的逻辑ID登记，文件改名/移动视为新文档；旧引用的改名关系在出现需求后再讨论。固定knowledge_base_id由部署调用方保持，不是人员身份。

metadata为knowledge_base_id、source_path（规范库内POSIX相对路径）、source_sha256（原字节64hex）、size_bytes、line_starts（Unicode字符偏移）。ID/text/metadata沿M0 Document，不新增公开类型字段。行起点按LF/CRLF/单CR实际分隔计算，末尾换行不虚构额外正文行；不读取或信任表头手写行号。

正文严格UTF-8解码，保留BOM、换行、标题、表格、代码/链接等原样，不替换非法字符或猜编码。空文件正常返回text为空、line_starts为空、合法SHA；后续M2不因此生成虚构chunk。目录为空返回[]。

## 4. 正常/异常与副作用

| 场景 | 负责层及结果 |
|---|---|
| 普通Markdown文件 | Loader一次读取所需原字节→hash/text/行起点→Document |
| 多文件目录 | load_all调用load，按规范相对路径排序返回全部Document |
| 重复读取同文件 | 同ID/版本/内容，无写入计数或重复摄取登记 |
| 相同内容两路径 | 两个不同ID/来源，同版本hash |
| 空文件/空目录 | 合法空Document/[]，不塞示例数据 |
| 文件缺失/不是文件/读取或扫描失败 | 固定LoadError及安全日志，调用失败 |
| 非UTF-8/超max_file_bytes | 明确报错，不清洗/截断/重试 |
| 绝对文件参数、..分量、库外目标、库内符号链接 | 拒绝，避免别名/越界；根目录本身由调用方显式指定并规范化 |
| 批次某文件失败 | 第一片建议整次load_all抛错、不返回部分成功列表；后续显式逐文件摄取任务另定结果契约 |

load_all扫描扩展名不区分大小写（.md/.MD），非Markdown文件不加载；使用标准库目录遍历并显式处理遍历错误，不靠会忽略权限错误的扫描当成功。子目录符号链接明确拒绝，不默认跟随。输入root/id/限额类型明确检查，bool不能冒充限额整数；max_file_bytes为正整数。读取最多limit+1字节判超限，不将原文/路径/异常原文写日志。返回的内容/hash来自同一次读取，不分两次读取拼不同版本。

LoadError新增固定code：invalid_loader_config、invalid_source_path、unsupported_source、source_read_failed、source_too_large、invalid_source_encoding、source_scan_failed。IO失败日志仅stage=load/code，异常from None。当前本机受信任导入目录，不承诺抵御恶意并发替换路径；读取后的文件更新由版本核对/后续索引生命周期处理。

无磁盘写入、网络、Embedding、索引或成功登记；读文件成功只能记加载成功，不能mark_success为完整摄取成功。load_all先采用内存列表，面向本轮小样本；大型目录的累计内存/流式处理需独立需求与验证。

## 5. 影响范围、复用与验收

拟6源码/测试文件：ingestion/__init__.py、ingestion/markdown_loader.py、core/errors.py、包__init__.py、tests/test_markdown_loader.py、tests/test_markdown_loader_wiring.py。无依赖升级、旧测试/helpers/Mock/缓存/原API修改；新源码不依赖experiments，单文件≤500行。

复用M0 Document及其往返校验；将已存在读取/hash/保留换行/行起点的机制整理为产品Loader。旧manifest实验入口尚有实验/基线消费者，不能凭名称相似删除；本片不整体搬迁。通用原文无Mock门槛，但现有retrieve_once资源链不在本片切换。

先失败测试确认缺Loader或预期行为，再最小实现。正常/空/异常及分支均独立确定性用例；合法临时普通Markdown不带manifest/synthetic，证明无Mock依赖。Mock结构样本与旧加载器比较正文/hash/行位置，仅ID不同且旧ID不改。另验中文、BOM、三类换行、表格/代码原文、修改内容ID稳定而hash变化、移动目录根ID稳定、改名ID变化、同内容不同路径不合并、读取/扫描失败无秘密日志、越界/符号链接/超限、批次失败/无文件无伪造数据。

L1确认6文件；L2真实读取/hash/定位/安全错误；L3公共load_all→单文件load→M0 Document与序列化真正消费，并核返回对原字节一致。仅库级加载接线，不宣称新文档进入查询/M2分块/索引。合法空文件不构造SourceSpan（当前Span要求非空区间）。

计划命令尚未执行：

```sh
.venv/bin/python -m pytest -q tests/test_markdown_loader.py tests/test_markdown_loader_wiring.py
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q naiyue_rag experiments tests
.venv/bin/python -m pip check
git diff --check
```

构建不适用，compileall仅语法。验证仅公开/合成资料；用户真实文件仍在另一机器，后续迁移执行另记，不冒充已读/已测。

## 6. 参考差异与下一步

沿参考load→Document、SHA256与分块分层；必要差异为原Markdown不转换、逻辑路径ID与版本分开、限定导入根且禁止符号链接、原文不进日志、先仅加载而不提前登记摄取完成。SQLite成功/失败登记必须在M4真实存储消费者就绪后接，不能在M1假称完整幂等摄取已实现。

无数据或索引迁移，读取接口不会改源文件；旧A2入口继续可用。回滚/删除不自动执行。设计时下一步为确认后实施，现已完成；当前下一步为Loader模块分支/测试走读，追踪课堂仍待学，不登记掌握。

## 7. 实际实施与验证

6文件范围已完成MarkdownLoader、ingestion导出、LoadError及包导出和两份新测试。Loader本身103行、导出4行；新测试206/83行，均≤500。无新依赖、真实运行配置/索引/旧入口签名/实验资产变化，无模型请求、其他仓库修改、提交或push。

TDD：先新增测试，实际2收集错误（缺MarkdownLoader导出）；最小实现后47通过。读取上限无法由Python IO表示时OverflowError未分类：新增回归红灯复现→只扩展读取错误分类，转source_read_failed并安全日志→48通过。没有改旧测试/helpers/放宽断言/skip。

实际最终命令与结果：

```sh
.venv/bin/python -m pytest -q tests/test_markdown_loader.py tests/test_markdown_loader_wiring.py
# 48 passed in 0.12s
.venv/bin/python -m pytest -q tests
# 708 passed in 57.11s
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0，无输出；语法检查，打包构建不适用
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0，无输出
```

L1：6文件存在。L2：真实受限原字节读取、严格UTF-8、SHA/逻辑ID、三类换行起点、路径/符号链接/扫描失败检查，安全错误，非占位；新增ingestion源码不导入experiments。L3：公开load_all→load→真实M0 Document构造和序列化消费，在无manifest的普通临时Markdown目录通过；当前Mock结构12文档与旧Loader正文/hash/行起点逐项相同，旧ID保持，新ID按已确认规则生成。长表格行原样保留且实际行起点可回读，手写L999只保留文本，不参与位置计算。

同路径更新ID保持/hash改变、根目录变化同ID、路径/知识库变化新ID、同内容不同路径不合并、重复读取稳定、空/非法编码/大小上限/缺文件/IO权限/扫描失败/批次失败/符号链接均通过。单次读取中源后来变化的故障注入仍保证Document.text与hash来自同一已读字节快照，不宣称文件在读取后未变化。

保护证据data/research/spec0016-evidence：153既有代码/测试/Mock/锁/历史资产hash保持，2允许修改旧文件另存前状态；135已装分发版本保持，source-checks记录6文件hash/行数。合法样本完全合成/既有Mock结构；真实远端文档、跨机器安装与Windows行为未验证。

限制：仅原文加载与源快照定位，未解析标题语义/用例列/文档引用或切分；没有完整摄取成功/增量登记、持久索引或新文档查询接线。load_all为内存列表、任一失败整批抛错；root为受信任本机导入范围，不承诺恶意并发路径替换防御。max_file_bytes来自调用方，无法表示的read上限明确报source_read_failed，无截断/重试。M2消费当前Document，M4接完整索引成功登记。

课堂位置：用户只确认设计，未执行测试调试或完整模块复述，不登记理解/独立实现。下一步按完整Loader职责与正常/更新/失败分支地图开展Lesson8，优先现有确定性测试；追踪课继续暂挂。
