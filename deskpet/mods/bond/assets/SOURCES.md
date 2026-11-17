# 成长纪念集素材说明

- 页面设计：本项目绘制的书脊、纸页、线框与花形装饰，不依赖远程资源。
- 新增装订布纹、金边、贴纸、唱片、票根、月亮、点心碗、聊天气泡、音符、成长节点均由本项目使用 Qt 基础图形原创绘制，无外部图标、字体或纹理文件，随代码按项目许可证提供。短记录展示粘贴式纪念卡；长记录保留完整分页。
- 角色配色参考：[Vsinger 官方角色页](https://vsinger.com/vsinger)，洛天依代表色为 #66CCFF。
- `tianyi-cover.webp`：从非官方资料站 [洛天依 · Luo Tianyi](https://120712.com/) 的人物立绘下载；原文件为 <https://120712.com/assets/images/lt_main.png>，获取于 2026-11-17。原图 479 × 1050，等比例缩小并转为透明 WebP；保留原有标识，没有重绘角色。
- 该站将图片标注为官方角色立绘，但本站未独立确认这张图的绘制者和授权范围。洛天依角色及相关形象权利属于相应权利人。资料站可访问不代表图片获得开源授权。
- **代码的 MIT 许可证不覆盖人物插图**。该图按用户要求随独立 Mod 分发，仍从代码 Git 跟踪中排除；提供来源不代表图片获得开源授权，后续再分发应自行确认图片权利。构建时允许缺失此图，界面自动回退为花形封面。

## 交互与视觉研究（2026-11-17）

以下为设计研究的一手来源；没有将这些作品的截图、人物、UI 图片、音频或图标放入程序或打包素材。

| 作品及主来源 | 可借鉴的结构 | 本次落地 |
| --- | --- | --- |
| [Neko Atsume 官方 How to Play](https://nekoatsume.com/en/about.html) 与 [官方 FAQ](https://www.nekoatsume.com/en/support.html) | Catbook 和 Album 按对象收集、单独回看纪念照片；官网有实际界面示例，FAQ说明相册入口 | 按真实互动类型绘制贴纸；第一次发生日期与正文分开，章节显示实际收录数量 |
| [Spirit City: Lofi Sessions 开发者 Steam 页面](https://store.steampowered.com/app/2113850/Spirit_City_Lofi_Sessions/) | 开发者介绍发现和收集伙伴、通过相伴累积等级与解锁；页面提供官方图集 | 成长足迹采用六节点进程，已抵达和未来页区分，未开放内容保留条件与留白 |
| [Chill with You: Lo-Fi Story 开发者 Steam 页面](https://store.steampowered.com/app/3548580/) | 以音乐、共处和逐渐加深的关系组织陪伴体验；官方截图可研究低干扰音乐界面 | 听歌纪念采用原创黑胶唱片、猜歌与演出票根，不导入作品音乐或人物 |

补充观察：[Finch 官方网站](https://finchcare.com/) 展示日常自我照料与宠物成长的陪伴关系，参考其轻量反馈语气。以上“本次落地”是本项目的设计取舍，并非对原作界面功能的逐项复刻；第三方游戏素材保留各自权利，不适用本项目 MIT 许可证。

## 陪伴窗口主题

- `tianyi-music.webp` 缩放自本项目已有的 `assets/stickers/tianyi/music.webp`，仅调整尺寸和压缩，未重绘人物。该素材的原始授权信息未在项目中确认，角色及插画权利属于相应权利人；代码许可证不自动覆盖插画，公开再分发前应确认授权。
- 青蓝与音乐主题的设计参考：[Vsinger 官方角色页](https://vsinger.com/vsinger) 和 [洛天依日本官方网站](https://www.luotianyi.jp/profile/)。未将这两站的图片加入本包；横幅渐变与圆弧由程序绘制。

- `tianyi-stage.webp` 缩放自项目现有 `assets/character/tianyi-refined-v3-costume.png`，仅缩小与压缩；原图的插画授权信息未在项目中确认，公开再分发前应核实。

- `tianyi-sing-front.webp`、`tianyi-sing-left.webp`、`tianyi-sing-right.webp`：复用本机 `assets/character/states/sing-front.png`、`sing-left.png`、`sing-right.png`，仅等比缩小到 420×630 并转为透明 WebP，三张约 174 KiB。原制作记录 `assets/character/states/唱歌与侧转制作记录.md` 记载为 2026-10-17 通过 imagegen 基于现有角色图制作。角色及服装相关权利仍属于相应权利人；这些是三方向持麦状态图，不是 Live2D 绑定或歌词口型素材。
- 三种舞台的海浪、气泡、花枝、花瓣、帷幕、聚光与星光由 `stage_art.py` 用 Qt 图形绘制，没有新增第三方场景图片。

- `tianyi-background.webp` 来自用户本机桌宠聊天背景 `chat/background.png`，原图 1242×1863；等比缩小为 1066×1600 并压缩，保留画面及原图标识。原图显示“哔哩哔哩收藏集”标识，但具体画师和授权信息未确认；按用户要求作为 Mod 主题背景分发，不包含聊天数据；图片权利不属于本项目代码许可证范围。
