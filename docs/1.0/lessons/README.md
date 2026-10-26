# 课堂笔记

- [Lesson 42：阶段B·6.5 完整查询走读与定位练习](lesson-42.md)

- [Lesson 41：阶段B·6.4 追踪、延迟和用量的证据边界](lesson-41.md)

- [Lesson 40：阶段B·6.3 失败归因与单变量实验](lesson-40.md)

- [Lesson 39：阶段B·6.2 标注单位、Recall@k与固定样本对照](lesson-39.md)

- [Lesson 38：阶段B·6.1 检索质量、回答质量与工程质量](lesson-38.md)

- [Lesson 37：阶段B·5.8 跨文档补读与再次检索](lesson-37.md)

- [Lesson 36：阶段B·5.7 完整证据、预算与引用](lesson-36.md)

- [Lesson 35：阶段B·5.6 LLM与CrossEncoder重排](lesson-35.md)

- [Lesson 34：阶段B·5.5 双路互补与RRF](lesson-34.md)

- [Lesson 33：阶段B·5.4 全库与范围统计及排序影响](lesson-33.md)

- [Lesson 32：阶段B·5.3 TF、DF、IDF、长度归一化与BM25](lesson-32.md)

- [Lesson 31：阶段B·5.2 余弦相似度、距离与向量召回](lesson-31.md)

- [Lesson 30：阶段B·5.1 查询处理、范围与top_k](lesson-30.md)

- [Lesson 29：阶段B·4.5 重复摄取、更新、移除与历史保留](lesson-29.md)

- [Lesson 28：阶段B·4.4 同版本激活与固定查询快照](lesson-28.md)

- [Lesson 27：阶段B·4.3 BM25索引的构建与重载](lesson-27.md)

- [Lesson 26：阶段B·4.2 Chroma向量存储与相似度索引](lesson-26.md)

- [Lesson 25：阶段B·4.1 原文、资料包与索引的区别](lesson-25.md)

- [Lesson 24：阶段B·3.6 超限、整次失败与真实用量](lesson-24.md)

- [Lesson 23：阶段B·3.5 成对批处理、ID与hash配对](lesson-23.md)

- [Lesson 22：阶段B·3.4 文档与查询编码的一致性](lesson-22.md)

- [Lesson 21：阶段B·3.3 分词、词频与稀疏表示](lesson-21.md)

- [Lesson 20：阶段B·3.2 Embedding和向量空间](lesson-20.md)

- [Lesson 19：阶段B·3.1 原文、检索文本与编码输入](lesson-19.md)

- [Lesson 18：阶段B·2.6 显式引用、文件名配对与跨文档关系](lesson-18.md)

- [Lesson 17：阶段B·2.5 用例表格识别与完整性](lesson-17.md)

- [Lesson 16：阶段B·2.4 结构规则与语义分块](lesson-16.md)

- [Lesson 15：阶段B·2.3 固定长度、重叠与递归切分](lesson-15.md)

- [Lesson 14：阶段B·2.2 Markdown结构与原文定位](lesson-14.md)

- [Lesson 13：阶段B·2.1 Markdown读取与Document](lesson-13.md)

- [Lesson 12：阶段B·1.4 正常、空结果与失败的完整链路](lesson-12.md)

- [Lesson 11：阶段B·1.3 查询输入与结构化证据输出](lesson-11.md)

- [Lesson 10：阶段B·1.2 建库与查询两条数据流](lesson-10.md)

- [Lesson 9：阶段B·1.1 RAG解决什么，检索和推理怎样分工](lesson-9.md)

- [Lesson 8：调用链与成对批次编码](lesson-8.md)
- [Lesson 1：检索前确定文档范围](lesson-1.md)：已讲解query范围计算，用户回答本题“B”正确；仅登记引导后回答，独立实现及其他边界复述尚未验证。
- [Lesson 2：候选与原文绑定](lesson-2.md)：已讲解ID/范围/正文/元数据核对和异常传播；用户回答“整次报错”正确，完整校验的独立复述/实现仍未验证。
- [Lesson 3：距离、分数与排序](lesson-3.md)：用户对distance=1回答“0，0.5”正确；只记录引导后计算，余弦推导/独立排序复写未验证。
- [Lesson 4：等权RRF融合](lesson-4.md)：用户回答排名不变时RRF分数“不会”变化正确；原分数记录仍会变化，独立算法复写未验证。
- [Lesson 5：完整证据与字符预算](lesson-5.md)：用户回答超预算后“尝试C”正确；只记录该控制流引导题，整体查询复述/独立实现未验证。
- [Lesson 6：QueryRequest入口契约](lesson-6.md)：用户回答由post_init显式检查拒绝非法值正确；只记录该题引导后理解，独立复写/其他边界未验证。
- [Lesson 7：配置路径与资源加载](lesson-7.md)：用户正确给出config/vectors路径；只记录该题引导后判断，独立复写/异常复述未验证。

用户对整条查询表示“这里我已经理解了”，综合题不继续追问，记录自述理解；没有收取该题复述或独立实现证据。已转模块主线，Spec0012即时Embedding暂停；Spec0014配置课已记录，Spec0015追踪实施验收完成、课堂待开展。上述为历史课堂记录。阶段B当前进度以[学习地图](../learning-roadmap.md)为准，从Lesson9开始，历史Lesson8完整走读仍未完成。
