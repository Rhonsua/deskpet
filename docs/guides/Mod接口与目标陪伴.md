# Mod 接口与目标陪伴

## 使用

0.4.1 主程序只保留 Mod 接口，不内置目标陪伴。从桌宠设置或系统托盘打开“扩展功能 / Mod”，点击“打开 Mod 文件夹”，将单独发布的目标陪伴 ZIP 中 `goals` 文件夹解压到这里（`mod-packages/goals/mod.json`）。退出并重新打开桌宠，选择目标陪伴并勾选“启用此功能”。首次安装默认关闭，启用后建立独立目标数据库。曾经启用过同 ID 功能的存档会恢复启用状态；已有目标记录仍可使用。

新建目标，填写截止时间，可附加备注和逐行待办，点击“保存目标与待办”。勾选待办立即保存，百分比按已完成步骤计算；没有步骤则不显示百分比。“今天推进了”只记录最近进展时间，不替用户勾选步骤。修改名称、备注、截止时间或待办文字不会计为进展。

目标可以暂停、恢复、完成、重新打开、删除。暂停和完成的目标不提醒；恢复目标后重新计算未记录进展的时长。删除会要求确认。关闭窗口保留本次运行中的编辑草稿，停用功能前如有未保存编辑会提醒确认；程序退出不会保存未提交的草稿。已保存目标在停用、重启、切换角色后保留。

## 提醒与声音

程序每分钟检查一次，优先提醒逾期目标，其次是未来 24 小时内截止的目标，再次是多日未记录新进展的目标。未记录进展的默认阈值是 2 天，可以为每个目标改为 1–30 天。此判断只依据用户记录，不推断实际工作情况。

所有 Mod 共用以下默认策略，可在“提醒设置”更改并保存：

| 设置 | 默认值 |
| --- | --- |
| 提示音 | 开启，使用系统提示音 |
| 免打扰 | 每天 22:00 至次日 08:00 |
| 每日提醒上限 | 3 次 |
| 两次提醒最短间隔 | 120 分钟 |

同一目标另有至少 24 小时的冷却，不随全局间隔调整。“暂缓提醒 1 小时”只延后资格，之后恢复检查，仍受其他限制，不能保证恰好一小时后提醒。

提醒显示为 10 秒气泡，不切换角色动作，不改变音乐或成长奖励。气泡实际显示时才播放一次系统提示音；系统静音或关闭系统提示音时可能听不到。提示音开关与音乐音量独立。

桌宠隐藏、边缘吸附、睡觉、玩手机、拖动、执行临时动作、已有气泡，或菜单、歌单、聊天、扩展窗口、模态对话框打开时暂缓。没有显示的提醒不占用配额、不播放声音；恢复可提醒状态后在后续检查中重新判断。启动约一分钟后首次检查；退出桌宠时不运行，不创建系统计划任务。电脑时间按本地时区处理。

## 第一版接口

这是可信本地 Python Mod 接口。启动时扫描应用数据目录 `mod-packages` 下的子目录，读取 `mod.json`，未启用时不执行包代码。每个包入口固定为 `entry.py`，导出可调用的 `factory(context)`。角色外观包与纯数据人格插件继续使用现有接口。

目标陪伴包结构：

```text
goals/
  mod.json
  entry.py
  __init__.py
  mod.py
  store.py
  widget.py
  README.md
```

`mod.json` 示例：

```json
{"id":"goals","name":"目标陪伴","version":"0.1.0","description":"手动记录目标和待办","api_version":1}
```

`entry.py` 示例：

```python
from .mod import GoalMod
factory = GoalMod
```

Mod 可以使用包内相对导入以及主程序提供的 `deskpet.mods.api`；依赖必须已由宿主提供，不会自动安装 pip 依赖。更新、卸载 Mod 前应退出桌宠；移除代码文件夹保留 `mods/<id>` 存档。启用状态会保存，因此替换已启用的代码包后下次启动会运行新版。仅安装可信来源，Mod 拥有当前进程的文件和网络权限。

扫描拒绝重复 ID、保留的 `builtin` / `builtin-` / `builtin_` 命名空间、目录链接、越界路径及不兼容的接口版本。单包最多 1024 个文件或目录、总计 16 MiB、单文件 4 MiB；元数据最多 64 KiB。首次启用前会再次检查。包根 `__init__.py` 不会自动执行，初始化应放在入口或 `start` 中。

