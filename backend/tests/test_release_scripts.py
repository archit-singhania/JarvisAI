"""Windows release regressions without microphone access or network installs."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which('pwsh')


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_powershell(script):
    if not POWERSHELL:
        pytest.skip('PowerShell 7 is required for Windows release checks')
    result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


def test_launcher_retries_failed_install_and_repairs_changed_dependencies(tmp_path):
    script = r"""
$ErrorActionPreference='Stop'
$taskRoot=TEST_ROOT
$taskLauncher=LAUNCHER
$taskTokens=$null;$taskErrors=$null
$taskAst=[Management.Automation.Language.Parser]::ParseFile($taskLauncher,[ref]$taskTokens,[ref]$taskErrors)
if($taskErrors.Count){throw 'Launcher syntax is invalid'}
$taskDefinition=$taskAst.FindAll({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Initialize-WednesdayCore'},$true)[0]
. ([ScriptBlock]::Create($taskDefinition.Extent.Text))
New-Item -ItemType Directory -Path (Join-Path $taskRoot 'backend') -Force | Out-Null
Set-Content -LiteralPath (Join-Path $taskRoot 'backend/requirements-core.txt') -Value 'fixture-package==1'
$script:taskInstallCount=0;$script:taskCreateCount=0;$script:taskProbeFailure=$false
function Invoke-WednesdayCoreCommand {
  param([string]$Python,[string[]]$Arguments,[string]$FailureMessage)
  if($Arguments[0] -eq '-m' -and $Arguments[1] -eq 'venv'){
    $script:taskCreateCount++
    $taskScripts=Join-Path $Arguments[2] 'Scripts'
    New-Item -ItemType Directory -Path $taskScripts -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $taskScripts 'python.exe'),'fixture')
  } elseif($Arguments[0] -eq '-m' -and $Arguments[1] -eq 'pip'){
    $script:taskInstallCount++
    if($script:taskInstallCount -eq 1){throw 'Simulated interrupted pip install'}
  } elseif($Arguments[0] -eq '-c' -and $script:taskProbeFailure){throw 'Simulated missing dependency'}
}
$taskFailed=$false
try{Initialize-WednesdayCore -AppRoot $taskRoot -Python 'fixture-python' | Out-Null}catch{$taskFailed=$true}
$taskMarker=Join-Path $taskRoot '.venv/wednesday-core.sha256'
if(-not $taskFailed -or (Test-Path -LiteralPath $taskMarker)){throw 'A failed install was recorded as complete'}
Initialize-WednesdayCore -AppRoot $taskRoot -Python 'fixture-python' | Out-Null
if($script:taskInstallCount -ne 2 -or $script:taskCreateCount -ne 1 -or -not (Test-Path -LiteralPath $taskMarker)){throw 'Retry skipped dependency installation'}
Initialize-WednesdayCore -AppRoot $taskRoot -Python 'fixture-python' | Out-Null
if($script:taskInstallCount -ne 2){throw 'Unchanged working dependencies were reinstalled'}
Add-Content -LiteralPath (Join-Path $taskRoot 'backend/requirements-core.txt') -Value 'fixture-package-two==2'
Initialize-WednesdayCore -AppRoot $taskRoot -Python 'fixture-python' | Out-Null
if($script:taskInstallCount -ne 3){throw 'Changed dependency manifest was ignored'}
$script:taskProbeFailure=$true
Initialize-WednesdayCore -AppRoot $taskRoot -Python 'fixture-python' | Out-Null
if($script:taskInstallCount -ne 4){throw 'Damaged dependencies were not repaired'}
Write-Output 'Bootstrap retry, manifest update and repair passed'
"""
    run_powershell(script.replace('TEST_ROOT', ps_literal(tmp_path)).replace('LAUNCHER', ps_literal(ROOT / 'scripts/Start-Wednesday.ps1')))


def test_desktop_reminder_default_uses_selected_zone_and_dst():
    script = r"""
$ErrorActionPreference='Stop'
Add-Type -Path CLOCK_FILE -CompilerOptions '/nullable:enable'
$taskSummer=[DateTimeOffset]::Parse('2026-07-01T00:00:00Z')
$taskWinter=[DateTimeOffset]::Parse('2026-01-01T00:00:00Z')
if([JarvisAI.ReminderClock]::Suggest('Asia/Kolkata',$taskSummer) -ne '2026-07-01 06:30'){throw 'India default is not one hour ahead in its selected zone'}
if([JarvisAI.ReminderClock]::Suggest('Europe/London',$taskSummer) -ne '2026-07-01 02:00'){throw 'Summer timezone offset was ignored'}
if([JarvisAI.ReminderClock]::Suggest('Europe/London',$taskWinter) -ne '2026-01-01 01:00'){throw 'Winter timezone offset was ignored'}
if($null -ne [JarvisAI.ReminderClock]::Suggest('/invalid',$taskSummer)){throw 'Invalid zone was accepted'}
Write-Output 'Selected timezone and DST passed'
"""
    run_powershell(script.replace('CLOCK_FILE', ps_literal(ROOT / 'desktop/ReminderClock.cs')))
