from dataclasses import dataclass, fields

from sqlalchemy import Engine, MetaData, Table, create_engine, select
from typing_extensions import Any

from config import Region, load_config
from tunnel import SSHTunnel


def map_to_dataclass(cls, row):
    field_names = {f.name for f in fields(cls)}
    filtered = {
        field_name: value
        for field_name, value in row.items()
        if field_name in field_names
    }

    return cls(**filtered)


@dataclass(frozen=True)
class DataSource:
    username: str
    password: str
    database_server_url: str
    schema_name: str
    region: Region | None = None
    shard_hosts: str | None = None


def construct_uri(data_source: DataSource) -> str:
    return f"mysql+pymysql://{data_source.username}:{data_source.password}@{data_source.database_server_url}/{data_source.schema_name}"


class DevTunnel:
    def __init__(self, data_source: DataSource, region: Region) -> None:
        self.data_source = data_source
        self.region = region

    def __enter__(self) -> Engine:
        if self.region.devbox_required and self.region.devbox:
            self.tunnel = SSHTunnel(
                dev_box=self.region.devbox,
                remote_host=self.region.remote_bind_address,
                remote_port=self.region.remote_bind_port,
            )

            local_address = self.tunnel.start()
            print(f"SSH tunnel established at {local_address}")

            tunnel_data_source = DataSource(
                database_server_url=f"{local_address.host}:{local_address.port}",
                schema_name=self.data_source.schema_name,
                username=self.data_source.username,
                password=self.data_source.password,
            )

            self.engine = self._create_engine(
                tunnel_data_source, self.region.devbox.ca_file
            )
        else:
            self.engine = self._create_engine(self.data_source)

        return self.engine

    def __exit__(self, exc_type: Any, exc_value: Any, exc_traceback: Any) -> None:
        self.engine.dispose()
        if self.region.devbox_required:
            self.tunnel.stop()

    def _create_engine(
        self, data_source: DataSource, ca_file: str | None = None
    ) -> Engine:
        tenant_uri = construct_uri(data_source)
        if ca_file is None:
            return create_engine(tenant_uri)

        return create_engine(
            tenant_uri,
            connect_args={
                "ssl": {
                    "ca": ca_file,
                    "check_hostname": False,
                    "verify_server_cert": False,
                }
            },
        )


class Tenant:
    def find_by_host_name(
        self, host_name: str, regions: list[Region]
    ) -> list[DataSource]:

        data_sources = []
        for region in regions:
            global_data_source = DataSource(
                username=region.username,
                password=region.password,
                database_server_url=region.remote_bind_address,
                schema_name="performancecentre_global",
            )
            with DevTunnel(global_data_source, region) as engine:
                try:
                    with engine.connect() as connection:
                        metadata = MetaData()
                        data_source = Table(
                            "data_source", metadata, autoload_with=engine
                        )
                        query = select(data_source).where(
                            data_source.c.shard_hosts.like(f"%{host_name}%")
                        )
                        rows = connection.execute(query).mappings()

                        region_data_sources = [
                            DataSource(
                                shard_hosts=row["shard_hosts"],
                                username=row["username"],
                                password=row["password"],
                                database_server_url=row["database_server_url"],
                                schema_name=row["schema_name"],
                                region=region,
                            )
                            for row in rows
                        ]

                        if region_data_sources:
                            data_sources += region_data_sources
                except Exception:
                    print(
                        f"Connection failed: {region.remote_bind_address}. Turn on VPN and try again. "
                    )

        return data_sources


if __name__ == "__main__":
    tenant = Tenant()
    regions = load_config("config.yaml")

    regs = [region for region in regions if region.devbox_required]
    data_sources = tenant.find_by_host_name("amp", regs)
    for ds in data_sources:
        print(
            f"{ds.shard_hosts.split(',')[0]}\t{ds.schema_name}\t{ds.region.remote_bind_address}"
        )
