# arXiv Research Radar

**本地研究雷达：可解释的论文推荐、版本追踪与有证据约束的 Agent 解读。**

[English](README.md) · [Agent 操作合同](docs/agent-harness.md) · [配置说明](docs/configuration.md) · [参与贡献](CONTRIBUTING.md)

持续跟进研究方向，知道每篇论文为什么被推荐，也知道一次扫描是否完整。

![arXiv 研究雷达界面](docs/images/dashboard.zh-CN.png)

## 能做什么

- **获取论文：** 按研究分类扫描 arXiv 官方元数据，支持分页、请求限速、重试与原始响应归档。
- **解释推荐：** 根据研究配置匹配标题和摘要，展示命中的关键词与方向。
- **追踪变化：** SQLite 去重合并跨分类记录，区分首次发现与版本更新，保留收藏和阅读反馈。
- **约束解读：** 导出待阅读队列，由人工或外部 Agent 生成解读；导入时核对论文版本和摘要原文引文。
- **集中阅读：** 本地界面支持英中切换、搜索、筛选、收藏、运行记录、Markdown 简报与 BibTeX 导出。
- **说明覆盖：** 扫描中断、达到分页上限或降级至 RSS 时明确标注；RSS 不会被当作完整历史扫描。

检索和界面**只依赖 Python 标准库，不需要模型 API Key**。程序自身不调用大模型；中文解读由外部 Agent 生成 JSON 后导入。详见 [Agent 操作合同](docs/agent-harness.md)。

## 快速开始

需要 **macOS 或 Linux，以及 Python 3.10+**。扫描锁使用 `fcntl`，目前不支持 Windows。

```bash
git clone https://github.com/xiangyanjin/arxiv-research-radar.git
cd arxiv-research-radar
```

**先体验离线示例：**

```bash
python3 examples/load_demo.py
ARXIV_RADAR_DATA_DIR=data/demo python3 -m radar serve
```

打开 **[http://127.0.0.1:8765](http://127.0.0.1:8765)**。示例使用公开论文元数据的部分快照，存储在独立的 `data/demo` 目录；它不是实时或完整扫描结果。

**建立自己的论文库：** 停止示例服务后运行：

```bash
python3 -m radar scan
python3 -m radar serve
```

使用界面时保持服务终端运行。也可以先启动 `serve`，再从界面发起扫描。

首次默认回溯 14 天。后续从上一次完整覆盖的范围继续扫描，并保留重叠区间，避免接口故障造成日期遗漏。选择较多分类时，首次扫描可能需要几分钟；进度和覆盖情况会保存到本地。

## 配置自己的方向

```bash
cp config/profile.json config/profile.local.json
```

在本地副本中修改分类、研究方向、关键词和推荐阈值。该文件已被 Git 忽略，并优先于仓库默认配置加载。附带示例覆盖随机矩阵、张量统计、马尔可夫链和集中不等式，你可以换成自己的方向。

也可以使用 `ARXIV_RADAR_PROFILE` 指定配置文件、使用 `ARXIV_RADAR_DATA_DIR` 指定数据目录。[查看配置说明 →](docs/configuration.md)

## Harness 如何工作

```text
arXiv API → 原始数据归档 → SQLite + 可解释排序 → 本地界面
    │                           │
    └─ RSS 降级（部分覆盖）       └─ 待解读队列
                                     │
                               人工 / 外部 Agent
                                     │
                                版本与引文校验
                                     │
                                研究简报与通知账本
```

```bash
python3 -m radar review-queue --output data/review-queue.json
# 由外部 Agent 阅读队列，生成 data/reviews.json。
python3 -m radar import-reviews data/reviews.json
python3 -m radar digest
```

[Agent 指南](docs/agent-harness.md) 提供 JSON 格式和可复用提示词。有终端和文件访问能力的编码 Agent 可以按合同运行；仓库没有内置专用 Codex 或 Claude Code 集成。

## 每日使用

通过你选择的调度器定时运行 CLI。**克隆仓库或启动界面不会自动创建或启用定时任务。** [调度说明](docs/scheduling.md) 包含时区、失败处理和通知去重约定。

| 命令 | 用途 |
| --- | --- |
| `python3 -m radar scan --days 7` | 请求扫描最近七天 |
| `python3 -m radar status` | 查看最新运行与本地状态 |
| `python3 -m radar delivery-plan --output data/delivery-plan.json` | 生成尚未确认通知的论文和版本清单 |
| `python3 -m radar acknowledge data/delivery-plan.json` | 将准备通知的范围写入本地账本 |
| `python3 -m radar serve --port 8766` | 更换本地界面端口 |

`acknowledge` 是本地去重记录，不是邮件或消息平台的送达回执。仓库未内置邮件或聊天推送连接器。

## 当前边界

- 相关性分数来自规则匹配，**不代表概率、论文质量或证明正确性**。
- 解读证据限于**摘要**。原文引文校验可发现引用不匹配和过期版本，但不保证生成内容的每个判断都正确。
- RSS 公告日期与 API 首稿、修订日期分别存储。
- 收藏、已读等反馈会持久保存，目前不会训练排序模型。
- 这是本地单用户工具，服务绑定 `127.0.0.1`，不是托管的多人协作平台。

## 参与开发

```bash
python3 -m unittest discover -s tests -v
```

测试使用本地样例和模拟网络响应，不请求真实 arXiv。欢迎改进检索正确性、可解释排序、无障碍体验与可复现评测。提交前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

作者：[向彦瑾 / Yanjin Xiang](https://xiangyanjin.github.io/)。项目与 arXiv 无隶属关系。代码采用 [MIT 许可](LICENSE)，链接论文保留各自的许可。
