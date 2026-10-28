# Windows 试用安装包

最新发行物为 **0.5.0 EXE 安装包与免安装 ZIP**：包含 API 加载并行、边缘收起优化、摸头反馈、Live2D 左右散步、拖起闭眼挥臂，以及歌词跟随位置调整。运行 `TianyiPet-0.5.0-Setup.exe` 安装，或完整解压 ZIP 后运行 `TianyiPet.exe`。安装包剔除未使用的 Qt PDF、虚拟键盘及 QML 依赖和 AVIF 解码器，采用高压缩率；保留软件 OpenGL 与音频、TLS 后端。下文 0.4.2 功能说明为历史记录。

构建 0.5.0 ZIP：先执行 `.\.venv\Scripts\python.exe -m PyInstaller --noconfirm packaging/deskpet.spec`，然后执行 `.\.venv\Scripts\python.exe packaging/build_portable.py --version 0.5.0`。输出 `dist/TianyiPet-0.5.0-portable.zip` 及同名 `.zip.sha256` 校验文件；压缩包包含 `VERSION.txt` 和 `更新公告.txt`。只收录当前正在使用的洛天依模型及其依赖，不收录旧模型备份、工程、Miku、Mod 本体或用户数据。

0.4.2 阶段新增网易云网页登录及播放、歌词右键颜色/隐藏/左键穿透，并修复中文描边遮挡和本地 MP3 节拍解码。默认使用 Live2D 洛天依，包含静态切换、自定义 PNG 角色接口、弹性拖拽、鼠标互动与背景效果，以及可选 API 文字聊天、洛天依人格插件、本地陪伴任务限制和头像图标，面向 Windows 10 / 11 x64。包含 Python、Qt、Live2D 运行依赖、当前洛天依模型与内置静态角色图片、本地音频辅助程序及 B站网页辅助程序，无需用户安装 Python。B站仍需系统安装 Microsoft Edge WebView2 Runtime；网页登录、验证码与网站播放限制由用户在网页处理。

主程序只带 Mod 接口、管理页面与加载器，不包含目标陪伴代码或任何内置注册的 Mod。新数据目录中的扩展列表为空，默认没有启用任何 Mod。目标陪伴作为单独的 ZIP 分享，主程序和免安装包均排除 `pet_mods.goals`。

默认安装到当前用户的 `%LOCALAPPDATA%\Programs\TianyiPet`，无需管理员权限，可选桌面快捷方式，并添加开始菜单及 Windows 卸载入口。关闭旧桌宠后再安装。开机自启仍在桌宠设置中由用户选择。

卸载按安装清单删除程序文件，保留听歌记录、用户设置及额外放入目录的文件。不会递归删除整个用户选择的安装目录。更新已运行的程序前，安装器会要求先从托盘退出。

安装包为本地生成的未签名试用版，尚未验证全新电脑、杀毒软件兼容性或系统升级场景。安装/卸载的文件操作与打包版的图片、原生 Live2D 渲染与静态切换、本地音频和 WebView2 启动已在独立临时目录测试。真实快捷方式、Windows“已安装的应用”入口及跨机器使用仍需试用确认。

## 构建

在 Windows x64 的项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm packaging/deskpet.spec
.\.venv\Scripts\python.exe packaging/build_goal_mod.py
.\.venv\Scripts\python.exe packaging/build_installer.py --portable
.\.venv\Scripts\python.exe tests/smoke_installer.py
```

打包使用 PyInstaller 目录模式；安装器使用 Windows 自带的 IExpress 和 .NET Framework C# 编译器，不依赖在线安装编译工具。保留两套可执行入口是为了让后台音频/网页进程拥有通信管道，前台不显示控制台。

输出文件：

- `dist/TianyiPet-0.5.0-Setup.exe`：新版，有安装进度、位置选择、快捷方式和卸载入口。
- `dist/TianyiPet-0.5.0-portable.zip`：与安装包相同的主程序文件，解压后运行 `TianyiPet.exe`。
- `dist/TianyiPet-GoalCompanion-0.1.0.zip`：单独的目标陪伴 Mod，含源码、固定入口、元数据、说明和 MIT LICENSE；不包含用户数据库。
- 旧版安装包的保留和清理由主发布流程决定；新版通过验证后只保留 0.4.1 安装包以便回退。
- `dist/SHA256SUMS.txt`：本次生成安装包、免安装包及已存在的目标 Mod ZIP 的 SHA-256。
- `dist/TEST-REPORT-0.5.0-installer.json`：本机安装、启动和卸载检查结果。

`build/` 和 `dist/` 不提交到 Git。需要分享时单独发送安装包，本次不上传 GitHub，也不自动发布安装文件。安装包仅包含洛天依，明确排除 Miku 素材、Miku 专用人格、自定义角色包和历史模型工程；保留通用角色及人格模板。用户本地已有的 Miku 目录不会因构建而删除。

## 安装独立目标 Mod

在桌宠的「扩展功能 / Mod」中点击「打开 Mod 文件夹」，把独立 ZIP 解压到该应用数据下的 `mod-packages` 文件夹，使 `goals/mod.json` 和 `goals/entry.py` 直接位于其中。退出并重新打开桌宠后启用「目标陪伴」。扫描只读取信息；仅启用后执行代码，已启用状态可在重启后恢复。目标数据库独立保存在应用数据 `mods/goals/goals.db`，停用不删除数据。Python 扩展没有沙箱，仅安装和启用可信来源的包。

安装检查会读取可执行文件的 CArchive/PYZ，断言无 `pet_mods.goals`，然后使用冻结程序 `--self-check --mod-pack <独立ZIP> --report <临时报告>`，在隔离数据路径先验证空扩展列表，再解压独立 ZIP、启用、创建页面、保存目标、经统一通知接口提醒和检查持久化。此过程不触碰真实存档，也不调用模型服务。
