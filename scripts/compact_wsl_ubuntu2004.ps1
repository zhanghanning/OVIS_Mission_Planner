$ErrorActionPreference = "Stop"
$VhdPath = "F:\wsl\Ubuntu2004\ext4.vhdx"

function Test-Administrator {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Administrator)) {
    throw "Please run this script in an Administrator PowerShell window."
}

if (-not (Test-Path $VhdPath)) {
    throw "VHDX not found: $VhdPath"
}

Write-Host "Shutting down WSL..."
wsl --shutdown

Write-Host "Compacting $VhdPath ..."
$temp = Join-Path $env:TEMP "compact_wsl_ubuntu2004.txt"
@"
select vdisk file="$VhdPath"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"@ | Set-Content -Path $temp -Encoding ascii

diskpart /s $temp
Remove-Item $temp -Force -ErrorAction SilentlyContinue

Write-Host "Done."
