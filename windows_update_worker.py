"""Fixed, private PowerShell transaction run by the elevated Windows broker.

No command is read from a download. The working directory was created by the
broker under Program Files. No running process needs Eggie's runtime DLLs by
the time Inno runs.
"""

MONITOR = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$gate = [Threading.EventWaitHandle]::OpenExisting($gateName)
$show = [Threading.EventWaitHandle]::OpenExisting(($gateName+'-show'))
$shown = [Threading.EventWaitHandle]::OpenExisting(('Local\Eggie-Update-'+$token+'-shown'))
$abort = [Threading.EventWaitHandle]::OpenExisting(('Local\Eggie-Update-'+$token+'-abort'))
$finish = [Threading.EventWaitHandle]::OpenExisting(('Local\Eggie-Update-'+$token+'-finish'))
$form = [Windows.Forms.Form]::new()
$form.Text = 'Eggie 软件更新'
$form.ClientSize = [Drawing.Size]::new(452,218)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.AutoScaleMode = 'Dpi'
$form.BackColor = [Drawing.ColorTranslator]::FromHtml('#F6F5F1')
$form.Font = [Drawing.Font]::new('Microsoft YaHei UI',10)
$heading = [Windows.Forms.Label]::new()
$heading.Text = '正在更新 Eggie'
$heading.Font = [Drawing.Font]::new($form.Font.FontFamily,17,[Drawing.FontStyle]::Bold)
$heading.SetBounds(26,24,402,36)
$phase = [Windows.Forms.Label]::new()
$phase.Text = '准备更新'
$phase.SetBounds(26,78,402,26)
$bar = [Windows.Forms.ProgressBar]::new()
$bar.Style = 'Marquee'
$bar.MarqueeAnimationSpeed = 30
$bar.SetBounds(27,116,398,5)
$detail = [Windows.Forms.Label]::new()
$detail.Text = '完成后会自动打开，请勿重复启动。'
$detail.ForeColor = [Drawing.ColorTranslator]::FromHtml('#58635F')
$detail.SetBounds(26,141,402,52)
$close = [Windows.Forms.Button]::new()
$close.Text = '关闭'
$close.SetBounds(346,222,80,32)
$close.Visible = $false
$close.Add_Click({$form.Close()})
$script:allowClose = $false
$form.Add_FormClosing({param($sender,$e) if (!$script:allowClose) {$e.Cancel=$true}})
$form.Controls.AddRange(@($heading,$phase,$bar,$detail,$close))
$form.Show()
$form.Activate()
[Windows.Forms.Application]::DoEvents()
if (!$form.Visible -or !$form.IsHandleCreated) {throw 'Progress window was not shown'}
$null = $shown.Set()
$shown.Dispose()
$stageFile = [IO.Path]::Combine($job,'stage')
$script:lastStage = ''
function Pump-Progress([int]$milliseconds=0) {
    $until = [DateTime]::UtcNow.AddMilliseconds($milliseconds)
    do {
        if ($abort.WaitOne(0)) {Complete-Guard;$script:allowClose=$true;$form.Close();exit}
        if ($null -ne $show -and $show.WaitOne(0)) {$null=$show.Reset();$form.WindowState='Normal';$form.Activate()}
        if ([IO.File]::Exists($stageFile)) {
            try {
                $s = [IO.File]::ReadAllText($stageFile)
                if ($s -and $s -ne $script:lastStage) {
                    $script:lastStage = $s
                    $phase.Text = switch ($s) {
                        'install' {'安装更新'}
                        'verify-target' {'安装更新 · 核对文件'}
                        'start-new-version' {'正在启动 · 检查新版本'}
                        'restore' {'正在恢复原版本'}
                        'restored' {'正在打开原版本'}
                        default {'准备更新'}
                    }
                }
            } catch { }
        }
        [Windows.Forms.Application]::DoEvents()
        if ([DateTime]::UtcNow -lt $until) {Start-Sleep -Milliseconds 50}
    } while ([DateTime]::UtcNow -lt $until)
}
function Wait-Responsive($process,[int]$milliseconds) {
    $until = [DateTime]::UtcNow.AddMilliseconds($milliseconds)
    while (!$process.HasExited -and [DateTime]::UtcNow -lt $until) {
        Pump-Progress 100
        $process.Refresh()
    }
    return $process.HasExited
}
function Open-Eggie {
    $script:permit = [Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset,
        ('Local\Eggie-Update-'+$token+'-launch'))
    return Start-Process -FilePath $exe -ArgumentList ('--eggie-update-launch='+$token) -WorkingDirectory $app -PassThru
}
function Complete-Guard {
    # Detach before leaving the result visible. An old result must never signal
    # or consume notifications from a subsequent update of this installation.
    if ($null -ne $script:gate) {
        $script:show.Dispose();$script:show=$null
        if ($finish.WaitOne(0)) {$null=$script:gate.Set()}
        $script:gate.Dispose();$script:gate=$null
    }
}
$exe = [IO.Path]::Combine($app,'Eggie DocuFlow.exe')
$probe = [IO.Path]::Combine($job,'probing')
$status = [IO.Path]::Combine($job,'result')
$checked = $false
$running = $null
for ($i=0; $i -lt 9000; $i++) {
    if ([IO.File]::Exists($status)) {break}
    if (!$checked -and [IO.File]::Exists($probe)) {
        $checked = $true
        $success = $false
        try {
            $smoke = Start-Process -FilePath $exe -ArgumentList '--check-install' -WorkingDirectory $app -PassThru
            if (!(Wait-Responsive $smoke 45000)) { $smoke.Kill(); $smoke.WaitForExit(5000); throw 'Smoke check timed out' }
            if ($smoke.ExitCode -ne 0) { throw 'Smoke check failed' }
            $running = Open-Eggie
            for ($attempt=0; $attempt -lt 90; $attempt++) {
                Pump-Progress 500
                $running.Refresh()
                if ($running.HasExited) {throw 'New application exited'}
                if ($running.MainWindowHandle -ne 0 -and $running.Responding) {
                    Pump-Progress 750
                    $running.Refresh()
                    if (!$running.HasExited -and $running.MainWindowHandle -ne 0 -and $running.Responding) {
                        $success = $true; break
                    }
                }
            }
        } catch { $success = $false }
        if ($null -ne $permit) {$permit.Dispose();$permit=$null}
        if (!$success -and $running -and !$running.HasExited) {
            $null = $running.CloseMainWindow()
            if (!(Wait-Responsive $running 5000)) {$running.Kill();$running.WaitForExit(5000)}
        }
        $suffix = if ($success) {'-ready'} else {'-bad'}
        $signal = [Threading.EventWaitHandle]::OpenExisting(('Local\Eggie-Update-'+$token+$suffix),
            [Security.AccessControl.EventWaitHandleRights]::Modify)
        $null = $signal.Set(); $signal.Dispose()
    }
    Pump-Progress 300
}
$r = if ([IO.File]::Exists($status)) {[IO.File]::ReadAllText($status)} else {'timeout'}
$message = switch ($r) {
    'ok' {'更新已完成，可以继续使用。'}
    'restored' {'更新未完成，已恢复原版本。'}
    'recovered' {'已恢复原版本，请通过平时的快捷方式重新打开 Eggie。'}
    'not-started' {'更新准备未完成，原版本未改动。'}
    'unchanged' {'本次更新未开始，请先关闭仍在运行的 Eggie 窗口后重试。'}
    default {'更新未完成。恢复备份位于 '+$job}
}
if ($r -in @('restored','not-started')) {
    try {
        $phase.Text='正在打开原版本'
        $old=Open-Eggie
        for ($i=0;$i -lt 90;$i++) {
            Pump-Progress 500
            $old.Refresh()
            if ($old.HasExited -or ($old.MainWindowHandle -ne 0 -and $old.Responding)) {break}
        }
        if (!$old.HasExited -and $old.MainWindowHandle -ne 0 -and $old.Responding) {$message+='可以继续使用。'}
        else {$message+='请重新打开 Eggie。'}
    } catch {$message+='请重新打开 Eggie。'}
    finally {if ($null -ne $permit) {$permit.Dispose();$permit=$null}}
}
# Keep the guard active if recovery failed or the worker is still unconfirmed.
if ($r -in @('ok','restored','recovered','not-started','unchanged')) {Complete-Guard}
$script:allowClose=$true
$bar.Visible=$false
$heading.Text=if ($r -eq 'ok') {'Eggie 更新完成'} else {'Eggie 更新未完成'}
$phase.Text=if ($r -eq 'ok') {'新版本已打开'} else {'请查看下方说明'}
$detail.Text=$message
if ($r -eq 'ok') {Pump-Progress 1500;$form.Close()}
else {
    $form.ClientSize=[Drawing.Size]::new(452,274)
    $detail.SetBounds(26,120,402,90)
    $close.Visible=$true
    $form.Activate()
    while (!$form.IsDisposed) {
        # The independent administrator recovery helper may finish after this
        # monitor has already shown a timeout or recovery-failure result.
        if ($null -ne $gate -and [IO.File]::Exists($status)) {
            try {
                if ([IO.File]::ReadAllText($status) -eq 'recovered') {
                    Complete-Guard
                    $phase.Text='已恢复原版本'
                    $detail.Text='已恢复原版本，请通过平时的快捷方式重新打开 Eggie。'
                }
            } catch { }
        }
        Pump-Progress 100
    }
}
if ($null -ne $gate) {$gate.Dispose();$show.Dispose()}
$abort.Dispose()
$finish.Dispose()
"""


TRANSACTION = r"""
$ErrorActionPreference = 'Stop'
$job = (Get-Location).Path
$config = [IO.File]::ReadAllText([IO.Path]::Combine($job,'rollback.json')) | ConvertFrom-Json
$app = [string]$config.install_dir
$backup = [IO.Path]::Combine($job,'backup')
$setup = [IO.Path]::Combine($job,'update.exe')
$system = [Environment]::SystemDirectory
$reg = [IO.Path]::Combine($system,'reg.exe')
$savedRegistry = [IO.Path]::Combine($job,'uninstall.reg')
$result = 'unchanged'
$mutated = $false
$lock = $null
$stage = 'commit'
$installerExitCode = $null

