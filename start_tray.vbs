Option Explicit

Dim shell, fso, projectRoot, pythonw, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(projectRoot, ".venv\Scripts\pythonw.exe")

If Not fso.FileExists(pythonw) Then
    MsgBox "Run setup.ps1 first.", 16, "YT Music Telegram Sync"
    WScript.Quit 1
End If

command = Chr(34) & pythonw & Chr(34) & " -m yt_music_telegram_sync --tray"
shell.CurrentDirectory = projectRoot
shell.Run command, 0, False
