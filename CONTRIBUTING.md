# 贡献指南

欢迎提交 issue 与 PR。这个项目是 Windows 桌面端的小工具，最需要的是**在不同机器上的真实反馈**：不同的开始菜单结构、多显示器、高 DPI 缩放、非英文分类名等，单机很难覆盖。

## 本地环境

- Windows 10 / 11
- Python 3.10+（开发验证环境为 3.11）
- `pip install -r requirements.txt`

```bat
python launcher.py --windowed   :: 调试时用窗口模式，别直接全屏
python test_logic.py            :: 纯逻辑单测，不需要 PySide6 / GUI
```

## 提交前检查

1. 运行 `python test_logic.py`，全部 PASS。
2. 运行 `python -m compileall -q launcher.py theme.py store.py build.py test_logic.py`。
3. 确认没有把本机信息带进提交：绝对路径（盘符 + 用户名）、截图、缓存文件、`custom.json`、`.env`、任何凭据。
4. 在 PR 描述里说明改动动机；若涉及视觉，附一张截图（`screenshots/` 已被忽略，可贴到 PR 里）。

## 代码约定

- `theme.py` 是尺寸 / 动效 / 色板 token 的唯一事实来源，新样式优先复用 token，不要在 `launcher.py` 里散落新的颜色与圆角字面量。
- `store.py` 与 `theme.py` 保持 **Qt-free**（不 import PySide6），这样 `test_logic.py` 才能在无 GUI 的 CI 上跑。
- 涉及缓存、配置、去重、扫描发射顺序的逻辑，请同时补一条 `test_logic.py` 里的行为测试；只做源码字符串匹配的断言不算测试。
- 新增 `QPropertyAnimation` / `QParallelAnimationGroup` 时，注意复用实例或 `deleteLater()`，历史版本出现过多次动画对象泄漏。
- 异常不要静默 `pass`；确实要忽略时写一行注释说明原因。

## 提交信息

用简短的英文或中文祈使句，例如 `fix: keep cache entries in manual-only mode`。
不要在提交信息、作者信息或文件内容里填写真实邮箱、姓名或本机路径。把
把 `ci/ci.yml.example` 复制到 `.github/workflows/ci.yml` 即可启用 CI，其中包含一次凭据扫描。

## 行为准则

保持友善、就事论事。安全相关问题请走仓库的私密漏洞报告通道，不要发在公开 issue 里。
