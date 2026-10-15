from __future__ import annotations

import re
from pathlib import Path

from sentinel_provision.cameras import CameraSpec
from sentinel_provision.credentials import write_private

ACL_BLOCK_TEMPLATE = """
# Added by sentinel-provision for {frigate_name}
user {mqtt_username}
topic write sentinel/{camera_id}/#
topic read sentinel/{camera_id}/cmd
""".strip()


def ensure_acl_block(acl_path: Path, cam: CameraSpec, *, repo_root: Path | None = None) -> bool:
    """
    Append mosquitto ACL lines for a camera if not already present.
    Creates secrets/mosquitto/acl from host/mosquitto/acl.example when missing.
    """
    text = ""
    if acl_path.is_file():
        text = acl_path.read_text()
    else:
        example = None
        if repo_root is not None:
            example = repo_root / "host" / "mosquitto" / "acl.example"
        if example and example.is_file():
            text = example.read_text()
        else:
            text = "# Mosquitto ACL\n"

    # Whole-line match: acl.example carries `# user cam_b` as a comment, which must not count.
    if re.search(rf"^user[ \t]+{re.escape(cam.mqtt_username)}[ \t]*$", text, re.MULTILINE):
        if not acl_path.is_file():
            write_private(acl_path, text)
            return True
        return False

    block = ACL_BLOCK_TEMPLATE.format(
        frigate_name=cam.frigate_name,
        mqtt_username=cam.mqtt_username,
        camera_id=cam.camera_id,
    )
    if text and not text.endswith("\n"):
        text += "\n"
    text += block + "\n"
    write_private(acl_path, text)
    return True
