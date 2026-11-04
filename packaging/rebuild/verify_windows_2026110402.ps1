param([Parameter(Mandatory)][string]$OldInstaller)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../..").Path
Set-Location $root
if ((Get-FileHash $OldInstaller).Hash.ToLower() -ne 'c453af5cb6e7e3de6363afccb33b0a0f323cbd31e6ae4cb23dd37bf3923a4df9') { throw 'Unexpected old installer' }
$stage = Join-Path ([IO.Path]::GetTempPath()) ("Eggie-" + [guid]::NewGuid())
New-Item -ItemType Directory $stage | Out-Null
function Install-App([string]$setup,[string]$folder) {
  $p = Start-Process $setup -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR=`"$folder`"" -Wait -PassThru
  if ($p.ExitCode -ne 0 -or !(Test-Path "$folder/Eggie DocuFlow.exe")) {throw "Installation failed ($($p.ExitCode))"}
}
function Check-App([string]$folder) {
  $exe = Join-Path $folder 'Eggie DocuFlow.exe'
  $p = Start-Process $exe -ArgumentList '--check-install' -PassThru
  if (!$p.WaitForExit(45000)) { $p.Kill(); throw 'Frozen parser test timed out' }
  if ($p.ExitCode -ne 0) { throw "Frozen parser test failed ($($p.ExitCode))" }
  $p = Start-Process $exe -PassThru
  try {
    for ($i=0;$i -lt 60;$i++) {
      Start-Sleep -Milliseconds 500
      $p.Refresh()
      if ($p.HasExited) { throw 'GUI exited early' }
      if ($p.MainWindowHandle -ne 0 -and $p.Responding) { break }
    }
    if ($p.MainWindowHandle -eq 0 -or !$p.Responding) { throw 'No responsive main window' }
    Write-Host "Responsive GUI: $($p.MainWindowTitle)"
    $null = $p.CloseMainWindow()
    if (!$p.WaitForExit(15000) -or $p.ExitCode -ne 0) { throw 'GUI did not exit normally' }
  } finally { if (!$p.HasExited) { $p.Kill() } }
}
$old = Join-Path $stage 'upgrade'
$fresh = Join-Path $stage 'fresh'
Install-App $OldInstaller $old
$dist = Join-Path $stage 'dist'
python -m PyInstaller --clean --noconfirm --distpath $dist --workpath "$stage/work" packaging/EggieDocuFlow_windows.spec
if ($LASTEXITCODE) {throw 'PyInstaller failed'}
$app = Join-Path $dist 'Eggie DocuFlow'
# Omit known host-only runtime duplicates that were absent in the verified release.
Get-ChildItem "$app/_internal" -File | Where-Object {
  $_.Name -match '^(api-ms-win-[\w-]+|ucrtbase|lib(crypto|ssl)-3-x64)\.dll$' -and
  !(Test-Path (Join-Path "$old/_internal" $_.Name))
} | Remove-Item
$include = 'packaging/retired_2026110401.iss'
python packaging/rebuild/windows_retired_files.py $old $app $include
if ($LASTEXITCODE) {throw 'Upgrade manifest failed'}
$env:EGGIE_APP_VERSION='1.5.1'
$env:EGGIE_APP_SOURCE_DIR=$app
$env:EGGIE_APP_OUTPUT_DIR=(New-Item -ItemType Directory "$stage/installer").FullName
$env:EGGIE_CHINESE_LANGUAGE_FILE=(Resolve-Path 'packaging/ChineseSimplified.isl').Path
$compiler="${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
& $compiler '/Q' 'packaging/EggieDocuFlow_windows.iss'
if ($LASTEXITCODE) {throw 'Inno Setup failed'}
$new = (Get-ChildItem "$stage/installer/*.exe").FullName
Install-App $new $fresh
Check-App $fresh
Set-Content "$old/_internal/user-retained.txt" 'example'
Install-App $new $old
Check-App $old
python -c "import hashlib, pathlib, sys; a,b=map(pathlib.Path,sys.argv[1:]); inv=lambda root:{p.relative_to(root).as_posix():hashlib.file_digest(p.open('rb'),'sha256').hexdigest() for p in root.rglob('*') if p.is_file()}; x,y=inv(a),inv(b); assert y.pop('user-retained.txt') and x==y, (set(x)^set(y), [k for k in x.keys() & y.keys() if x[k]!=y[k]])" "$fresh/_internal" "$old/_internal"
if ($LASTEXITCODE) {throw 'Installed file inventories do not match'}
New-Item -ItemType Directory 'verified' | Out-Null
Copy-Item $new, $include -Destination 'verified'
Get-FileHash $new
