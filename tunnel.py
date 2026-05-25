import logging
import subprocess
import time

logging.basicConfig(level=logging.INFO)

WARP_CLI = "/Applications/Cloudflare WARP.app/Contents/Resources/warp-cli"

logger = logging.getLogger(__name__)


def _warp_is_connected() -> bool:
    result = subprocess.run(
        [WARP_CLI, "status"],
        capture_output=True,
        text=True,
    )
    output = result.stdout
    return "Connected" in output and "healthy" in output


def switch_vnet(virtual_network_id: str, timeout: float = 30.0, interval: float = 1.0) -> None:
    logger.info(f"Switching WARP virtual network to {virtual_network_id}")
    result = subprocess.run(
        [WARP_CLI, "vnet", virtual_network_id],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or "Success" not in result.stdout:
        raise RuntimeError(
            f"warp-cli vnet failed: {result.stderr.strip() or result.stdout.strip()}"
        )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _warp_is_connected():
            logger.info("WARP connected and healthy")
            return
        time.sleep(interval)

    raise RuntimeError(f"WARP did not reach Connected/healthy state within {timeout}s")


if __name__ == "__main__":
    switch_vnet("d682d9f1-67b3-43c5-ac45-60cf50a5de46")
