# Native PowerShell algorithm tests: only temporary XML and a synthetic named pipe.
$folder=Join-Path ([IO.Path]::GetTempPath()) ('remote-desktops-modes-'+[guid]::NewGuid().ToString('N'))
$null=New-Item -ItemType Directory -Path $folder
$Settings=Join-Path $folder 'settings.xml'
$Pipe='remote-desktops-test-'+[guid]::NewGuid().ToString('N')
$Width=1920;$Height=1080;$Refresh=120
$script=Join-Path $PSScriptRoot 'VirtualDisplayModes.ps1'
function Invoke-TestSync([bool]$Listening) {
 $server=$null
 try {
  if ($Listening) {
   $server=[IO.Pipes.NamedPipeServerStream]::new($Pipe,[IO.Pipes.PipeDirection]::In,1,[IO.Pipes.PipeTransmissionMode]::Byte,[IO.Pipes.PipeOptions]::Asynchronous)
   $waiting=$server.BeginWaitForConnection($null,$null)
  }
  $result=(& $script | ConvertFrom-Json)
  if ($Listening -and $result.ok) {
   if (-not $waiting.AsyncWaitHandle.WaitOne(5000)) {throw 'Test pipe was not contacted'}
   $server.EndWaitForConnection($waiting)
   $buffer=New-Object byte[] 13
   $read=$server.Read($buffer,0,$buffer.Length)
   if ([Text.Encoding]::ASCII.GetString($buffer,0,$read) -ne 'RELOAD_DRIVER') {throw 'Unexpected reload command'}
  }
  return $result
 } finally {if ($null -ne $server) {$server.Dispose()}}
}
try {
 $entries=1..10 | ForEach-Object {"<resolution><width>$(1000+$_)</width><height>900</height><refresh_rate>60</refresh_rate></resolution>"}
 $entries += '<resolution><width>1920</width><height>1080</height><refresh_rate>60</refresh_rate></resolution>'
 [IO.File]::WriteAllText($Settings,('<vdd_settings><resolutions>'+($entries -join '')+'</resolutions></vdd_settings>'))
 $failed=Invoke-TestSync $false
 if ($failed.ok -or $failed.error -notlike 'virtual-display-reload-failed:*') {throw 'Reload failure was not reported'}
 [xml]$xml=Get-Content $Settings -Raw
 if ($xml.vdd_settings.resolutions.resolution.Count -ne 12) {throw 'Existing modes were lost or refresh was ignored'}
 foreach($old in $entries) {if ($xml.OuterXml -notlike ('*'+$old+'*')) {throw 'Existing mode changed'}}
 $before=[IO.File]::ReadAllText($Settings)
 $retry=Invoke-TestSync $true
 if (-not $retry.ok -or $retry.result.changed -or -not $retry.result.reloaded) {throw 'Pending reload was not retried'}
 if ([IO.File]::ReadAllText($Settings) -cne $before) {throw 'Retry rewrote unchanged XML'}
 $duplicate=Invoke-TestSync $false
 if (-not $duplicate.ok -or $duplicate.result.changed -or $duplicate.result.reloaded) {throw 'Exact duplicate must not reload'}
 foreach ($Refresh in @(0,19,241,300)) {
  $invalid=Invoke-TestSync $false
  if ($invalid.ok -or $invalid.error -ne 'invalid refresh rate') {throw 'Invalid refresh was accepted'}
 }
} finally {Remove-Item -LiteralPath $folder -Recurse -Force}
