<#
    CowAgent-Rev - enable the remote debug channel (OpenSSH Server).

    Run via enable-ssh.cmd, which elevates first. Idempotent: each step checks
    its own state, so re-running is harmless and reports what is already done.

    Scope: inbound TCP 22 on the PRIVATE firewall profile only (your LAN).
    Nothing here touches the router, so this is not reachable from the internet
    unless you forward port 22 yourself. Don't.

    Optional first argument: an SSH public key to authorize, e.g.
        enable-ssh.cmd "ssh-ed25519 AAAAC3... you@mac"
    Omit it and the script prompts, or skips key setup if you press Enter.
#>

param([string]$PublicKey = "")

$ErrorActionPreference = "Stop"

function Step($n, $text) { Write-Host "`n[$n] $text" -ForegroundColor Cyan }
function Ok($text)       { Write-Host "    OK  $text" -ForegroundColor Green }
function Info($text)     { Write-Host "    --  $text" -ForegroundColor DarkGray }
function Warn($text)     { Write-Host "    !!  $text" -ForegroundColor Yellow }
function Die($text)      { Write-Host "`n[X] $text" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  CowAgent-Rev  -  remote debug channel" -ForegroundColor White
Write-Host "  ------------------------------------" -ForegroundColor DarkGray

# --------------------------------------------------------------- 1. install
Step 1 "OpenSSH Server"
$cap = Get-WindowsCapability -Online -Name "OpenSSH.Server*" |
       Select-Object -First 1
if ($null -eq $cap) {
    Die "This Windows build does not offer the OpenSSH Server capability.
    Install it from Settings > System > Optional features, or use Win10 1809+."
}
if ($cap.State -ne "Installed") {
    Info "installing $($cap.Name) (this can take a minute)..."
    Add-WindowsCapability -Online -Name $cap.Name | Out-Null
    Ok "installed"
} else {
    Ok "already installed"
}

# --------------------------------------------------------------- 2. service
Step 2 "sshd service"
Set-Service -Name sshd -StartupType Automatic
if ((Get-Service sshd).Status -ne "Running") {
    Start-Service sshd
    Ok "started, and set to start automatically"
} else {
    Ok "already running, set to start automatically"
}

# -------------------------------------------------------------- 3. firewall
Step 3 "Firewall rule (inbound TCP 22, Private profile only)"
$ruleName = "CowAgent SSH"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound `
        -LocalPort 22 -Protocol TCP -Action Allow -Profile Private | Out-Null
    Ok "rule created"
} else {
    Ok "rule already present"
}
# A LAN adapter still classified Public would leave the rule inert.
$publicNets = Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq "Public" }
if ($publicNets) {
    Warn "These adapters are on the PUBLIC profile, where the rule does not apply:"
    $publicNets | ForEach-Object { Warn "      $($_.InterfaceAlias) - $($_.Name)" }
    Warn "If your LAN is one of them, set it to Private:"
    Warn '      Set-NetConnectionProfile -InterfaceAlias "<name>" -NetworkCategory Private'
}

# ------------------------------------------------------------------- 4. key
Step 4 "Authorized key"
if (-not $PublicKey) {
    Write-Host "    Paste the client's SSH PUBLIC key (or press Enter to skip):" -ForegroundColor DarkGray
    $PublicKey = Read-Host "    key"
}
$PublicKey = $PublicKey.Trim()

if (-not $PublicKey) {
    Info "skipped - you will be asked for a password when connecting"
} elseif ($PublicKey -notmatch '^(ssh-(rsa|ed25519|dss)|ecdsa-sha2-\S+)\s+\S+') {
    Die "That does not look like a public key. It must start with ssh-ed25519,
    ssh-rsa or ecdsa-... . Never paste a PRIVATE key (the file WITHOUT .pub)."
} else {
    # Windows quirk: for accounts in the Administrators group, sshd ignores
    # ~\.ssh\authorized_keys entirely and reads only this shared file. Getting
    # this wrong is the usual reason key auth "silently" falls back to a
    # password prompt.
    $isAdmin = ([Security.Principal.WindowsPrincipal] `
                [Security.Principal.WindowsIdentity]::GetCurrent()
               ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if ($isAdmin) {
        $keyFile = "$env:ProgramData\ssh\administrators_authorized_keys"
        Info "this account is an Administrator -> using administrators_authorized_keys"
    } else {
        $keyFile = "$env:USERPROFILE\.ssh\authorized_keys"
        Info "standard account -> using ~\.ssh\authorized_keys"
    }

    $dir = Split-Path $keyFile
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    $existing = if (Test-Path $keyFile) { Get-Content $keyFile } else { @() }
    if ($existing -contains $PublicKey) {
        Ok "key already authorized"
    } else {
        Add-Content -Path $keyFile -Value $PublicKey
        Ok "key added to $keyFile"
    }

    if ($isAdmin) {
        # sshd refuses this file if anyone but Administrators/SYSTEM can write it.
        icacls $keyFile /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null
        Ok "permissions locked to Administrators + SYSTEM"
    }
    Restart-Service sshd
    Ok "sshd restarted so the key takes effect"
}

# ---------------------------------------------------------------- 5. report
Step 5 "Connection details"
$ips = Get-NetIPAddress -AddressFamily IPv4 |
       Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } |
       Select-Object -ExpandProperty IPAddress
if (-not $ips) { Die "No usable IPv4 address found - is this machine on a network?" }

$user = $env:USERNAME
Write-Host ""
Write-Host "  Host  : $($ips -join '  ')" -ForegroundColor White
Write-Host "  User  : $user" -ForegroundColor White
Write-Host "  Port  : 22" -ForegroundColor White
Write-Host ""
Write-Host "  From the Mac, add this to ~/.ssh/config:" -ForegroundColor DarkGray
Write-Host ""
Write-Host "      Host win" -ForegroundColor Gray
Write-Host "          HostName $($ips[0])" -ForegroundColor Gray
Write-Host "          User $user" -ForegroundColor Gray
Write-Host ""
Write-Host "  then:  ssh win" -ForegroundColor DarkGray

$listening = (Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue)
if ($listening) { Ok "sshd is listening on port 22" }
else { Warn "nothing is listening on port 22 - check: Get-Service sshd" }
