using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using System.Windows.Automation;

// A fail-closed GUI experiment. This is not a headless synthesis API.
internal static class Program
{
    static volatile bool cancelled;
    static DateTime deadline;
    static bool sessionMode;
    static readonly object outputLock = new object();
    static int pid;
    static DateTime started;
    static string stage = "arguments";
    static readonly string[] Suspicious = { "license", "licence", "activation", "activate", "authoriz", "授权", "privacy", "agreement", "consent", "利用規約", "認証", "プライバシー", "同意", "save changes", "unsaved changes", "変更を保存", "保存更改" };
    static int Main(string[] args)
    {
        Console.InputEncoding = new System.Text.UTF8Encoding(false); Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        if (args.Length == 2 && args[0] == "--session") return Session(args[1]);
        if (args.Length == 1 && args[0] == "--help") { Console.WriteLine("bridge <VOCALOID6.exe> <input.vsqx> <new-output.wav> <timeout-seconds> [cancel-file]"); return 0; }
        if (args.Length < 4 || args.Length > 5) { Console.Error.WriteLine("invalid arguments; use --help"); return 2; }
        string exe, input, output, cancelFile;
        int timeout;
        try {
            exe = Path.GetFullPath(args[0]); input = Path.GetFullPath(args[1]); output = Path.GetFullPath(args[2]);
            cancelFile = args.Length == 5 ? Path.GetFullPath(args[4]) : null;
            if (!File.Exists(exe) || !File.Exists(input) || !String.Equals(Path.GetExtension(input), ".vsqx", StringComparison.OrdinalIgnoreCase) || !String.Equals(Path.GetExtension(output), ".wav", StringComparison.OrdinalIgnoreCase) || File.Exists(output) || !Directory.Exists(Path.GetDirectoryName(output)) || !int.TryParse(args[3], out timeout) || timeout < 10 || timeout > 1800 || (cancelFile != null && File.Exists(cancelFile))) throw new ArgumentException("Invalid input, output, timeout or cancel file");
        } catch (Exception e) { Console.Error.WriteLine(e.Message); return 2; }
        bool acquired = false;
        using (var mutex = new Mutex(false, @"Local\TianyiVocaloidBridge")) {
            try { try { acquired = mutex.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; } if (!acquired) { Console.Error.WriteLine("busy"); return 3; }
                if (Process.GetProcessesByName("VOCALOID6").Length != 0) { Console.Error.WriteLine("busy: existing VOCALOID6; no editor touched"); return 3; }
                deadline = DateTime.UtcNow.AddSeconds(timeout);
                Exception failure = null;
                var worker = new Thread(() => { try { Run(exe, input, output, cancelFile); } catch (Exception e) { failure = e; } });
                worker.IsBackground = true; worker.SetApartmentState(ApartmentState.STA); worker.Start();
                while (worker.IsAlive) {
                    if ((cancelFile != null && File.Exists(cancelFile)) || DateTime.UtcNow >= deadline) { cancelled = true; Console.Error.WriteLine("cancelled or timed out at " + stage + "; owned editor left open for inspection"); return 4; }
                    worker.Join(100);
                }
                if (failure != null) { Console.Error.WriteLine("failed at " + stage + ": " + failure.Message + "; owned editor left open"); return 1; }
                Console.WriteLine("OK " + output); return 0;
            } finally { if (acquired) mutex.ReleaseMutex(); }
        }
    }
    static void Emit(object data) { lock (outputLock) { Console.WriteLine(new JavaScriptSerializer().Serialize(data)); Console.Out.Flush(); } }
    static int Session(string editor) {
        sessionMode = true;
        string exe;
        try { exe = Path.GetFullPath(editor); if (!File.Exists(exe)) throw new Exception("editor missing"); }
        catch (Exception e) { Emit(new { error = e.Message }); return 2; }
        using (var mutex = new Mutex(false, @"Local\TianyiVocaloidBridge")) {
            bool acquired = false;
            try {
                try { acquired = mutex.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
                if (!acquired || Process.GetProcessesByName("VOCALOID6").Length != 0) { Emit(new { error = "busy: existing editor or bridge" }); return 3; }
                var queue = new BlockingCollection<string>();
                var reader = new Thread(() => { string line; while ((line = Console.ReadLine()) != null) queue.Add(line); queue.CompleteAdding(); });
                reader.IsBackground = true; reader.Start();
                Emit(new { @event = "ready" });
                while (true) {
                    string line;
                    if (!queue.TryTake(out line, 100)) { if (queue.IsCompleted) return 0; continue; }
                    Dictionary<string, object> cmd;
                    try { cmd = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(line); }
                    catch { Emit(new { error = "invalid JSON" }); continue; }
                    string action = cmd.ContainsKey("cmd") ? Convert.ToString(cmd["cmd"]) : "";
                    if (action == "quit") return 0;
                    if (action != "render") { Emit(new { error = "expected render or quit" }); continue; }
                    string id = cmd.ContainsKey("id") ? Convert.ToString(cmd["id"]) : "";
                    string input, output; int timeout;
                    try {
                        input = Path.GetFullPath(Convert.ToString(cmd["input"])); output = Path.GetFullPath(Convert.ToString(cmd["output"]));
                        timeout = cmd.ContainsKey("timeout") ? Convert.ToInt32(cmd["timeout"]) : 120;
                        if (id.Length == 0 || !File.Exists(input) || !input.EndsWith(".vsqx", StringComparison.OrdinalIgnoreCase) || !output.EndsWith(".wav", StringComparison.OrdinalIgnoreCase) || File.Exists(output) || !Directory.Exists(Path.GetDirectoryName(output)) || timeout < 10 || timeout > 1800) throw new Exception("invalid input/output/timeout/id");
                    } catch (Exception e) { Emit(new { @event = "error", id = id, error = e.Message }); continue; }
                    cancelled = false; deadline = DateTime.UtcNow.AddSeconds(timeout); Exception failure = null;
                    var worker = new Thread(() => { try { Run(exe, input, output, null); } catch (Exception e) { failure = e; } });
                    worker.IsBackground = true; worker.SetApartmentState(ApartmentState.STA); worker.Start();
                    Emit(new { @event = "started", id = id });
                    while (worker.IsAlive) {
                        if (DateTime.UtcNow >= deadline) cancelled = true;
                        string incoming;
                        if (queue.TryTake(out incoming, 100)) {
                            try { var other = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(incoming); string c = other.ContainsKey("cmd") ? Convert.ToString(other["cmd"]) : "";
                                if (c == "cancel" && other.ContainsKey("id") && Convert.ToString(other["id"]) == id) cancelled = true;
                                else Emit(new { @event = "busy", id = id });
                            } catch { Emit(new { error = "invalid JSON" }); }
                        }
                        if (cancelled) { Emit(new { @event = "cancelled", id = id, stage = stage, note = "session ended; owned editor left open" }); return 4; }
                    }
                    if (failure != null) { Emit(new { @event = "error", id = id, stage = stage, error = failure.Message, note = "session ended; editor left open" }); return 1; }
                    Emit(new { @event = "completed", id = id, output = output });
                }
            } finally { if (acquired) mutex.ReleaseMutex(); }
        }
    }
    static void Check() { if (cancelled || DateTime.UtcNow >= deadline) throw new OperationCanceledException(); if (pid != 0) { var p = Process.GetProcessById(pid); if (p.HasExited || p.StartTime.ToUniversalTime() != started) throw new Exception("editor identity changed"); } }
    static AutomationElement[] All(AutomationElement root) { return root.FindAll(TreeScope.Descendants, Condition.TrueCondition).Cast<AutomationElement>().ToArray(); }
    static AutomationElement[] Windows() { Check(); return AutomationElement.RootElement.FindAll(TreeScope.Children, new PropertyCondition(AutomationElement.ProcessIdProperty, pid)).Cast<AutomationElement>().ToArray(); }
    static void Safety() {
        bool reported = false;
        while (true) {
            bool found = false;
            foreach (var w in Windows()) { if (w.Current.AutomationId == "xMainWindow" || w.Current.IsOffscreen) continue;
                var labels = new[] { w }.Concat(All(w).Where(e => e.Current.ControlType == ControlType.Text));
                foreach (var e in labels) { string text = e.Current.Name ?? ""; if (Suspicious.Any(x => text.IndexOf(x, StringComparison.OrdinalIgnoreCase) >= 0)) { found = true; break; } }
            }
            if (!found) return;
            if (!reported) { if (sessionMode) Emit(new Dictionary<string, object> { {"event", "wait_user"}, {"stage", stage}, {"reason", "activation, privacy or license decision"} }); else Console.Error.WriteLine("WAIT_USER: activation, privacy or license decision"); reported = true; }
            Check(); Thread.Sleep(250);
        }
    }
    static AutomationElement Wait(Func<AutomationElement> fn, string label) { while (true) { Check(); Safety(); var e = fn(); if (e != null) return e; Thread.Sleep(150); } }
    static AutomationElement Id(AutomationElement root, string id) { return All(root).FirstOrDefault(e => e.Current.AutomationId == id && e.Current.IsEnabled && !e.Current.IsOffscreen); }
    static AutomationElement Named(AutomationElement root, ControlType type, params string[] names) { return All(root).FirstOrDefault(e => e.Current.ControlType == type && e.Current.IsEnabled && !e.Current.IsOffscreen && names.Any(n => String.Equals(e.Current.Name, n, StringComparison.OrdinalIgnoreCase))); }
    static void Invoke(AutomationElement e) { Check(); Safety(); object p; if (e.TryGetCurrentPattern(InvokePattern.Pattern, out p)) ((InvokePattern)p).Invoke(); else if (e.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out p)) ((ExpandCollapsePattern)p).Expand(); else throw new Exception("control does not expose Invoke/Expand"); }
    static void Run(string exe, string input, string output, string cancelFile)
    {
        stage = "launch"; Check();
        if (pid == 0) {
        // Recheck immediately before launch. Other programs cannot honor our mutex, so recheck again after launch.
        if (Process.GetProcessesByName("VOCALOID6").Length != 0) throw new Exception("existing editor detected");
        var p = Process.Start(new ProcessStartInfo(exe) { UseShellExecute = false, WorkingDirectory = Path.GetDirectoryName(exe) });
        if (p == null) throw new Exception("editor failed to start"); pid = p.Id; started = p.StartTime.ToUniversalTime();
        if (Process.GetProcessesByName("VOCALOID6").Any(q => q.Id != pid)) throw new Exception("another editor appeared; stopping without touching it");
        Console.Error.WriteLine("owned-editor pid=" + pid + " start=" + started.ToString("o"));
        }
        stage = "wait editor window";
        var homeOrMain = Wait(() => Windows().FirstOrDefault(w => w.Current.AutomationId == "xMainWindow" || w.Current.AutomationId == "xHomeWindow"), stage);
        stage = "open project";
        if (homeOrMain.Current.AutomationId == "xHomeWindow") {
            var openButton = Wait(() => All(homeOrMain).FirstOrDefault(e => e.Current.ControlType == ControlType.Button && e.Current.IsEnabled && !e.Current.IsOffscreen && (e.Current.Name == "OPEN" || All(e).Any(c => c.Current.ControlType == ControlType.Text && c.Current.Name == "OPEN"))), "home OPEN");
            Invoke(openButton);
        } else {
            var fileMenu = Wait(() => Named(homeOrMain, ControlType.MenuItem, "File", "ファイル", "文件"), "File menu"); Invoke(fileMenu);
            var open = Wait(() => Windows().SelectMany(All).FirstOrDefault(e => e.Current.ControlType == ControlType.MenuItem && new[]{"Open", "Open...", "Open…", "開く", "開く...", "打开", "打开..."}.Any(n => String.Equals(e.Current.Name,n,StringComparison.OrdinalIgnoreCase)) && e.Current.IsEnabled && !e.Current.IsOffscreen), "Open menu"); Invoke(open);
        }
        stage = "open file dialog"; FileDialog(input);
        stage = "verify project";
        var expectedTitle = "VOCALOID6 Editor - " + Path.GetFileNameWithoutExtension(input);
        var main = Wait(() => Windows().Where(w => w.Current.AutomationId == "xMainWindow").FirstOrDefault(w => All(w).Any(e => e.Current.ControlType == ControlType.Text && String.Equals(e.Current.Name, expectedTitle, StringComparison.OrdinalIgnoreCase))), "project title");
        stage = "show musical editor";
        var showEdit = Wait(() => Id(main, "xShowEditButton"), "show edit"); Invoke(showEdit);
        stage = "verify singer";
        // Strictly require a currently visible, exact UI value; no project-file claims or automatic guessing.
        var combo = Wait(() => Id(main, "xVoiceBankComboBox"), "voice selector");
        object pattern; string value = combo.Current.HelpText;
        if (!String.Equals((value ?? "").Trim(), "Luo_Tianyi_Meng", StringComparison.Ordinal) && combo.TryGetCurrentPattern(ValuePattern.Pattern, out pattern)) value = ((ValuePattern)pattern).Current.Value;
        if (!String.Equals((value ?? "").Trim(), "Luo_Tianyi_Meng", StringComparison.Ordinal)) throw new Exception("Singer not verified from visible selector: " + value);
        stage = "mixdown"; var file = Wait(() => Named(main, ControlType.MenuItem, "File", "ファイル", "文件"), "File menu"); Invoke(file);
        var mix = Wait(() => Windows().SelectMany(All).FirstOrDefault(e => e.Current.ControlType == ControlType.MenuItem && e.Current.IsEnabled && !e.Current.IsOffscreen && (e.Current.Name.IndexOf("Audio Mixdown", StringComparison.OrdinalIgnoreCase) >= 0 || e.Current.Name.Contains("オーディオミックスダウン"))), "mixdown menu"); Invoke(mix);
        stage = "mixdown options";
        var dialog = Wait(() => Windows().SelectMany(All).FirstOrDefault(e => e.Current.AutomationId == "xAudioMixdownDlg" && !e.Current.IsOffscreen) ?? Windows().FirstOrDefault(e => e.Current.AutomationId == "xAudioMixdownDlg"), "mixdown settings");
        SelectOption(dialog, "xSampleRateComboBox", new[]{"44.1 kHz", "44.1kHz", "44100 Hz", "44100"});
        SelectOption(dialog, "xBitDepthComboBox", new[]{"16 bit", "16bit", "16-bit", "16"});
        var explorer = Id(dialog, "xOpenExplorerCheckBox"); object toggle;
        if (explorer != null && explorer.TryGetCurrentPattern(TogglePattern.Pattern, out toggle) && ((TogglePattern)toggle).Current.ToggleState == ToggleState.On) ((TogglePattern)toggle).Toggle();
        var ok = Id(dialog,"xOKButton"); if (ok == null) throw new Exception("mixdown confirmation missing"); Invoke(ok);
        stage = "save file dialog"; if (File.Exists(output)) throw new Exception("output appeared; refusing overwrite"); FileDialog(output);
        stage = "validate wav"; ValidateWave(output);
    }
    static void SelectOption(AutomationElement dialog, string id, string[] allowed) {
        var combo = Id(dialog, id); if (combo == null) throw new Exception("Missing mixdown selector " + id);
        object pattern; string existing = combo.Current.Name ?? "";
        if (combo.TryGetCurrentPattern(ValuePattern.Pattern, out pattern)) existing = ((ValuePattern)pattern).Current.Value;
        if (allowed.Any(x => String.Equals(x, existing.Trim(), StringComparison.OrdinalIgnoreCase))) return;
        if (!combo.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out pattern)) throw new Exception("Cannot expand " + id);
        ((ExpandCollapsePattern)pattern).Expand();
        var item = Wait(() => Windows().SelectMany(All).FirstOrDefault(e => e.Current.ControlType == ControlType.ListItem && e.Current.IsEnabled && !e.Current.IsOffscreen && allowed.Any(x => String.Equals(x, e.Current.Name.Trim(), StringComparison.OrdinalIgnoreCase))), id + " choice");
        object selection; if (!item.TryGetCurrentPattern(SelectionItemPattern.Pattern, out selection)) throw new Exception("Cannot select " + id);
        ((SelectionItemPattern)selection).Select();
        if (!((SelectionItemPattern)selection).Current.IsSelected) throw new Exception("Could not verify " + id);
    }
    static void FileDialog(string path) {
        var d = Wait(() => Windows().FirstOrDefault(w => w.Current.ClassName == "#32770" && w.Current.IsEnabled && !w.Current.IsOffscreen), "file dialog");
        var field = All(d).FirstOrDefault(e => e.Current.ControlType == ControlType.Edit && e.Current.AutomationId == "1148" && e.Current.IsEnabled && !e.Current.IsOffscreen); object v; if (field == null || !field.TryGetCurrentPattern(ValuePattern.Pattern, out v)) throw new Exception("filename field unavailable");
        ((ValuePattern)v).SetValue(path); var button = Id(d, "1"); if (button == null) throw new Exception("file confirmation unavailable"); Invoke(button);
    }
    static void ValidateWave(string path) {
        long last = -1; int stable = 0;
        while (stable < 4) { Check(); Safety(); long len = File.Exists(path) ? new FileInfo(path).Length : 0; stable = len > 44 && len == last ? stable + 1 : 0; last = len; Thread.Sleep(250); }
        using (var f = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) using (var b = new BinaryReader(f)) {
            if (new string(b.ReadChars(4)) != "RIFF") throw new Exception("not RIFF"); long expected = b.ReadUInt32() + 8L; if (expected > f.Length || new string(b.ReadChars(4)) != "WAVE") throw new Exception("incomplete WAVE");
            bool format = false, sound = false;
            while (f.Position + 8 <= expected) { string tag = new string(b.ReadChars(4)); uint n = b.ReadUInt32(); long end = f.Position + n; if (end > expected) throw new Exception("truncated chunk");
                if (tag == "fmt " && n >= 16) { int pcm = b.ReadUInt16(), channels = b.ReadUInt16(); uint rate = b.ReadUInt32(); b.ReadUInt32(); b.ReadUInt16(); int bits = b.ReadUInt16(); format = pcm == 1 && (channels == 1 || channels == 2) && rate == 44100 && bits == 16; }
                if (tag == "data") { while (f.Position + 1 < end) if (Math.Abs((int)b.ReadInt16()) > 16) { sound = true; break; } }
                f.Position = end + (n & 1);
            }
            if (!format || !sound) throw new Exception("WAV is not non-silent 44.1kHz 16-bit PCM");
        }
    }
}
