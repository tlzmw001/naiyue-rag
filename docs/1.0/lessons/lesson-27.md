# Lesson 27：阶段B·4.3 BM25索引的构建与重载

日期：2026-10-23，第4章共5节，本节第3节。目标：从SparseRecord到倒排/词表/权重矩阵及持久行映射，核验重开后片段归属和数值不变。完整BM25公式与global/scope排序在第5章展开。

## 业务与职责

SparseEncoder已按固定策略生成tokens/TF/长度，BM25Indexer直接消费Bundle中保存的词项，不重新读取Markdown、分词或请求Embedding。BM25Store重载关键词产物，之后供SparseRetriever使用。关键词行与Chroma共用item_id，但不依赖先写Chroma再取得ID。

实际链路：BundleStore.load→按encoding_result.records顺序取r.sparse→_prepare统计与行映射→BM25S.index(tokens)→save原生文件→写rows/ready→重载审计→发布新目录。版本激活由上层DocumentManager协调，build ready不代表当前查询已切换。

## 具体小样本：从词到片段

本机探针人工提供三份合法SparseRecord，用于解释原生存储机制，不声称词项来自真实需求：

| 矩阵行 | 片段ID | tokens | doc_length |
|---:|---|---|---:|
| 0 | C1 | 开关、开关、0.5 | 3 |
| 1 | C2 | 开关、关闭 | 2 |
| 2 | C3 | [] | 0 |

正向看是片段→词；倒排看是词→包含它的片段行及TF：开关→{0:2,1:1}，0.5→{0:1}，关闭→{1:1}。重复词保留给TF，不能先把文档tokens去重。

N=3是参与索引的片段数，不是Markdown文件数；DF(开关)=2是包含该词的片段数，不是TF总和3。avgdl=(3+2+0)/3=5/3。nnz=4是非零“片段-词项”组合数，不是tokens总数5。

若示意词表顺序为[开关,0.5,关闭]，原始TF表为：

```text
       开关  0.5  关闭
C1      2    1    0
C2      1    0    1
C3      0    0    0
```

词表编号是索引内部坐标，不是片段业务ID，也不承诺所有重新构建都使用同一编号；必须保存并与矩阵一起加载。本次实际SDK词表为关闭:0、开关:1、0.5:2，不影响按词查询结果。

## BM25S保存的是贡献权重

本机核对bm25s0.3.13。backend显式method/idf_method=lucene、numpy、float64、int32、auto_compile=False；参数k1/b显式配置，本节用1.5/0.75，不称最优。

BM25S.index会根据TF、DF、片段长度、平均长度等预计算每个非零词项-片段组合的贡献权重，不只是把原始TF矩阵写入磁盘。get_scores将查询词转为词表整数ID，读取相应列并累计到片段分数。已核安装SDK __init__.py的index/get_scores/get_scores_from_ids及scoring.py的Lucene实现，不用“库会处理”替代数据形状。

本次使用真实backend.build_native/load_native，查询['开关']实际分数：C1=0.213638、C2=0.172478、C3=0；输出为示例舍入到6位。保存前/重开后原始浮点列表完全相同。分数无概率含义，不能只根据TF2比1就推断所有场景排名；完整公式第5章再推导。

当前本机Lucene权重定义由锁定SDK和audit_model手算一致核验，不把网上其他BM25变体的绝对分数当作应完全相同。bm25_backend.audit_model核每个词的行集合/TF/DF/长度并重算期望权重，容差rel_tol=1e-12、abs_tol=1e-15。

## 三份稀疏数组与持久ID映射

当前使用按词列压缩的CSC结构，初学先理解三类信息：

- data：实际非零贡献权重。
- indices：每个权重属于哪一个片段行。
- indptr：每个词的记录在上述数组的哪个区间。

例如找开关对应列，取indptr中的起止位置，再用indices找到片段行、用data取得贡献。大部分0不需要逐格保存。本例data/indices长度4，indptr长度词表数+1=4，num_docs=3。数组具体压缩算法不在本节展开。

BM25S原生文件5份：data.csc.index.npy、indices.csc.index.npy、indptr.csc.index.npy、vocab.index.json、params.index.json。项目另存：

| 文件 | 职责 |
|---|---|
| rows.json | 行号按列表位置对应item_id、source_document_id、source_sha256、retrieval_text_sha256、doc_length、unique_terms |
| ready.json | 包/索引/编码身份、计数、参数、avgdl/native_state、各文件字节/hash |

正常indexed目录合计7文件。第1行得高分时必须按保存的rows[1].item_id定位，不能用新扫描目录顺序猜归属，更不能把原始Markdown文件编号当片段行号。完整Chunk仍从同版本Bundle取得。

## 空词片段必须保留行

示例C3无词项，仍是第2行，分数0；它参与N/avgdl，Dense仍可检索它。删掉这行既改变统计，也可能造成关键词行号与片段ID错位。

| 状态 | 保存方式 |
|---|---|
| 有词片段与空词片段混合 | 保留所有行，构建原生稀疏索引 |
| 有片段但全部tokens为空 | native_state=empty，保存rows.json/ready.json两文件，不调用原生空词表index |
| 零片段 | 仍有明确空态和空行映射，不补占位词 |
| 正常索引缺少原生文件 | 不当成合法空态，明确失败 |

