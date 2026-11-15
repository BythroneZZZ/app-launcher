# app-launcher

面向 Windows 的**全屏应用启动器**：扫描开始菜单、桌面快捷方式与 UWP / 商店应用，
用 Steam Deck 风格的「聚光灯 + 卡片货架」展示并启动。图标主色会自动提取，
作为每张卡片的光晕与强调色。

纯本地运行，**无对外网络请求、无遥测、无账号**。

> Windows 10/11 · Python 3.10+ · PySide6 · MIT License
>
> [English quick start](#english-quick-start) · [贡献指南](CONTRIBUTING.md) · [安全与隐私](SECURITY.md)

## 快速开始

```bat
pip install -r requirements.txt

python launcher.py                  :: 全屏启动器
python launcher.py --windowed       :: 窗口模式（调试用）
python launcher.py --autostart      :: 创建开机自启快捷方式后退出（可选）
python launcher.py --uninstall      :: 移除自启并清缓存（加 --keep-cache 保留数据）
python test_logic.py                :: 纯逻辑单测，不需要 GUI / PySide6
python build.py                     :: 可选：PyInstaller 打包成 dist/AppLauncher/（需先 pip install pyinstaller）
```

> **先读这段再运行**：默认以**无边框全屏**启动，界面里没有常驻退出按钮。
> `Esc` 收起到任务栏，`Ctrl+Q` 或 `Alt+F4` 退出，或右键**系统托盘图标 → 退出**。
> 建议第一次用 `--windowed`。托盘左键可显示 / 收起，重复启动只会唤起已有实例（单实例）。

## 主要特性

- 扫描「用户 + 公共」开始菜单、桌面 `.lnk`，以及 `shell:AppsFolder` 里的 UWP / 商店应用
- 按目标 exe 去重、过滤卸载器与说明类快捷方式；同名但不同目标的应用都会显示
- 256px 系统图标提取 + 主色提取 + 自动裁白边；元数据、主图与缩略图落盘缓存，按修改时间失效
- 4 线程并行提取；扫描代际守卫避免取消后的迟到事件造成卡片翻倍
- 手动添加 / 拖拽添加（`.exe`、`.lnk`、`.url`）、隐藏与恢复、最近使用置顶、48h 角标
- 底部菜单岛分类 chips、150ms 防抖搜索、空结果一键清除；主界面任意输入直接落入搜索框
- 键盘导航（方向键 + Enter）、托盘菜单、管理模式（卡片抖动 + × 移除）、窗口化调试
- 视觉：预渲染卡面与动态阴影、缓存背景（噪点 + 暗角 + 双级辉光 400ms 补间）、
  海报淡入、骨架加载卡、缺图标首字母占位、悬浮半透明底栏
- 动效三档（180 / 240 / 400ms），尺寸与色板集中在 `theme.py`；尊重系统「减少动画」
- 日志滚动写入 `%LOCALAPPDATA%\AppLauncher\logs\`，未捕获异常自动记录

## 交互

| 操作 | 效果 |
|---|---|
| 左键点击卡片 | 启动应用（等同双击快捷方式），启动后自动收进托盘 |
| `Esc` | 最小化到任务栏；管理模式下先退出管理 |
| 方向键 + `Enter` | 移动焦点 / 启动 |
| 直接键入 | 落入搜索框，回车启动焦点应用 |
| 悬停卡片 | 聚光灯与背景主视觉联动（80ms 悬停确认，横扫不闪） |
| 底部菜单岛「＋ 添加」 | 手动选择 `.exe` / `.lnk` / `.url` 添加，持久化保存 |
| 拖文件进窗口 | 直接添加 `.lnk` / `.exe` / `.url` |
| 底部菜单岛「管理」 | 卡片抖动并出现 × 角标，点 × 移除 |
| 右键卡片 | 启动 / 移除（手动添加）或隐藏（扫描来的） |
| 右键空白处（非卡片区域） | 添加应用 / 进入或退出管理模式 |
| 分类 chips / 搜索框 | 按文件夹筛选 / 按名称搜索 |
| 托盘图标 | 显示启动器 / 仅显示我添加的应用 / 恢复全部隐藏 / 退出 |
| `Ctrl+Q` / `Alt+F4` | 退出 |

## 数据与隐私

程序**不发起任何对外网络请求**：源码里没有 HTTP 客户端、socket、更新检查或统计上报。
唯一的 `QtNetwork` 类是 `QLocalServer` / `QLocalSocket`，用于**本机命名管道**上的单实例
唤起，不监听网络端口。

- 读取：用户与公共「开始菜单 / 桌面」的 `.lnk` 文件名、目标路径、系统图标；
  `shell:AppsFolder` 中的应用名与 AUMID
- 写入：`%LOCALAPPDATA%\AppLauncher\`（`meta.json`、`icons/*.png`、`custom.json`、`logs/app.log`）
- 可选：`--autostart` 在用户 Startup 目录建快捷方式，**默认不启用**
- 启动应用使用 `os.startfile`（UWP 走 `shell:` 协议），与双击等价，不请求管理员提权

缓存与日志里会包含本机已安装应用的名称、路径与运行记录，**请勿提交到版本库或发给他人**；
提 issue 时请打码。完整行为清单与彻底清理方式见 [SECURITY.md](SECURITY.md)。

图标在运行时从用户本机提取，仓库内**不含任何第三方图标**。文档或 issue 中的截图可能
附带第三方应用商标，仅作识别用途，权利归各自所有者。

## 性能

- 首次启动：全量扫描 + 4 线程提取图标（IID 修正后 SHGetImageList 真正生效），随后把元数据、主图与 80px 缩略图写入缓存
- 热启动：主要开销是读 JSON 与解码缩略图（约为 256px 图的 2%），缓存命中通常在一秒内
- 参考量级（本机 144 应用 / SSD / PySide6 6.12，**测量起点 = 扫描线程启动，终点 = done 信号**，
  不含窗口构造与首帧渲染）：冷扫约 2.4–4.7s、热启动约 0.2–0.5s。
  UWP 列表落盘缓存（uwp_cache.json，24h TTL 跨进程），热启动不再含 COM 枚举。
  **注意**：IID 修正后首次启动会触发 v2→v3 缓存迁移（全量重提 256px 图标，约多 1–2s），之后恢复热启动速度。
  数值取决于快捷方式数量、磁盘缓存与机器性能，**不是性能保证**
- 实现上用了 `constBits()` 批量读像素、卡面预渲染、背景位图缓存、视口外卡面释放、
  动画组即用即毁，以控制 CPU 光栅下的重绘成本

## 高级选项

| 环境变量 / 参数 | 作用 |
|---|---|
| `AL_WORKERS=4` | 并行图标提取线程数（默认 4） |
| `AL_UWP=0` | 关闭 UWP / 商店应用枚举（排查用） |
| `--keep-cache` | 配合 `--uninstall`，只移除自启、保留缓存数据 |

## 项目结构

| 文件 | 作用 |
|---|---|
| `launcher.py` | 主窗口、卡片绘制、交互、单实例 IPC、托盘、日志 |
| `scan.py` | 扫描与图标提取（COM/UWP/并行/缓存路径/Workers） |
| `background.qml` | GPU 加速背景层（渐变 + 噪点 + 暗角 + 辉光；`AL_QML=1` 启用） |
| `theme.py` | 视觉 / 动效 / 布局 token（Qt-free，唯一事实来源） |
| `store.py` | 元数据与配置读写、缓存合并（Qt-free） |
| `build.py` | 可选的 PyInstaller 打包脚本 |
| `test_logic.py` | 无 GUI 的逻辑单元测试 |
| `test_e2e.ps1` | 手动截图脚本（**无自动断言**，坐标基于 1920×1080，输出到被忽略的 `screenshots/`） |

`test_logic.py` 只依赖 `store.py`，因此 CI 可以在不带 Qt 的 Linux runner 上跑。

## 已知边界

- 仅支持 Windows；依赖系统 Shell COM、开始菜单目录结构与 `shell:AppsFolder`
- UWP 图标优先走 `IShellItemImageFactory::GetImage` 256px（IID 实测修正为 BCC18B79）；
  接口不可用时退回 64px hIcon，再失败走首字母占位；UWP 显示名以 Windows 报告为准
- 以管理员权限运行的程序，从卡片启动默认不带提权
- 高 DPI、多显示器与非英文分类名的覆盖还不完整，欢迎反馈

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。最有帮助的贡献是**在另一台机器上跑一遍**并反馈
异常：不同的开始菜单结构、UWP 集合、多显示器、缩放比例、非 ASCII 分类名。

## 许可

本项目源码采用 [MIT License](LICENSE)。运行时依赖 PySide6（社区版 LGPLv3 / GPLv3）
与 pywin32（PSF / 混合许可），它们**不随本仓库分发**；构建工具 PyInstaller 为可选依赖。
若自行打包 exe 分发，需自行履行 LGPLv3 义务。
详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

## English quick start

A full-screen, offline application launcher for Windows. It scans Start Menu,
Desktop shortcuts and UWP / Store apps, and shows them as a Steam Deck-style
hero + card shelf. No outbound network requests, no telemetry, no account.

```bat
pip install -r requirements.txt
python launcher.py --windowed
```

Requirements: Windows 10/11, Python 3.10+, PySide6 6.6+, pywin32.

**Important:** the default mode is a borderless full-screen window with no visible
exit button. Press `Esc` to minimize, `Ctrl+Q` or `Alt+F4` to quit, or use the
tray icon. Start with `--windowed` on your first run.

The launcher reads local shortcuts and writes its cache and logs to
`%LOCALAPPDATA%\AppLauncher\`. Nothing leaves the machine; `QLocalServer` is used
only for local single-instance IPC. See [SECURITY.md](SECURITY.md) for the full
data boundary and cleanup instructions. When filing an issue, please redact your
user name and local paths from logs and screenshots.

Logic tests need no GUI: `python test_logic.py`. Contributions are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md). Licensed under MIT.
