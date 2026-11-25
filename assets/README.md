# 素材规范

## 授权范围

仓库根目录的 MIT 许可证仅适用于本项目自行编写的源代码及配套技术文档，不适用于角色图片、动画、演示媒体、参考素材或音乐。

本目录角色素材由 imagegen 生成或编辑，为参考洛天依经典 V3 公式服的同人素材。本项目不持有洛天依角色及相关名称、商标等全部权利，也不通过 MIT 许可证授予这些权利。素材尚未另行授予开放使用许可；公开仓库不代表已获素材的转载、修改、再分发或商业使用许可，相关使用应另行核对权利人的授权。参考素材和用户自行添加的图片、音乐仍归相应权利人，遵循原有授权。

## 非官方同人声明与权益联系

本项目为个人非营利同人 Demo，未获得洛天依相关权利人的官方授权，与官方不存在合作或背书关系。AI 生成或编辑、公开展示及非营利性质均不代表已获得角色或参考素材授权。

如相关权利人认为素材使用涉及权益问题，请通过 [仓库 Issues](https://github.com/Rhonsua/deskpet/issues) 联系维护者，并提供涉及内容及权利说明。我们会及时核查处理；确认存在未经许可使用的内容后，将及时移除相关素材，并视情况停止提供相关下载。上述声明不代替权利人的授权。

## 制作与存放

`ui/shop/` 收录 2026-11-25 使用 ImageGen 为本项目绘制的 Q 版商店素材。十二件物品和四套静态布景来自两张透明图集。云端练歌台、荷塘萤夜、糖星彩排夜来自第三张全幅场景图，三个场景分别转换为 512 × 640 的 WebP。它们以糖果色、圆润的粗描边与两级色块塑造小物，软件为整幅场景叠加流云与纸飞机、萤火与水纹、追光与上升的音符。商品卡和桌面共用这些图像。商品分类与选购方式参考 [VPet 的商店布局](https://github.com/LorisYounger/VPet/blob/main/VPet-Simulator.Windows/WinDesign/winBetterBuy.xaml)。

「云上八音街」由内置 ImageGen 绘制。全景原画位于 `ui/shop/panoramas/musicbox-town.webp`（1672 × 941），商店预览使用 `ui/shop/musicbox-town.webp`（640 × 360）。画面采用浅薄荷、薰衣草和杏色的水粉，左侧是留声机唱片铺，中间是运河拱桥，右侧是音乐盒亭和摩天轮。圆窗和透明边缘由桌宠实时绘制。

<details>
<summary>云上八音街的生成提示词</summary>

```text
Use case: illustration-story. Illustration for a premium Q版 chibi desktop pet shop landscape called 云上八音街.
A continuous full-bleed extra-wide 16:9 landscape map illustration (2560x1440 if available) of a music-box canal town in the clouds, in soft late-afternoon light.
Left: a mint-roofed little music shop with a brass gramophone horn, blue ceramic pots and a winding cobblestone footpath.
Middle: a duck-egg-blue canal with a little cream arched footbridge and gentle reflections.
Right: a hilltop music-box pavilion and a ferris wheel with pastel gondolas as the scene recedes.
Lower foreground has lavender flower planters, tiny balconies and the canal bank, upper quarter has distant lavender rooftops, small clouds and blue haze.
Each part is its own small discovery when looking through a moving circular peephole; spread distinguishable landmarks across the full width and make all four corners interesting.
Soft gouache on lightly textured paper, rounded toy-like chibi proportions, confident fine dusky-teal linework and warm creams, muted mint greens, sky blues with apricot and lavender highlights.
Hand-drawn game background matching cute Chinese rhythm-game merchandise. Calm legible silhouettes and deeper foreground value; airy, uncluttered, detailed enough to zoom.
Print-ready horizontal landscape, landscape art fills every edge. Only scenery, no people, no pets, no typography, no logos, no frames, no vignette, no circular mask. The program will do the mask.
```

</details>

已生成并接入 `character/tianyi-master-v1.png`，为透明 Q 版洛天依母版。详细提示词与使用记录见 `character/素材记录.md`。当前动画为整图浮动和摇摆，尚不是分层或序列帧动画。

静态角色当前仅使用精致版。简单（圆润）版 `character/tianyi-simple-v3-costume.png` 已移出可选角色和打包清单，仅保留本地历史素材。旧版文件留档，服装参考和编辑提示词见 `character/V3公式服修正.md`。

精致版现改用 `character/tianyi-refined-v3-smooth.png`，仅简化头顶八字辫编织细节，作为静态外观；当前默认外观为 Live2D。参考图保留在本地，不随仓库分发；来源链接保留在素材记录中。

后续按 `character/<state>/000.png` 存放透明序列帧；母版建议 512×512，所有状态统一脚底锚点。第一批制作 idle（待机）与 listening（听歌），确认小尺寸效果后再补齐其他状态。

每组正式素材须同时记录原始参考链接、创作者/生成方式、制作日期、授权范围和修改记录。图片参考入口见项目设计方案。
