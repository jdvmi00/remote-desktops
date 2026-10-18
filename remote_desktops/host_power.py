"""Bounded SSH setup calls for the independently running Linux host policy."""
import json
from pathlib import Path
import re
import subprocess


def remote(computer, operation, policy=None):
    if computer.get("platform") != "linux":
        raise ValueError("host-power-requires-linux: host power is supported on Omarchy Linux")
    alias = computer.get("ssh", {}).get("alias", "")
    if not isinstance(alias, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", alias):
        raise ValueError("host-power-ssh-required: enter a host alias from your SSH configuration")
    source = Path(__file__).with_name("linux_power_host.py").read_text()
    request = {"operation": operation, "pairing_uuid": computer["pairing_uuid"], "policy": policy}
    if operation == "configure":
        request["source"] = source
    program = "REQUEST = " + repr(request) + "\n" + source
    try:
        result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                                 "-o", "ConnectTimeout=5", alias, "python3 -"],
                                input=program, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=110)
    except subprocess.TimeoutExpired:
        raise ValueError("host-power-outcome-uncertain: recheck the host before trying again") from None
    if result.returncode:
        raise ValueError("host-power-ssh-failed: check the host alias and key access")
    if len(result.stdout) > 65536:
        raise ValueError("host-power-invalid-response")
    try:
        reply = json.loads(result.stdout)
        if not isinstance(reply, dict):
            raise ValueError("host-power-invalid-response")
        if reply.get("ok") is not True:
            raise ValueError(reply.get("error", "host-power-failed"))
        if not isinstance(reply.get("result"), dict):
            raise ValueError("host-power-invalid-response")
        return reply["result"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise ValueError("host-power-invalid-response") from None
