# Spec0039：M5.5 同版本原文补读与显式引用导航

日期2026-10-15。状态：已实现/接线/M5模块本地全量验收通过。

## 1. 当前链与范围

M5.1–M5.4已经从新问题走一次编码、固定版本/范围、两路检索/RRF。M5还承诺受控引用导航和原文补读。本片只提供库级读取：按命中片段读完整内容、按实际行号读原文、列出已有显式关系。由调用方选择补读对象；不加自动扩展召回、Agent循环或第二轮推理。

先搜后写结果：M4已有DocumentManager列表/详情和BundleStore完整原文；M2 `markdown_structure.source_span`已有实际位置生成、document_relations已有原文引用/名称配对；旧experiments/relation_index为自动多跳扩展，可能改变A2排序且有负向质量证据，不作为本片主链。参考项目检索→get_by_ids→CitationGenerator/ResponseBuilder消费片段，并无本项目L0/L1/L2的显式精读接口，因此新增业务适配而不复制图框架。参考仍main/f658c5a4（完整URL见Spec0038），2026-10-15只读核对。

## 2. 接口与数据

`query/knowledge_reader.py::KnowledgeReader(storage_settings)`仅持有BundleStore和防御复制的StorageSettings，不要求Provider/Tokenizer/原始文档根。方法：

- `read_chunk(prepared, chunk_id, *, max_characters)`：返回dict，仅active、chunk两字段；Chunk完整正文/元数据/上下文/实际SourceSpan和用例字段，不按字符截断。max_characters限制正文长度，完整JSON另受存储max_bundle_bytes限制。
- `read_lines(prepared, document_id, *, start_line, end_line, max_characters)`：行号从1起、end包含，基于保存原文的实际line_starts，复用source_span；返回dict，仅active、document_id、source_path、source_sha256、span、text。不按表头手写行号纠偏或猜位置。空文档只接受1..1，返回text空/span=None；其他越界明确失败，不自动截取。CRLF/CR/LF原样保留。
- `related_documents(prepared, document_id, *, max_links)`：返回dict，仅active、document_id、relations、omitted_by_scope。列出已存原生引用/名称配对的入向和出向边，原edge字段及quote/source_span/derivation完整；两个端点都需在本次文档范围。范围外不返回正文/ID，仅明确排除计数。超过max_links整次超限，不静默截断或自动跟随；关系不是业务有效性的证明。

所有输出先深复制并有界JSON校验；本片为受控库接口，没有反序列化执行入口。未来MCP/Agent不得把任意外部PreparedQuery当权限授权，适配层须从实际配置和受控入口构造它。

## 3. 固定版本与失败链

每次读取clone PreparedQuery→按active.bundle_id读一个保存资料包→核对KB/源fingerprint/三身份/维度/文档片段总数→核对scope与chunk_ids准确投影→执行显式读取→复制/限额→返回。不读catalog/latest、不读原始Markdown或.env、不启动两路SDK/分词器/编码，不要求当前索引健康才能读已存原文（沿M4只读管理边界）。

Dense/Sparse已有相同scope投影校验，此处为第三个实际消费者，提取`query/prepared_scope.py::validate_prepared_scope(prepared,bundle)`纯检查并迁移两路调用；各自索引健康/配置/错误阶段仍留各自Retriever，不共用整条执行链。

非法ID/参数/范围、无活动版本明确QueryJobError(resources,query_invalid_request/query_invalid_scope)，保留已选active，无本次模型请求所以不把旧编码报告作为本次用量。坏包/IO/身份沿StorageError固定码，必要失败安全记录。正文或JSON超限用document_limit_exceeded。BaseException保持，不自动重试/刷新或回滚。

## 4. 验收与影响

新增reader、纯scope检查与测试；更新Dense/Sparse的重复检查委托、根/query导出，不改公开签名/存储格式/真实配置/依赖/旧测试。正常读取不是相似度检索，不伪造召回/可信度或“已理解需求”。

- TDD红灯→实现；完整用例、标题/表头context与SourceSpan保持；真实行号/换行方式/空文档/非法越界及预算覆盖。
- 双向关系/配对、来源quote与边ID保持，scope过滤/超限/坏ID不自动扩展。读取中active切换仍取已选旧版，Markdown移走也可读。
- 禁catalog/SDK/编码/原始文档根/.env访问；读后资料包文件不变。实际Reader输出可JSON往返，返回后修改不能污染已存包/下次结果。
- Dense/Sparse原检查与M5.4回归；M5模块最终全量、compileall、pip check、资产/链接/格式检查。原生新进程从Hybrid结果的PreparedQuery/Chunk IDs读取同版完整用例及引用对应行，真实模型请求0。

## 5. 回退与下一步

纯只读新增，无自动数据删除或回滚。索引损坏时原文可读不代表召回成功；接口不代替Agent判断是否补查。完整包重核成本仍保留，性能按后续测量优化。

本片完成M5范围后进入M6：先对照参考重排/响应/引用链，明确启用/关闭基线、完整候选与预算、引用来源，再实现必要配置与适配。不同Provider和真实服务验收按证据与实际约束推进，不预填生产或本人掌握。

## 6. 实施与切片证据

新增KnowledgeReader及第三个消费者需要的纯scope校验函数；Dense/Sparse只迁移重复检查，各自索引审计与异常边界保持。源读取实际复用BundleStore/source_span，字段与边直接来自已存原文及M2关系，不使用模型“补全”事实。根/query实际导出Reader，四原生场景已消费HybridResult：检索进程保存内部DTO，另一进程按命中ID/实际行号读取完整用例/原文/双向关系；源根已移走，禁止SDK/编码/catalog/.env访问，存储全部文件内容与mtime不变。

TDD初始15 failed in5.20s（缺Reader/导出），实现后Reader+两路回归**106 passed in29.69s**。随后增加4种换行/空文档和4个原生场景；首轮**4 failed,141 passed in57.35s**，失败来自新测试用错IngestionPipeline.storage_settings属性，当前实际是settings。修正测试装配到真实settings，不给生产代码加虚假兼容属性；4种参数单独重跑**4 passed in1.31s**。测试正文/预算/行号/错误断言未放宽。完整日志见data/research/spec0039-evidence/。

214项旧资产仅根/query导出及Dense/Sparse四源码改变；新增Reader/纯scope校验和两测试，旧测试/配置/依赖保持，137安装版本不变、源码最大266行。

```zsh
.venv/bin/python -m pytest -q tests --tb=short
# 2046 passed in 341.34s (0:05:41)
.venv/bin/python -m compileall -q naiyue_rag tests
# exit 0，无错误输出
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0，无错误输出
```

上述均本轮实际运行，完整日志/资产与验收JSON在data/research/spec0039-evidence/；没有独立打包构建入口，compileall不替代功能测试。M5.4与本片共61新增，连同此前Dense/Sparse，本轮累计新增163项；旧测试保持。真实模型POST0、真实.env读改0，无参考执行、删除、提交/push；实际质量/大库性能未验，完整课堂暂挂。M5本地工程退出条件具备，M6和阶段A完整证据闭环尚未实现，不能声明纯RAG整体完成。
