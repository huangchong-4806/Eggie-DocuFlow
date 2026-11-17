param([string]$Installer, [int]$TimeoutSeconds=600, [switch]$TestWait)
$ErrorActionPreference = 'Stop'
function Wait-Success([System.Diagnostics.Process]$Process, [int]$Seconds) {
    if (-not $Process.WaitForExit($Seconds * 1000)) {
        $Process.Kill()
        throw "Process timed out after $Seconds seconds."
    }
    if ($Process.ExitCode -ne 0) { throw "Process failed with exit code $($Process.ExitCode)." }
}
if ($TestWait) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    Wait-Success (Start-Process powershell -PassThru -ArgumentList '-NoProfile -Command "Start-Sleep -Seconds 1; exit 0"') 10
    if ($clock.Elapsed.TotalSeconds -lt 1) { throw "Process returned early." }
    $failed = $false
    try { Wait-Success (Start-Process powershell -PassThru -ArgumentList '-NoProfile -Command "exit 7"') 10 }
    catch { if ($_.Exception.Message -notmatch 'exit code 7') { throw }; $failed = $true }
    if (-not $failed) { throw "Failure exit code was accepted." }
    $slow = Start-Process powershell -PassThru -ArgumentList '-NoProfile -Command "Start-Sleep -Seconds 15"'
    $timedOut = $false
    try { Wait-Success $slow 1 }
    catch { if ($_.Exception.Message -notmatch 'timed out') { throw }; $timedOut = $true }
    if (-not $timedOut -or -not $slow.WaitForExit(5000)) { throw "Timeout did not stop the process." }
    return
}
if (-not $Installer) { throw 'Select an installer.' }
$root = Join-Path $env:TEMP ("EggieCandidate-" + [guid]::NewGuid())
$log = Join-Path $env:TEMP ("EggieInstaller-" + [guid]::NewGuid() + ".log")
# Run this smoke check in a disposable CI runner, not over a user's registered install.
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Run the installation smoke check on a disposable Actions runner.' }
$proc = Start-Process -FilePath $Installer -PassThru -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/DIR="' + $root + '"'),('/LOG="' + $log + '"'))
Wait-Success $proc $TimeoutSeconds
$app = Join-Path $root 'Eggie DocuFlow.exe'
if (-not (Test-Path -LiteralPath $app -PathType Leaf)) { throw 'Installed executable missing.' }
Wait-Success (Start-Process -FilePath $app -PassThru -ArgumentList '--check-install') 120
