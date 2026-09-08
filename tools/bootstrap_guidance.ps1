<#
  One command puts a machine on the loop.

  Three things have to exist on every machine for a session to consult the
  board and file what it learns, and none of them travels with a repo or
  an account: the standing order in ~/.claude/CLAUDE.md, the pm-guidance
  bridge registered at user scope with the board's key, and the hooks in
  ~/.claude/settings.json that inject the rules at session start and
  refuse to let a session stop with an unfiled lesson. On 2026-09-04 a
  laptop had none of them, and nothing said so. This puts all three in
  place, and is safe to run again: the order is overwritten with the repo
  copy, the registration is replaced, and the hooks replace their own
  entries and touch nothing else.

  From the repo root:

      .\tools\bootstrap_guidance.ps1 -Key <PM_GUIDANCE_KEY>

  The key is GUIDANCE_API_KEY on the Built-By-Bean-Website Railway service.
#>
param([Parameter(Mandatory = $true)][string]$Key)

$repo = Split-Path -Parent $PSScriptRoot
$bridge = Join-Path $repo "tools\pm_guidance_mcp.py"
$order = Join-Path $repo "tools\STANDING_ORDER.md"
$installer = Join-Path $repo "tools\hooks\install.py"
$target = Join-Path $HOME ".claude\CLAUDE.md"

foreach ($f in @($bridge, $order, $installer)) {
    if (-not (Test-Path $f)) { throw "missing: $f" }
}

New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
Copy-Item $order $target -Force
Write-Host "standing order  -> $target"

# Replace rather than add beside: two registrations under one name is the
# kind of thing that works until the wrong one answers.
#
# Look for the CLI BEFORE removing anything, and report what actually
# happened rather than what was attempted. On 2026-09-07 this was run from
# inside a Claude Code session, where `claude` is not on PATH: both
# commands failed with CommandNotFoundException and the script still
# printed "registered at user scope". Nothing was lost that time only
# because the remove failed too - on a machine where the CLI exists and
# the add fails for any other reason, a remove-then-claim leaves the
# machine with NO bridge and a bootstrap that says it has one. That is
# strictly worse than either half, and the session that follows would
# discover it three files in.
$bridgeOk = $false
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "bridge          -> could not re-register: the 'claude' CLI is not on PATH."
    Write-Host "                   Nothing was removed - any existing registration stands."
    Write-Host "                   To refresh it, re-run from a terminal where 'claude'"
    Write-Host "                   resolves, not from inside a Claude Code session."
} else {
    claude mcp remove pm-guidance -s user 2>$null | Out-Null
    claude mcp add --scope user pm-guidance -e "PM_GUIDANCE_KEY=$Key" -- python $bridge
    if ($LASTEXITCODE -ne 0) {
        Write-Host "bridge          -> FAILED: 'claude mcp add' exited $LASTEXITCODE."
        Write-Host "                   The previous registration was removed first, so this"
        Write-Host "                   machine may now have none - the next line says which."
    }
}

# Ask the file, not the command. A registration that is not in
# ~/.claude.json is not a registration, whatever exit code was returned.
$configPath = Join-Path $HOME ".claude.json"
if (Test-Path $configPath) {
    try {
        $entry = (Get-Content $configPath -Raw | ConvertFrom-Json).mcpServers.'pm-guidance'
        if ($entry -and $entry.env.PM_GUIDANCE_KEY) { $bridgeOk = $true }
    } catch { }
}
if ($bridgeOk) {
    Write-Host "bridge          -> registered at user scope, key present ($bridge)"
} else {
    Write-Host "bridge          -> ABSENT from $configPath - the tools will not be in a session."
}

python $installer
if ($LASTEXITCODE -ne 0) { throw "the hook installer exited $LASTEXITCODE" }
Write-Host "hooks           -> ~/.claude/settings.json"

Write-Host ""
if ($bridgeOk) {
    Write-Host "Done. Start a fresh Claude session; it opens with the house rules in it."
} else {
    Write-Host "PARTLY DONE - the standing order and hooks are in place, but WITHOUT the"
    Write-Host "bridge a session cannot reach the board, consult a playbook or file a"
    Write-Host "lesson. Register it before relying on this machine."
    exit 1
}
