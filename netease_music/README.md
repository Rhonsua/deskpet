# 网易云信息、歌词与账号收藏

这是按需页面，依赖现有 PySide6、Python 标准库及轻量 qrcode（本地生成二维码，不需要 Pillow）。推荐通过 `browser_login.py` 启动 `netease_player_worker.py`，复用已有 pywebview/WebView2 打开官方网页。每次使用独立临时私密会话，仅接收该窗口自己的网易云 Cookie，不读 Edge、B站或网易云客户端的会话；读取官网账号资料后使用 DPAPI 加密管道回传，自动关闭窗口并加载歌单。用户勾选“记住登录”才持久保存。取消、隐藏、退出及更换账号会停止登录，过期结果不进入新会话。原直连扫码保留为备用；高级自定义服务默认收起。

歌曲和下载信号交由宿主的独立播放队列与下载队列处理。只有实际播放进度计入听歌，信息请求和下载不计奖励。网络使用 Qt 异步请求；单请求20秒、一次读取任务最多3分钟，可取消；旧 reply 回调被身份检查丢弃。响应最大8MiB，歌词最大256000字符；禁止携凭据自动跳转其他接口。网页登录等待上限10分钟，不自动操作验证码；真实账号登录仍需本人验收。

## 宿主接口

```python
from netease_music import NeteaseWidget
page = NeteaseWidget(data_dir, parent)
page.lyricsReady.connect(on_explicit_lyrics_binding)  # str song_id, str title, str lrc
page.playBoundRequested.connect(on_play_existing_binding)  # str song_id
page.playRequested.connect(on_play_cloud_queue)  # list metadata, int start_index
page.downloadRequested.connect(on_download)  # list metadata, bool lyrics_only
page.sessionChanged.connect(cancel_account_operations)
song = page.selected_song()  # {'id': '123', 'title': '...'} 或 None
page.shutdown()  # 程序退出调用，可重复
```

`bindRequested(str, str)` 保留供宿主扩展，本页默认绑定按钮只发 `lyricsReady`，避免重复绑定。获取歌词只显示在页内，必须点击绑定按钮才发信号；宿主应确认当前本地/B站版本并维护精确绑定。打开网易云原页仅调用系统浏览器。隐藏页面会取消未完成请求和扫码，但不清除有效登录。

## 默认直连与高级社区API

网页登录另有 `account_probe.py` 后台核验路径：用当前 WebView2 窗口提供的限定 Cookie 直接请求同源 WEAPI 账号接口，避免只依赖网页内 fetch/WebCrypto。单请求 8 秒、每 15 秒最多自动启动一次，不跟随重定向、不使用 Cookie jar、不输出原始响应；结果与凭据指纹绑定，账号切换后不接收旧结果。合成测试覆盖空账号、8821、HTTP/网络失败、重试节流和凭据轮换。匿名联网返回“会话未生效”，真实本人登录尚待验收。

登录的二维码申请、二维码状态检查和账号核验使用对应的 `weapi` 请求，二维码申请与检查统一使用 type=1；加密依赖由 requirements.txt 中的 pycryptodome 提供。其余音源、歌单和歌词请求保持各自原有路径。Windows Client 在加载加密模块前选择 Qt Schannel TLS 后端，保留正常证书校验，避免已复现的 Crypto 先于 OpenSSL 懒初始化时的原生崩溃。匿名实际 Qt 请求已完成 key→check 并返回 801；这不等于真实账号扫码完成。

默认只向 `https://music.163.com` 请求歌曲、逐句LRC、歌单和独立扫码登录。`direct.py` 限定HTTPS固定域名及路径，Cookie仅以显式请求头发送到这些接口，只接收允许的会话Cookie，不使用自动Cookie jar或重定向。直连二维码由本机 qrcode 和 Qt 根据登录URL生成，不向任何第三方传递扫码key。完整歌曲链接限定 `music.163.com` / `y.music.163.com` 的 song/playlist 路径、唯一正整数ID；不自动展开短链接，不接受任意网址。

公开HTTP接口不是网易云承诺稳定的开放API。可在页面中配置并明确信任兼容 [NeteaseCloudMusicApiEnhanced](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced) 的自建社区服务。接受HTTPS，只有本机回环允许HTTP。可带固定基础路径，不能含用户密码、query或fragment。本程序不下载、安装或运行该项目代码，也不内置他人公共代理。**社区服务会收到独立登录凭据，用户必须信任服务运营者。** 社区地址改变时先退出并清除旧个人缓存；清理失败会阻止切换和重新扫码。

使用的社区路径为 `/song/detail`、`/lyric`、`/playlist/detail`、`/playlist/track/all`、`/user/playlist`、`/likelist`、`/login/qr/key`、`/login/qr/create`、`/login/qr/check`、`/login/status`。请求使用POST表单，Cookie在请求体而非URL；Qt自动Cookie载入和保存关闭，不使用系统或浏览器会话。

