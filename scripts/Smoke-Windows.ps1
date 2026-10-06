param(
  [string]$Executable='',
  [string]$ServiceUrl='http://127.0.0.1:8006',
  [string]$OutputDirectory=''
)
$ErrorActionPreference='Stop'
$taskRepo=Split-Path -Parent $PSScriptRoot
if(-not $Executable){$Executable=Join-Path $taskRepo 'desktop/bin/Release/net10.0-windows/JarvisAI.exe'}
if(-not $OutputDirectory){$OutputDirectory=Join-Path $taskRepo 'test-results/native'}
$taskService=[Uri]$ServiceUrl
if(-not $taskService.IsLoopback -or $taskService.Scheme -ne 'http'){throw 'Native acceptance requires an isolated loopback service'}
$taskState=Join-Path $OutputDirectory ('state-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskState -Force | Out-Null
$taskPreviousUrl=$env:WEDNESDAY_URL
$taskPreviousState=$env:WEDNESDAY_CLIENT_DATA
$taskPreviousLog=$env:WEDNESDAY_SMOKE_LOG
$taskPreviousDotnet=$env:DOTNET_ROOT
$taskBundledDotnet=Join-Path (Split-Path -Parent $taskRepo) '.tooling/dotnet'
if(-not $env:DOTNET_ROOT -and (Test-Path -LiteralPath (Join-Path $taskBundledDotnet 'dotnet.exe'))){$env:DOTNET_ROOT=$taskBundledDotnet}
$env:WEDNESDAY_URL=$ServiceUrl
$env:WEDNESDAY_CLIENT_DATA=$taskState
$env:WEDNESDAY_SMOKE_LOG=Join-Path $taskState 'native-errors.log'
function Invoke-NativeCheck([string[]]$CheckArguments){
  # Every argument is quoted as a native process argument, including spaced
  # package/output paths. The tested executable is intentionally invisible.
  $taskProcessArguments=$CheckArguments | ForEach-Object {'"'+$_+'"'}
  $taskProcess=Start-Process -FilePath $Executable -ArgumentList $taskProcessArguments -WindowStyle Hidden -PassThru
  try {
    if(-not $taskProcess.WaitForExit(30000)){throw 'Native acceptance timed out'}
    if($taskProcess.ExitCode -ne 0){throw 'Native acceptance failed; inspect its isolated error log'}
  } finally {if(-not $taskProcess.HasExited){Stop-Process -Id $taskProcess.Id}}
}
try {
  $taskHealth=Invoke-RestMethod "$ServiceUrl/health" -TimeoutSec 5
  if($taskHealth.status -ne 'ready' -or $taskHealth.version -ne 1){throw 'Wednesday service is not ready'}
  $taskBootstrap=Invoke-RestMethod "$ServiceUrl/api/session" -Method Post
  $taskHeaders=@{Authorization='Bearer '+$taskBootstrap.token}
  @{token=$taskBootstrap.token;conversation=''}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskState 'session.json')
  Invoke-RestMethod "$ServiceUrl/api/preferences" -Method Patch -Headers $taskHeaders -ContentType 'application/json' -Body '{"theme":"dark"}' | Out-Null
  Invoke-NativeCheck @("--smoke=$(Join-Path $OutputDirectory 'wpf-desktop-dark.png')","--motion-check=$(Join-Path $OutputDirectory 'motion.json')")
  $taskSession=Get-Content -Raw -LiteralPath (Join-Path $taskState 'session.json') | ConvertFrom-Json
  $taskHeaders=@{Authorization='Bearer '+$taskSession.token}
  $taskLight=@{theme='light';timezone='Europe/London';persona='Explain the concrete tradeoffs.';reduce_motion=$true}|ConvertTo-Json
  Invoke-RestMethod "$ServiceUrl/api/preferences" -Method Patch -Headers $taskHeaders -ContentType 'application/json' -Body $taskLight | Out-Null
  Invoke-NativeCheck @("--smoke=$(Join-Path $OutputDirectory 'wpf-desktop-light.png')")
  Invoke-NativeCheck @("--smoke=$(Join-Path $OutputDirectory 'wpf-preferences-light.png')",'--smoke-section=Preferences')
  $taskReadback=Invoke-RestMethod "$ServiceUrl/api/preferences" -Headers $taskHeaders
  if($taskReadback.theme -ne 'light' -or $taskReadback.timezone -ne 'Europe/London'){throw 'Native fixture preference readback failed'}
  if((Get-FileHash (Join-Path $OutputDirectory 'wpf-desktop-dark.png')).Hash -eq (Get-FileHash (Join-Path $OutputDirectory 'wpf-desktop-light.png')).Hash){throw 'Both appearance renders unexpectedly match'}
  $taskAudioRoot=Join-Path $taskRepo 'fixtures/audio'
  Invoke-NativeCheck @("--audio-check=$taskAudioRoot")
  $taskAudio=Get-Content -Raw -LiteralPath (Join-Path $taskAudioRoot 'native-audio-acceptance.json')|ConvertFrom-Json
  if(-not $taskAudio.passed){throw 'Native audio decoding failed'}
  $taskIsPackage=[IO.Path]::GetFullPath($Executable).StartsWith(([IO.Path]::GetFullPath((Join-Path $taskRepo 'release'))+[IO.Path]::DirectorySeparatorChar),[StringComparison]::OrdinalIgnoreCase)
  @{passed=$true;packagedExecutable=$taskIsPackage;syntheticFixtures=$true;checks=@('invisible runtime and clean exit','distinct light and dark renders','owned preference readback','preferences page render','WAV/MP3 production decoding','active route and orb clocks','mid-transition reduced motion cancellation','immediate reduced motion navigation','settled animation clocks')}|ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'acceptance.json')
  Write-Output 'Native Windows acceptance passed.'
} finally {
  $env:WEDNESDAY_URL=$taskPreviousUrl
  $env:WEDNESDAY_CLIENT_DATA=$taskPreviousState
  $env:WEDNESDAY_SMOKE_LOG=$taskPreviousLog
  $env:DOTNET_ROOT=$taskPreviousDotnet
}
