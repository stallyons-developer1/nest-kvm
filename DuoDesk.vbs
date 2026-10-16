' Double-click on Windows: updates, sets up, and opens DuoDesk. No console, no commands.
Option Explicit
Dim fso, sh, dir, py, pyw
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
py  = dir & "\.venv\Scripts\python.exe"
pyw = dir & "\.venv\Scripts\pythonw.exe"

' pull the latest code if git is available (ignore any error)
On Error Resume Next
sh.Run "cmd /c git -C """ & dir & """ pull", 0, True
On Error GoTo 0

' create the virtual environment on first run
If Not fso.FileExists(py) Then
    sh.Run "cmd /c python -m venv """ & dir & "\.venv""", 0, True
End If

If fso.FileExists(py) Then
    ' keep dependencies up to date, then launch with no console window
    sh.Run """" & py & """ -m pip install -q -r """ & dir & "\requirements.txt""", 0, True
    sh.Run """" & pyw & """ -m duodesk gui", 0, False
Else
    MsgBox "Python 3 was not found." & vbCrLf & _
           "Install it from python.org and tick 'Add Python to PATH', then double-click DuoDesk.vbs again.", _
           48, "DuoDesk"
End If
