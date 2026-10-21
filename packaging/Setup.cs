// Per-user installer. The packaged Python/Qt app runs without a Python install.
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Win32;

class Setup {
    const string Key = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\TianyiPet";
    static string[] Args;
    static bool Has(string value) { return Args.Contains(value); }
    static string Option(string name, string fallback) {
        int index = Array.IndexOf(Args, name);
        return index >= 0 && index + 1 < Args.Length ? Args[index + 1] : fallback;
    }
    static string Root(string value) { return Path.GetFullPath(value).TrimEnd(Path.DirectorySeparatorChar); }
    static string Child(string root, string relative) {
        string path = Path.GetFullPath(Path.Combine(root, relative));
        if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new IOException("安装文件路径无效");
        for (string folder = Path.GetDirectoryName(path); folder != null && folder.StartsWith(root, StringComparison.OrdinalIgnoreCase); folder = Path.GetDirectoryName(folder))
            if (Directory.Exists(folder) && (File.GetAttributes(folder) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("安装目录不能包含链接或目录联接。");
        return path;
    }
    static string StartFolder { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "TianyiPet"); } }
    static string DesktopLink { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "洛天依桌宠.lnk"); } }
    static void Shortcut(string path, string target, string arguments) {
        Type type = Type.GetTypeFromProgID("WScript.Shell");
        object shell = Activator.CreateInstance(type);
        object link = type.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
        Type item = link.GetType();
        item.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { target });
        item.InvokeMember("Arguments", BindingFlags.SetProperty, null, link, new object[] { arguments });
        item.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { Path.GetDirectoryName(target) });
        item.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
    }
    static void NotRunning(string root) {
        foreach (Process process in Process.GetProcessesByName("TianyiPet")) {
            try {
                if (Root(process.MainModule.FileName) == Root(Path.Combine(root, "TianyiPet.exe")))
                    throw new IOException("请先从系统托盘退出正在运行的桌宠，再重试。");
            } catch (System.ComponentModel.Win32Exception) { }
        }
    }
    static void Install(string destination, bool desktop, bool test, Action<int> progress) {
        string root = Root(destination);
        NotRunning(root);
        string archive = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "payload.zip");
        if (!File.Exists(archive)) throw new IOException("缺少安装文件 payload.zip，请重新下载安装包。");
        Directory.CreateDirectory(root);
        string manifestPath = Path.Combine(root, "installed-files.txt");
        if (File.Exists(Path.Combine(root, "TianyiPet.exe")) && !File.Exists(manifestPath))
            throw new IOException("请选择空目录，或之前安装此版本桌宠的目录。");
        var installed = new System.Collections.Generic.List<string>();
        File.WriteAllLines(manifestPath, new string[] { "installed-files.txt" });
        using (ZipArchive zip = ZipFile.OpenRead(archive)) {
            long total = Math.Max(1, zip.Entries.Sum(e => e.Length)), copied = 0;
            foreach (ZipArchiveEntry entry in zip.Entries) {
                if (String.IsNullOrEmpty(entry.Name)) continue;
                string target = Child(root, entry.FullName.Replace('/', Path.DirectorySeparatorChar));
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                entry.ExtractToFile(target, true);
                installed.Add(entry.FullName.Replace('/', Path.DirectorySeparatorChar));
                File.WriteAllLines(manifestPath, installed.Concat(new string[] { "installed-files.txt" }));
                copied += entry.Length;
                progress((int)(copied * 95 / total));
            }
        }
        File.Copy(Application.ExecutablePath, Path.Combine(root, "TianyiSetup.exe"), true);
        installed.Add("TianyiSetup.exe");
        installed.Add("installed-files.txt");
        File.WriteAllLines(manifestPath, installed);
        if (!test) {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(Key)) {
                key.SetValue("DisplayName", "洛天依桌宠");
                key.SetValue("DisplayVersion", "0.4.0");
                key.SetValue("InstallLocation", root);
                key.SetValue("DisplayIcon", Path.Combine(root, "TianyiPet.exe"));
                key.SetValue("UninstallString", "\"" + Path.Combine(root, "TianyiSetup.exe") + "\" --uninstall --dir \"" + root + "\"");
                key.SetValue("NoModify", 1); key.SetValue("NoRepair", 1);
            }
            Directory.CreateDirectory(StartFolder);
            Shortcut(Path.Combine(StartFolder, "洛天依桌宠.lnk"), Path.Combine(root, "TianyiPet.exe"), "");
            Shortcut(Path.Combine(StartFolder, "卸载洛天依桌宠.lnk"), Path.Combine(root, "TianyiSetup.exe"), "--uninstall --dir \"" + root + "\"");
            if (desktop) Shortcut(DesktopLink, Path.Combine(root, "TianyiPet.exe"), "");
        }
        progress(100);
    }
    static void Uninstall(string destination, bool test) {
        string root = Root(destination);
        NotRunning(root);
        string manifest = Path.Combine(root, "installed-files.txt");
        if (!File.Exists(manifest)) throw new IOException("找不到安装清单，未删除任何文件。");
        var directories = new System.Collections.Generic.HashSet<string>();
        foreach (string relative in File.ReadAllLines(manifest)) {
            string path = Child(root, relative);
            for (string folder = Path.GetDirectoryName(path); folder != null && folder.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase); folder = Path.GetDirectoryName(folder))
                directories.Add(folder);
            if (File.Exists(path)) File.Delete(path);
        }
        foreach (string directory in directories.OrderByDescending(x => x.Length))
            if (Directory.Exists(directory) && !Directory.EnumerateFileSystemEntries(directory).Any()) Directory.Delete(directory);
        if (!Directory.EnumerateFileSystemEntries(root).Any()) Directory.Delete(root);
        if (!test) {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(Key)) {
                if (key != null && String.Equals(key.GetValue("InstallLocation") as string, root, StringComparison.OrdinalIgnoreCase)) {
                    key.Close(); Registry.CurrentUser.DeleteSubKeyTree(Key, false);
                }
            }
            using (RegistryKey run = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", true)) {
                string value = run == null ? null : run.GetValue("TianyiDeskPet") as string;
                if (value != null && value.IndexOf(Path.Combine(root, "TianyiPet.exe"), StringComparison.OrdinalIgnoreCase) >= 0)
                    run.DeleteValue("TianyiDeskPet", false);
            }
            foreach (string path in new string[] { DesktopLink, Path.Combine(StartFolder, "洛天依桌宠.lnk"), Path.Combine(StartFolder, "卸载洛天依桌宠.lnk") })
                if (File.Exists(path)) File.Delete(path);
            if (Directory.Exists(StartFolder) && !Directory.EnumerateFileSystemEntries(StartFolder).Any()) Directory.Delete(StartFolder);
        }
    }
    [STAThread] static int Main(string[] args) {
        Args = args;
        Application.EnableVisualStyles();
        string destination = Option("--dir", Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "TianyiPet"));
        bool quiet = Has("--quiet"), test = Has("--test");
        try {
            if (Has("--uninstall")) {
                if (!quiet && !Has("--temp") && MessageBox.Show("卸载洛天依桌宠？听歌记录和设置会保留。", "卸载", MessageBoxButtons.YesNo) != DialogResult.Yes) return 0;
                if (Root(Application.ExecutablePath).StartsWith(Root(destination) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) {
                    string copy = Path.Combine(Path.GetTempPath(), "TianyiUninstall-" + Guid.NewGuid().ToString("N") + ".exe");
                    File.Copy(Application.ExecutablePath, copy);
                    Process.Start(copy, "--uninstall --temp --quiet --dir \"" + destination + "\"" + (test ? " --test" : "") + " --parent " + Process.GetCurrentProcess().Id);
                    return 0;
                }
                string parent = Option("--parent", "");
                if (parent != "") { try { Process.GetProcessById(Int32.Parse(parent)).WaitForExit(5000); } catch (ArgumentException) { } }
                Uninstall(destination, test);
                if (!quiet) MessageBox.Show("卸载完成。听歌记录和设置已保留。", "洛天依桌宠");
                return 0;
            }
            if (quiet) { Install(destination, false, test, value => { }); return 0; }
            Form form = new Form { Text = "安装洛天依桌宠", ClientSize = new Size(490, 265), StartPosition = FormStartPosition.CenterScreen, FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false };
            Label title = new Label { Text = "洛天依桌宠", Font = new Font("Microsoft YaHei UI", 17), Bounds = new Rectangle(22, 18, 440, 36) };
            Label detail = new Label { Text = "Windows 10 / 11 64 位 · 无需安装 Python\nB站播放需要 Microsoft Edge WebView2。", Bounds = new Rectangle(24, 60, 440, 42) };
            TextBox pathBox = new TextBox { Text = destination, Bounds = new Rectangle(24, 112, 350, 25) };
            Button browse = new Button { Text = "更改位置", Bounds = new Rectangle(382, 110, 85, 28) };
            browse.Click += (sender, e) => { using (FolderBrowserDialog folder = new FolderBrowserDialog()) { if (folder.ShowDialog() == DialogResult.OK) pathBox.Text = Path.Combine(folder.SelectedPath, "TianyiPet"); } };
            CheckBox desktop = new CheckBox { Text = "创建桌面快捷方式", Checked = true, Bounds = new Rectangle(24, 150, 220, 25) };
            ProgressBar bar = new ProgressBar { Bounds = new Rectangle(24, 187, 443, 14) };
            Button install = new Button { Text = "安装", Bounds = new Rectangle(365, 218, 102, 30) };
            bool complete = false;
            BackgroundWorker worker = new BackgroundWorker { WorkerReportsProgress = true };
            worker.DoWork += (sender, e) => Install((string)((object[])e.Argument)[0], (bool)((object[])e.Argument)[1], false, value => worker.ReportProgress(value));
            worker.ProgressChanged += (sender, e) => bar.Value = e.ProgressPercentage;
            worker.RunWorkerCompleted += (sender, e) => { install.Enabled = true; if (e.Error != null) { MessageBox.Show(e.Error.Message, "安装未完成"); pathBox.Enabled = browse.Enabled = desktop.Enabled = true; } else { complete = true; install.Text = "启动桌宠"; detail.Text = "安装完成，可通过桌面或开始菜单打开。\n卸载时会保留听歌记录和设置。"; } };
            form.FormClosing += (sender, e) => { if (worker.IsBusy) e.Cancel = true; };
            install.Click += (sender, e) => { if (complete) { Process.Start(Path.Combine(pathBox.Text, "TianyiPet.exe")); form.Close(); } else { install.Enabled = pathBox.Enabled = browse.Enabled = desktop.Enabled = false; worker.RunWorkerAsync(new object[] { pathBox.Text, desktop.Checked }); } };
            form.Controls.AddRange(new Control[] { title, detail, pathBox, browse, desktop, bar, install });
            Application.Run(form); return 0;
        } catch (Exception error) { if (!quiet) MessageBox.Show(error.Message, "未完成"); else File.WriteAllText(Path.Combine(Path.GetTempPath(), "TianyiSetup-error.txt"), error.ToString()); return 1; }
    }
}