`deskpet/mods/api.py` 定义：

```python
ModManifest(id, name, version, description='', api_version=1)
ModContext(data_dir, notify, services=None)

class Mod:
    def start(self): ...
    def tick(self, now): ...
    def stop(self): ...
    def create_widget(self, parent=None): ...
```

工厂接收 `ModContext`，返回 Mod 实例。宿主通过 `ModManager.register(manifest, factory)` 注册扫描通过的包，启用时加载入口。`id` 为以小写字母开头的 1–64 位小写字母、数字、下划线或连字符；2026-11-16 源码兼容接口版本 1、2，已发布 0.7.1 只支持 1。`start` 初始化资源，`tick` 接收本地无时区 `datetime`，`stop` 释放资源，`create_widget` 延迟创建界面。

`context.data_dir` 是该 Mod 的独立目录。`context.notify(text)` 只接收纯文本，最长 500 字符；返回 `True` 才表示提醒实际交付。业务层只在成功时记录已提醒。全局策略、次数和最近时间由管理器持久保存，防止重启绕过配额；保存失败时暂停提醒。设置损坏时使用默认关闭状态并展示警告，本次运行暂停提醒。

生命周期、更新或界面创建抛出异常时，管理器停止该 Mod 并显示错误，其他功能继续运行。这不是进程隔离或安全沙箱；Mod 在界面线程运行，应只做短时本地操作，不进行阻塞网络请求或长时间任务。

## 文件与存档

### API 2：互动与成长扩展

`context.services` 在桌宠宿主提供，当前 `version == 3`，包含原 API 2 能力；独立无宿主运行时可能是 `None`，扩展应检查最低版本。原 API 1/2 扩展保持兼容。

| 方法 | 契约 |
| --- | --- |
| `subscribe(callback)` | 注册 `callback(kind, data)`。`headpat` 为有效摸头、`feed` 为成功投喂、`chat` 为陪伴回复提交成功、`listen` 为可听的有效播放增量、`action` 为成功触发的动作。每个监听收到独立数据副本。 |
| `snapshot(music=False)` | 取得角色名、是否忙碌/播放、当前标题、本地路径、音量和活动；`music=True` 才复制当前拍点缓存，不做分析或网络调用。 |
| `growth(callback)` | 独占成长投影。回调返回 `level/xp/xp_goal` 和可选 `stage/affinity/growth_label`，`1<=level<=100, 0<=xp<=xp_goal`。启用期间冻结原经验，保留原音符规则；停用/异常释放投影。不能覆写饱食、心情或音符。 |
| `companion_context(callback)` | 普通陪伴调用时追加简短本地事实，每包最多 1200 字符、合计 2400；停用停止注入。不得编造共同经历或夹带工作模式指令。 |
| `act(name)` | 支持 `wave/happy/turn/celebrate/sing`，以自动动作优先级请求；忙碌、拖拽、摸头、停靠、工作及不支持的动作返回 False。不移动窗口、不切换歌单、不发奖励。 |

`listen` 的 `seconds` 为本次已确认有效的增量，最多 5 秒，包含 `source/at/title`；并不意味着歌曲自然播完。`feed` 包含 `food/at`；`action` 包含 `action`。扩展自行做去重、持久化及汇总，不能按回调次数直接发成长。聊天事件不含聊天正文、API Key 或远程账号凭据。

停用、失败和宿主退出会清理注册监听、记忆提供者及成长投影。回调发生异常时只停用对应 Mod 并显示错误；包仍在界面线程内执行，应保持轻量。外部包属于可信 Python 扩展，以上接口不是权限隔离机制。

互动养成包的完整规则和后续边界见 [互动养成增强 Mod 方案](../design/互动养成增强Mod方案.md)，构建命令为 `.venv\Scripts\python.exe packaging/build_bond_mod.py`。

### API 3：主面板、音乐与确定性消费

