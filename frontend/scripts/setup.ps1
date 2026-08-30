# Wrapper - forward to root scripts/setup.ps1
$Root = (Resolve-Path "$PSScriptRoot/../..").Path
& "$Root/scripts/setup.ps1" @args
