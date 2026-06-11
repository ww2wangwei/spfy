param(
  [switch]$ForceRepair,
  [switch]$DiagnoseOnly
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
  Write-Host ""
  Write-Host "== $Message ==" -ForegroundColor Cyan
}

function Write-Result([string]$Name, $Value) {
  Write-Host ("{0}={1}" -f $Name, $Value)
}

function Test-File([string]$Path) {
  return (Test-Path -LiteralPath $Path)
}

function Copy-IfExists([string]$Path, [string]$DestinationDir) {
  if (Test-Path -LiteralPath $Path) {
    Copy-Item -LiteralPath $Path -Destination $DestinationDir -Force
  }
}

function Write-JsonNoBom([string]$Path, $Object) {
  $jsonText = $Object | ConvertTo-Json -Depth 20
  [System.IO.File]::WriteAllText($Path, $jsonText, [System.Text.UTF8Encoding]::new($false))
}

function Get-PluginVersion([string]$PluginDir) {
  $pluginJson = Join-Path $PluginDir ".codex-plugin\plugin.json"
  if (-not (Test-Path -LiteralPath $pluginJson)) {
    throw "Missing plugin.json: $pluginJson"
  }

  $json = Get-Content -LiteralPath $pluginJson -Raw | ConvertFrom-Json
  if (-not $json.version) {
    throw "Missing version in plugin.json: $pluginJson"
  }

  return [string]$json.version
}

function Reset-Latest([string]$LatestPath, [string]$TargetPath) {
  if (Test-Path -LiteralPath $LatestPath) {
    Remove-Item -LiteralPath $LatestPath -Recurse -Force
  }

  cmd /c mklink /J "`"$LatestPath`"" "`"$TargetPath`"" | Out-Null
  if (-not (Test-Path -LiteralPath $LatestPath)) {
    Copy-Item -LiteralPath $TargetPath -Destination $LatestPath -Recurse -Force
  }
}

function Assert-LatestTarget([string]$LatestPath) {
  $item = Get-Item -LiteralPath $LatestPath -Force -ErrorAction SilentlyContinue
  if (-not $item) {
    throw "latest missing: $LatestPath"
  }

  $actualTarget = $item.Target
  if (-not $actualTarget) {
    $scriptsDir = Join-Path $LatestPath "scripts"
    if (-not (Test-Path -LiteralPath $scriptsDir)) {
      throw "latest is a plain directory but is missing scripts: $LatestPath"
    }
    Write-Host "latest OK (plain dir): $LatestPath"
    return
  }

  if ($actualTarget -like "*\.tmp\bundled-marketplaces\*") {
    throw "latest still points to bundled .tmp: $actualTarget"
  }

  if ($actualTarget -like "*\chrome\latest*" -or $actualTarget -like "*\computer-use\latest*") {
    throw "latest points to itself or a recursive latest path: $actualTarget"
  }

  Write-Host "latest OK (junction -> $actualTarget): $LatestPath"
}

function Add-Or-EnablePluginBlock([string]$Text, [string]$PluginName) {
  $header = "[plugins.`"$PluginName`"]"
  $escapedHeader = [regex]::Escape($header)

  if ($Text -match "(?m)^$escapedHeader\s*$") {
    $pattern = "(?ms)(^$escapedHeader\s*\r?\n)(.*?)(?=^\[|\z)"
    return [regex]::Replace($Text, $pattern, {
      param($m)
      $body = $m.Groups[2].Value
      if ($body -match "(?m)^\s*enabled\s*=") {
        $body = [regex]::Replace($body, "(?m)^\s*enabled\s*=.*$", "enabled = true")
      } else {
        $body = "enabled = true`r`n" + $body
      }
      return $m.Groups[1].Value + $body
    }, 1)
  }

  $separator = if ($Text.EndsWith("`r`n") -or $Text.EndsWith("`n")) { "" } else { "`r`n" }
  return $Text + $separator + "`r`n$header`r`nenabled = true`r`n"
}

