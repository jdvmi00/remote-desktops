# Keep a virtual display's size list in step with a stream size, then ask the
# driver to reload so the size can be applied. Used by Remote Desktops over SSH
# (variables set in a preamble) or as a Sunshine prep command on the host
# (sizes from SUNSHINE_CLIENT_WIDTH/HEIGHT). Never changes the active mode:
# Sunshine's dd_resolution_option = auto does that and reverts it.
$ErrorActionPreference = 'Stop'
if (-not $Settings) { $Settings = 'C:\VirtualDisplayDriver\vdd_settings.xml' }
if (-not $Width) { $Width = [int]$env:SUNSHINE_CLIENT_WIDTH; $Height = [int]$env:SUNSHINE_CLIENT_HEIGHT }
if ($null -eq $Refresh) { $Refresh = 60 }
if (-not $Pipe) { $Pipe = 'MTTVirtualDisplayPipe' }
$lock = $null
try {
  $Width = [int]$Width; $Height = [int]$Height; $Refresh = [int]$Refresh
  if ($Width -lt 240 -or $Width -gt 16384 -or $Height -lt 240 -or $Height -gt 16384) { throw 'invalid stream size' }
  if (-not (Test-Path -LiteralPath $Settings)) { throw "virtual-display-settings-missing: $Settings" }
  if ($Refresh -lt 20 -or $Refresh -gt 240) { throw 'invalid refresh rate' }
  # Serialize settings and pending reload ownership, including retries.
  $lock = [IO.File]::Open("$Settings.remote-desktops.lock", [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
  $pending = "$Settings.remote-desktops.reload-pending"
  $xml = New-Object System.Xml.XmlDocument
  $xml.PreserveWhitespace = $true
  $xml.Load($Settings)
  $list = $xml.SelectSingleNode('/vdd_settings/resolutions')
  if ($null -eq $list) { throw 'virtual-display-settings-invalid: no resolutions element' }
  $entries = @($list.SelectNodes('resolution'))
  $present = @($entries | Where-Object { [int]$_.width -eq $Width -and [int]$_.height -eq $Height -and @($_.refresh_rate | Where-Object { [double]$_ -eq $Refresh }).Count -gt 0 })
  $changed = $false; $reloaded = $false
  if ($present.Count -eq 0) {
    $backup = "$Settings.remote-desktops.bak"
    if (-not (Test-Path -LiteralPath $backup)) { Copy-Item -LiteralPath $Settings -Destination $backup }
    $node = $xml.CreateElement('resolution')
    foreach ($pair in @(@('width', $Width), @('height', $Height), @('refresh_rate', $Refresh))) {
      $child = $xml.CreateElement($pair[0]); $child.InnerText = [string]$pair[1]; [void]$node.AppendChild($child)
    }
    [void]$list.AppendChild($xml.CreateWhitespace("`n    "))
    [void]$list.AppendChild($node)
    # Preserve every existing user/driver mode; we do not own those entries.
    $tmp = "$Settings.tmp"
    $xml.Save($tmp)
    # Persist retry intent before the settings change can become visible.
    $intent = [IO.File]::Open($pending, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
      $bytes = [Text.Encoding]::ASCII.GetBytes('reload required')
      $intent.Write($bytes, 0, $bytes.Length); $intent.Flush($true)
    } finally { $intent.Dispose() }
    Move-Item -LiteralPath $tmp -Destination $Settings -Force
    $changed = $true
  }
  # Retry failed reloads even when the tuple is already in the XML. Exact
  # unchanged modes without pending work do not disrupt the driver.
  if (Test-Path -LiteralPath $pending) {
    $stream = $null
    try {
      $stream = New-Object System.IO.Pipes.NamedPipeClientStream('.', $Pipe, [System.IO.Pipes.PipeDirection]::Out)
      $stream.Connect(3000)
      $bytes = [System.Text.Encoding]::ASCII.GetBytes('RELOAD_DRIVER')
      $stream.Write($bytes, 0, $bytes.Length); $stream.Flush()
      $reloaded = $true
      Remove-Item -LiteralPath $pending
    } catch { throw 'virtual-display-reload-failed: settings saved; retry when the driver pipe is available' }
    finally { if ($null -ne $stream) { $stream.Dispose() } }
  }
  $modes = @($list.SelectNodes('resolution') | ForEach-Object { "$($_.width)x$($_.height)" })
  @{ok=$true;result=@{changed=$changed;reloaded=$reloaded;modes=$modes;settings=$Settings}} | ConvertTo-Json -Compress -Depth 5
} catch {
  @{ok=$false;error=$_.Exception.Message} | ConvertTo-Json -Compress
  if ($env:SUNSHINE_CLIENT_WIDTH) { exit 1 }
} finally { if ($null -ne $lock) { $lock.Dispose() } }
