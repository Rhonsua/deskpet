# Windows 试用安装包

安装包版本为 0.3.0，默认使用 Live2D 洛天依，包含静态切换、自定义 PNG 角色接口、弹性拖拽、鼠标互动与背景效果，面向 Windows 10 / 11 x64。包含 Python、Qt、Live2D 运行依赖、当前洛天依模型与内置静态角色图片、本地音频辅助程序及 B站网页辅助程序，无需用户安装 Python。B站仍需系统安装 Microsoft Edge WebView2 Runtime；网页登录、验证码与网站播放限制由用户在网页处理。

默认安装到当前用户的 `%LOCALAPPDATA%\Programs\TianyiPet`，无需管理员权限，可选桌面快捷方式，并添加开始菜单及 Windows 卸载入口。关闭旧桌宠后再安装。开机自启仍在桌宠设置中由用户选择。

卸载按安装清单删除程序文件，保留听歌记录、用户设置及额外放入目录的文件。不会递归删除整个用户选择的安装目录。更新已运行的程序前，安装器会要求先从托盘退出。

安装包为本地生成的未签名试用版，尚未验证全新电脑、杀毒软件兼容性或系统升级场景。安装/卸载的文件操作与打包版的图片、原生 Live2D 渲染与静态切换、本地音频和 WebView2 启动已在独立临时目录测试。真实快捷方式、Windows“已安装的应用”入口及跨机器使用仍需试用确认。

## 构建

在 Windows x64 的项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm packaging/deskpet.spec
.\.venv\Scripts\python.exe packaging/build_installer.py
.\.venv\Scripts\python.exe tests/smoke_installer.py
```

打包使用 PyInstaller 目录模式；安装器使用 Windows 自带的 IExpress 和 .NET Framework C# 编译器，不依赖在线安装编译工具。保留两套可执行入口是为了让后台音频/网页进程拥有通信管道，前台不显示控制台。

输出文件：

- `dist/TianyiPet-0.3.0-Setup.exe`：有安装进度、位置选择、快捷方式和卸载入口。
- `dist/TianyiPet-0.3.0-portable.zip`：解压后运行 `TianyiPet.exe`，保持辅助程序及 `_internal` 目录完整。
- `dist/SHA256SUMS.txt`：这两个文件的 SHA-256。
- `dist/TEST-REPORT.json`：本机安装、启动和卸载检查结果。

`build/` 和 `dist/` 不提交到 Git。需要分享时单独发送安装包，本次不上传 GitHub，也不自动发布安装文件。安装包仅包含洛天依，明确排除自定义角色包和历史模型工程。