$CodexHome = Join-Path $env:USERPROFILE ".codex"
$BackupRoot = Join-Path $env:USERPROFILE "codex-plugin-backups"
$Desktop = [Environment]::GetFolderPath("Desktop")
$OpenAILocal = Join-Path $env:LOCALAPPDATA "OpenAI"
$CodexLocal = Join-Path $OpenAILocal "Codex"
$ExtensionManifest = Join-Path $OpenAILocal "extension\com.openai.codexextension.json"
$CodexNativeHosts = Join-Path $CodexHome "chrome-native-hosts.json"
$LocalNativeHosts = Join-Path $CodexLocal "chrome-native-hosts.json"
$BundledTmpRoot = Join-Path $CodexHome ".tmp\bundled-marketplaces\openai-bundled"
$BundledMarketplaceJson = Join-Path $BundledTmpRoot ".agents\plugins\marketplace.json"
$PluginCacheRoot = Join-Path $CodexHome "plugins\cache\openai-bundled"
$ChromeCacheRoot = Join-Path $PluginCacheRoot "chrome"
$ComputerUseCacheRoot = Join-Path $PluginCacheRoot "computer-use"
$ChromeLatest = Join-Path $ChromeCacheRoot "latest"
$ComputerUseLatest = Join-Path $ComputerUseCacheRoot "latest"

Write-Step "Path collection"
Write-Result "CodexHome" $CodexHome
Write-Result "BackupRoot" $BackupRoot
Write-Result "Desktop" $Desktop
Write-Result "BundledTmpRoot" $BundledTmpRoot
Write-Result "PluginCacheRoot" $PluginCacheRoot

Write-Step "Pre-repair backup"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupDir = Join-Path $BackupRoot "openai-bundled-lock-repair-$Stamp"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$FilesToBackup = @(
  (Join-Path $CodexHome "config.toml"),
  (Join-Path $CodexHome ".codex-global-state.json"),
  $CodexNativeHosts,
  $LocalNativeHosts,
  $ExtensionManifest
)

foreach ($file in $FilesToBackup) {
  Copy-IfExists $file $BackupDir
}

$StateFile = Join-Path $BackupDir "pre-repair-state.txt"
$BundledTmpListing = "missing"
if (Test-Path -LiteralPath $BundledTmpRoot) {
  $BundledTmpListing = Get-ChildItem -LiteralPath $BundledTmpRoot -Force -Recurse -ErrorAction SilentlyContinue |
    Select-Object -First 200 FullName,Length |
    Format-Table -AutoSize |
    Out-String
}
$ChromeCacheListing = "missing"
if (Test-Path -LiteralPath $ChromeCacheRoot) {
  $ChromeCacheListing = Get-ChildItem -LiteralPath $ChromeCacheRoot -Force -ErrorAction SilentlyContinue |
    Format-Table -AutoSize |
    Out-String
}
$ComputerUseCacheListing = "missing"
if (Test-Path -LiteralPath $ComputerUseCacheRoot) {
  $ComputerUseCacheListing = Get-ChildItem -LiteralPath $ComputerUseCacheRoot -Force -ErrorAction SilentlyContinue |
    Format-Table -AutoSize |
    Out-String
}
@(
  "BackupDir=$BackupDir",
  "CodexHome=$CodexHome",
  "BundledTmpRoot=$BundledTmpRoot",
  "PluginCacheRoot=$PluginCacheRoot",
  "",
  "Processes:",
  (Get-Process extension-host,codex-computer-use -ErrorAction SilentlyContinue | Format-Table -AutoSize | Out-String),
  "",
  "Bundled tmp listing:",
  $BundledTmpListing,
  "",
  "Chrome cache listing:",
  $ChromeCacheListing,
  "",
  "Computer Use cache listing:",
  $ComputerUseCacheListing
) | Set-Content -LiteralPath $StateFile -Encoding UTF8
Write-Result "BackupDir" $BackupDir

