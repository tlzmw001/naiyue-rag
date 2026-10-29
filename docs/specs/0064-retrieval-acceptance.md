# Spec0064：共享检索服务分发与验收

后续[Spec0065](0065-nyr-shared-service-adapter.md)已把nyr/HTTP接入同一共享模块，新增CLI与真实连接断开验收；下方“旧CLI/HTTP”及制品摘要为0064完成时的历史快照，当前候选和最终验证见0065。

新包naiyue_rag.serving显式加入setuptools发现范围；配置模板、源码导出与正式CI清单同步。
旧CLI/HTTP仍使用原本机运行时；本轮交付新独立Python入口，调用示例清楚区分，不能声称旧HTTP已支持团队远程访问。
MCP/Agent以后持有同一RetrievalService实例，不每次工具调用重新启动；网络认证/传输另片实现。

文档说明2执行/20等待、端到端超时与HTTP等待区别、取消保留槽位、无自动重试、状态及关闭失败处理。
提供只使用新入口的十条突发合成验收和Linux真实资料验收命令；输出聚合耗时/执行重叠/峰值RSS，
不输出原问题/证据/凭据。2路和4路分开测，不声称无GPU机器已达到未测吞吐。

门禁：相关新测试、原生并发双索引/更新、全部tests、build、分发内容和Twine检查、离源码安装入口smoke。
系统原生调用永久卡死仍是第一版已接受边界；有限关闭测试必须能主动释放受控阻塞，避免挂死测试进程。
不自动提交/发布/部署；0.1.0不可覆盖发布，后续版本发布需用户授权。回退新模块和模板即可，不改用户数据。

## 最终本机验收（2026-10-28）

- `.venv/bin/python -m pytest -q tests --tb=short`：2424 passed in490.51s。
- 独立原生测试：十条全部受理并返回、2条真实执行重叠、热查询全库重放0、并行发布时旧请求revision1/新请求revision2。
- `.venv/bin/python -m build --outdir dist/shared-retrieval-final`成功；wheel129文件、sdist136文件，含serving全部模块。
- `scripts/inspect_distribution.py`、`twine check --strict`、compileall、源码与安装环境pip check及git diff --check通过。
- 从全新虚拟环境在线安装候选及全部依赖，然后以pip --no-deps --force-reinstall换装最终wheel，
  在/tmp以该环境Python -I运行scripts/installed_smoke.py，最终status=passed、installed_version=0.1.0、
  native_documents=2、revision=1、query_evidence=2、shared_retrieval_queries=10、model_requests=29、
  real_vendor_requests=0、weights_downloaded=false、reopened_after_process_crash=true。
- 平台为macOS26.4 arm64/Python3.12.14；真实Chroma/BM25/SQLite、合成HTTP模型。
  当前Mac Ollama未运行，未把该smoke标为本轮真实Ollama并发或LinuxCPU吞吐证明。

最终本地候选仍沿0.1.0源码版本构建，仅用于验证，不能覆盖已发布版本。
wheel SHA256：537fbb14193ae7981b9529fde9ad2cb21f935e79db3f40f40b090b195f8db547。
sdist SHA256：b25e571fdd5d4bb92ddbc3a97a6176dad106e1c83d61e59d2d8dfcb2182ebc97。
详见docs/shared-retrieval.md；Linux可运行python -m naiyue_rag.serving.benchmark，分别比较2/4路真实材料。
未提交、push、发布、远程部署或修改真实配置；下一步须先安排新版本/候选交付，再由用户在Linux回传聚合验收。
