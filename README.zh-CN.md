# RePoE

[English](README.md) | **简体中文**

面向《流放之路》工具开发者的游戏数据。本 fork 维护 PoE2 客户端导出器和 [PoBR](https://github.com/ackness/pobr) 使用的游戏数据包，同时保留上游的 PoE1 与 PoE2 解析器。

RePoE 读取客户端资源，保留它们的身份与相互关系，并把选定的事实转换成带版本的 JSON 包。每个包都记录其来源字节、生产者和验证范围。

## 从这里开始

| 你想要…… | 阅读 |
| --- | --- |
| 使用已发布的游戏数据包 | tag 为 `game/<patch>-<n>` 的 [GitHub Releases](https://github.com/ackness/repoe/releases)（[Release 包含什么](RELEASING.md#publish)） |
| 搭建导出器环境或在本地导出 | 下文的[开发](#开发)与[导出数据](#导出数据) |
| 把事实转换成 PoBR 运行时 JSON | [Rust 数据适配器](tools/pobr-data-adapter/README.md) |
| 构建并发布新的 PoBR 游戏包 | [RELEASING.md](RELEASING.md)（`release:build` → `release:publish` → PoBR `data:bump`） |
| 查看客户端资源及其来源 | [客户端获取](RePoE/docs/client/client-sources.md)与[资源查找](RePoE/docs/client/client-index.md) |
| 查找某个领域的 schema 或验证范围 | 下文的[数据契约](#数据契约)与[文档索引](RePoE/docs/README.md) |
| 在这里修改代码或数据 | [AGENTS.md](AGENTS.md)（规则、目录结构、验证）与 [CONTRIBUTING.md](CONTRIBUTING.md) |

## 在 PoBR 生态中的角色

RePoE 负责客户端事实与游戏包；[poe2-zh-cn-stats](https://github.com/ackness/poe2-zh-cn-stats) 负责语言数据；[PoBR](https://github.com/ackness/pobr) 负责计算，并 pin 住两个包。职责与边界只在一处定义：PoBR 的[数据架构](https://github.com/ackness/pobr/blob/master/docs/data-architecture.md)；当前缺口见[数据现状](https://github.com/ackness/pobr/blob/master/docs/data-status.md)。

## 提供什么

| 层 | 内容 | 使用者 |
| --- | --- | --- |
| 客户端输入 | 明确选定的客户端资源、schema pin、获取回执与资源摘要 | 导出器与来源校验 |
| 原生事实 | DAT 行、天赋图、宝石与物品身份、角色关系、元数据，以及有序的 CSD 描述分支 | 领域适配器与翻译仓库 |
| 游戏包 | PoBR 运行时 JSON、单独标识的兼容输入与来源回执 | PoBR 的固定输入流水线 |
| 旧版导出 | 属性、词缀、基底物品、宝石、职业、制作及其他上游 JSON 格式 | 现有 PoE 工具 |

各个包的范围不同。事实导出成功不代表游戏语义完整。本地化文本不代表国际服与国服数值相同。部分运行时字段仍保留明确 pin 住的 PoB2 或社区解释；领域契约记录了这些限制。

## 使用已发布的包

每个游戏包是一个 GitHub Release `game/<patch>-<n>`，带三个附件：`pobr-game-<patch>.zip`、它的 `receipt.json`（生产者提交、契约、每个输入的 pin 和每个成员的来源类别）以及 `SHA256SUMS`。PoBR 在 `pipeline/data.lock.json` 中 pin 一个游戏 Release 和配套的语言 Release（`mise run data:bump`，见 PoBR 的 [RELEASING.md](https://github.com/ackness/pobr/blob/master/RELEASING.md)）。使用者不需要 Python、Rust、客户端安装或本仓库的 checkout。

使用 Release 之前发布的包（以及 `release:build` 读取的较早输入）位于由 `handoff/*` tag 保持可达的孤立提交上。这些 tag 从不移动或删除：`release/<patch>[-<n>]/inputs.lock.json` 通过提交、路径和 SHA-256 定位它们。新的输入是 GitHub Release `inputs/<patch>-<n>`（`mise run release:inputs`），与游戏包一样按仓库、tag、附件和 SHA-256 定位。

## 开发

安装 [mise](https://mise.jdx.dev/)，在仓库根目录运行：

```sh
mise trust
mise install --locked
mise bootstrap --only packages
mise run setup
mise run check
```

`mise.lock` pin 住 Python 和 uv；`uv.lock` pin 住 Python 依赖，包括 PyPoE 的完整 Git revision。`setup` 用 `uv sync --locked` 创建 `.venv`。首次安装需要联网；在没有可用 wheel 时，Linux 的编译器／JPEG／zlib 软件包用于构建 pin 住的 Pillow 版本。

`check` 校验依赖锁和 schema 校验和，运行 Ruff 和离线回归测试，并检查 CLI。它不下载客户端，也不发布数据。只想做更窄的检查时用 `mise run test` 或 `mise run lint`。

Rust 适配器是一个独立的 Cargo workspace，有自己的锁和根目录的 `rust-toolchain.toml`：

```sh
mise run adapter -- --help
mise run adapter:check
mise run adapter:keystones
```

`adapter:keystones` 从最高的 `release/<patch>[-<n>]/` 声明的 `reference` 包（目前是 `game/0.5.5.5-1`）的天赋树重建基石规则，并逐字节比较。生成的 `RePoE/model/` 文件用 `mise run models:generate -- [schema 路径]` 显式维护。

CI 有两个 workflow。`verify.yml`（每个 PR 和 master push）运行 `mise run check`，另一个作业运行 `adapter:check` 和 `adapter:keystones`。`release-build.yml` 只在发布构建读取的内容改变时运行（`RePoE/release/`、它导入的 client 模块、`release/`、适配器、mise 与工具链文件），用 `release:build -- --config release/<dir> --fetch --check` 重建每个声明。

## 导出数据

使用旧版导出器时，选择本地客户端和单独的输出目录：

```sh
mise exec -- uv run --locked --offline repoe --help
mise exec -- uv run --locked --offline repoe stat_translations --poe2 \
  --file /path/to/client --outdir .cache/exports/client-descriptions
```

PoE2 的 `stat_translations` 默认读取客户端描述。可选的离线交易文本关联需要显式提供快照；见[描述契约](RePoE/docs/stat_translations.md#poe2-offline-trade-candidates)。`uv --offline` 只控制依赖解析：`--file` 选择本地客户端数据，其他导出模块可能有各自的网络行为。

原生导出器使用明确的来源锁和已校验的原始资源。例如：

```sh
mise run facts:candidate -- --source-lock /path/to/source-lock.json \
  --source SOURCE_KEY --raw /path/to/raw-resources --out .cache/facts/example
```

默认原生 profile 覆盖八张 DAT 表和 PSG。可选的 `core-skills-a0`、`gems-constraints-a1` 和 `items-actors-bc` profile 扩展导出的事实；它们的契约说明输入、schema 和限制。其他领域请使用对应的[契约](#数据契约)，不要把部分 profile 当作完整的游戏快照。

客户端解码使用单独选定、带指纹的环境。与回执绑定的环境保持不变；工具链升级在另一个环境中测试。[`schema/`](schema/README.md) 说明固定 schema 和候选流程。

## 目录结构

```text
RePoE/parser/                 上游 PoE1 与 PoE2 导出器（repoe CLI 是 RePoE/run_parser.py）
RePoE/poe/                    上游 PyPoE 文件格式扩展
RePoE/schema/, RePoE/model/   上游旧版 JSON schema 及其生成的模型
RePoE/client/                 补丁观测、获取、草稿、资源查找、来源信封
RePoE/native/                 原生事实、表、描述、继承、制作和玩家上下文导出器
RePoE/release/                游戏包的构建、发布与输入打包，以及发布作业
RePoE/trade_snapshot.py       stat_translations 使用的离线交易文本快照读取器
RePoE/docs/                   格式与契约，按代码分组（索引：RePoE/docs/README.md）
release/                      每个游戏包一个 pin 住的声明（release/<patch>[-<n>]/）
schema/                       pin 住的 dat-schema 及其来源
sources/                      原始材料来源台账与保留的来源元数据
tools/pobr-data-adapter/      Rust 适配器、它的 policies/ 和按领域的 docs/
tests/                        离线 Python 回归测试：client/、native/、release/、parser/
scripts/                      维护脚本（复现 PyPoE pin）
.github/workflows/            verify.yml 与 release-build.yml
.cache/                       本地候选、导出与发布构建；Git 忽略
RePoE/data/                   旧版导出的默认目录；Git 忽略
```

哪些路径来自上游、新代码放在哪里、哪些文件必须保持字节不变：见 [AGENTS.md](AGENTS.md#layout)。

## 数据契约

| 主题 | 文档 |
| --- | --- |
| 客户端获取与补丁观测 | [来源](RePoE/docs/client/client-sources.md)、[版本](RePoE/docs/client/client-version.md)、[草稿](RePoE/docs/client/client-source-draft.md)、[查找](RePoE/docs/client/client-index.md)、[校验](RePoE/docs/client/source-rebinding.md) |
| 原生技能与宝石 | [基础事实](RePoE/docs/native/native_facts.md)、[核心技能](RePoE/docs/native/native_core_skills.md)、[宝石约束](RePoE/docs/native/native_gems.md) |
| 物品与角色 | [物品／角色事实](RePoE/docs/native/native_items_actors.md)、[物品继承](RePoE/docs/native/native_item_inheritance.md)、[角色模板](RePoE/docs/native/native_actor_templates.md)、[玩家上下文](RePoE/docs/native/native_player_context.md) |
| 描述与语言 | [CSD 分支](RePoE/docs/native/native_descriptions.md)、[补充／本地化表](RePoE/docs/native/native_tables.md)、[描述关系](RePoE/docs/native/description_relations.md) |
| 制作与天赋树 | [制作事实](RePoE/docs/native/native_crafting_facts.md)、[PoBR 制作目录](RePoE/docs/release/pobr_crafting_catalog.md)、[历史天赋树选择器](RePoE/docs/release/pobr_historical_trees.md) |
| PoBR 运行时转换 | [适配器模式](tools/pobr-data-adapter/README.md)与[领域 policy](tools/pobr-data-adapter/policies/README.md) |
| PoBR 运行时领域 | [ordinary-facts 领域](tools/pobr-data-adapter/docs/ordinary-facts.md)，每个领域一个 `docs/ordinary-<domain>.md` |
| 旧版 JSON 格式 | [属性](RePoE/docs/stats.md)、[词缀](RePoE/docs/mods.md)、[物品](RePoE/docs/base_items.md)、[宝石](RePoE/docs/gems.md)、[augments](RePoE/docs/augments.md)，以及[其他领域文件](RePoE/docs/README.md#legacy-json-formats-repoeparser) |

文档（除本页外）均为英文。

## 上游与致谢

本仓库从保留的上游 fork 快照开始。一次性的历史裁剪、提交映射和已有 checkout 的迁移见[历史与克隆大小](RePoE/docs/history.md)。

本 fork 源自 [repoe-fork/RePoE](https://github.com/repoe-fork/RePoE) 和 [brather1ng/RePoE](https://github.com/brather1ng/RePoE)，最初为 PoESkillTree 开发。客户端解析使用 [PyPoE](https://github.com/Project-Path-of-Exile-Wiki/PyPoE) 和 [poe-tool-dev DAT schema](https://github.com/poe-tool-dev/dat-schema)。

代码许可见 [LICENSE.md](LICENSE.md)；schema 的署名见 [schema/](schema/README.md)。《流放之路》游戏数据归 Grinding Gear Games 所有。发布的来源与生成的数据保留各自上游的权利。
