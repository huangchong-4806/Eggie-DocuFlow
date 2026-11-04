$ErrorActionPreference = 'Stop'

$ProjectRoot = [System.IO.Directory]::GetParent($PSScriptRoot).FullName
$Python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
$SharedReleaseDir = [System.IO.Path]::Combine($ProjectRoot, 'release')
$BuildId = [guid]::NewGuid().ToString('N')
$LocalBuildRoot = [System.IO.Path]::Combine($env:LOCALAPPDATA, 'EggieDocuFlowBuild', $BuildId)
$PreviousCache = $env:PYINSTALLER_CONFIG_DIR
$CreatedBuildRoot = $false
$StagedInstaller = $null
$DistDir = [System.IO.Path]::Combine($LocalBuildRoot, 'dist')
$BuildDir = [System.IO.Path]::Combine($LocalBuildRoot, 'build')
$LocalReleaseDir = [System.IO.Path]::Combine($LocalBuildRoot, 'release')
$SpecFile = [System.IO.Path]::Combine($ProjectRoot, 'packaging', 'EggieDocuFlow_windows.spec')
$InstallerFile = [System.IO.Path]::Combine($ProjectRoot, 'packaging', 'EggieDocuFlow_windows.iss')

function Find-InnoSetupCompiler {
    $candidate = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($candidate) {
        return $candidate.Source
    }

    $paths = @(
        [System.IO.Path]::Combine(${env:ProgramFiles(x86)}, 'Inno Setup 6', 'ISCC.exe'),
        [System.IO.Path]::Combine($env:ProgramFiles, 'Inno Setup 6', 'ISCC.exe'),
        [System.IO.Path]::Combine($env:LOCALAPPDATA, 'Programs', 'Inno Setup 6', 'ISCC.exe'),
        [System.IO.Path]::Combine($env:LOCALAPPDATA, 'Inno Setup 6', 'ISCC.exe')
    )
    foreach ($path in $paths) {
        if ($path -and (Test-Path $path)) {
            return $path
        }
    }
    throw 'Inno Setup 6 was not found. Install it, then run this script again.'
}

Push-Location $ProjectRoot
try {
    $versionFile = [System.IO.Path]::Combine($ProjectRoot, 'version.py')
    $versionText = [System.IO.File]::ReadAllText($versionFile)
    $versionMatch = [System.Text.RegularExpressions.Regex]::Match($versionText, '^APP_VERSION\s*=\s*"([^"]+)"', 'Multiline')
    $Version = $versionMatch.Groups[1].Value
    if (-not $Version) {
        throw 'The application version could not be read.'
    }

    New-Item -ItemType Directory -Path $LocalBuildRoot -ErrorAction Stop | Out-Null
    $CreatedBuildRoot = $true
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $LocalBuildRoot 'pyinstaller-cache'
    New-Item -ItemType Directory -Force $LocalReleaseDir | Out-Null

    & $Python -m PyInstaller --noconfirm --clean --distpath $DistDir --workpath $BuildDir $SpecFile
    if ($LASTEXITCODE -ne 0) {
        throw 'Windows application build failed.'
    }

    $ApplicationPath = [System.IO.Path]::Combine($DistDir, 'Eggie DocuFlow', 'Eggie DocuFlow.exe')
    if (-not (Test-Path $ApplicationPath)) {
        throw "Application file was not created: ${ApplicationPath}"
    }

    $env:EGGIE_APP_VERSION = $Version
    $env:EGGIE_APP_SOURCE_DIR = [System.IO.Path]::GetDirectoryName($ApplicationPath)
    $env:EGGIE_APP_OUTPUT_DIR = $LocalReleaseDir
    $env:EGGIE_CHINESE_LANGUAGE_FILE = [System.IO.Path]::Combine($ProjectRoot, 'packaging', 'ChineseSimplified.isl')
    if (-not (Test-Path $env:EGGIE_CHINESE_LANGUAGE_FILE)) {
        throw 'Chinese installer language file was not found.'
    }
    $Compiler = Find-InnoSetupCompiler
    & $Compiler $InstallerFile
    if ($LASTEXITCODE -ne 0) {
        throw 'Windows installer build failed.'
    }

    $LocalInstallerPath = [System.IO.Path]::Combine($LocalReleaseDir, "EggieDocuFlow_V${Version}_Windows_x64_Setup.exe")
    if (-not (Test-Path $LocalInstallerPath)) {
        throw "Installer file was not created: ${LocalInstallerPath}"
    }

    New-Item -ItemType Directory -Force $SharedReleaseDir | Out-Null
    $InstallerPath = [System.IO.Path]::Combine($SharedReleaseDir, [System.IO.Path]::GetFileName($LocalInstallerPath))
    $StagedInstaller = Join-Path $SharedReleaseDir ".$BuildId.tmp"
    if ((Get-Item -LiteralPath $LocalInstallerPath).Length -eq 0) {
        throw 'The generated installer is empty.'
    }
    $ExpectedHash = (Get-FileHash -LiteralPath $LocalInstallerPath -Algorithm SHA256).Hash
    Copy-Item -LiteralPath $LocalInstallerPath -Destination $StagedInstaller
    if ((Get-FileHash -LiteralPath $StagedInstaller -Algorithm SHA256).Hash -ne $ExpectedHash) {
        throw 'Installer copy failed its SHA-256 check.'
    }
    # Publish by same-directory rename, including on Windows PowerShell 5.1.
    & $Python -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' $StagedInstaller $InstallerPath
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot replace the installer at $InstallerPath. Check permissions and close any program using it."
    }

    Write-Host "Installer created: ${InstallerPath}"
} finally {
    $env:PYINSTALLER_CONFIG_DIR = $PreviousCache
    if ($StagedInstaller -and (Test-Path -LiteralPath $StagedInstaller)) {
        Remove-Item -LiteralPath $StagedInstaller -Force -ErrorAction Continue
    }
    if ($CreatedBuildRoot) {
        Remove-Item -LiteralPath $LocalBuildRoot -Recurse -Force -ErrorAction Continue
    }
    Pop-Location
}
