"""Read-only, launch-scoped Sunshine evidence for optional Windows display matching.

The XML mode list is configuration, not proof of the driver's active modes.
Only fresh Sunshine capture observations can establish a host resolution.
"""
import json
import re
import time
from . import windows_display


def output_id(value):
    candidate = value[1:-1] if isinstance(value, str) and value.startswith('{') and value.endswith('}') else value
    if not isinstance(candidate, str) or not windows_display.GUID.fullmatch(candidate):
        raise ValueError('display-selection-required: inspect the PC and select its Sunshine capture display')
    return '{' + candidate.lower() + '}'


def snapshot(host, cursor=None):
    alias = host.computer.get('ssh', {}).get('alias')
    if not alias:
        raise ValueError('display-verification-required: host matching needs read-only SSH verification; use existing host display for a connection without SSH')
    identity = host.computer.get('pairing_uuid', '')
    if not windows_display.GUID.fullmatch(identity):
        raise ValueError('invalid Sunshine UUID')
    expected = output_id(host.display.get('output'))
    offset = cursor['offset'] if cursor else -1
    if type(offset) is not int or offset < -1:
        raise ValueError('invalid display observation cursor')
    script = r'''$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
try {
 $root=Join-Path $env:ProgramFiles 'Sunshine\config'
 $state=Get-Content (Join-Path $root 'sunshine_state.json') -Raw | ConvertFrom-Json
 if ($state.root.uniqueid -ine '__UUID__') {throw 'host-identity-mismatch'}
 $conf=[IO.File]::ReadAllText((Join-Path $root 'sunshine.conf'))
 $options=@{}
 foreach ($key in @('output_name','dd_configuration_option','dd_resolution_option')) {
  $m=[regex]::Matches($conf,('(?m)^'+$key+'\s*=\s*([^\r\n]+)'))
  if ($m.Count -ne 1) {throw ('display-configuration-required: set '+$key+' explicitly in Sunshine')}
  $options[$key]=$m[0].Groups[1].Value.Trim()
 }
 $path=Join-Path $root 'sunshine.log'; $file=Get-Item -LiteralPath $path
 $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
 try {
  $length=$stream.Length; $text=''; $offset=__OFFSET__
  if ($offset -ge 0) {
   if ($length -lt $offset -or $length-$offset -gt 131072) {throw 'display-verification-lost: Sunshine log changed; reconnect to verify'}
   [void]$stream.Seek($offset,[IO.SeekOrigin]::Begin)
   $reader=[IO.StreamReader]::new($stream); $buffer=New-Object char[] 65537
   $read=$reader.ReadBlock($buffer,0,$buffer.Length)
   if ($read -gt 65536) {throw 'display-verification-lost: too much Sunshine log output; reconnect to verify'}
   $text=[string]::new($buffer,0,$read)
  }
 } finally {$stream.Dispose()}
 @{ok=$true;options=$options;offset=$length;created=$file.CreationTimeUtc.Ticks.ToString();text=$text} | ConvertTo-Json -Compress
} catch {@{ok=$false;error=$_.Exception.Message} | ConvertTo-Json -Compress}
'''.replace('__UUID__', identity).replace('__OFFSET__', str(offset))
    reply = windows_display.powershell(alias, script, timeout=20)
    if not reply.get('ok'):
        raise ValueError(reply.get('error', 'display verification failed'))
    # Keep the same bound at the helper boundary, including malformed replies.
    # The cursor deliberately remains launch-scoped until an incremental parser
    # can retain identity and revoke stale capture evidence across chunks.
    end = reply.get('offset')
    text = reply.get('text', '')
    if (type(end) is not int or end < 0 or not isinstance(text, str)
            or len(text) > 65536
            or (cursor and (end < offset or end - offset > 131072))):
        raise ValueError('display-verification-lost: Sunshine log exceeded the observation bound or changed; reconnect to verify')
    options = reply['options']
    if output_id(options.get('output_name')) != expected:
        raise ValueError('capture-display-changed: Sunshine no longer selects the configured display')
    if options.get('dd_resolution_option') != 'auto' or options.get('dd_configuration_option') not in ('verify_only', 'ensure_active', 'ensure_primary', 'ensure_only_display'):
        raise ValueError('display-configuration-required: enable Sunshine display configuration and automatic resolution switching')
    if cursor and reply.get('created') != cursor.get('created'):
        raise ValueError('display-verification-lost: Sunshine log rotated; reconnect to verify')
    return reply


def begin(record, host, persist):
    observed = snapshot(host)
    record['display_observation'] = {'offset': observed['offset'], 'created': observed['created'], 'started': time.time()}
    record.setdefault('resolved', {})['host_display'] = {'verified': False}
    persist()


def health(record, host):
    resolved = record.setdefault('resolved', {})
    resolved['host_display'] = {'verified': False}
    cursor = record.get('display_observation')
    if not cursor:
        raise ValueError('display-verification-required: reconnect to verify the selected host display')
    observed = snapshot(host, cursor)
    text = observed.get('text', '')
    # Never accept Sunshine's fallback capture after a selected-display failure.
    if re.search(r'(?im)^.*(?:Error:|Warning:).*(?:not available in the system|display|resolution|topology)', text):
        raise ValueError('capture-display-unavailable: Sunshine could not use the selected display; check it on the host')
    expected = output_id(host.display.get('output'))
    # Scope evidence to the latest launch, never a previous request in the log.
    parts = text.rsplit('Using the following configuration:', 1)
    launch = None
    capture = ''
    if len(parts) == 2:
        try:
            body = parts[1].lstrip()
            launch, end = json.JSONDecoder().raw_decode(body)
            capture = body[end:]
        except (ValueError, TypeError):
            pass  # A partial log write is not evidence.
    if launch is not None:
        if not isinstance(launch, dict) or output_id(launch.get('device_id')) != expected:
            raise ValueError('capture-display-changed: Sunshine selected a different display')
        requested = launch.get('resolution') or {}
        if not isinstance(requested, dict) or f'{requested.get("width")}x{requested.get("height")}' != record.get('stream_resolution'):
            raise ValueError('display-request-mismatch: Sunshine did not request this stream resolution')
    sizes = re.findall(r'Desktop resolution \[(\d{3,5})x(\d{3,5})\]', capture)
    if launch is None or not sizes:
        if time.time() - cursor['started'] > 30:
            raise ValueError('display-unverified: Sunshine did not confirm the selected capture display and resolution')
        return {'reconnect': False}
    width, height = map(int, sizes[-1])
    size = f'{width}x{height}'
    if size != record.get('stream_resolution'):
        raise ValueError(f'display-resolution-mismatch: requested {record.get("stream_resolution")}, host captured {size}')
    resolved['host_display'] = {'verified': True, 'resolution': size, 'output': expected, 'checked_at': int(time.time())}
    return {'reconnect': False}
