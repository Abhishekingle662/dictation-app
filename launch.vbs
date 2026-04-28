Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
python  = appDir & "\.venv\Scripts\pythonw.exe"
script  = appDir & "\run.py"

WshShell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & script & Chr(34), 0, False

Set WshShell = Nothing
Set fso = Nothing
