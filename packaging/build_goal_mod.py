"""Package the optional goal companion separately; never bundles user data."""
import argparse
import json
from pathlib import Path
import zipfile


MANIFEST = dict(id='goals', name='目标陪伴', version='0.1.0', api_version=1,
                description='手动记录目标和待办，在临期、逾期或未记录新进展时温柔提醒。')
README = '''目标陪伴 Mod 0.1.0（桌宠 Mod API 1，适用于 TianyiPet 0.4.1）

此 ZIP 为独立可选扩展，主程序不包含目标陪伴本体，默认没有安装或启用任何 Mod。
安装：打开桌宠「扩展功能 / Mod」窗口，点击「打开 Mod 文件夹」。
把本 ZIP 解压到这个应用数据下的 mod-packages 文件夹，得到：
  mod-packages/goals/mod.json
  mod-packages/goals/entry.py
不要多套一层 ZIP 名称目录。退出并重新打开桌宠，在扩展窗口启用「目标陪伴」。
发现/显示信息时不运行扩展代码，只在启用时执行；启用状态可在重启时恢复。

这是可信 Python 扩展，没有沙箱，拥有应用进程的权限；只安装信任的包。
目标属于用户，切换角色不会拆分目标。数据独立保存在应用数据 mods/goals/goals.db。
停用保留目标数据。程序运行且 Mod 启用时才检查提醒，不监控屏幕、不联网。
进展手动记录，今天推进了只更新时间，不伪造百分比；进度来自已完成待办/全部待办。
暂停、完成或暂缓期间不提醒；临期/逾期优先于停滞提醒。每个目标至少冷却24小时，
并受桌宠统一免扰、每日上限和全局提醒间隔约束，暂缓1小时不是承诺1小时后响铃。
提示音由主程序的全局提醒设置控制，默认开启。
源代码使用随包 LICENSE 中的 MIT 许可。
'''


def build(output=None):
    root = Path(__file__).resolve().parents[1]
    source = root / 'pet_mods' / 'goals'
    output = Path(output) if output else root / 'dist' / 'TianyiPet-GoalCompanion-0.1.0.zip'
    files = {'goals/mod.json': json.dumps(MANIFEST, ensure_ascii=False, indent=2).encode('utf-8'),
             'goals/entry.py': b'"""Goal companion package entry point."""\nfrom .mod import GoalMod\n\nfactory = GoalMod\n',
             'goals/README.txt': README.encode('utf-8'),
             'goals/LICENSE': (root / 'LICENSE').read_bytes()}
    for name in ('__init__.py', 'mod.py', 'store.py', 'widget.py'):
        path = source / name
        if not path.resolve().is_relative_to(source.resolve()) or not path.is_file():
            raise ValueError('Missing or invalid goal source: ' + name)
        files['goals/' + name] = path.read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == set(files)
        assert archive.testzip() is None
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    print(build(parser.parse_args().output))
