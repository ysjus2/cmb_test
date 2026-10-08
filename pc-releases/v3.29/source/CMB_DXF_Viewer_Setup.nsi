Unicode True
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!ifndef APP_EXE
 !define APP_EXE "dist\CMB_DXF_Viewer.exe"
!endif
!ifndef LICENSE_FILE
 !define LICENSE_FILE "THIRD_PARTY_LICENSES.txt"
!endif
!ifndef OUTPUT_FILE
 !define OUTPUT_FILE "CMB_DXF_Viewer_Setup.exe"
!endif
Name "CMB DXF Viewer"
OutFile "${OUTPUT_FILE}"
InstallDir "$PROGRAMFILES64\CMB_DXF_Viewer"
RequestExecutionLevel admin
SetCompressor zlib
ShowInstDetails show
!define APP_VERSION "3.29"
Var PowerShellPath
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\CMB_DXF_Viewer.exe"
!define MUI_FINISHPAGE_RUN_TEXT "CMB DXF Viewer 실행"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Korean"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP|MB_OK "Windows x64가 필요합니다."
    Abort
  ${EndIf}
  SetRegView 64
  SetShellVarContext all
  StrCpy $PowerShellPath "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  InitPluginsDir
FunctionEnd

Function CheckVCRuntime
  ReadRegDWORD $0 HKLM "SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Installed"
  ${If} $0 == 1
    Return
  ${EndIf}
  File /oname=$PLUGINSDIR\ensure_vcredist.ps1 "ensure_vcredist.ps1"
  ExecWait '"$PowerShellPath" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\ensure_vcredist.ps1" -Quiet' $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP|MB_OK "Visual C++ Runtime 설치 확인에 실패했습니다."
    Abort
  ${EndIf}
FunctionEnd

Section "CMB DXF Viewer"
  Call CheckVCRuntime
  SetOutPath "$INSTDIR"
  ClearErrors
  File /oname=CMB_DXF_Viewer.exe "${APP_EXE}"
  File /oname=THIRD_PARTY_LICENSES.txt "${LICENSE_FILE}"
  File /oname=README.txt "README.md"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ${If} ${Errors}
    SetErrorLevel 13
    Abort
  ${EndIf}
  CreateDirectory "$SMPROGRAMS\CMB DXF Viewer"
  CreateShortCut "$SMPROGRAMS\CMB DXF Viewer\CMB DXF Viewer.lnk" "$INSTDIR\CMB_DXF_Viewer.exe"
  CreateShortCut "$SMPROGRAMS\CMB DXF Viewer\Uninstall CMB DXF Viewer.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\CMB DXF Viewer.lnk" "$INSTDIR\CMB_DXF_Viewer.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "DisplayName" "CMB DXF Viewer"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "Publisher" "CMB"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "DisplayIcon" "$INSTDIR\CMB_DXF_Viewer.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "NoRepair" 1
  ${If} ${Errors}
    MessageBox MB_ICONSTOP|MB_OK "바로가기 또는 제거 등록을 완료하지 못했습니다."
    SetErrorLevel 13
    Abort
  ${EndIf}
SectionEnd


Section "Uninstall"
  SetRegView 64
  SetShellVarContext all
  Delete "$DESKTOP\CMB DXF Viewer.lnk"
  Delete "$SMPROGRAMS\CMB DXF Viewer\CMB DXF Viewer.lnk"
  Delete "$SMPROGRAMS\CMB DXF Viewer\Uninstall CMB DXF Viewer.lnk"
  RMDir "$SMPROGRAMS\CMB DXF Viewer"
  Delete "$INSTDIR\CMB_DXF_Viewer.exe"
  Delete "$INSTDIR\THIRD_PARTY_LICENSES.txt"
  Delete "$INSTDIR\README.txt"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer"
SectionEnd
