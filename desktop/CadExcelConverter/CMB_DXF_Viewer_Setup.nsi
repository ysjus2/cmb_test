Unicode True
!include "MUI2.nsh"
!include "LogicLib.nsh"

Name "CMB DXF Viewer"
OutFile "CMB_DXF_Viewer_Setup.exe"
InstallDir "$PROGRAMFILES64\CMB_DXF_Viewer"
RequestExecutionLevel admin
SetCompressor zlib
ShowInstDetails show

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "Korean"

Function CheckVCRuntime
  IfSilent silentSkip 0

  ReadRegDWORD $0 HKLM "SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Installed"
  ${If} $0 == 1
    DetailPrint "Microsoft Visual C++ x64 Runtime detected."
    Return
  ${EndIf}

  MessageBox MB_OKCANCEL|MB_ICONINFORMATION \
    "Microsoft Visual C++ x64 Runtime이 필요합니다.$\r$\n$\r$\n확인을 누르면 Microsoft 공식 설치 프로그램이 실행됩니다.$\r$\n설치가 끝나면 CMB DXF Viewer 설치가 자동으로 계속됩니다." \
    IDOK +2
  Abort

  InitPluginsDir
  File /oname=$PLUGINSDIR\ensure_vcredist.ps1 "ensure_vcredist.ps1"
  DetailPrint "Microsoft Visual C++ x64 Runtime installer 준비 중..."
  ExecWait 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\ensure_vcredist.ps1"' $1

  ${If} $1 != 0
    MessageBox MB_ICONSTOP|MB_OK "Visual C++ Runtime 설치가 완료되지 않았습니다. 설치를 완료한 뒤 다시 실행해 주세요. (코드: $1)"
    Abort
  ${EndIf}

  ReadRegDWORD $0 HKLM "SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Installed"
  ${If} $0 != 1
    MessageBox MB_ICONSTOP|MB_OK "Visual C++ Runtime 설치 확인에 실패했습니다."
    Abort
  ${EndIf}

  DetailPrint "Microsoft Visual C++ x64 Runtime 설치 확인 완료."
  Return

silentSkip:
  DetailPrint "Silent validation mode: VC Runtime prerequisite UI skipped."
FunctionEnd

Section "CMB DXF Viewer" SEC_MAIN
  Call CheckVCRuntime

  SetOutPath "$INSTDIR"
  File "dist\CMB_DXF_Viewer.exe"
  File /oname=THIRD_PARTY_LICENSES.txt "THIRD_PARTY_LICENSES.txt"
  File /oname=README.txt "README.md"

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\CMB DXF Viewer"
  CreateShortCut "$SMPROGRAMS\CMB DXF Viewer\CMB DXF Viewer.lnk" "$INSTDIR\CMB_DXF_Viewer.exe" "" "$INSTDIR\CMB_DXF_Viewer.exe" 0
  CreateShortCut "$SMPROGRAMS\CMB DXF Viewer\Uninstall CMB DXF Viewer.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\CMB DXF Viewer.lnk" "$INSTDIR\CMB_DXF_Viewer.exe" "" "$INSTDIR\CMB_DXF_Viewer.exe" 0

  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "DisplayName" "CMB DXF Viewer"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "DisplayVersion" "3.20"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "Publisher" "CMB"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "DisplayIcon" "$INSTDIR\CMB_DXF_Viewer.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "NoRepair" 1
SectionEnd

Section "Uninstall"
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

Function .onInstSuccess
  IfSilent done 0
  Exec '"$INSTDIR\CMB_DXF_Viewer.exe"'
done:
FunctionEnd
