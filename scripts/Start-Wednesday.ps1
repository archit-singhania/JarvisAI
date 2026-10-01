param([string]$Python='python',[ValidateRange(1024,65535)][int]$Port=8000)
$ErrorActionPreference='Stop'
$taskAppRoot=if(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'backend')){$PSScriptRoot}else{Split-Path -Parent $PSScriptRoot}
if(-not (Test-Path -LiteralPath (Join-Path $taskAppRoot 'desktop/JarvisAI.exe'))){throw 'Use this launcher from an extracted Wednesday release. For source, run dotnet run --project desktop/JarvisAI.csproj.'}
$taskProbe=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$Port)
$taskProbe.Server.ExclusiveAddressUse=$true
try{$taskProbe.Start()}catch{throw "Port $Port is already in use. Close the existing backend or choose -Port with another free port."}finally{$taskProbe.Stop()}
$taskVenv=Join-Path $taskAppRoot '.venv'
if(-not (Test-Path -LiteralPath (Join-Path $taskVenv 'Scripts/python.exe'))){
  & $Python -m venv $taskVenv
  if($LASTEXITCODE -ne 0){throw 'Install Python 3.11 or 3.12 first'}
  & (Join-Path $taskVenv 'Scripts/python.exe') -m pip install -r (Join-Path $taskAppRoot 'backend/requirements-core.txt')
  if($LASTEXITCODE -ne 0){throw 'Dependency setup failed'}
}
$taskUrl="http://127.0.0.1:$Port"
$taskPreviousUrl=$env:WEDNESDAY_URL
$taskPreviousOrigins=$env:ALLOWED_ORIGINS
$env:WEDNESDAY_URL=$taskUrl
$env:ALLOWED_ORIGINS="${taskUrl},http://localhost:$Port,aura://app"
$taskLogRoot=Join-Path $taskAppRoot 'logs'
New-Item -ItemType Directory -Path $taskLogRoot -Force | Out-Null
$taskServer=$null
try {
  $taskServer=Start-Process -FilePath (Join-Path $taskVenv 'Scripts/python.exe') -ArgumentList @('-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $taskAppRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLogRoot 'backend-output.log') -RedirectStandardError (Join-Path $taskLogRoot 'backend-error.log') -PassThru
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
