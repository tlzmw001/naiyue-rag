# Spec0018：M2第二切片——规则文本准备与可追溯元数据

状态：承接用户“好的继续”及M2第二切片说明，已按规范/TDD实现并接线；40新增测试通过，全量787通过。属于本机离线文本准备验收，尚未接编码/索引或比较检索质量。

## 1. 当前链与参考事实

当前MarkdownLoader.load→DocumentChunker.split_document→源绑定Chunk。Chunk.text必须等于原文[start_offset:end_offset]；contexts含标题、维度、列头等真实SourceSpan。新Chunk尚未接编码/索引，旧A2冻结消费者继续存在。

参考：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER，main，commit f658c5a4011c8b826707a65a3b11ce9301b0626f；2026-10-12只读本机源码，没有刷新远端或运行其服务。

源码链IngestionPipeline.run内chunk_refiner.transform→metadata_enricher.transform→编码。chunk_refiner.py:_rule_based_refine去页脚/HTML/空白后替换Chunk.text；metadata_enricher.py:_rule_based_enrich补title/summary/tags，可有模型增强及fallback。这是源码事实，不是效果或成熟度验证。本片借鉴职责和顺序，不复制源码；Markdown正文保真与实际位置要求决定以下差异。

## 2. 范围与选择

- 新建ingestion/chunk_preparation.py，包含ChunkRefiner、MetadataEnricher和唯一装配入口prepare_document；同属小型规则准备切片，不建立BaseTransform/Factory/注册层。
- 原始Chunk.text、ID、source_ref、body_span、offset、contexts、原元数据保留。返回新Chunk，输入不变。
- text_mode必须显式为raw或labeled_case，无默认推荐值。raw原文；labeled_case只对已识别test_case使用case_columns/case_fields生成“原列名：原字段”，所有列按原顺序保留。普通正文/代码/一般表格原样。
- 仅无反引号的用例字段把未被反斜杠转义的HTML br/br /换成换行；含反引号的整个字段保留原样。这是保守规则：不损坏代码，但可能保留代码之外的br。独立记录规则，不承诺通用HTML清洗或完整Markdown重渲染。
- 不删除注释/标签，不压缩空白，不改公式/链接/转义管道，不扩写复用TC的前置条件。不加模型摘要/标签或臆测有效历史。
- 不把标题或上下文重复拼入检索文本；已有contexts保留供证据层使用。标题前缀等属于后续单变量实验。

## 3. 接口与字段

新增接口（旧公开签名不变）：

```python
ChunkRefiner().transform(document, chunks, *, text_mode) -> list[Chunk]
MetadataEnricher().transform(document, chunks) -> list[Chunk]
prepare_document(document, chunker, *, text_mode) -> (list[Chunk], diagnostics)
```

prepare_document实际调用split_document→Refiner→Enricher，继承原诊断；空文档正常返回空及原诊断。两个独立阶段也校验源绑定，防止脱离入口后接受伪造派生字段。

Refiner输出metadata.retrieval_view：text、text_mode、policy_id、input_sha256、text_sha256、rules。input_sha256包含源版本、chunk ID、正文、用例列/字段；不通过派生正文改变原证据ID。规则模式/指纹随JSON序列化保存；M3/M4必须消费并核验这些字段，不能复用不同视图的旧向量。当前消费者是prepare_document返回值及离线检查，尚无向量编码消费者。

Enricher输出metadata.document_info：title.value/basis/span（首个document_title context解析其标题，缺标题用文件名且span=null）、directory_level（路径目录唯一L0/L1/L2，否则null）、declared_level.value/status/candidates（文件名前缀和标题中的层级声明）。多个声明一致才value确定；相互冲突value=null/status=conflict；无声明unknown。目录与声明不同正常分别记录，不把层级推断为文档依赖。原document_classification沿用，不另造历史/当前角色。

## 4. 正常和异常路径

