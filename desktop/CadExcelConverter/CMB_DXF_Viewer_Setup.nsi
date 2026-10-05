Unicode True
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "nsDialogs.nsh"

Name "CMB DXF Viewer"
OutFile "CMB_DXF_Viewer_Setup.exe"
InstallDir "$PROGRAMFILES64\CMB_DXF_Viewer"
RequestExecutionLevel admin
SetCompressor zlib
ShowInstDetails show

!define APP_VERSION "3.20"
!define NOTICE_VERSION "CMB-INTERNAL-USE-2026-10-05-v1"
!define ACK_DIR "$COMMONAPPDATA\CMB\CMB_DXF_Viewer"
!define ACK_LOG "$COMMONAPPDATA\CMB\CMB_DXF_Viewer\install_acknowledgement.log"

Var InstallerName
Var InstallerDept
Var InstallerConsent
Var NameField
Var DeptField
Var ConsentCheckbox

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
Page custom InstallerInfoPage InstallerInfoPageLeave
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "Korean"

Function InstallerInfoPage
  IfSilent silentMode 0

  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 100% 26u "사내 업무용 소프트웨어 사용 확인"
  Pop $0

  ${NSD_CreateLabel} 0 28u 100% 58u "본 프로그램은 회사 내부 업무 목적으로만 제공됩니다.$\r$\n회사의 사전 승인 없이 설치파일, 실행파일 또는 관련 자료를 외부인·외부업체에 복사·전달·반출하는 것을 금지합니다.$\r$\n무단 반출 또는 제3자 제공 시 회사 내부 규정 및 관계 법령에 따른 책임이 발생할 수 있습니다."
  Pop $0

  ${NSD_CreateLabel} 0 92u 28% 12u "사용자명(성명)"
  Pop $0
  ${NSD_CreateText} 30% 90u 68% 12u "$InstallerName"
  Pop $NameField

  ${NSD_CreateLabel} 0 112u 28% 12u "부서명"
  Pop $0
  ${NSD_CreateText} 30% 110u 68% 12u "$InstallerDept"
  Pop $DeptField

  ${NSD_CreateCheckbox} 0 136u 100% 24u "위 내용을 확인하였으며 사내 업무 목적으로만 사용하고 외부 반출 금지 의무를 준수하겠습니다."
  Pop $ConsentCheckbox
  ${If} $InstallerConsent == "1"
    ${NSD_Check} $ConsentCheckbox
  ${EndIf}

  nsDialogs::Show
  Return

silentMode:
  StrCpy $InstallerName "CI-VALIDATION"
  StrCpy $InstallerDept "CI"
  StrCpy $InstallerConsent "1"
FunctionEnd

Function InstallerInfoPageLeave
  IfSilent done 0

  ${NSD_GetText} $NameField $InstallerName
  ${NSD_GetText} $DeptField $InstallerDept
  ${NSD_GetState} $ConsentCheckbox $0

  ${If} $InstallerName == ""
    MessageBox MB_ICONEXCLAMATION|MB_OK "사용자명(성명)을 입력해 주세요."
    Abort
  ${EndIf}
  ${If} $InstallerDept == ""
    MessageBox MB_ICONEXCLAMATION|MB_OK "부서명을 입력해 주세요."
    Abort
  ${EndIf}
  ${If} $0 != ${BST_CHECKED}
    MessageBox MB_ICONEXCLAMATION|MB_OK "사내 사용 및 외부 반출 금지 고지에 동의해야 설치를 진행할 수 있습니다."
    Abort
  ${EndIf}

  StrCpy $InstallerConsent "1"
done:
FunctionEnd

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

Function WriteAcknowledgement
  CreateDirectory "${ACK_DIR}"
  FileOpen $0 "${ACK_LOG}" a
  FileWrite $0 "----------------------------------------$\r$\n"
  FileWrite $0 "Installer name: $InstallerName$\r$\n"
  FileWrite $0 "Department: $InstallerDept$\r$\n"
  FileWrite $0 "Computer: $COMPUTERNAME$\r$\n"
  FileWrite $0 "Windows user: $USERNAME$\r$\n"
  FileWrite $0 "Installed at: ${__DATE__} ${__TIME__}$\r$\n"
  FileWrite $0 "Application version: ${APP_VERSION}$\r$\n"
  FileWrite $0 "Notice version: ${NOTICE_VERSION}$\r$\n"
  FileWrite $0 "Internal-use consent: YES$\r$\n"
  FileClose $0
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
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "Publisher" "CMB"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "DisplayIcon" "$INSTDIR\CMB_DXF_Viewer.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\CMB_DXF_Viewer" "NoRepair" 1

  Call WriteAcknowledgement
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
  ; Deliberately keep ${ACK_LOG} for audit/history even after uninstall.
SectionEnd

Function .onInstSuccess
  IfSilent done 0
  Exec '"$INSTDIR\CMB_DXF_Viewer.exe"'
done:
FunctionEnd
