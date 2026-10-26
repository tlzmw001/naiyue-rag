# Lesson 15：阶段B·2.3 固定长度、重叠与递归切分

日期：2026-10-21，第2章共6节。目标：从实际小文本理解切分、递归下钻和合并窗口，并沿当前框架实现追到项目Chunk。没有模型调用或业务质量结论。

## 模块职责与实际配置

DocumentChunker.split_document先scan_document；只有kind=text进入RecursiveCharacterTextSplitter，code/table/test_case直接按完整结构范围生成Chunk。已安装langchain-text-splitters 1.1.3，核对本机character.py::_split_text与base.py::_merge_splits/create_documents。

项目设置：chunk_size/overlap来自IngestionSettings，size为正整数、0<=overlap<size；长度函数len，按Python字符计数，不是UTF-8字节或模型token。普通正文输出不超过size，size不是必须填满的长度；非text原子块可以更大并记atomic_oversize，后续编码限额仍独立检查。

SEPARATORS当前在源码中：['\n\n','\n','. ','! ','? ','; ',', ',' ','']。保持分隔符、strip_whitespace=False、add_start_index=True。普通分隔符按字面量匹配；中文句号、逗号当前没有专用条目，不假定自动识别中文句界。末尾''表示没有其他可用边界时退到字符。

## 输入输出：本次真实小样本

输入text='关闭折扣 保留金额 校验数量 记录日志'，len=19。使用现有document测试helper＋真实DocumentChunker，无新教学实现或文件。

固定每8字符切片：'关闭折扣 保留金'、'额 校验数量 记'、'录日志'。这是纯切片对照，展示可能断开信息，不代表已测业务质量。

真实递归配置size=8/overlap=0：'关闭折扣'[0,4)、' 保留金额'[4,9)、' 校验数量'[9,14)、' 记录日志'[14,19)。空格被保留在后一个片段开头，不是strip后的文本。

size=10/overlap=0：'关闭折扣 保留金额'[0,9)、' 校验数量 记录日志'[9,19)。相邻短片段会在上限内合并，而非遇到分隔符就永久生成一个Chunk。

## 递归在哪里发生

_split_text按优先顺序找到当前文本实际出现的第一个分隔符；先切成较小段。足够短的段进入good_splits后合并；达到当前阈值的段会先刷新已有good_splits，再以剩余更细分隔符递归调用自身；没有更细分隔符就返回当前单元。当前源码用len(s)<chunk_size判定good_splits，恰好等长也可能下钻，最终上限合同仍为<=size。

本次真实例：'说明\n关闭折扣 保留金额 校验数量 记录日志'，size10/overlap0。

1. 没有双换行，有单换行：选\n，保留分隔符后得到'说明'和'\n关闭折扣 保留金额 校验数量 记录日志'。
2. 第二段过长，递归时只使用更细的剩余分隔符；这里找到空格。
3. 得到5字符左右短段，合并到不超过10字符。
4. 最终'说明'[0,2)、'\n关闭折扣 保留金额'[2,12)、' 校验数量 记录日志'[12,22)。全部Chunk原文切片匹配True。

递归指同一函数处理更小子问题、尝试更细边界，不是调用大模型判断意义。

## 重叠的合并窗口

_merge_splits维护current_doc短段列表与total长度；追加下一段将超size时先输出当前Chunk，然后从列表开头整段移除，直到剩余总长<=overlap且能放入下一段，再继续合并。重叠是在该合并窗口中的尾段保留，不是对每个成品强取最后N字符；不同结构区域或递归分支之间也不保证重叠。

同一19字符输入的真实结果：

| size/overlap | 输出字符范围 |
|---|---|
| 10/0 | [0,9)、[9,19) |
| 10/3 | [0,9)、[9,19)，没有重叠 |
| 10/5 | [0,9)、[4,14)、[9,19) |

以第一窗口['关闭折扣'(4),' 保留金额'(5)]为例，总长9，下一段' 校验数量'长5，不能直接追加。overlap3时移除首段剩5，仍>3，继续移除后为空；overlap5时移除首段剩5，正好可保留，再加入下一段得到10。因而3不产生重叠、5保留5字符。