## 分页、顺序和快照

优先读取歌单完整trackIds，按200个ID批量取详情；详情未提供全部ID时，社区接口按offset/limit读取所有曲目页。直接公共接口若不能提供全部ID，则明确展示部分结果，不伪造完整分页。每首歌按ID去重，保留云歌单原顺序，元数据分页返回的乱序不会改变顺序。缺页、不可访问、曲目缺失、格式异常、重复分页均标记部分结果。最多读取20000首／10000个账号歌单，超过范围明确停止。

创建与收藏按creator.userId分类，账号歌单处理offset分页；喜欢列表先查specialType=5的本人歌单以保留歌单顺序，否则展示 `/likelist` 返回顺序并明确这是无序接口，不能还原客户端排序。未登录不请求个人接口；过期/无权限不循环重试，而是退出会话并尝试清除个人缓存。

快照与获取时间保存在本页专用数据目录，区分public/private。账号会话启用期间的查询结果只写private。刷新失败不覆盖旧快照，部分结果也不覆盖上次完整快照；歌词刷新失败保留旧可用歌词。选中歌词24小时内优先使用缓存，可用完整歌曲链接显式联网刷新。收藏快照与歌词缓存均不并入本地音频库。退出删除独立凭据和整个private目录，公开快照保留；清理失败会明确提示且阻止切换账号。

“记住登录”默认勾选，可取消；仅勾选时用当前Windows用户DPAPI加密保存。未勾选时Cookie只在内存。保护失败不保存明文，但本次有效登录仍可自动加载歌单。直连会话使用 `api=''`，与自定义API完整地址严格隔离；切换服务必先清理。高级社区模式兼容API返回的PNG data URI，不从任意远程图片地址加载。

## 原始资料与验证范围

查阅日期2026-10-22：

- [用户歌单分页实现](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/main/module/user_playlist.js)：uid、limit、offset。
- [歌单详情](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/main/module/playlist_detail.js)、[全曲目分页](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/main/module/playlist_track_all.js)：后者按完整trackIds切片后获取歌曲详情。
- [歌曲详情](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/main/module/song_detail.js)、[歌词](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/main/module/lyric.js)。
- [喜欢列表](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/main/module/likelist.js)：原实现注释明确“无序”。
- [扫码key](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/main/module/login_qr_key.js)、[二维码](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/main/module/login_qr_create.js)、[确认结果和Cookie](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/main/module/login_qr_check.js)、[登录状态](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/main/module/login_status.js)。

本次真实只读抽查（不保存整首歌词）：歌曲185633的metadata与LRC请求code=200，公开歌单3778678返回code=200、result.trackCount=200、tracks=200、无trackIds。这只验证了这几个公共样本，不代表所有歌曲或歌单可读取。

默认直连补充实测：Qt Client 获取二维码key后检查返回801（等待扫码），未展示真实二维码、未登录；v6公开歌单返回完整200个trackIds。站内接口并非稳定的官方开发者API。

自动测试使用临时目录、合成元数据、假Cookie、回环HTTP服务和离屏Qt页面，未使用真实用户账号。**待用户主动扫码后验证**：App确认兼容性、会话过期、本人私密歌单可见性、创建/收藏与喜欢列表完整性、超大真实歌单的分页与排序。接口可能变化，错误会明确显示，不能把代码路径存在说成账号功能已实测通过。逐字歌词暂未实现，播放与节拍编排由宿主模块负责。

## 音源、下载与验证

`Service.media(id, download=False)` 只使用正常播放或下载接口，返回可信CDN的HTTPS地址、音频格式、时长、大小及试听信息。下载权限与播放权限分开；下载失败不回退播放接口或第三方解锁。CDN不携带账号Cookie，所有URL只在内存中流转，不写入快照。

`Downloader` 异步逐块写入临时文件，校验响应状态、类型、文件头、实际长度和200MiB上限后，以不覆盖已有文件的方式提交；取消及失败清理本次临时文件。歌词保存同名UTF-8 LRC，缺失时明确报告。跳转不会携带凭据转发。

真实公开歌曲554322674正常HTTPS音源已用隔离设置、静音的Windows播放器实播超过2秒，Loaded/position正常且无错误；未导出音频或签名URL。账号下载权限仍待用户验收。

验证命令：`python -m unittest tests.test_netease_music tests.test_netease_client tests.test_netease_media tests.test_netease_downloads tests.test_netease_download_queue -v`；`python -m tests.smoke_netease`、`python -m tests.smoke_netease_playback`、`python -m tests.smoke_netease_audio`。
