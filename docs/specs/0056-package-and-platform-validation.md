# Spec0056：首版第5片／发行物和平台验收

日期2026-10-26，依赖0052–0055。实现与本地构建已获授权；提交/push、标签、PyPI上传、正式许可证/版本另确认。

## 发行合同

新增pyproject.toml，setuptools构建wheel/sdist，包名naiyue-rag，nyr=naiyue_rag.cli:main。暂用0.1.0.dev0本地候选（唯一版本源_version.py），Python限制3.12以对应本轮实际ABI，后续扩版本另测；不擅选项目许可证。显式包发现正式core/encoding/ingestion/query/reranking/response/storage/validation及resources，排除旧实验依赖的bootstrap/a2_snapshot等早期顶层模块（保留仓库资产和已有测试），不把experiments克隆打进包。正式根导出及app直接依赖都须在wheel中；validation只含正式核心消费者。

按真实import和运行时版本门禁固定直接依赖：openai/jiter、httpx、python-dotenv、PyYAML、markdown-it-py、langchain-text-splitters、jieba、numpy、chromadb、bm25s、FastAPI/Starlette/Uvicorn及完整本地重排栈。所有功能默认安装；测试/实验框架不为正式运行依赖，开发依赖单独列文件。不复制整个旧虚拟环境或macOS专用hash锁作为三平台锁，不升级原有固定运行版本。构建不初始化HOME或下载权重。

## 平台边界（用户本轮明确接受）

Linux x86_64、Windows x86_64、macOS arm64目标（CI为ubuntu-24.04/windows-2022/macos-15，标签/架构依据GitHub官方runner说明且运行时核对），首轮Python3.12；具体系统支持只随实际runner/主机证据声明。BundleStore._sync_directory在Windows仅检查真实目录并记录directory_sync_unavailable平台限制，不调用不支持的POSIX目录open/fsync；文件fsync、SQLite事务、三制品完整性和激活前审计均保留。POSIX仍真实目录fsync并传播失败；不对任意IO错误降级。Windows不声称突然断电时与POSIX目录同步相同的持久性，正常关闭/进程异常后的恢复仍须实际主机测试。来源：[Microsoft目录句柄](https://learn.microsoft.com/en-us/windows/win32/fileio/obtaining-a-handle-to-a-directory)、[FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers)。

## 发行物验证

先失败测试核对元数据、全功能依赖、入口、资源和归档边界；再构建。干净临时venv从wheel安装全部依赖，pip check，离开源码目录且不补sys.path/PYTHONPATH执行nyr帮助/默认初始化/HTTP服务/chat生命周期及合成材料闭环。合成模型通过本机测试HTTP服务提供符合SDK合同的固定向量/重排响应，Chroma/BM25/SQLite全部原生；不下载模型权重、不请求真实厂商或真实用户材料。

CI矩阵在三个真实系统独立构建/干净安装/执行同一smoke；正式源码独立测试集由macOS作业执行，明确文件清单不依赖私有旧快照；本机仍执行包含历史实验的完整回归，不将旧实验源码暗带入发行物。未执行的远端CI写待验，不能把配置文件存在当平台通过。wheel/sdist逐项审计，无真实配置/.env/凭据、知识库、下载模型、测试/实验源码或构建缓存；hash记录供候选复核。发布前另确认包名可用、版本、许可证、目标账号和最终上传范围，不自动发布。

影响pyproject/MANIFEST、发行文档、CI、smoke脚本、BundleStore目录同步最小分支和对应测试。失败不改用户索引、不重置配置；发行候选可弃置，源码资产不删除。实际命令/环境/限制实施后补充。

## 首次发行物与独立套件核验

首次构建wheel118文件/sdist125文件，归档边界检查通过；完整运行依赖在全新临时venv一次安装成功，pip check为No broken requirements found。离开源码目录以-I执行installed_smoke.py，实际结果：macOS26.4 arm64/Python3.12.14、2份文档、revision1、2条证据、3次合成本机模型请求、真实厂商请求0、权重下载false，status=passed。此为本机候选证据，Linux/Windows以及macOS15 runner尚未执行。

CI正式清单按实际消费者审计：旧core_contract_wiring执行未随包发布的A2适配，evidence_units/markdown_checks只测试experiments，与缺私有快照/实验专用LlamaIndex有关；保留在本机完整套件，不纳入正式独立套件。为清单新增架构门禁，不放宽这些历史测试本身的断言或skip；干净源码副本还须有Git元数据，供既有.env忽略规则测试使用。独立套件使用真实新依赖解析环境与不含data/.venv-lightrag的副本重新验证，最终结果后附。

## 最终发行候选

发行物位于dist/（Git忽略，不随源码提交）。最终wheel118文件/196554字节，SHA256=59bd37096b7c1b12807aa55ec9ff59ff817c950667d8723afee9f22763509fbe；sdist125文件/194379字节，SHA256=92a463ed6bd53fcc9f01f465eda42e40756a6f390180b10697b31cfe4bf1ef59。

`python scripts/validate_candidate.py --wheel /tmp/nyr-reviewed-dist/naiyue_rag-0.1.0.dev0-py3-none-any.whl --venv /tmp/nyr-reviewed-install-01a17887/venv`退出0。该全新环境由一次pip安装全部运行依赖，pip check无破损；不安装pytest/历史实验包。随后-I且离开源码cwd执行真实nyr，JSON结果status=passed、macOS26.4/arm64/Python3.12.14、2份文档、revision1、2条证据、9次合成本机模型HTTP请求、真实厂商0、权重下载false、reopened_after_process_crash=true。覆盖终端真实查询、服务复用、正常信号关闭、稳定版本进程强杀后的新进程重开；不把后者说成任意发布时点或机器断电证明。

归档成员路径先以Windows路径语义模拟暴露1项红灯，改用归档规范的PurePosixPath解析，拒绝绝对/穿越/反斜杠成员；发行合同5 passed in0.27s，真实wheel/sdist审计仍通过。这是审计工具的可移植性测试，不替代Windows本机执行。

## 最终回归与L1/L2/L3

冻结最终生产源码后，本仓库`.venv/bin/python -m pytest -q tests --tb=short`：2352 passed in479.72s (0:07:59)，包含保留的历史测试。由Git源码/本轮文件构造、不含data/.venv-lightrag的独立Git副本，使用新依赖环境运行`python scripts/run_formal_tests.py`：1681 passed in422.97s (0:07:02)。运行开始后仅新增归档工具回归测试，随后发行合同5 passed；无后续生产代码变化。完整命令中的计数不伪写为未实际运行的2353/1682。

build退出0，compileall退出0，当前开发环境及最终纯运行环境pip check均No broken requirements found，git diff --check退出0。L1：0052–0056、统一模板、CLI/服务/打包/CI文件存在；L2：严格配置/凭据、显式认证/预算、进程归属与资源清理为真实实现；L3：最终SHA对应wheel从全新环境真实进入nyr并完成原生闭环，不经源码cwd或PYTHONPATH补丁。

剩余：三平台GitHub Actions尚未push运行，Windows/macOS15 runner/Linux主机结果待验；不把本机Mac26证明为三平台完成。0.1.0.dev0仅本地候选，未提交/push/tag或上传PyPI，许可证/正式版本/发布账号另确认。既有用户配置、真实.env、原始知识库、模型权重与历史快照未修改。
