import pytest
from pathlib import Path

from amneziawg_manager_cli import cli

def test_load_amnezia_data_from_resource_files(tmp_path: Path):
    resource_dir = Path(__file__).resolve().parent / "resources"
    config_source = resource_dir / "smoke_wg.conf"
    table_source = resource_dir / "smok_clients_table"

    config_path = tmp_path / "wg0.conf"
    clients_table_path = tmp_path / "clientsTable"

    config_path.write_text(config_source.read_text(encoding="utf-8"), encoding="utf-8")
    clients_table_path.write_text(table_source.read_text(encoding="utf-8"), encoding="utf-8")

    runtime = cli.RuntimeOptions()
    assert cli.uses_amnezia_clients_table(config_path, runtime)

    table = cli.load_amnezia_clients_table(config_path, runtime)
    assert len(table) == 2
    assert table[0]["userData"]["clientName"] == "Admin [macOS 26.1]"
    assert table[1]["clientId"] == "CLIENT_1_PUBLIC_KEY"

    assert cli.lookup_client_public_key(config_path, runtime, "client.1") == "CLIENT_1_PUBLIC_KEY"
    assert cli.lookup_client_name(config_path, runtime, "ADMIN_PUBLIC_KEY") == "Admin [macOS 26.1]"
    assert cli.lookup_client_config_path(config_path, runtime, "client.1").name == "client.1.conf"


def test_create_and_lookup_amnezia_client_from_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    resource_dir = Path(__file__).resolve().parent / "resources"
    config_source = resource_dir / "smoke_wg.conf"
    table_source = resource_dir / "smok_clients_table"

    config_path = tmp_path / "wg0.conf"
    config_path.write_text(config_source.read_text(encoding="utf-8"), encoding="utf-8")
    clients_table_path = tmp_path / "clientsTable"
    clients_table_path.write_text(table_source.read_text(encoding="utf-8"), encoding="utf-8")

    def fake_run_wg(args, input_text=None, runtime=None):
        if args == ["genkey"]:
            return "TEST_CLIENT_PRIVATE_KEY"
        if args == ["genpsk"]:
            return "TEST_PRESHARED_KEY"
        if args == ["pubkey"]:
            if input_text == "TEST_CLIENT_PRIVATE_KEY\n":
                return "TEST_CLIENT_PUBLIC_KEY"
            return "TEST_SERVER_PUBLIC_KEY"
        raise ValueError(f"Unsupported args: {args}")

    monkeypatch.setattr(cli, "_run_wg", fake_run_wg)

    runtime = cli.RuntimeOptions()
    output_path = cli.create_client(
        config_path,
        endpoint="127.0.0.1s:51820",
        client_name="new client",
        update_server=True,
        runtime=runtime,
    )

    assert output_path.exists()

    content = output_path.read_text(encoding="utf-8")
    assert content.startswith("# ClientName = new client")
    assert "[Peer]" in config_path.read_text(encoding="utf-8")

    new_public_key = cli.lookup_client_public_key(config_path, runtime, "new client")
    assert new_public_key
    assert cli.lookup_client_name(config_path, runtime, new_public_key) == "new client"
    assert cli.lookup_client_config_path(config_path, runtime, "new client").name == "new client.conf"

    table = cli.load_amnezia_clients_table(config_path, runtime)
    assert any(
        entry.get("clientId") == new_public_key
        and entry.get("userData", {}).get("clientName") == "new client"
        for entry in table
    )

    clients = cli.list_clients(cli.parse_config(config_path.read_text(encoding="utf-8")), config_path, runtime)
    assert any(name == "new client" for _, name, _, _, _ in clients)


def test_delete_amnezia_client_from_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    resource_dir = Path(__file__).resolve().parent / "resources"
    config_source = resource_dir / "smoke_wg.conf"
    table_source = resource_dir / "smok_clients_table"

    config_path = tmp_path / "wg0.conf"
    config_path.write_text(config_source.read_text(encoding="utf-8"), encoding="utf-8")
    clients_table_path = tmp_path / "clientsTable"
    clients_table_path.write_text(table_source.read_text(encoding="utf-8"), encoding="utf-8")

    def fake_run_wg(args, input_text=None, runtime=None):
        if args == ["genkey"]:
            return "TEMP_CLIENT_PRIVATE_KEY"
        if args == ["genpsk"]:
            return "TEMP_PRESHARED_KEY"
        if args == ["pubkey"]:
            if input_text == "TEMP_CLIENT_PRIVATE_KEY\n":
                return "TEMP_CLIENT_PUBLIC_KEY"
            return "TEMP_SERVER_PUBLIC_KEY"
        raise ValueError(f"Unsupported args: {args}")

    monkeypatch.setattr(cli, "_run_wg", fake_run_wg)
    runtime = cli.RuntimeOptions()
    output_path = cli.create_client(
        config_path,
        endpoint="example.com:51820",
        client_name="temporary client",
        update_server=True,
        runtime=runtime,
    )
    assert output_path.exists()

    removed_peer, removed_name, deleted_config = cli.delete_client(
        config_path,
        name="temporary client",
        remove_config=True,
        update_server=True,
        runtime=runtime,
    )

    assert removed_name == "temporary client"
    assert deleted_config == output_path
    assert not output_path.exists()
    assert "temporary client" not in [entry.get("userData", {}).get("clientName") for entry in cli.load_amnezia_clients_table(config_path, runtime)]

    with pytest.raises(ValueError):
        cli.lookup_client_public_key(config_path, runtime, "temporary client")


def test_amnezia_clients_table_index_and_save_roundtrip(tmp_path: Path):
    resource_dir = Path(__file__).resolve().parent / "resources"
    table_source = resource_dir / "smok_clients_table"

    config_path = tmp_path / "wg0.conf"
    config_path.write_text("[Interface]\nPrivateKey = abc\n", encoding="utf-8")

    clients_table_path = tmp_path / "clientsTable"
    clients_table_path.write_text(table_source.read_text(encoding="utf-8"), encoding="utf-8")

    runtime = cli.RuntimeOptions()
    index = cli.amnezia_clients_table_index(config_path, runtime)
    assert index["ADMIN_PUBLIC_KEY"]["clientName"] == "Admin [macOS 26.1]"
    assert index["CLIENT_1_PUBLIC_KEY"]["allowedIps"] == "10.8.1.2/32"

    table = cli.load_amnezia_clients_table(config_path, runtime)
    table.append(
        {
            "clientId": "NEW_PUBLIC_KEY",
            "userData": {
                "allowedIps": "10.8.1.3/32",
                "clientName": "new client",
                "creationDate": "Wed Jan 1 00:00:00 2026",
            },
        }
    )
    cli.save_amnezia_clients_table(config_path, runtime, table)

    reloaded = cli.load_amnezia_clients_table(config_path, runtime)
    assert any(entry.get("clientId") == "NEW_PUBLIC_KEY" for entry in reloaded)
