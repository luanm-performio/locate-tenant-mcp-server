from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class Region:
    remote_bind_address: str
    username: str
    password: str
    remote_bind_port: int = 3306
    virtual_network_id: str | None = None


def load_config(config_path: str) -> list[Region]:
    with open(config_path, "r") as f:
        config_dict = yaml.safe_load(f)

    return [
        Region(
            remote_bind_address=r["remote_bind_address"],
            remote_bind_port=r.get("remote_bind_port", 3306),
            username=r["username"],
            password=r["password"],
            virtual_network_id=r.get("virtual_network_id"),
        )
        for r in config_dict["regions"]
    ]