Write-Step "File diagnostics"
$DiagnosticChecks = [ordered]@{
  BundledMarketplaceJsonExists = (Test-File $BundledMarketplaceJson)
  BundledChromePluginJsonExists = (Test-File (Join-Path $BundledTmpRoot "plugins\chrome\.codex-plugin\plugin.json"))
  BundledChromeClientExists = (Test-File (Join-Path $BundledTmpRoot "plugins\chrome\scripts\browser-client.mjs"))
  BundledChromeHostExists = (Test-File (Join-Path $BundledTmpRoot "plugins\chrome\extension-host\windows\x64\extension-host.exe"))
  BundledComputerUsePluginJsonExists = (Test-File (Join-Path $BundledTmpRoot "plugins\computer-use\.codex-plugin\plugin.json"))
  BundledComputerUseClientExists = (Test-File (Join-Path $BundledTmpRoot "plugins\computer-use\scripts\computer-use-client.mjs"))
  ChromeLatestClientExists = (Test-File (Join-Path $ChromeLatest "scripts\browser-client.mjs"))
  ChromeLatestHostExists = (Test-File (Join-Path $ChromeLatest "extension-host\windows\x64\extension-host.exe"))
  ComputerUseLatestClientExists = (Test-File (Join-Path $ComputerUseLatest "scripts\computer-use-client.mjs"))
  ComputerUseLatestExeExists = (Test-File (Join-Path $ComputerUseLatest "node_modules\@oai\sky\bin\windows\codex-computer-use.exe"))
}

foreach ($entry in $DiagnosticChecks.GetEnumerator()) {
  Write-Result $entry.Key $entry.Value
}

Write-Step "Latest targets"
foreach ($latest in @($ChromeLatest, $ComputerUseLatest)) {
  $item = Get-Item -LiteralPath $latest -Force -ErrorAction SilentlyContinue
  if ($item) {
    Write-Host "Path=$latest"
    Write-Host "Target=$($item.Target)"
    Write-Host "FullName=$($item.FullName)"
  } else {
    Write-Host "Path=$latest missing"
  }
}

Write-Step "Recent log evidence"
$EvidenceFile = Join-Path $BackupDir "log-evidence.txt"
$LogRoots = @(
  (Join-Path $env:LOCALAPPDATA "Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\Codex\Logs"),
  (Join-Path $CodexHome "sessions")
)
$Patterns = @(
  "EBUSY",
  "resource busy or locked",
  "plugin_cache_windows_file_lock",
  "failed to back up plugin cache entry",
  "failed to remove existing plugin cache entry",
  "os error 5",
  "marketplace\.json.*does not exist",
  "extension-host\\windows\\x64",
  "Windows Computer Use helper paths are unavailable",
  "os error 740"
) -join "|"
$LogMatches = @()
foreach ($root in $LogRoots) {
  if (Test-Path -LiteralPath $root) {
    $matches = Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 80 |
      Select-String -Pattern $Patterns -AllMatches -ErrorAction SilentlyContinue |
      Select-Object -First 80 Path,LineNumber,Line
    $LogMatches += $matches
  }
}
$LogMatches | Format-List | Out-String | Set-Content -LiteralPath $EvidenceFile -Encoding UTF8
Get-Content -LiteralPath $EvidenceFile | Select-Object -First 120

$HasLockEvidence = $false
$HasElevationEvidence = $false
$LockEvidencePatterns = @(
  "EBUSY",
  "resource busy or locked",
  "plugin_cache_windows_file_lock",
  "failed to back up plugin cache entry",
  "failed to remove existing plugin cache entry",
  "os error 5",
  "marketplace\.json.*does not exist",
  "extension-host\\windows\\x64",
  "Windows Computer Use helper paths are unavailable"
)
$ElevationEvidencePatterns = @(
  "os error 740"
)
foreach ($match in $LogMatches) {
  foreach ($pattern in $LockEvidencePatterns) {
    if ($match.Line -match $pattern) {
      $HasLockEvidence = $true
      break
    }
  }
  foreach ($pattern in $ElevationEvidencePatterns) {
    if ($match.Line -match $pattern) {
      $HasElevationEvidence = $true
      break
    }
  }
}

