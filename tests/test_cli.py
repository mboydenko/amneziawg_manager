import base64
import json
import os
import re
import ipaddress
from datetime import datetime
from pathlib import Path

import pytest

from amneziawg_manager_cli import cli


def test_parse_and_serialize_roundtrip():
    text = """[Interface]
PrivateKey = abc123
Address = 10.0.0.1/24

[Peer]
PublicKey = pubkey
AllowedIPs = 10.0.0.2/32
"""
    config = cli.parse_config(text)
    assert config.interface.options["PrivateKey"] == "abc123"
    assert config.peers[0].options["PublicKey"] == "pubkey"
    assert cli.serialize_config([config.interface, *config.peers]).strip() == text.strip()


def test_resolve_clients_table_path_default_and_override(tmp_path: Path):
    config_path = tmp_path / "wg0.conf"
    runtime = cli.RuntimeOptions()
    assert cli.resolve_clients_table_path(config_path, runtime) == tmp_path / "clientsTable"

    custom_path = tmp_path / "custom-table.json"
    runtime = cli.RuntimeOptions(clients_table_path=custom_path)
    assert cli.resolve_clients_table_path(config_path, runtime) == custom_path


def test_read_write_server_config_and_sidecar(tmp_path: Path):
    config_path = tmp_path / "wg0.conf"
    config_path.write_text("[Interface]\nPrivateKey = abc\n", encoding="utf-8")
    runtime = cli.RuntimeOptions()

    assert "PrivateKey" in cli.read_server_config(config_path, runtime)

    cli.write_server_config(config_path, runtime, "[Interface]\nPrivateKey = def\n")
    assert config_path.read_text(encoding="utf-8") == "[Interface]\nPrivateKey = def\n"

    sidecar = tmp_path / "clientsTable"
    cli.write_sidecar_file(config_path, runtime, sidecar, "[]")
    assert sidecar.read_text(encoding="utf-8") == "[]"
    assert cli.read_sidecar_file(config_path, runtime, sidecar) == "[]"


