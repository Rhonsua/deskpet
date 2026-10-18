# 自定义角色接口（少量准备，尚未启用）

已提供 v1 配置草案、动作路径描述与手动校验工具。内置洛天依的素材路径已集中到同一模块；**桌宠仍只显示内置角色，没有扫描、导入或切换外部角色的入口**。角色包不会在启动时读取，也不能执行脚本。

## 准备角色包

复制 `example/character.json.example` 到自己新建的角色目录，重命名为 `character.json`，修改名称、作者、来源并添加图片：

```text
characters/
  my-character/
    character.json
    idle.png
    blink.png       # 可选
```

示例目录只包含配置模板，没有占位图片，也不代表已能切换的角色。素材请自行准备并确认使用许可。

| 字段 | 约定 |
| --- | --- |
| `version` | 固定为整数 `1`；目前为预备格式 |
| `id` | 小写字母开头，后接小写字母、数字、`_` 或 `-`，总长不超过 64 |
| `name` | 必填显示名称，最多 80 字符 |
| `author` / `source` | 作者、素材来源与授权说明，可选，最多 120 / 500 字符 |
| `states` | `idle` 必填；其余动作可选，接口查询缺失动作时返回 `idle` |
| `anchors` | 可选 `head` / `feet`，相对整张画布的 `[x, y]`，范围 0～1；默认值见模板，目前仅保存数据，未用于点击与停靠 |

动作名称支持 `idle`、`blink`、`happy`、`eat`、`lift`、`sleep`、`phone`、`sing-front`、`sing-left`、`sing-right`。图片使用带透明通道的 PNG；各动作保持相同画布尺寸、角色比例与脚底位置。透明通道检查不会判断画面中是否还画有不透明背景。

图片必须位于本角色目录内，支持子目录，拒绝绝对路径及指向目录外的路径或符号链接。单张最多 4096×4096、16 MiB；配置文件最多 64 KiB。

## 手动校验

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe character_packs.py characters/my-character
```

校验配置、素材路径、PNG 解码、透明通道与画布尺寸。仅校验，不启用角色，不修改文件。

代码接口在 `character_packs.py`：`read_pack(folder)` 读取并检查配置及路径，`validate_images(pack)` 进一步检查图片，`pack.state_path(action)` 提供缺失动作回退。图片依赖按需导入，普通启动不会加载外部图片。

后续再接设置中的扫描/切换、实际素材加载、锚点换算，以及不同体型的点击和边缘探头适配。当前不要把“校验通过”当作运行时接入已完成。