$MissingBundled = -not $DiagnosticChecks.BundledMarketplaceJsonExists -or
  -not $DiagnosticChecks.BundledChromePluginJsonExists -or
  -not $DiagnosticChecks.BundledComputerUsePluginJsonExists
$MissingCache = -not $DiagnosticChecks.ChromeLatestClientExists -or
  -not $DiagnosticChecks.ChromeLatestHostExists -or
  -not $DiagnosticChecks.ComputerUseLatestClientExists -or
  -not $DiagnosticChecks.ComputerUseLatestExeExists
$ChromeLatestItem = Get-Item -LiteralPath $ChromeLatest -Force -ErrorAction SilentlyContinue
$ComputerUseLatestItem = Get-Item -LiteralPath $ComputerUseLatest -Force -ErrorAction SilentlyContinue
$LatestPointsToTmp = (($ChromeLatestItem -and $ChromeLatestItem.Target -like "*\.tmp\bundled-marketplaces\*") -or
  ($ComputerUseLatestItem -and $ComputerUseLatestItem.Target -like "*\.tmp\bundled-marketplaces\*"))

Write-Step "Diagnosis summary"
Write-Result "HasLockEvidence" $HasLockEvidence
Write-Result "HasElevationEvidence" $HasElevationEvidence
Write-Result "MissingBundledMarketplaceOrPlugin" $MissingBundled
Write-Result "MissingCacheKeyFiles" $MissingCache
Write-Result "LatestPointsToTmp" $LatestPointsToTmp

if ($HasElevationEvidence -and -not $ForceRepair) {
  throw "Found os error 740 / elevation evidence. Stop here and investigate Windows sandbox permissions separately."
}

if ($DiagnoseOnly) {
  Write-Host "DiagnoseOnly was set. No repair performed."
  exit 0
}

$LooksLikeBundledLockDamage = $HasLockEvidence -or $MissingBundled -or $MissingCache -or $LatestPointsToTmp
if (-not $LooksLikeBundledLockDamage -and -not $ForceRepair) {
  Write-Host "This does not clearly look like bundled plugin lock/cache damage. Use -ForceRepair only if you intentionally want to rebuild the bundled cache."
  exit 0
}

if (-not $ForceRepair) {
  Write-Host ""
  Write-Host "Close Chrome before continuing. Codex Desktop can remain open, but restarting it after repair is recommended." -ForegroundColor Yellow
  $answer = Read-Host "Proceed with bundled plugin cache repair? Type YES to continue"
  if ($answer -ne "YES") {
    Write-Host "Repair cancelled. Backup is still available at: $BackupDir"
    exit 0
  }
}

Write-Step "Stop helper processes"
Get-Process extension-host -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process codex-computer-use -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

Write-Step "Find bundled source in WindowsApps"
$BundledSource = $null
$WindowsAppsRoot = Join-Path $env:ProgramFiles "WindowsApps"
$PackageRoots = @(Get-ChildItem -LiteralPath $WindowsAppsRoot -Directory -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like "OpenAI.Codex_*_x64__2p2nqsd0c76g0" } |
  Sort-Object LastWriteTime -Descending)

foreach ($pkg in $PackageRoots) {
  $candidate = Join-Path $pkg.FullName "app\resources\plugins\openai-bundled"
  if (Test-Path -LiteralPath (Join-Path $candidate ".agents\plugins\marketplace.json")) {
    $BundledSource = $candidate
    break
  }
}

if (-not $BundledSource) {
  $marketplace = Get-ChildItem -LiteralPath $WindowsAppsRoot -Recurse -File -Filter "marketplace.json" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -like "*\OpenAI.Codex_*_x64__2p2nqsd0c76g0\app\resources\plugins\openai-bundled\.agents\plugins\marketplace.json" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if ($marketplace) {
    $BundledSource = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $marketplace.FullName))
  }
}

if (-not $BundledSource) {
  throw "Cannot find Codex bundled source under WindowsApps. Confirm Codex Desktop is installed and WindowsApps is readable."
}

