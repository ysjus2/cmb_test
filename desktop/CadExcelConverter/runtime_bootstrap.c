#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <strsafe.h>

static BOOL vc_runtime_installed(void) {
    HKEY key = NULL;
    DWORD installed = 0;
    DWORD size = sizeof(installed);
    DWORD type = 0;
    LONG rc = RegOpenKeyExW(HKEY_LOCAL_MACHINE,
        L"SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64",
        0, KEY_READ | KEY_WOW64_64KEY, &key);
    if (rc != ERROR_SUCCESS) return FALSE;
    rc = RegQueryValueExW(key, L"Installed", NULL, &type, (LPBYTE)&installed, &size);
    RegCloseKey(key);
    return rc == ERROR_SUCCESS && type == REG_DWORD && installed == 1;
}

static BOOL get_own_dir(wchar_t *out, size_t cch) {
    DWORD n = GetModuleFileNameW(NULL, out, (DWORD)cch);
    if (n == 0 || n >= cch) return FALSE;
    wchar_t *slash = wcsrchr(out, L'\\');
    if (!slash) return FALSE;
    *slash = L'\0';
    return TRUE;
}

static DWORD run_wait(const wchar_t *file, const wchar_t *params, const wchar_t *cwd, int show) {
    SHELLEXECUTEINFOW sei;
    ZeroMemory(&sei, sizeof(sei));
    sei.cbSize = sizeof(sei);
    sei.fMask = SEE_MASK_NOCLOSEPROCESS;
    sei.lpVerb = L"open";
    sei.lpFile = file;
    sei.lpParameters = params;
    sei.lpDirectory = cwd;
    sei.nShow = show;
    if (!ShellExecuteExW(&sei) || !sei.hProcess) return (DWORD)-1;
    WaitForSingleObject(sei.hProcess, INFINITE);
    DWORD code = (DWORD)-1;
    GetExitCodeProcess(sei.hProcess, &code);
    CloseHandle(sei.hProcess);
    return code;
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR cmd, int show) {
    (void)hInst; (void)hPrev; (void)cmd; (void)show;
    wchar_t dir[MAX_PATH];
    wchar_t script[MAX_PATH];
    wchar_t app[MAX_PATH];
    wchar_t params[2 * MAX_PATH];

    if (!get_own_dir(dir, MAX_PATH)) {
        MessageBoxW(NULL, L"프로그램 경로를 확인할 수 없습니다.", L"CMB DXF Viewer", MB_ICONERROR);
        return 10;
    }

    StringCchPrintfW(script, MAX_PATH, L"%s\\ensure_vcredist.ps1", dir);
    StringCchPrintfW(app, MAX_PATH, L"%s\\CMB_DXF_Viewer_App.exe", dir);

    if (GetFileAttributesW(app) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"CMB_DXF_Viewer_App.exe 파일이 없습니다. 배포 ZIP의 모든 파일을 같은 폴더에 압축 해제해 주세요.", L"CMB DXF Viewer", MB_ICONERROR);
        return 11;
    }

    if (!vc_runtime_installed()) {
        if (GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
            MessageBoxW(NULL, L"Visual C++ Runtime 설치 스크립트가 없습니다. 배포 ZIP의 모든 파일을 같은 폴더에 압축 해제해 주세요.", L"CMB DXF Viewer", MB_ICONERROR);
            return 12;
        }

        int answer = MessageBoxW(NULL,
            L"Microsoft Visual C++ x64 Runtime이 필요합니다.\n\n확인을 누르면 Microsoft 공식 설치 프로그램을 실행합니다. 설치가 끝나면 CMB DXF Viewer가 자동으로 계속 실행됩니다.",
            L"필수 구성요소 설치", MB_OKCANCEL | MB_ICONINFORMATION);
        if (answer != IDOK) return 13;

        StringCchPrintfW(params, 2 * MAX_PATH,
            L"-NoProfile -ExecutionPolicy Bypass -File \"%s\"", script);
        DWORD rc = run_wait(L"powershell.exe", params, dir, SW_HIDE);
        if (rc != 0 || !vc_runtime_installed()) {
            MessageBoxW(NULL,
                L"Visual C++ Runtime 설치가 완료되지 않았습니다. 설치를 완료한 뒤 다시 실행해 주세요.",
                L"CMB DXF Viewer", MB_ICONERROR);
            return 14;
        }
    }

    HINSTANCE launched = ShellExecuteW(NULL, L"open", app, NULL, dir, SW_SHOWNORMAL);
    if ((INT_PTR)launched <= 32) {
        MessageBoxW(NULL, L"CMB DXF Viewer 실행에 실패했습니다.", L"CMB DXF Viewer", MB_ICONERROR);
        return 15;
    }
    return 0;
}
