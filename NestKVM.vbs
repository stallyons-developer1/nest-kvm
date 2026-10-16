' Double-click on Windows to open NestKVM with NO console window.
' First run falls back to NestKVM.bat (visible) to set things up.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
venvpyw = dir & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(venvpyw) Then
    sh.Run "cmd /c """ & dir & "\NestKVM.bat""", 1, True
End If
If fso.FileExists(venvpyw) Then
    sh.Run """" & venvpyw & """ -m nestkvm gui", 0, False
End If
