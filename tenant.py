from dataclasses import dataclass, fields

from sqlalchemy import Engine, MetaData, Table, create_engine, select
from sqlalchemy.pool import NullPool
from typing_extensions import Any

from config import Region, load_config
from tunnel import switch_vnet


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


class VPNTunnel:
    def __init__(self, data_source: DataSource, region: Region) -> None:
        self.data_source = data_source
        self.region = region

    def __enter__(self) -> Engine:
        if self.region.virtual_network_id:
            switch_vnet(self.region.virtual_network_id)
        self.engine = create_engine(construct_uri(self.data_source), poolclass=NullPool)
        return self.engine

    def __exit__(self, exc_type: Any, exc_value: Any, exc_traceback: Any) -> None:
        self.engine.dispose()


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
            with VPNTunnel(global_data_source, region) as engine:
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
                        f"Connection failed: {region.remote_bind_address}. Check VPN and try again."
                    )

        return data_sources


if __name__ == "__main__":
    tenant = Tenant()
    regions = load_config("config.yaml")

    data_sources = tenant.find_by_host_name("amp", regions)
    for ds in data_sources:
        print(
            f"{ds.shard_hosts.split(',')[0]}\t{ds.schema_name}\t{ds.region.remote_bind_address}"
        )
