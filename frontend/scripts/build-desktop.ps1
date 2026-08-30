# Wrapper - forward to root scripts/build-desktop.ps1
$Root = (Resolve-Path "$PSScriptRoot/../..").Path
& "$Root/scripts/build-desktop.ps1" @args
