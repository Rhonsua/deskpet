# Experimental VOCALOID6 GUI bridge

This is an unverified Windows UI Automation experiment, not a headless engine. It is not connected to chat. Close the editor yourself before an authorized test. Existing VOCALOID6 processes are rejected; only the process launched by this bridge is targeted. The bridge never closes it. Errors or cancellation end the session, leaving the editor open for inspection. A new session will refuse to attach to it.

Build from the repository root using Windows Framework64/v4.0.30319/csc.exe, referencing WPF/UIAutomationClient.dll, UIAutomationTypes.dll, WindowsBase.dll and System.Web.Extensions.dll. No SDK download is required.

Single job: `bridge.exe <editor.exe> <input.vsqx> <new-output.wav> <timeout-seconds> [cancel-file]`.

Persistent UTF-8 JSON lines: `bridge.exe --session <editor.exe>`; wait for `{"event":"ready"}`, then send one job per line:

```json
{"cmd":"render","id":"job1","input":"C:\\absolute\\input.vsqx","output":"C:\\absolute\\new.wav","timeout":120}
```

Responses include `started`, `wait_user`, `completed`, or `error`. Activation/privacy prompts are not answered; a `wait_user` event asks the person at the editor to handle the prompt while the job remains pending until timeout. The bridge does not accept another render while busy. Send `{"cmd":"cancel","id":"job1"}` to end the current session safely without closing the editor, and `{"cmd":"quit"}` while idle to stop the bridge. Never play an output unless the corresponding `completed` event is received. The caller owns output files and must choose a new path for each job. No text or tool output is synthesized here.

It opens the home OPEN control or main File/Open, verifies the visible project title and exact selected singer `Luo_Tianyi_Meng`, selects 44.1 kHz and 16-bit options, then validates stable non-silent PCM WAVE. Controls, labels, UI version, export dialog behavior, authorization prompt detection and consecutive jobs have not yet been verified against a running editor. In particular, reopening an unsaved project can raise a confirmation which requires the user. Unknown prompts are not answered. This workflow uses the visible desktop and may interfere with activity. User-launched editor and output creation races cannot be completely excluded. Do not treat this as unattended chat synthesis until the UI and continuous jobs have been verified.
