param([string]$Dotnet='dotnet')
$ErrorActionPreference='Stop'
$taskRepo=Split-Path -Parent $PSScriptRoot
$taskReleaseRoot=Join-Path $taskRepo 'release'
$taskStamp=(Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
$taskPackage=Join-Path $taskReleaseRoot "Wednesday-win-x64-$taskStamp"
if(-not [IO.Path]::GetFullPath($taskPackage).StartsWith([IO.Path]::GetFullPath($taskReleaseRoot)+[IO.Path]::DirectorySeparatorChar)){throw 'Invalid package path'}
New-Item -ItemType Directory -Path $taskPackage -Force | Out-Null
& $Dotnet publish (Join-Path $taskRepo 'desktop/JarvisAI.csproj') -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o (Join-Path $taskPackage 'desktop')
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
Copy-Item -LiteralPath (Join-Path $taskRepo 'backend/.env.example') -Destination (Join-Path $taskPackage 'backend')
Copy-Item -LiteralPath (Join-Path $taskRepo 'ui') -Destination $taskPackage -Recurse
Copy-Item -LiteralPath (Join-Path $taskRepo 'README.md') -Destination $taskPackage
Copy-Item -LiteralPath (Join-Path $taskRepo 'docs') -Destination $taskPackage -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Start-Wednesday.ps1') -Destination $taskPackage
Compress-Archive -Path (Join-Path $taskPackage '*') -DestinationPath "$taskPackage.zip"
Get-FileHash -LiteralPath "$taskPackage.zip" -Algorithm SHA256 | Select-Object Hash,Path
