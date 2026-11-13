"""Windows group-share helper for the 0.7.0 desktop pet."""
import ctypes
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from download import NAME
from install import DATA, install


def main():
    res = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    beside = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
    app = tk.Tk()
    app.title('洛天依桌宠 · 语音环境安装助手')
    frame = ttk.Frame(app, padding=18)
    frame.pack(fill='both', expand=True)
    frame.columnconfigure(0, weight=1)
    frame.columnconfigure(1, minsize=84)
    font = ('Microsoft YaHei UI', 10)
    app.option_add('*Font', font)
    ttk.Label(frame, text='安装 A / C 语音包所需的本机环境',
              font=('Microsoft YaHei UI', 14, 'bold')).grid(row=0, columnspan=2, sticky='w')
    ttk.Label(frame, text='Windows 10 / 11 x64 · 首次下载约 8.84 GB，建议选择有 25 GiB 空闲的磁盘。\n'
              '可选群里收到的语音包，安装后会用它试合成，并连接到桌宠。').grid(
              row=1, columnspan=2, sticky='w', pady=(6, 14))
    base = tk.StringVar(value=str(Path(os.environ['LOCALAPPDATA']) / 'TianyiPet'))
    search = [d/n for d in (beside, beside.parent, DATA/'语音包') for n in ('A-演出原声.zip', 'C-演唱微调.zip')]
    voice = tk.StringVar(value=str(next((p for p in search if p.is_file()), '')))
    archive = tk.StringVar(value=str(next((d/NAME for d in (beside, beside.parent) if (d/NAME).is_file()), '')))
    inputs = []
    def picker(row, label, var, choose):
        ttk.Label(frame, text=label).grid(row=row, columnspan=2, sticky='w', pady=(6, 3))
        entry = ttk.Entry(frame, textvariable=var)
        entry.grid(row=row+1, column=0, sticky='ew')
        def browse():
            selected = choose()
            if selected:
                var.set(selected)
        button = ttk.Button(frame, text='选择…', command=browse)
        button.grid(row=row+1, column=1, sticky='ew', padx=(8, 0))
        inputs.extend((entry, button))
    picker(2, '安装到哪个文件夹（助手会在里面新建独立目录）', base,
           lambda: filedialog.askdirectory(parent=app, title='选择安装位置'))
    picker(4, '语音包 ZIP（可选，留空可在桌宠里添加）', voice,
           lambda: filedialog.askopenfilename(parent=app, filetypes=[('语音包', '*.zip')]))
    picker(6, '已有官方环境 7z（可选，留空自动下载）', archive,
           lambda: filedialog.askopenfilename(parent=app, filetypes=[('官方环境', '*.7z')]))
    progress = ttk.Progressbar(frame, maximum=100)
    progress.grid(row=8, columnspan=2, sticky='ew', pady=(20, 6))
    status = tk.StringVar(value='准备就绪。语音模型使用群里单独提供的 ZIP。')
    ttk.Label(frame, textvariable=status, wraplength=520).grid(row=9, columnspan=2, sticky='w')
    events = queue.Queue()
    cancel = threading.Event()
    busy = False
    def start():
        nonlocal busy
        if busy:
            return
        path = base.get().strip()
        if not path or not Path(path).is_absolute():
            messagebox.showerror('安装位置', '请选择完整的安装目录。', parent=app)
            return
        selected = Path(voice.get().strip()) if voice.get().strip() else None
        source = Path(archive.get().strip()) if archive.get().strip() else None
        busy = True
        cancel.clear()
        for widget in [*inputs, go]:
            widget.state(['disabled'])
        progress['value'] = 0
        status.set('正在检查安装目录和语音包…')
        def run():
            try:
                engine = install(Path(path), selected, source, res,
                                 lambda msg, pct=0: events.put(('progress', msg, pct)), cancel=cancel)
                events.put(('done', engine, selected))
            except InterruptedError as exc:
                events.put(('paused', str(exc), None))
            except Exception as exc:
                events.put(('error', str(exc), None))
        threading.Thread(target=run, daemon=True).start()
    def poll():
        nonlocal busy
        try:
            while True:
                kind, value, extra = events.get_nowait()
                if kind == 'progress':
                    status.set(value)
                    progress['value'] = extra
                    pause.state(['!disabled'] if value.startswith('正在下载') and not cancel.is_set() else ['disabled'])
                    continue
                busy = False
                pause.state(['disabled'])
                for widget in [*inputs, go]:
                    widget.state(['!disabled'])
                if kind == 'done':
                    progress['value'] = 100
                    msg = ('环境已安装，所选语音包已合成通过。' if extra else
                           '环境已安装，请把 A 或 C 的 ZIP 放入语音包文件夹。')
                    status.set(msg)
                    messagebox.showinfo('安装完成', msg + '\n从托盘退出并重开桌宠，到「陪伴模式 → 语音设置」试听。',
                                        parent=app)
                elif kind == 'paused':
                    status.set(value)
                else:
                    status.set('安装未完成。可保留已下载的进度再试。')
                    messagebox.showerror('安装未完成', value + '\n\n自检和解压日志（如已运行）\n' +
                                         str(DATA / 'voice-setup/install.log'), parent=app)
        except queue.Empty:
            pass
        app.after(200, poll)
    def open_folder():
        folder = DATA/'语音包'
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)
    actions = ttk.Frame(frame)
    actions.grid(row=10, column=0, sticky='w', pady=(16, 0))
    ttk.Button(actions, text='打开语音包文件夹', command=open_folder).pack(side='left')
    def stop_download():
        cancel.set()
        pause.state(['disabled'])
        status.set('正在保存已下载的分段…')
    pause = ttk.Button(actions, text='暂停下载', command=stop_download)
    pause.pack(side='left', padx=8)
    pause.state(['disabled'])
    go = ttk.Button(frame, text='开始安装', command=start)
    go.grid(row=10, column=1, sticky='ew', pady=(16, 0))
    def close():
        if busy:
            messagebox.showinfo('正在安装', '请等安装完成后关闭。网络中断时，再次安装会接着下载。', parent=app)
        else:
            app.destroy()
    app.protocol('WM_DELETE_WINDOW', close)
    app.minsize(570, 420)
    if getattr(sys, 'frozen', False):
        # External Python and 7-Zip must load their own DLLs, not PyInstaller's.
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    app.after(100, poll)
    app.mainloop()


if __name__ == '__main__':
    main()
