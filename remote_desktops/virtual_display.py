"""A Windows virtual display that follows the stream size.

Sunshine's display-device option (`dd_resolution_option = auto`) switches
the captured display to the size the client asks for and reverts it after the
session. Driver-specific mode synchronization is optional. Read-only SSH
verification checks fresh Sunshine capture evidence; basic streaming with the
external adapter does not require SSH.
"""
from pathlib import Path
import re
from . import windows_display

SETTINGS = r"C:\VirtualDisplayDriver\vdd_settings.xml"
PATH = re.compile(r"[A-Za-z]:\\[^\r\n\"'`$]{1,240}\Z")
RESOLUTION = re.compile(r"(\d{3,5})x(\d{3,5})\Z")


def settings_path(display):
    path = display.get("settings") or SETTINGS
    if not PATH.fullmatch(path):
        raise ValueError("invalid virtual display settings path")
    return path


def script(width, height, settings, refresh=60):
    preamble = "$Width=%d; $Height=%d; $Refresh=%d; $Settings='%s'\n" % (width, height, refresh, settings.replace("'", "''"))
    return preamble + Path(__file__).with_name("windows").joinpath("VirtualDisplayModes.ps1").read_text()


def sync(alias, resolution, settings=SETTINGS, refresh=60):
    """Make sure the virtual display offers `resolution`; returns the driver's size list."""
    m = RESOLUTION.fullmatch(resolution or "")
    if not m:
        raise ValueError("resolution must be WIDTHxHEIGHT")
    reply = windows_display.powershell(alias, script(int(m[1]), int(m[2]), settings, refresh), timeout=45)
    if not reply.get("ok"):
        raise ValueError(reply.get("error", "virtual display update failed"))
    result = reply["result"]
    if resolution not in (result.get("modes") or []):
        raise ValueError("virtual-display-mode-missing: the driver did not accept " + resolution)
    return result


def inspect(alias, pairing_uuid, settings=SETTINGS):
    """Read-only: the driver's size list and Sunshine's display-device options."""
    if not windows_display.GUID.fullmatch(pairing_uuid or ""):
        raise ValueError("invalid Sunshine UUID")
    body = r'''$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
try {
 $sunshineRoot=Join-Path $env:ProgramFiles 'Sunshine\config'
 $state=Get-Content (Join-Path $sunshineRoot 'sunshine_state.json') -Raw | ConvertFrom-Json
 if ($state.root.uniqueid -ine '__UUID__') {throw 'host-identity-mismatch: SSH host is not the paired Sunshine computer'}
 $conf=[IO.File]::ReadAllText((Join-Path $sunshineRoot 'sunshine.conf'))
 $option=[regex]::Match($conf,'(?m)^dd_resolution_option\s*=\s*([^\r\n]+)')
 $output=[regex]::Match($conf,'(?m)^output_name\s*=\s*([^\r\n]+)')
 $modes=@(); $exists=Test-Path -LiteralPath '__SETTINGS__'
 if ($exists) { $xml=New-Object System.Xml.XmlDocument; $xml.Load('__SETTINGS__'); $modes=@($xml.SelectNodes('/vdd_settings/resolutions/resolution') | ForEach-Object { "$($_.width)x$($_.height)" }) }
 $pipe=[IO.Directory]::GetFiles('\\.\pipe\') -contains '\\.\pipe\MTTVirtualDisplayPipe'
 @{ok=$true;result=@{settings='__SETTINGS__';settings_present=$exists;modes=$modes;driver_pipe=$pipe;
   sunshine_output=$(if ($output.Success) {$output.Groups[1].Value.Trim()} else {$null});
   dd_resolution_option=$(if ($option.Success) {$option.Groups[1].Value.Trim()} else {'unset'})}} | ConvertTo-Json -Depth 6 -Compress
} catch {@{ok=$false;error=$_.Exception.Message} | ConvertTo-Json -Compress}
'''.replace("__UUID__", pairing_uuid).replace("__SETTINGS__", settings.replace("'", "''"))
    reply = windows_display.powershell(alias, body, timeout=45)
    if not reply.get("ok"):
        raise ValueError(reply.get("error", "virtual display inspection failed"))
    return reply["result"]


def prepare(record, host, persist):
    """Optional driver-specific size sync, followed by fresh capture verification."""
    from . import sunshine_display
    # Verification is independent of mode management; an XML entry is not proof.
    sunshine_display.snapshot(host)
    if host.display.get("sync_modes", False):
        sync(host.computer["ssh"]["alias"], record["stream_resolution"], settings_path(host.display),
             host.profile.get("fps", 60))
    record.setdefault("resolved", {})["restoration"] = "sunshine"
    sunshine_display.begin(record, host, persist)