Write-Result "BundledSource" $BundledSource
foreach ($required in @(
  (Join-Path $BundledSource ".agents\plugins\marketplace.json"),
  (Join-Path $BundledSource "plugins\chrome\.codex-plugin\plugin.json"),
  (Join-Path $BundledSource "plugins\computer-use\.codex-plugin\plugin.json")
)) {
  if (-not (Test-Path -LiteralPath $required)) {
    throw "Bundled source is incomplete: $required"
  }
}

$ChromeVersion = Get-PluginVersion (Join-Path $BundledSource "plugins\chrome")
$ComputerUseVersion = Get-PluginVersion (Join-Path $BundledSource "plugins\computer-use")
Write-Result "ChromeVersion" $ChromeVersion
Write-Result "ComputerUseVersion" $ComputerUseVersion

Write-Step "Rebuild bundled marketplace tmp"
Get-Process extension-host -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process codex-computer-use -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

if (Test-Path -LiteralPath $BundledTmpRoot) {
  Remove-Item -LiteralPath $BundledTmpRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $BundledTmpRoot) | Out-Null
Copy-Item -LiteralPath $BundledSource -Destination $BundledTmpRoot -Recurse -Force

Get-Content -LiteralPath $BundledMarketplaceJson -Raw | ConvertFrom-Json | Out-Null
foreach ($required in @(
  (Join-Path $BundledTmpRoot "plugins\chrome\scripts\browser-client.mjs"),
  (Join-Path $BundledTmpRoot "plugins\chrome\extension-host\windows\x64\extension-host.exe"),
  (Join-Path $BundledTmpRoot "plugins\computer-use\scripts\computer-use-client.mjs")
)) {
  if (-not (Test-Path -LiteralPath $required)) {
    throw "Bundled tmp rebuild is missing key file: $required"
  }
}

Write-Step "Rebuild plugin cache"
$ChromeSource = Join-Path $BundledSource "plugins\chrome"
$ComputerUseSource = Join-Path $BundledSource "plugins\computer-use"
$ChromeVersionDir = Join-Path $ChromeCacheRoot $ChromeVersion
$ComputerUseVersionDir = Join-Path $ComputerUseCacheRoot $ComputerUseVersion

New-Item -ItemType Directory -Force -Path $ChromeCacheRoot | Out-Null
New-Item -ItemType Directory -Force -Path $ComputerUseCacheRoot | Out-Null

if (Test-Path -LiteralPath $ChromeVersionDir) {
  Remove-Item -LiteralPath $ChromeVersionDir -Recurse -Force
}
if (Test-Path -LiteralPath $ComputerUseVersionDir) {
  Remove-Item -LiteralPath $ComputerUseVersionDir -Recurse -Force
}

Copy-Item -LiteralPath $ChromeSource -Destination $ChromeVersionDir -Recurse -Force
Copy-Item -LiteralPath $ComputerUseSource -Destination $ComputerUseVersionDir -Recurse -Force

Reset-Latest (Join-Path $ChromeCacheRoot "latest") $ChromeVersionDir
Reset-Latest (Join-Path $ComputerUseCacheRoot "latest") $ComputerUseVersionDir
Assert-LatestTarget (Join-Path $ChromeCacheRoot "latest")
Assert-LatestTarget (Join-Path $ComputerUseCacheRoot "latest")

