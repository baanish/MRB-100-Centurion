# tools/Run-Remote.ps1 for the exterior pass: runs on the remote host's default tree, receives into a folder of its own,
# and moves the returned files into place only when every one is the pass's own (.cache/art/exterior_pass/; Python
# bytecode is dropped). Anything else stops the run with the list, left in the receive folder.
# Usage: pwsh -NoProfile -File Invoke-Remote.ps1 -Ship <a,b,c> -Run <command line> [-Tree <name>]
# -Tree runs in a named worktree of its own on the host (tools/Run-Remote.ps1), beside jobs in the default one.
param([string]$Ship = '', [Parameter(Mandatory)][string]$Run, [string]$Tree = '')
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot/../../..").Path
Set-Location $repo
$recvRel = ".cache/art/exterior_pass/recv-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$recv = Join-Path $repo $recvRel
$treeArgs = if ($Tree) { @('-Tree', $Tree) } else { @() }
& pwsh -NoProfile -File tools/Run-Remote.ps1 -Ship $Ship -ReceiveTo $recvRel -Run $Run @treeArgs
$code = $LASTEXITCODE
if (-not (Test-Path -LiteralPath $recv)) { exit $code }
$files = @(Get-ChildItem -LiteralPath $recv -Recurse -File | ForEach-Object { [IO.Path]::GetRelativePath($recv, $_.FullName).Replace('\', '/') })
$kept = @($files | Where-Object { $_ -notmatch '(^|/)__pycache__/' })
$foreign = @($kept | Where-Object { $_ -notmatch '^\.cache/art/exterior_pass/' })
if ($foreign.Count) {
    Write-Output "STOP: the run returned files outside the exterior pass (left in $recvRel): $($foreign -join ', ')"
    exit 3
}
foreach ($f in $kept) {
    $dest = Join-Path $repo $f
    New-Item -ItemType Directory -Force (Split-Path -Parent $dest) | Out-Null
    Move-Item -LiteralPath (Join-Path $recv $f) -Destination $dest -Force
}
Write-Output "received $($kept.Count) files ($($files.Count - $kept.Count) bytecode dropped)"
& pwsh -NoProfile -File tools/Remove-Generated.ps1 $recv | Out-Null
exit $code
