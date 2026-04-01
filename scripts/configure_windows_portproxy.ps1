$ErrorActionPreference = "Stop"
$Port = 8081
$RuleName = "MissionPlanner-8081"
$LogPath = "C:\Users\Public\mission_planner_portproxy.log"

function Get-WslIpv4 {
    $raw = (wsl.exe sh -lc "hostname -I" 2>$null)
    if (-not $raw) {
        throw "Unable to query WSL IPv4. Start WSL first, then rerun this script."
    }

    $ips = $raw -split "\s+" | Where-Object {
        $_ -match "^\d+\.\d+\.\d+\.\d+$" -and $_ -ne "127.0.0.1"
    }

    if (-not $ips -or $ips.Count -eq 0) {
        throw "No non-loopback WSL IPv4 detected."
    }

    return $ips[0]
}

function Get-HostIpv4s {
    Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object {
            $_.IPAddress -notmatch "^127\." -and
            $_.IPAddress -notmatch "^169\.254\." -and
            $_.InterfaceAlias -notmatch "vEthernet|WSL|Hyper-V|Loopback"
        } |
        Select-Object -ExpandProperty IPAddress -Unique
}

Start-Transcript -Path $LogPath -Append | Out-Null

$WslIp = Get-WslIpv4
$HostIps = @(Get-HostIpv4s)

Write-Host "Detected WSL IPv4: $WslIp"
if ($HostIps.Count -gt 0) {
    Write-Host ("Windows LAN IPv4s: " + ($HostIps -join ", "))
}
Write-Host "Configuring Windows portproxy 0.0.0.0:$Port -> ${WslIp}:$Port"

netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=0.0.0.0 | Out-Null
netsh interface portproxy add v4tov4 listenport=$Port listenaddress=0.0.0.0 connectport=$Port connectaddress=$WslIp | Out-Null

netsh advfirewall firewall delete rule name=$RuleName | Out-Null
netsh advfirewall firewall add rule name=$RuleName dir=in action=allow protocol=TCP localport=$Port | Out-Null

Write-Host ""
Write-Host "Current portproxy rules:"
netsh interface portproxy show all
Write-Host ""
Write-Host "Firewall rule ensured: $RuleName"
if ($HostIps.Count -gt 0) {
    Write-Host ""
    Write-Host "LAN test URLs:"
    foreach ($ip in $HostIps) {
        Write-Host ("  http://{0}:{1}/health" -f $ip, $Port)
    }
}

Stop-Transcript | Out-Null