1. 校验Document原字节hash/实际行起点；每个Chunk用M0校验，再核ID/版本/路径/库ID、正文原文区间、所有context正文和完整SourceSpan实际行号；重复chunk ID拒绝。
2. 用例列/字段须与原行及原列头一致，不能接受修改后的case_fields；代码、表格不可借test_case标记改变形状。重用现有结构扫描的_cells规则核验，不另写表格解析器。
3. 规则转换→指纹→复制；Enricher只生成声明事实。重复执行稳定，调用方改变返回对象不影响原输入或其他输出。
4. 非法输入/模式抛PreparationError固定code，并日志stage=preparation；转换依赖异常或装配阶段异常分别固定code，整次失败，无部分结果/静默原文fallback。Exception隔离，不捕获BaseException；不输出原文、路径、任意异常正文。

## 5. 影响与验收

代码：chunk_preparation.py、ingestion/__init__.py、包__init__.py、core/errors.py；新测试test_chunk_preparation.py、test_preparation_wiring.py。不修改Settings、真实YAML/.env、依赖、旧索引/旧测试/其他仓库。阶段完成只同步README、handoff摘要、学习地图和Spec索引，不预填课堂或掌握。

红灯须由于新组件不存在。确定性测试覆盖raw/labeled_case、完整所有列、br及保守代码策略、原位置/序列化/指纹、目录与声明区别/冲突/未知、伪造body/context/case列字段、重复ID、阶段故障及安全日志、空结果、配置→Loader→Chunker→两阶段接线。固定12Mock重新回读所有原片段/contexts、两模式用例数量一致；阻断socket，没有模型/存储请求。用例标签为合成结构标签，不作为人工业务质量标注。

命令：目标pytest、全量pytest、compileall、pip check、git diff --check。无应用构建入口，compileall只是语法检查。记录前后原资产hash与依赖版本；参数值显式由测试提供，不选择最佳切分值或宣称更好检索质量。

## 6. 边界与回退

本片无摄取成功登记、LLM增强、编码、索引、检索、重排、Agent、MCP、权限或真实材料验证。派生text不是可直接引用的原文，仍用Chunk.text/body_span引用。旧split_document入口保持可用，调用方可继续只获取原始Chunk；失败不自动降级。回退范围仅本片新增规则入口与字段，旧实验资产不迁移或清理。

## 7. 实际验证

2026-10-12实际执行：

```sh
.venv/bin/python -m pytest -q tests/test_chunk_preparation.py tests/test_preparation_wiring.py
# 首次：2 errors during collection，缺PreparationError/prepare_document，预期红灯。
# 最小实现后：40 passed in 0.27s
.venv/bin/python -m pytest -q tests
# 787 passed in 57.13s
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0，无输出；仅语法检查
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0
```

L1存在：chunk_preparation.py及两份新测试；L2实质：规则转换、源绑定校验、SHA256、事实元数据及明确错误实现；L3接线：prepare_document实际调用现有chunker→Refiner→Enricher，Mock测试观察两个真实方法的调用顺序，不用假实现替换它们。

12份现有结构Mock，两模式各72片段/12完整用例/248处原文位置回读、1条原诊断；raw变更视图0条，labeled_case变更12条。结构标签为合成标签；检索质量not_evaluated、service_usage=null、模型请求0。data/research/spec0018-evidence/validation.json记录实际结果，socket阻断核验。

75既有源码/测试/Mock/锁文件hash保持，另外3个既有文件只有本片错误类/导出接线改动；135包版本保持。新源码185行，两测试138/58行，没有修改旧测试。真实配置/旧向量/其他仓库未触碰，无提交/push。当前父包仍加载旧查询/实验兼容入口，不声明整个包已脱离experiments。

学习入口：test_view_preserves_raw_source_all_columns_and_serialization[labeled_case]观察输入chunks、refined、output及case.metadata两份派生字段；test_level_claims_never_infer_relationships[declaration-conflict]观察declared_level；test_stage_failures_return_no_partial_result_and_safe_error[refiner-refinement_failed]为mock故障入口，RuntimeError在failure中抛出，在prepare_document捕获，pytest.raises捕获PreparationError所以测试通过。可在VS Code Test Explorer选择Debug Test，入口断点prepare_document，第一个阶段返回后再观察chunks，F10/F11/Shift+F11走完整链。不通过重新执行transform获取返回值。

正文/用例双视图与元数据边界已说明；本人走读、复写或调试尚无证据。唯一下一步M2第三切片Spec：原文显式引用和需求/用例名称配对；不把链接当业务有效性或依赖推断。
