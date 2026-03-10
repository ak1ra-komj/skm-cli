---
created: 2026-03-10
tags:
  - install
  - linker
  - ux
---

# 安装时处理已存在的非符号链接技能目录

## 概要

`skm install` 在目标路径已存在非符号链接的文件或目录时会直接崩溃抛出 `FileExistsError`。本次 session 为此场景添加了交互式确认流程：提示用户选择覆盖或跳过。同时增加了 `--force` 命令行参数以支持非交互式场景下的自动覆盖。确认交互使用 `click.getchar()` 实现单键响应（无需按回车），覆盖时输出洋红色提示信息。

## 修改的文件

- `src/skm/linker.py` — `link_skill` 函数新增 `force` 参数，当 `force=True` 时自动移除已存在的文件/目录后创建符号链接
- `src/skm/commands/install.py` — `run_install`、`_install_local`、`_install_repo` 新增 `force` 参数传递；在 `link_skill` 调用处捕获 `FileExistsError`，通过 `_confirm_override` 提示用户确认或跳过；新增 `_confirm_override` 辅助函数
- `src/skm/cli.py` — `install` 命令新增 `--force` 选项
- `tests/test_linker.py` — 新增 3 个测试：非符号链接目录抛异常、`force` 覆盖目录、`force` 覆盖文件

## Git 提交记录

- `a8335fc` feat: prompt to override existing non-symlink skill dirs during install

## 注意事项

- 使用 `click.getchar()` 而非 `click.confirm()` 可实现单键响应（按 y 直接继续，不需要回车），提升交互体验
- `link_skill` 的 `force` 模式区分了目录（`shutil.rmtree`）和文件（`unlink`）两种情况
- 覆盖确认的逻辑放在 `install.py` 的调用方而非 `linker.py` 中，保持了 `link_skill` 作为底层函数不包含 IO 交互的职责分离
