# Links the required agent skills into .claude/skills as directory junctions.
# Sources are the owner's vendored clones in agent-homebase; pinned commits are in
# docs/adr/0002-agent-skills.md. Junctions are machine-local and git-ignored.
param(
    [string]$Vendor = "E:\Workspace\agent-homebase\vendor"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root ".claude\skills"
New-Item -ItemType Directory -Force $target | Out-Null

$links = @{}

Get-ChildItem (Join-Path $Vendor "cursor-plugins\pstack\skills") -Directory | ForEach-Object {
    $links[$_.Name] = $_.FullName
}
$links["impeccable"] = Join-Path $Vendor "impeccable\.claude\skills\impeccable"
foreach ($name in @(
        "animation-vocabulary", "find-animation-opportunities", "improve-animations",
        "apple-design")) {
    $links[$name] = Join-Path $Vendor "emilkowalski-skills\skills\$name"
}
# Newer than the vendored clone; pinned copy lives in the repo.
$links["animation-performance"] = Join-Path $root ".claude\vendor\emil-animation-performance"

foreach ($name in $links.Keys) {
    $source = $links[$name]
    if (-not (Test-Path $source)) { throw "missing skill source: $source" }
    $link = Join-Path $target $name
    if (Test-Path $link) { continue }
    New-Item -ItemType Junction -Path $link -Target $source | Out-Null
    Write-Output "linked $name"
}
Write-Output "skills in .claude/skills: $((Get-ChildItem $target -Directory).Count)"
