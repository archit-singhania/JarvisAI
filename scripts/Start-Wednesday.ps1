param([string]$Python='python',[ValidateRange(1024,65535)][int]$Port=8000)
$ErrorActionPreference='Stop'

function Invoke-WednesdayCoreCommand {
  param([string]$Python,[string[]]$Arguments,[string]$FailureMessage)
  & $Python @Arguments | Out-Host
  if($LASTEXITCODE -ne 0){throw $FailureMessage}
}

function Initialize-WednesdayCore {
  param([string]$AppRoot,[string]$Python)
  $taskCoreVenv=Join-Path $AppRoot '.venv'
  $taskInterpreter=Join-Path $taskCoreVenv 'Scripts/python.exe'
  if(-not (Test-Path -LiteralPath $taskInterpreter)){
    Invoke-WednesdayCoreCommand -Python $Python -Arguments @('-m','venv',$taskCoreVenv) -FailureMessage 'Install Python 3.11 or 3.12 first'
  }
  $taskRequirements=Join-Path $AppRoot 'backend/requirements-core.txt'
  $taskRequirementsHash=(Get-FileHash -LiteralPath $taskRequirements -Algorithm SHA256).Hash
  $taskMarker=Join-Path $taskCoreVenv 'wednesday-core.sha256'
  $taskNeedsSetup=-not (Test-Path -LiteralPath $taskMarker)
  if(-not $taskNeedsSetup){$taskNeedsSetup=(Get-Content -Raw -LiteralPath $taskMarker).Trim() -ne $taskRequirementsHash}
  if(-not $taskNeedsSetup){
    try {
      Invoke-WednesdayCoreCommand -Python $taskInterpreter -Arguments @('-c','import fastapi, uvicorn, httpx, pydantic_settings, multipart, pypdf, tzdata') -FailureMessage 'Core dependencies need repair'
    } catch {$taskNeedsSetup=$true}
  }
  if($taskNeedsSetup){
    Invoke-WednesdayCoreCommand -Python $taskInterpreter -Arguments @('-m','pip','install','-r',$taskRequirements) -FailureMessage 'Dependency setup failed; rerun the launcher to retry'
    Set-Content -LiteralPath $taskMarker -Value $taskRequirementsHash -Encoding ascii
  }
  return $taskInterpreter
}

$taskAppRoot=if(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'backend')){$PSScriptRoot}else{Split-Path -Parent $PSScriptRoot}
if(-not (Test-Path -LiteralPath (Join-Path $taskAppRoot 'desktop/JarvisAI.exe'))){throw 'Use this launcher from an extracted Wednesday release. For source, run dotnet run --project desktop/JarvisAI.csproj.'}
$taskProbe=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$Port)
$taskProbe.Server.ExclusiveAddressUse=$true
try{$taskProbe.Start()}catch{throw "Port $Port is already in use. Close the existing backend or choose -Port with another free port."}finally{$taskProbe.Stop()}
$taskInterpreter=Initialize-WednesdayCore -AppRoot $taskAppRoot -Python $Python
$taskUrl="http://127.0.0.1:$Port"
$taskPreviousUrl=$env:WEDNESDAY_URL
$taskPreviousOrigins=$env:ALLOWED_ORIGINS
$env:WEDNESDAY_URL=$taskUrl
$env:ALLOWED_ORIGINS="${taskUrl},http://localhost:$Port,aura://app"
$taskLogRoot=Join-Path $taskAppRoot 'logs'
New-Item -ItemType Directory -Path $taskLogRoot -Force | Out-Null
$taskServer=$null
try {
  $taskServer=Start-Process -FilePath $taskInterpreter -ArgumentList @('-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $taskAppRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLogRoot 'backend-output.log') -RedirectStandardError (Join-Path $taskLogRoot 'backend-error.log') -PassThru
  $taskReady=$false
  for($taskAttempt=0;$taskAttempt -lt 30;$taskAttempt++){
    if($taskServer.HasExited){throw 'Backend startup failed. See logs/backend-error.log.'}
    try{$taskHealth=Invoke-RestMethod "$taskUrl/health" -TimeoutSec 1;if($taskHealth.status -eq 'ready' -and $taskHealth.version -eq 1){$taskReady=$true;break}}catch{}
    Start-Sleep -Seconds 1
  }
  if(-not $taskReady){throw 'The local backend did not become ready'}
  Start-Process -FilePath (Join-Path $taskAppRoot 'desktop/JarvisAI.exe') -WorkingDirectory $taskAppRoot -Wait
} finally {
  if($taskServer -and -not $taskServer.HasExited){Stop-Process -Id $taskServer.Id}
  $env:WEDNESDAY_URL=$taskPreviousUrl
  $env:ALLOWED_ORIGINS=$taskPreviousOrigins
}