| 方法 | 契约 |
| --- | --- |
| `panel(summary, actions)` | `summary()` 返回纯文本；`actions` 是最多 12 个稳定 ID 到 `(标题, 回调)` 的映射。宿主负责摘要、固定入口和更多菜单；停用自动移除。 |
| `present(destination)` | 2026-11-17 新增的可选入口能力；用于用户点击 Mod 按钮时打开 `control` 原控制面板、`food` 投喂选择、`chat` 陪伴聊天或 `music` 歌单。返回是否打开；停用、未知入口返回 False。仅展示入口，不投喂、不摸头、不播放、不发成长。较早 API 3 宿主需通过 `getattr` 检测，缺失时引导用户使用原面板。 |
| `library()` | 返回已有本地歌单路径和文件名标题，不下载、不更改歌单；不存在或元数据不合适的音频由扩展跳过。 |
| `analysis(parent)` | 返回使用本 Mod 独立缓存目录的可取消 BeatController；分析在子进程完成，扩展负责并发限制和生命周期。 |
| `audio_claim() / audio_valid(token) / audio_release(token)` | 互斥的互动音频租约。普通播放中不能申请；扩展需持续检查普通播放、有效令牌和自身状态，失效停止自己的播放器。 |
| `audio_claim_mixed()` | 可选接口。允许互动与普通歌单同时播放，各互动共用一个租约，通过 `audio_valid` 检查并以 `audio_release` 释放。已发布的 0.7.2 主程序仅提供上一行的接口。 |
| `audio_preferences()` | 可选接口。返回桌宠音量（0～1）和用户选择的输出设备 ID，空 ID 表示跟随系统。 |
| `audio_route(audio, parent)` | 返回遵循宿主输出设置的 AudioRouter，关闭时停止其轮询。 |
| `shop(catalog)` | 注册商品 ID 到整数音符价格（0～10000）的映射；只列实际可提供的商品。 |
| `game_completed()` | 可选。当前启用的成长扩展在有效游戏成绩落盘后调用。宿主统一结算当日首局的 10 音符，返回本次实际发放数量。 |
| `buy(item) / owned()` | 返回 `(成功, 说明)` / 已拥有 ID；扣款与购买记录在同一事务，已拥有不重复扣款；停用不能再购买。 |

API 3 的 `listen` 在有效时附带 `track.source/position/duration`（秒）；`song_end` 是本地自然结束，`drag_end` 附轻晃幅度 `sway`。覆盖率与会话去重由扩展自行维护，不能把结束事件直接视为完整听完。当前歌曲完整纪念仅对本地可核验的音频启用。`snapshot` 另有 `hunger/notes`，均为只读。

这些接口不构成 Python 安全隔离。扩展仍需校验异步回调、关闭分析与播放器，不能通过持续回调抢用户动作。

| 文件 | 职责 |
| --- | --- |
| `deskpet/mods/api.py` | Qt 无关的接口与元数据 |
| `deskpet/mods/loader.py` | 元数据扫描、路径校验、启用时加载包入口 |
| `deskpet/mods/manager.py` | 注册、生命周期、启停、异常处理、提醒策略 |
| `deskpet/mods/host.py` | 桌宠状态检查、定时器、气泡与系统提示音 |
| `deskpet/mods/window.py` | 按需创建扩展管理与共用提醒设置 |
| `deskpet/mods/goals/store.py` | 目标与待办 SQLite 存储 |
| `deskpet/mods/goals/mod.py` | 提醒资格和文案 |
| `deskpet/mods/goals/widget.py` | 手动目标编辑和进度记录 |

应用数据目录下的 `mod-packages` 保存解压的代码包，`mods/settings.json` 保存启用状态、提醒偏好和全局记录；`mods/goals/goals.db` 保存目标、待办与最近进展。目标陪伴与聊天、API Key、成长数据库独立，不调用模型接口，不上传目标内容；其他 Mod 的行为由其作者决定。备份时退出桌宠再复制对应目录。

## 验证

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
.venv\Scripts\python.exe tests/smoke_goal_mod.py
.venv\Scripts\python.exe tests/smoke_mods.py
```

单元检查覆盖提醒优先级、冷却、免打扰、跨日配额、存储失败及异常停用。界面检查使用独立临时存档；宿主检查替换系统发声调用，验证默认开启、静音与状态抑制，不播放实际提示音、不调用真实 API。
