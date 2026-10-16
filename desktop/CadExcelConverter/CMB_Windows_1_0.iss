#define ProductName "CMB 도면추출·온라인 뷰어"
#define ProductVersion "1.0"
[Setup]
AppId={{C5B20043-4477-4A40-A184-5C956D5A1000}
AppName={#ProductName}
AppVersion={#ProductVersion}
AppVerName={#ProductName} {#ProductVersion} - 외부반출 금지
DefaultDirName={autopf}\CMB Viewer 1.0
DefaultGroupName=CMB Viewer 1.0
OutputDir=dist
OutputBaseFilename=CMB_Windows_1.0_Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
InfoBeforeFile=RELEASE_NOTICE.txt
UninstallDisplayName=CMB Viewer 1.0 - 외부반출 금지
[Files]
Source: "dist\CMB_DXF_Viewer_Windows_1.0_Rev35.exe"; DestDir: "{app}"; DestName: "CMB_Viewer_1.0.exe"; Flags: ignoreversion
Source: "RELEASE_NOTICE.txt"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{autoprograms}\CMB Viewer 1.0"; Filename: "{app}\CMB_Viewer_1.0.exe"
Name: "{autodesktop}\CMB Viewer 1.0"; Filename: "{app}\CMB_Viewer_1.0.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "바탕화면 바로가기 생성"; GroupDescription: "추가 작업:"
[Run]
Filename: "{app}\CMB_Viewer_1.0.exe"; Description: "CMB Viewer 1.0 실행"; Flags: nowait postinstall skipifsilent
