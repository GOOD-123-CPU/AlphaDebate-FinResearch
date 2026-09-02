# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [2.1.0] — 2026-09-03

### Added
- **多空对抗辩论引擎**：`DEBATE_MODE=adversarial` 下 Generator A 扮演多头研究员、
  Generator B 扮演空方/风控研究员，第二轮修订强制正面回应对手论点，
  Judge 中立仲裁；`parallel` 保留原始平行视角模式
- **辩论过程透明化面板**：前端新增「辩论过程」标签，展示四份稿件得分、
  双方优势与短板、胜者，以及多空终稿的五维评分雷达图（ECharts）
- **行情图表可视化**：新增 `/stock_chart_data`、`/stock_quote` 接口，
  前端 ECharts 渲染 30 日 K 线与成交量（涨红跌绿，A 股惯例）
- **全市场股票搜索**：新增 `/search_stocks` 接口与前端防抖搜索，
  覆盖沪/深/北三市代码与名称（本地 6 小时缓存底表）
- **历史报告中心**：新增 `/report_list` 接口与「历史报告」标签，
  报告列表带最终评分，点击回看
- **真流式输出**：LLM 客户端支持 OpenAI `stream=true` SSE 逐 token 推送，
  服务商不支持时自动回退模拟分块；主备 Key 401 自动切换
- **XSS 防护**：所有 Markdown 渲染统一经 DOMPurify 消毒
- 社区文件：CONTRIBUTING.md、CODE_OF_CONDUCT.md、SECURITY.md、
  DISCLAIMER.md、CHANGELOG.md

### Changed
- 配置中心新增 `DEBATE_MODE`、`LLM_STREAM` 环境变量（`.env.example` 同步）
- 辩论模式与完整评分记录写入 `result/metadata/*.json` 供前端回放
- README 重写核心特性与辩论引擎工作流（mermaid 时序图）

### Fixed
- 修复非流式 `/generate_report` 路由 `force_refresh` 未定义的 NameError
- 修复模板 `url_for` 端点未按蓝图命名导致的 BuildError

## [2.0.0] — 2026-09-03

### Added
- 全新开源就绪仓库（Flask 应用工厂 + 蓝图架构：auth/report/qa）
- 多 LLM 辩论式研报生成（双生成器 + 评审官，5 维度×20 分评分）
- 四类研报模板（股票分析/前景分析/风险预测/行业市场分析）
- AkShare 沪深京三市结构化数据抓取，组件级 JSON 缓存与降级
- SSE 流式生成（进度/草稿/正文逐字推送）
- 报告追问问答（LLM 联网增强 + 报告回退）
- 微调闭环：4 类金融分析指令数据（约 13MB）+ Unsloth LoRA 训练/推理脚本
- 密钥全部环境变量化（.env），仓库零硬编码密钥
- MIT License、CI（Python 3.10–3.12）、Dockerfile、部署文档

### Removed
- 移除旧版 MetaGPT 多智能体 RAG 引擎（约 2800 行重依赖代码，
  见 `docs/architecture.md` 历史演进说明）
- 移除全部硬编码 API Key 与内网服务器路径
- 572MB 完整训练集不入库（保留 4 个分项子集）

[Unreleased]: https://github.com/GOOD-123-CPU/finsightpro/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/GOOD-123-CPU/finsightpro/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/GOOD-123-CPU/finsightpro/releases/tag/v2.0.0
