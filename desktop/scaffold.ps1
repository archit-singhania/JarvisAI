# scaffold.ps1
# Run this ONCE from inside the desktop/ folder on Windows:
#   cd desktop
#   .\scaffold.ps1
#
# It creates the proper subfolder structure and moves files into place.

$base = Split-Path -Parent $MyInvocation.MyCommand.Path

# Create folders
New-Item -ItemType Directory -Force "$base\Models"   | Out-Null
New-Item -ItemType Directory -Force "$base\Services" | Out-Null
New-Item -ItemType Directory -Force "$base\Assets"   | Out-Null

# Move flat files into correct subfolders
$moves = @{
    "Models_ChatMessage.cs"               = "Models\ChatMessage.cs"
    "Services_JarvisWebSocketService.cs"  = "Services\JarvisWebSocketService.cs"
    "Services_AudioService.cs"            = "Services\AudioService.cs"
}

foreach ($src in $moves.Keys) {
    $srcPath  = Join-Path $base $src
    $destPath = Join-Path $base $moves[$src]
    if (Test-Path $srcPath) {
        Move-Item -Path $srcPath -Destination $destPath -Force
        Write-Host "  Moved: $src -> $($moves[$src])"
    }
}

# Remove Angular leftover
$angular = Join-Path $base "angular.json"
if (Test-Path $angular) {
    Remove-Item $angular -Force
    Write-Host "  Removed: angular.json"
}

Write-Host ""
Write-Host "Scaffold complete. Run: dotnet restore"
