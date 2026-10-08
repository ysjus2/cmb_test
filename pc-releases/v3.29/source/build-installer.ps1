param(
    [Parameter(Mandatory=$true)][string]$CompilerPath,
    [Parameter(Mandatory=$true)][string]$AppExe,
    [Parameter(Mandatory=$true)][string]$LicenseFile,
    [Parameter(Mandatory=$true)][string]$OutputFile
)
$ErrorActionPreference='Stop'
foreach($inputFile in @($CompilerPath,$AppExe,$LicenseFile)){if(-not(Test-Path -LiteralPath $inputFile -PathType Leaf)){throw 'Required build file missing'}}
$arguments=@('/WX',('/DAPP_EXE='+[IO.Path]::GetFullPath($AppExe)),('/DLICENSE_FILE='+[IO.Path]::GetFullPath($LicenseFile)),('/DOUTPUT_FILE='+[IO.Path]::GetFullPath($OutputFile)),(Join-Path $PSScriptRoot 'CMB_DXF_Viewer_Setup.nsi'))
& $CompilerPath @arguments
if($LASTEXITCODE -ne 0){throw 'Installer compilation failed'}
Get-FileHash -LiteralPath $OutputFile -Algorithm SHA256
