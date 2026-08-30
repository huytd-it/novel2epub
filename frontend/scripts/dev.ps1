# Wrapper - forward to root scripts/dev.ps1
$Root = (Resolve-Path "$PSScriptRoot/../..").Path
& "$Root/scripts/dev.ps1" @args
