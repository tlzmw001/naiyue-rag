# Spec0046：优化分片3／中文标点切分与固定边界对照

日期：2026-10-26。状态：已实现/接线/本地验收，本片完整回归2187项通过；D1/D2/D3均已确认。

## 1. 目标与当前调用链

MarkdownLoader→scan_document→正文块RecursiveCharacterTextSplitter→真实原文span→ChunkRefiner/MetadataEnricher→编码。只对普通正文增加中文句号/逗号字面量分隔符，不改变结构识别、Sparse分词、完整用例/代码/表格保护或模型。

现有v1分隔符为段落、换行、英文句号空格/感叹空格/问号空格/分号空格/逗号空格、空格、字符兜底；keep_separator=True。0045保证v1仍可原样重放。

## 2. 已确认D2：新策略的标点归属与启用方式

推荐markdown-source-zh-v2：分隔符按['\n\n','\n','. ','! ','? ','。','; ',', ','，',' ','']；is_separator_regex=False，strip_whitespace=False，keep_separator='end'。优先粗粒度再细分，不把列表顺序当最佳业务参数。

keep_separator='end'适用于整个v2正文分隔符列表，也会影响英文标点及换行的归属；不能宣称仅改变中文字符。推荐保留完整句末标点在前块，v1仍保留原行为。备选为沿用True（归后块），行为变化较少，但可能出现以句号起头或单独句号的块。

2026-10-26对本机langchain-text-splitters1.1.3做无文件/无模型合成探针：55字符正文、size24/overlap0时，True得到4块且末块单独“。”；end得到3块，均以对应句末标点结束。两者逐字符定位及拼接还原均True。仅机制证据，不是质量优选。

新建任务缺省采用v2；旧持久化缺省仍显式v1，显式v1任务继续可建。没有修改真实YAML或.env的必要。

2026-10-26，向用户说明标点归前块的具体例子、对英文分隔符/换行同样生效、新任务默认v2、旧资料包按保存策略读取及不自动重建既有知识库，用户明确回复“没问题”，确认该推荐方案。D2无需重问；这不代表确认0048的存储/报告合同D3，也不代表新策略已实施或检索质量已提升。

## 3. 接线、失效与异常

在0045策略注册中增加v2，DocumentChunker从已规范settings取参数，profile覆盖实际规则。相同原始文档从v1转v2视为处理身份失效，重新准备/编码并生成新完整版本。旧活动包仍可被读取核验，切换只在候选双索引核验后发生。

正文每个Chunk.text等于Document.text[start:end]，保留原标点，不靠事后补字符伪造原文。不强求每片固定重叠长度；保持现有字符上限及实际递归窗口合同。非正文原子块仍允许完整超长并给诊断。

未知策略/不可定位/组件失败维持显式错误，不静默切回v1。保留旧资料包；不自动启动用户知识库重建。

## 4. 影响文件与固定对照

core/chunking_policy.py、core/ingestion_settings.py（新任务默认选择）、tests/test_document_chunker.py、tests/test_chunking_wiring.py、tests/test_file_integrity.py、tests/test_ingestion_pipeline.py、tests/test_storage_bundle_wiring.py；必要的合成结构样本只放tests，实际配置不改。

先红灯覆盖纯中文长段、句逗组合、中英混排、条件/否定词/数值/技术标识符靠近边界、重复正文、LF/CRLF/CR、size边界及overlap。验证原文非空白覆盖、标点完整、准确定位、原子保护及策略指纹。

固定source+span证据标签，不用会随策略变化的chunk_id当跨分块金标准。固定size/overlap/语料比较v1与v2的块边界、数量、超长和证据是否跨块；不得同时改模型、top_k或预算解释差异。无新真实模型请求；真实检索质量另需同条件重编码实验，不能从结构对照宣布提升。

## 5. 验收与下一片

L1策略定义与测试存在；L2真实Splitter执行；L3配置对象→Chunker→输入准备→资料包与旧版本读取接线，证明新策略不能误用旧编码。

计划命令：

```sh
.venv/bin/python -m pytest -q tests/test_document_chunker.py tests/test_chunking_wiring.py tests/test_file_integrity.py tests/test_ingestion_pipeline.py tests/test_storage_bundle_wiring.py --tb=short
.venv/bin/python -m pytest -q tests --tb=short
.venv/bin/python -m compileall -q naiyue_rag experiments tests
.venv/bin/python -m pip check
git diff --check
```

构建不适用。新生成存储不允许旧版代码读新策略，代码回退前必须使用支持该策略的读取代码；不自动改活动指针或删除产物。完成后说明0047如何按文档源hash和处理身份形成编码/复用集合。

## 2026-10-26实施记录

新增test_chinese_chunking.py先9 failed in0.31s；注册v2并切换新任务默认后，与旧策略/结构/资料包/摄取回归145 passed in12.88s。旧策略测试的“隐式v1”输入改为从旧持久字段读取，不把新任务默认仍强定为v1；其余旧包原文/manifest断言保持。新v2由core/chunking_policy.py实际驱动Splitter，无新依赖/真实配置更改。完整回归已通过。

最终完整命令`.venv/bin/python -m pytest -q tests --tb=short`：2187 passed in435.13s（0:07:15）。语法/依赖/diff检查退出0。固定55字符正文size24/overlap0对照：v1/v2均3块且原文无损，v1末尾拆开TC-01，v2按完整句子保留；此为结构对照，不当真实质量通过。第3片L1/L2/L3完成；下一步0047复用规划。
