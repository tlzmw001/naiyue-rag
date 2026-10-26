# RAG 工程实践课程 1.0

2026-10-11学习顺序随[模块主线M0–M9](../project-plan.md)推进，后续课程绑定正在建设的模块输入/输出、代码、异常和验证。前五节是已有检索实验/Chroma资产的局部代码课，不登记为通用模块已掌握；下一课先建立公共契约/配置与摄取链的全局位置，再随模块Spec/TDD阅读实际代码。

从 [学习路线](learning-roadmap.md) 开始。每次只学一个机制，并与当前切片的输入、输出、源码、测试和失败案例对应。实际课堂笔记放在 `lessons/`；课程计划不代表已掌握。

2026-10-10总体目标已确认：[RAG核心知识库Agent](../decisions/0004-knowledge-agent-goal-and-boundaries.md)。Spec0010/0011及M0的Spec0013/0014/[0015追踪](../specs/0015-m0-minimal-tracing.md)已实现，最新660测试为本机工程验证。[笔记入口](lessons/README.md)现含七节课堂，路径题引导后回答正确，独立复写尚未验证。下一课追retrieve_with_trace正常/写失败/双失败控制流，不预填追踪代码已掌握。

配置路径课已记Lesson7；Spec0015已获具体策略及实施授权并验收，尚未逐行讲新追踪代码或本人练习。下一Lesson8随实际课堂记录，随后准备M1加载Spec。

## 当前入口（2026-10-26）

阶段A的M1–M6本地工程边界已验收，阶段B按六章34节学习。六章34节机制讲解与调试路线已覆盖，最新课堂见[Lesson42](lessons/lesson-42.md)，6.5本人定位练习待完成；唯一下一步为提交一次实际调试观察或卡住位置，阶段B不自动验收为完成，具体进度和学习证据以[学习路线](learning-roadmap.md)为准。用户理解待反馈，独立调试/实现未评估。

- [M5统一查询与RRF](../specs/0038-m5-hybrid-search.md)
- [M5原文补读与引用导航](../specs/0039-m5-knowledge-reading.md)
- [M6重排实现与验证](../specs/0041-m6-reranking-contract-and-glm.md)
- [M6证据与独立入口](../specs/0042-m6-evidence-and-independent-entry.md)
- [M6总体边界](../specs/0040-m6-reranking-and-evidence-plan.md)
- [学习路线与当前证据](learning-roadmap.md)
- [三阶段边界：独立RAG→系统学习→Agent及接入扩展](../project-plan.md)
- [Spec0035：M5.1查询准备实现与验证](../specs/0035-m5-query-preparation.md)
- [Lesson8：成对批处理调用链，完整课堂暂挂](lessons/lesson-8.md)
- [Spec0026：监督与服务验收](../specs/0026-m3-supervised-service-check.md)
- [Spec0031：同版本激活与重开验收](../specs/0031-m4-same-version-activation.md)
- [Spec0032：只读文档列表、详情与revision约束](../specs/0032-m4-document-management.md)
- [Spec0033：正式摄取、重复判断与文档更新验收](../specs/0033-m4-ingestion-and-updates.md)
- [Spec0034：显式文档移除与历史版本保留（实施及本地接线验证）](../specs/0034-m4-document-removal.md)
- [项目交接与唯一下一步](../handoff.md)
