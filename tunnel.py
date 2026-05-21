import logging
import socket
import subprocess
import time
from dataclasses import dataclass

from config import DevBox

logger = logging.getLogger(__name__)


@dataclass
class LocalAddress:
    """Local tunnel binding address."""

    port: int
    host: str = "127.0.0.1"

    def __str__(self) -> str:
        return f"{self.host}:{self.port}"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class SSHTunnel:
    def __init__(self, dev_box: DevBox, remote_host: str, remote_port: int):
        self.dev_box = dev_box
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.local_port = get_free_port()
        self.proc = None

    def start(self) -> LocalAddress:
        if not self.dev_box:
            raise ValueError("DevBox configuration is required to start SSH tunnel")

        logger.info(
            f"Starting SSH tunnel from {self.dev_box.username}@{self.dev_box.jumpbox}:22 to {self.remote_host}:{self.remote_port}"
        )

        self.proc = subprocess.Popen(
            [
                "ssh",
                f"{self.dev_box.username}@{self.dev_box.jumpbox}",
                "-L",
                f"{self.local_port}:{self.remote_host}:{self.remote_port}",
                "-N",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        time.sleep(1)

        if self.proc.poll() is not None:
            logger.error(self.proc.stderr.read())
            raise RuntimeError("SSH failed")

        return LocalAddress(self.local_port)

    def stop(self) -> None:
        logger.info("Stopping SSH tunnel")
        if self.proc:
            self.proc.terminate()
            self.proc.wait()

    def _is_alive(self) -> bool:
        return self.proc is not None
