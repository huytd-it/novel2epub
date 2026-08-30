# Wrapper - forward to root scripts/install.ps1
$Root = (Resolve-Path "$PSScriptRoot/../..").Path
& "$Root/scripts/install.ps1" @args