function Set-Stage([string]$name) {
    $script:stage = $name
    try { [IO.File]::WriteAllText([IO.Path]::Combine($job,'stage'),$name) } catch { }
}

function Save-Failure($errorRecord, [string]$name) {
    # Fixed diagnostic fields only: never serialize the signed input or event token.
    try {
        $message = [string]$errorRecord.Exception.Message
        if ($message.Length -gt 1200) {$message = $message.Substring(0,1200)}
        $record = [ordered]@{stage=$stage; error_type=$errorRecord.Exception.GetType().FullName;
            hresult=$errorRecord.Exception.HResult; message=$message; installer_exit=$installerExitCode}
        [IO.File]::WriteAllText([IO.Path]::Combine($job,$name),($record | ConvertTo-Json -Compress))
    } catch { }
}

function Check-Stamp([string]$dir, [string]$version, [string]$build, [bool]$verifyFiles) {
    $stampFile = [IO.Path]::Combine($dir,'eggie-runtime.json')
    $stamp = [IO.File]::ReadAllText($stampFile) | ConvertFrom-Json
    if ($stamp.schema -ne 1 -or $stamp.version -cne $version -or $stamp.build -cne $build) {
        throw 'Installed version does not match expected record'
    }
    if ($verifyFiles) {
        $base = [IO.Path]::GetFullPath($dir).TrimEnd('\') + '\'
        foreach ($entry in $stamp.files.PSObject.Properties) {
            $path = [IO.Path]::GetFullPath([IO.Path]::Combine($dir,$entry.Name))
            if (!$path.StartsWith($base,[StringComparison]::OrdinalIgnoreCase) -or
                $entry.Name.Contains(':') -or $entry.Value -notmatch '^[a-f0-9]{64}$' -or
                (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $entry.Value) {
                throw 'Installed runtime verification failed'
            }
        }
    }
}

function Clear-Tree([string]$path) {
    if ([IO.Directory]::Exists($path)) {
        # Do not follow links in rollback, cleanup, or a partially installed tree.
        foreach ($entry in [IO.Directory]::GetFileSystemEntries($path)) {
            $flags = [IO.File]::GetAttributes($entry)
            if (($flags -band [IO.FileAttributes]::Directory) -ne 0) {
                if (($flags -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                    [IO.Directory]::Delete($entry)
                } else { Clear-Tree $entry }
            } else {
                if (($flags -band [IO.FileAttributes]::ReadOnly) -ne 0 -and
                    ($flags -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
                    [IO.File]::SetAttributes($entry,($flags -band (-bnot [IO.FileAttributes]::ReadOnly)))
                }
                [IO.File]::Delete($entry)
            }
        }
        [IO.Directory]::Delete($path)
    }
}

function Save-BackupRecord {
    # Full repair deliberately accepts pre-existing drift or missing files.
    # Record what was actually backed up, independently of the release stamp.
    $prefix = [IO.Path]::GetFullPath($backup).TrimEnd('\') + '\'
    $files = [ordered]@{}
    foreach ($file in Get-ChildItem -LiteralPath $backup -Recurse -Force -File) {
        $name = $file.FullName.Substring($prefix.Length).Replace('\','/')
        $files[$name] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $record = [ordered]@{schema=1; version=$config.version; build=$config.build; files=$files}
    [IO.File]::WriteAllText([IO.Path]::Combine($job,'backup-tree.json'),($record | ConvertTo-Json -Depth 4 -Compress))
}

try {
    Set-Stage 'commit'
    $gate = [Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset)
    $gate.SafeWaitHandle = [Microsoft.Win32.SafeHandles.SafeWaitHandle]::new([IntPtr][long]$config.commit_handle,$true)
    try {
        if (!$gate.WaitOne(60000)) { throw 'Update was never committed by the caller' }
    } finally { $gate.Dispose() }
    Set-Stage 'wait-for-exit'
    $lockPath = [IO.Path]::Combine([IO.Directory]::GetParent($app).FullName,'.eggie-docuflow-update.lock')
    $lock = [IO.File]::Open($lockPath,'OpenOrCreate','ReadWrite','None')
    foreach ($procId in @($config.broker_pid,$config.gui_pid)) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($null -ne $proc) {
            if (![String]::Equals($proc.Path,[IO.Path]::Combine($app,'Eggie DocuFlow.exe'),
                    [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected running application' }
            if (!$proc.WaitForExit(120000)) { throw 'Application is still running' }
        }
    }
    # Avoid installing over another session or instance with locked runtime files.
    foreach ($proc in @(Get-Process -Name 'Eggie DocuFlow' -ErrorAction SilentlyContinue)) {
        if (!$proc.Path -or [String]::Equals($proc.Path,[IO.Path]::Combine($app,'Eggie DocuFlow.exe'),
            [StringComparison]::OrdinalIgnoreCase)) { throw 'Another process may be using this installation' }
    }
    $result = 'not-started'
    Set-Stage 'verify-base'
    Check-Stamp $app $config.version $config.build ($config.kind -eq 'delta')
    if ((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash -ine $config.sha256) {throw 'Package changed'}
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($app))
    $bytes = (Get-ChildItem -LiteralPath $app -Recurse -Force -File | Measure-Object -Property Length -Sum).Sum
    if ($drive.AvailableFreeSpace -lt ([long]$bytes*2 + (Get-Item -LiteralPath $setup).Length + 33554432)) {
        throw 'Insufficient disk space'
    }
    Set-Stage 'backup-registry'
    & $reg export $config.registry_key $savedRegistry /y /reg:64 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot back up uninstall record' }
    Set-Stage 'backup-files'
    $null = [IO.Directory]::CreateDirectory($backup)
    & ([IO.Path]::Combine($system,'robocopy.exe')) $app $backup /E /XJ /COPY:DATS /DCOPY:DA /R:0 /W:0 /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) { throw 'Cannot back up installation' }
    Check-Stamp $backup $config.version $config.build ($config.kind -eq 'delta')
    Save-BackupRecord
    if ((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash -ine $config.sha256) {throw 'Package changed'}
    [IO.File]::WriteAllText([IO.Path]::Combine($job,'installing'),'1')
    $mutated = $true
    Set-Stage 'install'
    $argsLine = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /RESTARTEXITCODE=19 /NORESTARTAPPLICATIONS /NOCLOSEAPPLICATIONS /SP- /DIR="' + $app + '" /EGGIEROLLBACK="' + $job + '" /LOG="' + [IO.Path]::Combine($job,'installer.log') + '"'
    $proc = Start-Process -FilePath $setup -ArgumentList $argsLine -PassThru -Wait -WorkingDirectory $job
    $installerExitCode = $proc.ExitCode
    if ($proc.ExitCode -ne 0) {throw 'Installer did not complete'}
    Set-Stage 'verify-target'
    Check-Stamp $app $config.target_version $config.target_build $true
    # Remove only unchanged files that belonged to the old package and were retired
    # from the target manifest. Unknown personal files never enter this list.
    $oldStamp = [IO.File]::ReadAllText([IO.Path]::Combine($backup,'eggie-runtime.json')) | ConvertFrom-Json
    $newStamp = [IO.File]::ReadAllText([IO.Path]::Combine($app,'eggie-runtime.json')) | ConvertFrom-Json
    $keep = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $newStamp.files.PSObject.Properties) { $null=$keep.Add($entry.Name) }
    foreach ($entry in $oldStamp.files.PSObject.Properties) {
        if ($keep.Contains($entry.Name)) {continue}
        $path = [IO.Path]::Combine($app,$entry.Name)
        if ([IO.File]::Exists($path)) {
            if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $entry.Value) {
                throw 'A retired managed file was edited locally'
            }
            [IO.File]::Delete($path)
        }
    }
    $signals = @(foreach ($h in @($config.ready_handle,$config.bad_handle)) {
        $e = [Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset)
        $e.SafeWaitHandle = [Microsoft.Win32.SafeHandles.SafeWaitHandle]::new([IntPtr][long]$h,$true)
        $e
    })
    try {
        Set-Stage 'start-new-version'
        [IO.File]::WriteAllText([IO.Path]::Combine($job,'probing'),'1')
        if ([Threading.WaitHandle]::WaitAny([Threading.WaitHandle[]]$signals,160000) -ne 0) {
            throw 'New application did not start for the original user'
        }
    } finally { foreach ($s in $signals) {$s.Dispose()} }
    $result = 'ok'
    Set-Stage 'complete'
} catch {
    Save-Failure $_ 'failure.json'
    if ($mutated) {
        $result = 'failed'
        try {
            Set-Stage 'restore'
            $damaged = [IO.Path]::Combine($job,'incomplete')
            if ([IO.Directory]::Exists($app)) { [IO.Directory]::Move($app,$damaged) }
            [IO.Directory]::Move($backup,$app)
            & $reg import $savedRegistry /reg:64 | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Cannot restore uninstall record' }
            $result = 'restored'
            Set-Stage 'restored'
        } catch { Save-Failure $_ 'restore-failure.json'; $result = 'failed' }
    }
} finally {
    if ($null -ne $lock) { $lock.Dispose() }
    if ($result -ne 'failed') {
        try {
            Clear-Tree $backup
            Clear-Tree ([IO.Path]::Combine($job,'incomplete'))
            Clear-Tree ([IO.Path]::Combine($job,'tmp'))
            [IO.File]::Delete($setup)
            [IO.File]::Delete($savedRegistry)
            [IO.File]::Delete([IO.Path]::Combine($job,'EggieUpdateRestore.exe'))
            [IO.File]::Delete([IO.Path]::Combine($job,'installing'))
        } catch { }
    }
    # Readers see a complete result. A failed rollback leaves the backup intact.
    $tmp = [IO.Path]::Combine($job,'result.tmp')
    [IO.File]::WriteAllText($tmp,$result)
    [IO.File]::Move($tmp,[IO.Path]::Combine($job,'result'))
}
"""
