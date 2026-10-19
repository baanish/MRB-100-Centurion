# Remove-Generated.ps1 <path> [<path> ...]   (positional; `-Path a b` fails under pwsh -File)
#
# The only way generated output gets deleted in this repo (recursive deletes are
# denied in .claude/settings.json). A target must sit strictly inside <repo>\.cache\
# or <repo>\build\ after resolving, and neither the target, any ancestor between it
# and the repo root, nor anything inside it may be a reparse point (junction or
# symlink): an agent once followed a junction and deleted 48,000 files in 100 s.
# Exits 1 if any path was refused. A path that doesn't exist is reported and skipped.
param(
    [Parameter(Mandatory, Position = 0, ValueFromRemainingArguments)]
    [string[]]$Path
)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$allowedRoots = @("$repo\.cache", "$repo\build")
$cwd = (Get-Location -PSProvider FileSystem).ProviderPath
$reparse = [IO.FileAttributes]::ReparsePoint

# Attributes of the item itself (a link is not followed), or $null if absent.
function Get-ItemAttributes([string]$p) {
    try { [IO.File]::GetAttributes($p) }
    catch [IO.FileNotFoundException], [IO.DirectoryNotFoundException] { $null }
}

# Returns a refusal reason, or $null if the path may be deleted.
function Test-Deletable([string]$full) {
    $root = $allowedRoots | Where-Object { $full.StartsWith("$_\", [StringComparison]::OrdinalIgnoreCase) }
    if (-not $root) { return "not strictly inside $($allowedRoots -join ' or ')" }

    $level = $full
    while ($level.Length -gt $repo.Length) {
        $attr = Get-ItemAttributes $level
        if ($null -ne $attr -and ($attr -band $reparse)) { return "reparse point at $level" }
        $level = [IO.Path]::GetDirectoryName($level)
    }

    $attr = Get-ItemAttributes $full
    if ($null -eq $attr -or -not ($attr -band [IO.FileAttributes]::Directory)) { return $null }

    # Walk the tree by hand so nothing below a reparse point is ever enumerated.
    $stack = [Collections.Generic.Stack[IO.DirectoryInfo]]::new()
    $stack.Push([IO.DirectoryInfo]::new($full))
    while ($stack.Count -gt 0) {
        try { $children = $stack.Pop().GetFileSystemInfos() }
        catch { return "cannot list contents: $($_.Exception.Message)" }
        foreach ($child in $children) {
            if ($child.Attributes -band $reparse) { return "contains reparse point $($child.FullName)" }
            if ($child -is [IO.DirectoryInfo]) { $stack.Push($child) }
        }
    }
    return $null
}

$refused = 0
foreach ($p in $Path) {
    $full = [IO.Path]::GetFullPath($p, $cwd).TrimEnd('\')
    $reason = Test-Deletable $full
    if ($reason) {
        Write-Output "REFUSED $full : $reason"
        $refused++
        continue
    }
    if ($null -eq (Get-ItemAttributes $full)) {
        Write-Output "ABSENT  $full"
        continue
    }
    Remove-Item -LiteralPath $full -Recurse -Force
    Write-Output "DELETED $full"
}
if ($refused) { exit 1 }
