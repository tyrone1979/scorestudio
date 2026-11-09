' Hidden launcher for MuseScore plugin (no console flash).
Option Explicit
Dim sh, fso, dir, cmd, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = "cmd.exe /c """ & dir & "\generate.cmd"""
rc = sh.Run(cmd, 0, True)
WScript.Quit rc