重叠有助于边界附近信息同时出现在相邻片段，但会增加片段/编码/索引/候选重复和上下文成本；不能保证一切跨段信息完整，也不保证召回更好。长度/重叠要通过固定样本单变量对照，不因示例参数或参考默认就认定最佳。

## 接回项目与位置校验

DocumentChunker第58–72行：原结构块raw→框架create_documents→临时parts（page_content＋metadata.start_index）→校验→项目Chunk。这里框架片段对象与项目整份Document不是同一个职责。

create_documents通过text.find在预计位置附近搜索Chunk内容，start_index是候选定位；项目再次检查类型、非空、范围、非倒退、raw[offset:offset+len(part)]==part及长度，然后将局部offset加到block.start，得到全局字符位置。保留分隔符/空白有助于保持来源映射，不把框架开关当作完整证明。重复原文的全局唯一定位不是仅凭字符串相等就能证明的额外保证。

调用链：IngestionPipeline._build_and_activate→prepare_knowledge_base→prepare_document→DocumentChunker.split_document→scan_document→框架create_documents/split_text/_split_text/_merge_splits→本项目_chunk。

## 关键分支与异常

| 场景 | 当前结果 |
|---|---|
| 短正文 | 可直接形成短Chunk，不填充到size |
| 有粗边界但某段仍大 | 使用更细分隔符递归 |
| 无可用边界 | 回退字符切分 |
| code/table/test_case | 绕过正文递归，保留结构单元，必要时oversize诊断 |
| size/overlap非法 | invalid_chunking_config |
| 框架调用失败或异常空返回 | splitter_failed |
| 框架片段与原文/位置/上限不匹配 | unmapped_fragment，不继续伪造来源 |

## Debug Test入口

首选tests/test_document_chunker.py::test_prose_boundaries_and_real_parameter_effects（无参数ID），现有输入为'# 模块\n\n## 行为\n\n'后接100段步骤文字；分别跑80/0、180/0、80/30，校验片段数量、范围、上限、实际重叠与原文绑定。未替换真实框架。

- Test Explorer→Debug Test，在测试第57行开始；F11进split_document。
- F5到DocumentChunker第59行，在raw较长的正文轮次观察len(raw)、self._size、self._overlap；raw只在第58行赋值后出现。
- F11进框架create_documents，必要时F5到character.py::_split_text，在该栈帧看repr(separator)、[len(s) for s in splits]；s尚未循环产生时不要观察它。递归调用前看repr(s)与new_separators。
- 在base.py::_merge_splits输出当前窗口前观察current_doc、total、len_，通过移除前缀理解overlap。
- 返回项目第65–71行，选split_document栈帧观察offset、len(text)、block['start']，确认局部到全局的转换。回测试查看[(c.start_offset,c.end_offset) for c in small[:3]]，不重新执行切分函数取输出。

故障测试tests/test_document_chunker.py::test_splitter_failure_and_unmapped_fragment_safe（无参数ID）：第186行将create_documents替换为fail，第185行raise，生产第60行捕获并抛splitter_failed；第189–190行改为返回不属于原文的临时Part，生产第65–69行拒绝unmapped_fragment。pytest.raises捕获预期异常，测试通过不代表故障调用成功。

## 本次验证与学习证据

命令：`.venv/bin/python -m pytest -q tests/test_document_chunker.py::test_prose_boundaries_and_real_parameter_effects tests/test_document_chunker.py::test_splitter_failure_and_unmapped_fragment_safe tests/test_document_chunker.py::test_ids_stable_version_bound_and_outputs_isolated`。

实际输出：`3 passed in 0.83s`。另有上文真实框架小样本探针，全部使用课堂合成输入，无模型/网络/索引写入。仅维护学习记录，未改源代码/依赖/配置；git diff --check另作格式检查。

已讲解2.3，用户理解与本人调试待反馈，独立实现/复写未评估。下一节2.4：结构规则与语义分块的区别，准确说明当前方案做了什么，以及没有什么保证。
