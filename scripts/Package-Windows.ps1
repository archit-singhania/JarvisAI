param([string]$Dotnet='dotnet',[switch]$NoRestore)
$ErrorActionPreference='Stop'
$taskRepo=Split-Path -Parent $PSScriptRoot
$taskReleaseRoot=Join-Path $taskRepo 'release'
$taskStamp=(Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
$taskPackage=Join-Path $taskReleaseRoot "Wednesday-win-x64-$taskStamp"
if(-not [IO.Path]::GetFullPath($taskPackage).StartsWith([IO.Path]::GetFullPath($taskReleaseRoot)+[IO.Path]::DirectorySeparatorChar)){throw 'Invalid package path'}
New-Item -ItemType Directory -Path $taskPackage -Force | Out-Null
[string[]]$taskRestoreArgs=@();if($NoRestore){$taskRestoreArgs=@('--no-restore')}
& $Dotnet publish (Join-Path $taskRepo 'desktop/JarvisAI.csproj') -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o (Join-Path $taskPackage 'desktop') @taskRestoreArgs
if($LASTEXITCODE -ne 0){throw 'Desktop publish failed'}
New-Item -ItemType Directory -Path (Join-Path $taskPackage 'backend/app') -Force | Out-Null
$taskAppRoot=Join-Path $taskRepo 'backend/app'
Get-ChildItem -LiteralPath $taskAppRoot -Recurse -File -Filter '*.py' | ForEach-Object {
  $taskRelative=[IO.Path]::GetRelativePath($taskAppRoot,$_.FullName)
  $taskDestination=Join-Path (Join-Path $taskPackage 'backend/app') $taskRelative
  New-Item -ItemType Directory -Path (Split-Path -Parent $taskDestination) -Force | Out-Null
  Copy-Item -LiteralPath $_.FullName -Destination $taskDestination
}
Copy-Item -LiteralPath (Join-Path $taskRepo 'backend/requirements-core.txt') -Destination (Join-Path $taskPackage 'backend')
Copy-Item -LiteralPath (Join-Path $taskRepo 'backend/requirements-speech.txt') -Destination (Join-Path $taskPackage 'backend')
Copy-Item -LiteralPath (Join-Path $taskRepo 'backend/.env.example') -Destination (Join-Path $taskPackage 'backend')
Copy-Item -LiteralPath (Join-Path $taskRepo 'ui') -Destination $taskPackage -Recurse
$taskPackageReadme=@'
# Wednesday Windows local release

This package contains a self-contained Windows x64 assistant, its maintained Python core service source, original browser interface, optional speech dependency manifest and manual acceptance documentation. The Windows client needs no .NET SDK. The backend needs Python 3.11 or 3.12 and internet for its first dependency installation.

Extract to a writable private folder. Keep its data and local client session private. Start a new backend and client with:

```powershell
./Start-Wednesday.ps1 -Python python -Port 8019
```

The launcher installs or repairs the local core environment, checks readiness, launches the assistant, and stops only its own backend when the client closes. A busy port fails clearly. If your normal service already runs, launch the client directly instead:

```powershell
$env:WEDNESDAY_URL = 'http://127.0.0.1:8000'
./desktop/JarvisAI.exe
```

Memory, documents, reminders, explicit time tools, workflows and JSON export work without a model. Configure selected AI/speech engines in private `backend/.env` only when you need them; the example never contains your keys. Preserve useful existing configuration and data. Missing providers return a readable error.

[Manual steps and expected results](docs/MANUAL-TESTING.md), [engine setup](docs/SETUP.md), [capability matrix](docs/CAPABILITIES.md), [architecture](docs/ARCHITECTURE.md) and [verification limits](docs/RELEASE.md) describe the full product. Source-checkout commands in those guides refer to the maintained repository; use the launcher or packaged executable above for this archive.

The binary is unsigned. Local render/relaunch and WAV/MP3 decoding checks passed; physical microphone/playback and interactive distribution-device acceptance remain manual. Live model inference, experimental engines and public hosting are separate gates. No real environment file, session credential or user database is included.
'@
Set-Content -LiteralPath (Join-Path $taskPackage 'README.md') -Value $taskPackageReadme -Encoding utf8
Copy-Item -LiteralPath (Join-Path $taskRepo 'docs') -Destination $taskPackage -Recurse
Copy-Item -LiteralPath (Join-Path $taskRepo 'fixtures') -Destination $taskPackage -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Start-Wednesday.ps1') -Destination $taskPackage
Compress-Archive -Path (Join-Path $taskPackage '*') -DestinationPath "$taskPackage.zip"
Get-FileHash -LiteralPath "$taskPackage.zip" -Algorithm SHA256 | Select-Object Hash,Path