$RequiredFiles = @(
  (Join-Path $ChromeVersionDir ".codex-plugin\plugin.json"),
  (Join-Path $ChromeVersionDir "scripts\browser-client.mjs"),
  (Join-Path $ChromeVersionDir "extension-host\windows\x64\extension-host.exe"),
  (Join-Path $ChromeVersionDir "assets\google-chrome.png"),
  (Join-Path $ComputerUseVersionDir ".codex-plugin\plugin.json"),
  (Join-Path $ComputerUseVersionDir "scripts\computer-use-client.mjs"),
  (Join-Path $ComputerUseVersionDir "node_modules\@oai\sky\bin\windows\codex-computer-use.exe"),
  (Join-Path $ComputerUseVersionDir "assets\app-icon.png")
)
$Missing = $RequiredFiles | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($Missing.Count -gt 0) {
  throw "Repair still has missing key files:`n$($Missing -join "`n")"
}

Write-Step "Repair Chrome native host JSON"
$ExtensionHostExe = Join-Path $ChromeVersionDir "extension-host\windows\x64\extension-host.exe"
if (-not (Test-Path -LiteralPath $ExtensionHostExe)) {
  throw "Cannot find extension-host.exe: $ExtensionHostExe"
}

foreach ($jsonPath in @($ExtensionManifest, $CodexNativeHosts, $LocalNativeHosts)) {
  if (-not (Test-Path -LiteralPath $jsonPath)) {
    continue
  }

  $obj = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
  if ($obj.path -and (($obj.path -like "*\chrome\latest\*") -or ($obj.path -like "*\.tmp\bundled-marketplaces\*"))) {
    $obj.path = $ExtensionHostExe
  }
  Write-JsonNoBom $jsonPath $obj
}

Write-Step "Ensure bundled plugins enabled in config.toml"
$ConfigToml = Join-Path $CodexHome "config.toml"
if (Test-Path -LiteralPath $ConfigToml) {
  $configText = Get-Content -LiteralPath $ConfigToml -Raw
  $configText = Add-Or-EnablePluginBlock $configText "chrome@openai-bundled"
  $configText = Add-Or-EnablePluginBlock $configText "computer-use@openai-bundled"
  $configText = Add-Or-EnablePluginBlock $configText "browser@openai-bundled"
  [System.IO.File]::WriteAllText($ConfigToml, $configText, [System.Text.UTF8Encoding]::new($false))
} else {
  @(
    '[plugins."chrome@openai-bundled"]',
    'enabled = true',
    '',
    '[plugins."computer-use@openai-bundled"]',
    'enabled = true',
    '',
    '[plugins."browser@openai-bundled"]',
    'enabled = true',
    ''
  ) | Set-Content -LiteralPath $ConfigToml -Encoding utf8
}

Write-Step "Final verification"
Get-Content -LiteralPath $BundledMarketplaceJson -Raw | ConvertFrom-Json | Out-Null

$FinalRequiredFiles = @(
  (Join-Path $BundledTmpRoot "plugins\chrome\assets\google-chrome.png"),
  (Join-Path $BundledTmpRoot "plugins\computer-use\assets\app-icon.png"),
  (Join-Path $ChromeCacheRoot "latest\scripts\browser-client.mjs"),
  (Join-Path $ChromeCacheRoot "latest\extension-host\windows\x64\extension-host.exe"),
  (Join-Path $ComputerUseCacheRoot "latest\scripts\computer-use-client.mjs"),
  (Join-Path $ComputerUseCacheRoot "latest\node_modules\@oai\sky\bin\windows\codex-computer-use.exe")
)
foreach ($file in $FinalRequiredFiles) {
  if (-not (Test-Path -LiteralPath $file)) {
    throw "Final verification missing: $file"
  }
  Write-Host "OK: $file"
}

foreach ($jsonPath in @($ExtensionManifest, $CodexNativeHosts, $LocalNativeHosts)) {
  if (-not (Test-Path -LiteralPath $jsonPath)) {
    continue
  }

  $content = Get-Content -LiteralPath $jsonPath -Raw
  if ($content -match [regex]::Escape("\chrome\latest\") -or $content -match [regex]::Escape("\.tmp\bundled-marketplaces\")) {
    throw "Native host JSON still points to an unstable path: $jsonPath"
  }

  $content | ConvertFrom-Json | Out-Null
  Write-Host "NativeHost JSON OK: $jsonPath"
}

Write-Step "Optional Codex CLI plugin state"
try {
  codex plugin marketplace list
} catch {
  Write-Host "codex plugin marketplace list failed: $($_.Exception.Message)"
}
try {
  codex plugin list
} catch {
  Write-Host "codex plugin list failed: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Repair completed. Backup directory: $BackupDir" -ForegroundColor Green
Write-Host "Restart Codex Desktop, then verify Chrome and Computer Use in the plugins/settings UI."