def test_read_write_server_config_docker(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_read(container, path):
        captured["read"] = (container, path)
        return "docker-content"

    def fake_write(container, path, content):
        captured["write"] = (container, path, content)

    monkeypatch.setattr(cli, "_docker_read_file", fake_read)
    monkeypatch.setattr(cli, "_docker_write_file", fake_write)

    runtime = cli.RuntimeOptions(docker_container="ctr")
    path = Path("/etc/wg0.conf")

    assert cli.read_server_config(path, runtime) == "docker-content"
    cli.write_server_config(path, runtime, "data")
    assert captured["write"] == ("ctr", path, "data")


def test_read_write_sidecar_file_docker(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_read(container, path):
        captured["read"] = (container, path)
        return "[]"

    def fake_write(container, path, content):
        captured["write"] = (container, path, content)

    monkeypatch.setattr(cli, "_docker_read_file", fake_read)
    monkeypatch.setattr(cli, "_docker_write_file", fake_write)

    runtime = cli.RuntimeOptions(docker_container="ctr")
    path = Path("/tmp/clientsTable")

    assert cli.read_sidecar_file(Path("/tmp/server.conf"), runtime, path) == "[]"
    cli.write_sidecar_file(Path("/tmp/server.conf"), runtime, path, "[]")
    assert captured["write"] == ("ctr", path, "[]")


def test_generate_key_material():
    private_key = cli.generate_private_key()
    assert isinstance(private_key, str)
    assert len(base64.b64decode(private_key)) == 32

    public_key = cli.generate_public_key(private_key)
    assert isinstance(public_key, str)
    assert len(base64.b64decode(public_key)) == 32

    preshared = cli.generate_preshared_key()
    assert isinstance(preshared, str)
    assert len(base64.b64decode(preshared)) == 32


def test_infer_endpoint_explicit_and_env(monkeypatch: pytest.MonkeyPatch):
    config = cli.ServerConfig(cli.WgSection("Interface", {"ListenPort": "51820"}), [])
    assert cli.infer_endpoint(config, "example.com:51820") == "example.com:51820"

    monkeypatch.setenv("AWG_ENDPOINT", "env.example:51820")
    assert cli.infer_endpoint(config, None) == "env.example:51820"
    monkeypatch.delenv("AWG_ENDPOINT", raising=False)

    monkeypatch.setenv("WG_ENDPOINT", "wg.example:51820")
    assert cli.infer_endpoint(config, None) == "wg.example:51820"
    monkeypatch.delenv("WG_ENDPOINT", raising=False)


def test_validate_client_name():
    assert cli.validate_client_name("client-1") == "client-1"
    with pytest.raises(ValueError):
        cli.validate_client_name("bad name")
    assert cli.validate_client_name("bad name", amnezia=True) == "bad name"


def test_amnezia_creation_date_format():
    when = datetime(2026, 5, 20, 12, 34, 56)
    data = cli.amnezia_creation_date(when)
    assert "2026" in data
    assert "May" in data
    assert re.match(r"^[A-Za-z]{3} [A-Za-z]{3} \d{1,2} \d{2}:\d{2}:\d{2} 2026$", data)


def test_client_config_filename_sanitizes():
    assert cli.client_config_filename("foo/bar") == "foo_bar.conf"
    assert cli.client_config_filename("test\0name") == "testname.conf"


def test_ip_allocation_helpers():
    config = cli.ServerConfig(
        cli.WgSection("Interface", {"Address": "10.0.0.0/30"}),
        [cli.WgSection("Peer", {"AllowedIPs": "10.0.0.1/32"})],
    )
    assert cli.collect_used_ips(config) == {
        ipaddress.ip_address("10.0.0.0"),
        ipaddress.ip_address("10.0.0.1"),
    }
    assert cli.get_next_client_ip(config) == "10.0.0.2"

    ipv6_config = cli.ServerConfig(
        cli.WgSection("Interface", {"Address": "fd00::/124"}),
        [cli.WgSection("Peer", {"AllowedIPs": "fd00::1/128"})],
    )
    next_ip = cli.get_next_client_ip(ipv6_config)
    assert next_ip.startswith("fd00::")
    assert next_ip != "fd00::1"


def test_copy_awg_params():
    source = {"Jc": "1", "Foo": "x"}
    target = {}
    cli.copy_awg_params(source, target)
    assert target == {"Jc": "1"}


def test_build_client_config():
    text = cli.build_client_config(
        client_private_key="a" * 44,
        client_address="10.0.0.2",
        server_public_key="b" * 44,
        preshared_key="c" * 44,
        server_interface={"Address": "10.0.0.1/24"},
        endpoint="example.com:51820",
        dns="1.1.1.1",
        allowed_ips="0.0.0.0/0",
        persistent_keepalive=25,
    )
    assert "[Interface]" in text
    assert "[Peer]" in text
    assert "Endpoint = example.com:51820" in text


def test_registry_persistence_and_lookup(tmp_path: Path):
    config_path = tmp_path / "wg0.conf"
    config_path.write_text("[Interface]\nPrivateKey = abc\n", encoding="utf-8")

    client_config = tmp_path / "foo.conf"
    client_config.write_text("[Interface]\nPrivateKey = x\n", encoding="utf-8")

    cli.register_client(
        config_path,
        cli.RuntimeOptions(),
        name="foo",
        public_key="pk1",
        ip="10.0.0.2",
        client_config_path=client_config,
    )

    registry = cli.load_clients_registry(config_path)
    assert registry["clients"]["foo"]["public_key"] == "pk1"
    assert cli.lookup_client_public_key(config_path, cli.RuntimeOptions(), "foo") == "pk1"
    assert cli.lookup_client_name(config_path, cli.RuntimeOptions(), "pk1") == "foo"
    assert cli.lookup_client_config_path(config_path, cli.RuntimeOptions(), "foo") == client_config

    removed = cli.unregister_client_by_public_key(config_path, cli.RuntimeOptions(), "pk1")
    assert removed == "foo"
    assert cli.load_clients_registry(config_path)["clients"] == {}


def test_amnezia_clients_table_registry(tmp_path: Path):
    config_path = tmp_path / "wg0.conf"
    config_path.write_text("[Interface]\nPrivateKey = abc\n", encoding="utf-8")

    runtime = cli.RuntimeOptions(amnezia=True)
    cli.register_client(
        config_path,
        runtime,
        name="bar",
        public_key="pk2",
        ip="10.0.0.3",
        client_config_path=tmp_path / "bar.conf",
    )

    assert cli.lookup_client_public_key(config_path, runtime, "bar") == "pk2"
    assert cli.lookup_client_name(config_path, runtime, "pk2") == "bar"

    removed = cli.unregister_client_by_public_key(config_path, runtime, "pk2")
    assert removed == "bar"
    assert cli.load_amnezia_clients_table(config_path, runtime) == []


def test_read_client_name_and_prepend_comment(tmp_path: Path):
    config_text = "# ClientName = name\n\n[Interface]\nPrivateKey = abc\n"
    assert cli.prepend_client_name_comment("x", "name").startswith("# ClientName = name")

    config_path = tmp_path / "tmp.conf"
    config_path.write_text(config_text, encoding="utf-8")
    assert cli.read_client_name_from_config(config_path) == "name"


def test_default_output_path_and_suffix(tmp_path: Path):
    config_path = tmp_path / "wg0.conf"
    assert cli.default_output_path(config_path, None, cli.RuntimeOptions()).name == "client-1.conf"

    (tmp_path / "client-1.conf").write_text("x", encoding="utf-8")
    assert cli.default_output_path(config_path, None, cli.RuntimeOptions()).name == "client-2.conf"

    assert cli.default_output_path(config_path, "alice", cli.RuntimeOptions()).name == "alice.conf"


def test_create_and_delete_client(tmp_path: Path):
    config_path = tmp_path / "wg0.conf"
    server_private_key = cli.generate_private_key()
    config_path.write_text(
        f"[Interface]\nPrivateKey = {server_private_key}\nAddress = 10.0.0.1/24\nListenPort = 51820\n",
        encoding="utf-8",
    )
    runtime = cli.RuntimeOptions()

    output_path = cli.create_client(
        config_path,
        endpoint="example.com:51820",
        client_name="foo",
        update_server=True,
        runtime=runtime,
    )

    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8").startswith("# ClientName = foo")
    assert "PublicKey" in config_path.read_text(encoding="utf-8")

    removed_peer, removed_name, deleted_config = cli.delete_client(
        config_path,
        name="foo",
        remove_config=True,
        update_server=True,
        runtime=runtime,
    )
    assert removed_name == "foo"
    assert deleted_config is not None
    assert not deleted_config.exists()
    assert "PublicKey" not in config_path.read_text(encoding="utf-8")


def test_server_config_label_for_docker():
    runtime = cli.RuntimeOptions(docker_container="ctr")
    assert cli._server_config_label(Path("/etc/wg0.conf"), runtime) == "ctr:/etc/wg0.conf"


def test_build_parser_subcommands():
    parser = cli.build_parser()

    add_args = parser.parse_args(["add", "wg0.conf", "--endpoint", "host:51820"])
    assert add_args.command == "add"
    assert add_args.server_config == Path("wg0.conf")
    assert add_args.endpoint == "host:51820"

    delete_args = parser.parse_args(["delete", "wg0.conf", "--ip", "10.0.0.2"])
    assert delete_args.command == "delete"
    assert delete_args.ip == "10.0.0.2"


def test_resolve_server_path_with_docker_container():
    runtime = cli.RuntimeOptions(docker_container="ctr")
    path = cli._resolve_server_path(Path("~/wg0.conf"), runtime)
    assert path == Path("~/wg0.conf").expanduser()


def test_reload_docker_interface_uses_docker_exec(monkeypatch: pytest.MonkeyPatch):
    executed = []

    def fake_exec(container, shell_cmd, input_text=None):
        executed.append((container, shell_cmd))
        return ""

    monkeypatch.setattr(cli, "_docker_exec", fake_exec)
    runtime = cli.RuntimeOptions(docker_container="ctr", reload=True, docker_wg_tool="wg")
    config_path = Path("/etc/wg0.conf")

    cli.reload_docker_interface(config_path, runtime)
    assert executed == [
        (
            "ctr",
            "wg-quick down wg0 && wg-quick up wg0",
        )
    ]
