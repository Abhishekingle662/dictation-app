; Inno Setup script for Dictation (per-user install under %LOCALAPPDATA%).
; Build (example):
;   1) Build exe:        powershell -ExecutionPolicy Bypass -File ..\build.ps1
;   2) Prefetch model:   python ..\tools\prefetch_model.py --model large-v3-turbo
;   3) Compile installer: ISCC.exe Dictation.iss

#define AppName "Dictation"
#define AppVersion "0.1.0"
#define AppExeName "Dictation.exe"
#define BundledModel "large-v3-turbo"
#define BundledModelDir "..\\bundle\\models\\" + BundledModel

[Setup]
AppId={{D9F6A4D8-1C23-4A55-9B44-38F4AE5E0B14}}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\\{#AppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputBaseFilename=DictationSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce
Name: "startup"; Description: "Start Dictation with Windows"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "..\\dist\\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

#ifexist "{#BundledModelDir}\\model.bin"
; Bundled starter model (recommended).
Source: "{#BundledModelDir}\\*"; DestDir: "{app}\\models\\{#BundledModel}"; Flags: ignoreversion recursesubdirs createallsubdirs
#else
; NOTE: Bundled model not found.
; Run:  python ..\tools\prefetch_model.py --model {#BundledModel}
#endif

[Icons]
Name: "{autoprograms}\\{#AppName}"; Filename: "{app}\\{#AppExeName}"
Name: "{autodesktop}\\{#AppName}"; Filename: "{app}\\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\\{#AppName}"; Filename: "{app}\\{#AppExeName}"; Tasks: startup