“没有该词的贡献”不等于业务无答案。全空词表与索引损坏依据保存的native_state和预期文件集合区分。

## 保存与重开核验

BM25Indexer.build先从Bundle推导预期header/rows/records；同索引存在则_load_index审计后unchanged，不重建。新候选pending→可选原生构建→rows→检查原生完整文件集→同步/逐文件hash→ready→_load_index重开审计→目录发布。

BM25Store._load_index读取清单/文件集合/大小/hash，rows字节必须与Bundle记录顺序推导的一致；先核参数/SDK版本/词表及NPY头的dtype/shape/长度/资源界限，再让原生加载。save/load均allow_pickle=False；加载后audit_model逐词逐行核权重，不能只检查文件hash或数组能打开。

篡改rows并重新计算清单文件hash仍会因源Bundle映射不一致被拒绝；这不是数字签名/身份授权机制，也不说明可抵御所有恶意篡改，只说明多层内部一致性校验。

k1/b改变会改变本组件index_id，从同一Bundle可构建另一个BM25候选，不需要本组件调用Dense。不能据此推断主摄取入口已经实现最小化重建；它的实际复用策略在4.5讨论。当前持久权重按全包统计，第5章再讨论已有global/scope查询选择。

失败时不自动修复坏索引；部分原生文件只留pending，不发布ready。日志固定错误码，不带原文/词项全文或供应商内容。

## Debug Test入口与分支

正常：`tests/test_bm25_store.py::test_build_reload_repeat_and_identity`，无参数。在第50行writer.build断点，F11到BM25Indexer.build；F5到backend.build_native或bm25_store.py第139行附近，选_prepare帧看rows前两项与records前两项tokens，核行序。进入bm25_backend.statistics看row/term/tf/postings，返回后看avgdl/nnz；build_native中model.index返回后看model.vocab_dict及model.scores各数组shape，不展开全部数组。

load审计到BM25Store._load_index第107行，看payloads['rows.json']与由rows产生的预期字节；回测试ready才存在。第53行把build_native替成forbidden，再次build必须只load/audit，文件字节和mtime不变。该测试使用真实BM25S，输入编码/词项是既有助手人工构造，不能当真实分词质量证明。

行错配：`tests/test_bm25_integrity.py::test_rehashed_corruption_rejected[mapping]`，精确参数ID=mapping。第39行rows.reverse，第40行rewrite同时更新文件描述hash。重开_load_index第107行仍发现与Bundle记录顺序不同，抛bm25_integrity_failed，被pytest.raises捕获；证明hash一致不等于来源正确。

空态：`tests/test_bm25_store.py::test_empty_rows_preserve_mapping[all-empty]`，精确参数ID=all-empty；另zero/mixed。第67–68行把build_native换成forbidden，合法空词表仍可保存/审计，只生成两文件。mixed保留空行并正常构建。

半写：`tests/test_bm25_store.py::test_native_save_partial_files_remain_unpublished`，无参数。第147行附近的partial_save仅保存data.csc.index.npy后抛OSError，替换真实BM25.save；build_native转换bm25_write_failed，外层不发布，测试核只有pending及原Bundle字节/mtime未变。故障注入不放宽断言。

原生跨进程：`tests/test_bm25_native.py::test_formal_sdk_encoding_native_save_reload[normal]`，精确ID=normal；另zero/all-empty/mixed。真实Loader/M2、真实Sparse、Dense/SDK使用MockTransport、真实BM25S；构建前把分词/编码入口设为forbidden，证明索引只消费保存词项。不同进程query.get_scores与行ID列表精确相同，重载未导入OpenAI/Chroma SDK。普通断点不自动进入子进程，不修改IDE。

## 本次验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_bm25_store.py::test_build_reload_repeat_and_identity \
  tests/test_bm25_store.py::test_empty_rows_preserve_mapping \
  tests/test_bm25_store.py::test_parameter_change_creates_new_candidate \
  'tests/test_bm25_integrity.py::test_rehashed_corruption_rejected[mapping]' \
  tests/test_bm25_integrity.py::test_hand_scoring_matches_persisted_model \
  'tests/test_bm25_integrity.py::test_invalid_npy_rejected_before_native_allocation[wrong-dtype]' \
  tests/test_bm25_store.py::test_native_save_partial_files_remain_unpublished \
  tests/test_bm25_native.py::test_formal_sdk_encoding_native_save_reload
# 13 passed in 6.67s
```

另人工3行真实SDK探针：N3/avgdl5/3/nnz4，保存5原生文件并重开，开关分数[0.213638,0.172478,0]（展示舍入），原始分数列表相等True。本节只写临时产物，无真实模型、源码/依赖/真实.env/运行配置/原索引修改。

L1已有BM25Indexer/Store/backend，L2真实Sparse→统计→原生权重/文件→审计，L3本次13项含四状态跨进程分数与ID一致；不证明真实资料检索质量或大库性能。构建不适用，不跑全量；git diff --check退出0。

## 学习证据与唯一下一步

4.3已讲解，助手核对SDK源码、人工数值与13项定向测试；用户理解待反馈，本人独立调试/实现未评估。讲解覆盖19/34节，余15节。下一节4.4：同版本激活与固定查询快照，把Bundle、Chroma、BM25三份产物绑定为一个可服务版本，解释失败为何不切换及查询为何不混版本。
