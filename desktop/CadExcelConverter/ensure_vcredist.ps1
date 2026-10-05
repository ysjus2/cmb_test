param(
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$runtimeKey = 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'

function Test-VCRuntime {
    try {
        $item = Get-ItemProperty -Path $runtimeKey -ErrorAction Stop
        return ($item.Installed -eq 1)
    } catch {
        return $false
    }
}

if (Test-VCRuntime) {
    Write-Host 'Microsoft Visual C++ x64 Runtime is installed.'
    exit 0
}

if ($CheckOnly) {
    Write-Host 'Microsoft Visual C++ x64 Runtime is not installed.'
    exit 2
}

$downloadUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
$tempFile = Join-Path $env:TEMP 'vc_redist.x64.exe'

Write-Host 'Microsoft Visual C++ x64 Runtime is required.'
Write-Host 'Downloading the official Microsoft installer...'
Invoke-WebRequest -Uri $downloadUrl -OutFile $tempFile -UseBasicParsing

$signature = Get-AuthenticodeSignature -FilePath $tempFile
if ($signature.Status -ne 'Valid') {
    Remove-Item $tempFile -Force -ErrorAction SilentlyContinue
    throw "VC++ Runtime installer signature is not valid: $($signature.Status)"
}

$subject = [string]$signature.SignerCertificate.Subject
if ($subject -notmatch 'Microsoft') {
    Remove-Item $tempFile -Force -ErrorAction SilentlyContinue
    throw "VC++ Runtime installer is not signed by Microsoft: $subject"
}

Write-Host "Verified Microsoft signature: $subject"
Write-Host 'Launching Microsoft Visual C++ x64 Runtime installer...'
# Run the official installer interactively. The bootstrap waits for this process.
$proc = Start-Process -FilePath $tempFile -Wait -PassThru
$exitCode = $proc.ExitCode
Remove-Item $tempFile -Force -ErrorAction SilentlyContinue

if ($exitCode -notin @(0, 1638, 3010)) {
    throw "VC++ Runtime installer did not complete successfully. Exit code: $exitCode"
}

if (-not (Test-VCRuntime)) {
    throw 'VC++ Runtime installation completed but the x64 runtime was not detected.'
}

if ($exitCode -eq 3010) {
    Write-Host 'VC++ Runtime installed successfully. Windows reports that a restart is recommended.'
} else {
    Write-Host 'VC++ Runtime installed successfully.'
}

exit 0
