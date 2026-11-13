# Windows 安装包

## 当前版本：0.7.1

从 [GitHub 发行页](https://github.com/Rhonsua/deskpet/releases/tag/v0.7.1) 下载 `TianyiPet-0.7.1-Setup.exe`，退出旧桌宠后安装。版本号以 `deskpet/version.py` 为准；安装包不会自动包含后续源码修改。

安装包包含 Python、Qt、Live2D 运行依赖和当前洛天依素材，排除 Miku、自定义角色、Mod 本体、个人音乐、聊天记录、API 配置及语音模型。语音模型和 GPT-SoVITS 环境单独准备，见[语音包说明](../deskpet/speech/README.md)。B站播放需要 Microsoft Edge WebView2 Runtime，登录或验证由用户在网页完成。

首次进入工作模式，缺少环境时会先准备校验过的 Node.js，再安装锁定版本的官方 DSH；不修改系统 PATH。工作会话和后台环境保存在应用用户数据目录，应用更新不会覆盖。版本清单以 `deskpet/chat/harness_runtime.py` 与自动安装模块为准。

## 构建

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements/build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm packaging/deskpet.spec
.\.venv\Scripts\python.exe packaging/build_installer.py
```

`build_installer.py` 默认读取当前版本，必须与源码版本一致；对应更新公告需在 `docs/release-notes/` 中。需要免安装包时才添加 `--portable`。打包使用 PyInstaller 目录模式，以及 Windows 的 IExpress 和 .NET Framework C# 编译器。前台和后台分别使用可执行入口，让音频、网页辅助进程保留通信管道。

输出按当前版本命名：

- `dist/TianyiPet-0.7.1-Setup.exe`：安装包。
- `dist/SHA256SUMS.txt`：发行附件校验值。
- `dist/TianyiPet/`：构建后的程序目录。
- `build/`：可重新生成的构建中间文件。

目标陪伴与工作人设 Mod 分别通过 `packaging/build_goal_mod.py`、`packaging/build_work_persona_mod.py` 构建为独立 ZIP。语音安装助手位于 `packaging/voice_setup/`，与桌宠安装包和语音模型分别分发。

## 检查与清理

```powershell
.\.venv\Scripts\python.exe tests/run_suite.py
.\.venv\Scripts\python.exe tests/smoke_installer.py
```

安装检查使用临时目录，不改变真实快捷方式和注册表。`tests/harness_smoke.py` 可单独检查打包后的工作后端；其 `--strict-path` 选项屏蔽开发机的 Node.js、Python 等 PATH 依赖，使用模拟模型接口检查读写文件、命令、审批、取消与恢复。

`build/`、`preview/`、临时安装测试目录与字节码缓存均可重新生成；有效回归测试保留。安装包按用户指定版本保留，不再按旧文档中“保留 0.5.0 及以后全部版本”的规则累积。2026-11-08 的本机清理保留现有 0.7.0 安装包、语音助手和独立 Mod 包；2026-11-13 将后续源码更新打包为 0.7.1，保留上一版 0.7.0。详细删除清单见本机 `local-work/cleanup-latest.json`。

历史更新说明保留在 `docs/release-notes/`，历史构建命令不要用于当前源码。`build/` 和 `dist/` 不提交 Git；安装包只通过 Releases 附件发布。

## 安装与卸载

默认安装到 `%LOCALAPPDATA%\Programs\TianyiPet`，无需管理员权限，可选桌面快捷方式，并提供开始菜单和卸载入口。更新时先退出运行中的桌宠；开机自启由用户在设置中选择。

卸载依据安装清单删除程序文件，保留个人数据和额外放入目录的文件，不递归清空整个安装位置。安装包未签名，本机检查不等同于已验证所有电脑或杀毒软件环境。

## GitHub 发行版更新

0.6.2 起支持后台检查 GitHub 正式发行版并由用户选择是否更新；0.6.1 及更早版本需先手动安装本版。安装器优先读取已有安装的位置作为默认目录。客户端在用户同意后下载安装包，校验通过后再次确认退出，再打开正常安装界面，不静默覆盖运行中的程序。

维护者需将对应版本的 `TianyiPet-<版本>-Setup.exe` 与 `SHA256SUMS.txt` 上传到 `Rhonsua/deskpet` 的 GitHub Release，标签使用 `v<版本>` 并标记为 Latest；文件仍不加入 Git 提交。详见 [GitHub 发行与更新](../docs/guides/GitHub发行与更新.md)。

## 安装独立目标 Mod

在桌宠的「扩展功能 / Mod」中点击「打开 Mod 文件夹」，把独立 ZIP 解压到该应用数据下的 `mod-packages` 文件夹，使 `goals/mod.json` 和 `goals/entry.py` 直接位于其中。退出并重新打开桌宠后启用「目标陪伴」。扫描只读取信息；仅启用后执行代码，已启用状态可在重启后恢复。目标数据库独立保存在应用数据 `mods/goals/goals.db`，停用不删除数据。Python 扩展没有沙箱，仅安装和启用可信来源的包。

安装检查会读取可执行文件的 CArchive/PYZ，断言无 `deskpet.mods.goals`，然后使用冻结程序 `--self-check --mod-pack <独立ZIP> --report <临时报告>`，在隔离数据路径先验证空扩展列表，再解压独立 ZIP、启用、创建页面、保存目标、经统一通知接口提醒和检查持久化。此过程不触碰真实存档，也不调用模型服务。
