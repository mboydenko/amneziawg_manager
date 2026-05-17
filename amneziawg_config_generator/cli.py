#!/usr/bin/env python3
"""Manage AmneziaWG clients using a server config file."""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

CLIENT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
CLIENT_NAME_COMMENT = re.compile(r"^#\s*ClientName\s*=\s*(.+?)\s*$")
CLIENTS_TABLE_FILENAME = "clientsTable"
_AMNEZIA_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_AMNEZIA_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

AWG_INTERFACE_PARAMS = (
    "Jc",
    "Jmin",
    "Jmax",
    "S1",
    "S2",
    "S3",
    "S4",
    "H1",
    "H2",
    "H3",
    "H4",
    "I1",
    "I2",
    "I3",
    "I4",
    "I5",
)


@dataclass
class WgSection:
    name: str
    options: dict[str, str] = field(default_factory=dict)


@dataclass
class ServerConfig:
    interface: WgSection
    peers: list[WgSection]


@dataclass
class RuntimeOptions:
    docker_container: str | None = None
    docker_config_path: Path | None = None
    docker_wg_tool: str | None = None
    reload: bool = False
    docker_interface: str | None = None
    clients_table_path: Path | None = None
    amnezia: bool = False
    _resolved_wg_tool: str | None = field(default=None, repr=False)

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> RuntimeOptions:
        container = getattr(args, "docker_container", None) or os.environ.get(
            "AWG_DOCKER_CONTAINER"
        )
        docker_config = getattr(args, "docker_config", None)
        clients_table = getattr(args, "clients_table", None)
        return cls(
            docker_container=container,
            docker_config_path=Path(docker_config) if docker_config else None,
            docker_wg_tool=getattr(args, "docker_wg_tool", None),
            reload=getattr(args, "reload", False),
            docker_interface=getattr(args, "docker_interface", None),
            clients_table_path=Path(clients_table) if clients_table else None,
            amnezia=getattr(args, "amnezia", False),
        )

    def uses_docker_config(self) -> bool:
        return bool(self.docker_container and self.docker_config_path)

    def uses_docker_wg(self) -> bool:
        return bool(self.docker_container)

    def wg_tool(self) -> str:
        if self.docker_wg_tool:
            return self.docker_wg_tool
        if self._resolved_wg_tool:
            return self._resolved_wg_tool
        if self.docker_container:
            self._resolved_wg_tool = _detect_wg_tool(self.docker_container)
            return self._resolved_wg_tool
        return "wg"


def parse_config(text: str) -> ServerConfig:
    sections: list[WgSection] = []
    current: WgSection | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            if current is not None:
                sections.append(current)
            current = WgSection(name=line[1:-1])
            continue
        if "=" not in line or current is None:
            continue
        key, value = line.split("=", 1)
        current.options[key.strip()] = value.strip()

    if current is not None:
        sections.append(current)

    if not sections or sections[0].name != "Interface":
        raise ValueError("Config must start with [Interface] section")

    interface = sections[0]
    peers = [s for s in sections[1:] if s.name == "Peer"]
    return ServerConfig(interface=interface, peers=peers)


def serialize_config(sections: list[WgSection]) -> str:
    lines: list[str] = []
    for index, section in enumerate(sections):
        if index:
            lines.append("")
        lines.append(f"[{section.name}]")
        for key, value in section.options.items():
            lines.append(f"{key} = {value}")
    lines.append("")
    return "\n".join(lines)


def server_config_to_sections(config: ServerConfig) -> list[WgSection]:
    return [config.interface, *config.peers]


def _wg_binary() -> str | None:
    path = shutil.which("wg")
    return path


def _detect_wg_tool(container: str) -> str:
    for tool in ("awg", "wg"):
        result = subprocess.run(
            ["docker", "exec", container, "sh", "-c", f"command -v {tool}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return tool
    raise ValueError(
        f"Neither awg nor wg found in Docker container '{container}'"
    )


def _docker_exec(
    container: str,
    shell_cmd: str,
    *,
    input_text: str | None = None,
) -> str:
    result = subprocess.run(
        ["docker", "exec", "-i", container, "sh", "-c", shell_cmd],
        input=input_text,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _docker_read_file(container: str, path: Path) -> str:
    result = subprocess.run(
        ["docker", "exec", container, "cat", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _docker_write_file(container: str, path: Path, content: str) -> None:
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "sh",
            "-c",
            f"cat > {shlex.quote(str(path))}",
        ],
        input=content,
        text=True,
        check=True,
    )


def read_server_config(server_path: Path, runtime: RuntimeOptions) -> str:
    if runtime.uses_docker_config():
        assert runtime.docker_container
        assert runtime.docker_config_path
        return _docker_read_file(runtime.docker_container, runtime.docker_config_path)
    return server_path.read_text(encoding="utf-8")


def write_server_config(
    server_path: Path,
    runtime: RuntimeOptions,
    content: str,
) -> None:
    if runtime.uses_docker_config():
        assert runtime.docker_container
        assert runtime.docker_config_path
        _docker_write_file(runtime.docker_container, runtime.docker_config_path, content)
        return
    server_path.write_text(content, encoding="utf-8")


def _config_data_dir(server_path: Path, runtime: RuntimeOptions) -> Path:
    if runtime.docker_config_path:
        return runtime.docker_config_path.parent
    return server_path.parent


def resolve_clients_table_path(server_path: Path, runtime: RuntimeOptions) -> Path:
    if runtime.clients_table_path:
        return runtime.clients_table_path
    return _config_data_dir(server_path, runtime) / CLIENTS_TABLE_FILENAME


def read_sidecar_file(
    server_path: Path,
    runtime: RuntimeOptions,
    path: Path,
) -> str | None:
    if runtime.uses_docker_config():
        assert runtime.docker_container
        try:
            return _docker_read_file(runtime.docker_container, path)
        except subprocess.CalledProcessError:
            return None
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return None


def write_sidecar_file(
    server_path: Path,
    runtime: RuntimeOptions,
    path: Path,
    content: str,
) -> None:
    if runtime.uses_docker_config():
        assert runtime.docker_container
        _docker_write_file(runtime.docker_container, path, content)
        return
    path.write_text(content, encoding="utf-8")


def uses_amnezia_clients_table(server_path: Path, runtime: RuntimeOptions) -> bool:
    if runtime.amnezia:
        return True
    table_path = resolve_clients_table_path(server_path, runtime)
    return read_sidecar_file(server_path, runtime, table_path) is not None


def reload_docker_interface(server_path: Path, runtime: RuntimeOptions) -> None:
    if not runtime.reload or not runtime.docker_container:
        return

    config_path = runtime.docker_config_path or server_path
    interface = runtime.docker_interface or config_path.stem
    container = runtime.docker_container
    assert container

    for quick_base in (runtime.wg_tool(), "awg", "wg"):
        quick = f"{quick_base}-quick"
        try:
            _docker_exec(
                container,
                f"{quick} down {shlex.quote(interface)} && "
                f"{quick} up {shlex.quote(interface)}",
            )
            return
        except subprocess.CalledProcessError:
            continue

    raise ValueError(
        f"Failed to reload interface '{interface}' in container '{container}'"
    )


def _run_wg(
    args: list[str],
    *,
    input_text: str | None = None,
    runtime: RuntimeOptions | None = None,
) -> str:
    if runtime and runtime.uses_docker_wg():
        tool = runtime.wg_tool()
        container = runtime.docker_container
        assert container
        if args == ["genkey"]:
            return _docker_exec(container, f"{tool} genkey")
        if args == ["genpsk"]:
            return _docker_exec(container, f"{tool} genpsk")
        if args == ["pubkey"]:
            return _docker_exec(container, f"{tool} pubkey", input_text=input_text)
        raise ValueError(f"Unsupported wg command: {args}")

    wg = _wg_binary()
    if not wg:
        raise FileNotFoundError("wg")
    result = subprocess.run(
        [wg, *args],
        input=input_text,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def generate_private_key(runtime: RuntimeOptions | None = None) -> str:
    try:
        return _run_wg(["genkey"], runtime=runtime)
    except (FileNotFoundError, subprocess.CalledProcessError):
        if runtime and runtime.uses_docker_wg():
            raise
        return _generate_private_key_cryptography()


def generate_public_key(
    private_key_b64: str,
    runtime: RuntimeOptions | None = None,
) -> str:
    try:
        return _run_wg(
            ["pubkey"],
            input_text=private_key_b64 + "\n",
            runtime=runtime,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        if runtime and runtime.uses_docker_wg():
            raise
        return _generate_public_key_cryptography(private_key_b64)


def generate_preshared_key(runtime: RuntimeOptions | None = None) -> str:
    try:
        return _run_wg(["genpsk"], runtime=runtime)
    except (FileNotFoundError, subprocess.CalledProcessError):
        if runtime and runtime.uses_docker_wg():
            raise
        return base64.b64encode(os.urandom(32)).decode()


def _generate_private_key_cryptography() -> str:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    private_key = X25519PrivateKey.generate()
    raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw = _clamp_private_key(raw)
    return base64.b64encode(raw).decode()


def _generate_public_key_cryptography(private_key_b64: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    raw = base64.b64decode(private_key_b64)
    private_key = X25519PrivateKey.from_private_bytes(raw)
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(public_raw).decode()


def _clamp_private_key(key: bytes) -> bytes:
    key = bytearray(key)
    key[0] &= 248
    key[31] &= 127
    key[31] |= 64
    return bytes(key)


def collect_used_ips(config: ServerConfig) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    used: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()

    interface_address = config.interface.options.get("Address", "")
    if interface_address:
        for part in interface_address.split(","):
            used.add(ipaddress.ip_interface(part.strip()).ip)

    for peer in config.peers:
        allowed = peer.options.get("AllowedIPs", "")
        for part in allowed.split(","):
            part = part.strip()
            if not part:
                continue
            network = ipaddress.ip_network(part, strict=False)
            if network.prefixlen == network.max_prefixlen:
                used.add(network.network_address)

    return used


def get_next_client_ip(config: ServerConfig) -> str:
    interface_address = config.interface.options.get("Address")
    if not interface_address:
        raise ValueError("Server [Interface] has no Address")

    network = ipaddress.ip_network(interface_address.split(",")[0].strip(), strict=False)
    used = collect_used_ips(config)

    if isinstance(network, ipaddress.IPv4Network):
        for host in network.hosts():
            if host not in used:
                return str(host)
    else:
        # For IPv6 pick the next address after the largest used host in the subnet.
        hosts = sorted(
            (ip for ip in used if ip in network),
            key=int,
        )
        if hosts:
            return str(hosts[-1] + 1)
        return str(next(network.hosts()))

    raise ValueError(f"No free IP addresses in subnet {network}")


def copy_awg_params(source: dict[str, str], target: dict[str, str]) -> None:
    for param in AWG_INTERFACE_PARAMS:
        if param in source:
            target[param] = source[param]


def build_client_config(
    *,
    client_private_key: str,
    client_address: str,
    server_public_key: str,
    preshared_key: str,
    server_interface: dict[str, str],
    endpoint: str,
    dns: str,
    allowed_ips: str,
    persistent_keepalive: int,
) -> str:
    interface_opts: dict[str, str] = {
        "Address": f"{client_address}/32",
        "PrivateKey": client_private_key,
    }
    if dns:
        interface_opts["DNS"] = dns
    copy_awg_params(server_interface, interface_opts)

    peer_opts: dict[str, str] = {
        "PublicKey": server_public_key,
        "PresharedKey": preshared_key,
        "AllowedIPs": allowed_ips,
        "Endpoint": endpoint,
        "PersistentKeepalive": str(persistent_keepalive),
    }

    sections = [
        WgSection(name="Interface", options=interface_opts),
        WgSection(name="Peer", options=peer_opts),
    ]
    return serialize_config(sections)


def infer_endpoint(config: ServerConfig, explicit: str | None) -> str:
    if explicit:
        return explicit

    env_endpoint = os.environ.get("AWG_ENDPOINT") or os.environ.get("WG_ENDPOINT")
    if env_endpoint:
        return env_endpoint

    listen_port = config.interface.options.get("ListenPort", "51820")
    raise ValueError(
        "Endpoint is required. Pass --endpoint host:port "
        f"or set AWG_ENDPOINT / WG_ENDPOINT (ListenPort on server: {listen_port})."
    )


def validate_client_name(name: str, *, amnezia: bool = False) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Client name cannot be empty")
    if amnezia:
        if "\n" in name or "\r" in name:
            raise ValueError("Client name must not contain line breaks")
        return name
    if not CLIENT_NAME_PATTERN.match(name):
        raise ValueError(
            "Client name must be 1-64 characters: letters, digits, "
            "underscore or hyphen; must start with a letter or digit. "
            "For Amnezia names (spaces, dots, etc.) use --amnezia."
        )
    return name


def amnezia_creation_date(when: datetime | None = None) -> str:
    when = when or datetime.now()
    weekday = _AMNEZIA_WEEKDAYS[when.weekday()]
    month = _AMNEZIA_MONTHS[when.month - 1]
    return f"{weekday} {month} {when.day} {when:%H:%M:%S} {when.year}"


def client_config_filename(name: str) -> str:
    safe = name.replace("/", "_").replace("\0", "")
    return f"{safe}.conf"


def clients_registry_path(server_path: Path) -> Path:
    return server_path.parent / f"{server_path.stem}.clients.json"


def load_clients_registry(server_path: Path) -> dict[str, dict]:
    path = clients_registry_path(server_path)
    if not path.exists():
        return {"clients": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if "clients" not in data or not isinstance(data["clients"], dict):
        raise ValueError(f"Invalid clients registry format: {path}")
    return data


def save_clients_registry(server_path: Path, registry: dict[str, dict]) -> None:
    path = clients_registry_path(server_path)
    path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_amnezia_clients_table(
    server_path: Path,
    runtime: RuntimeOptions,
) -> list[dict]:
    table_path = resolve_clients_table_path(server_path, runtime)
    raw = read_sidecar_file(server_path, runtime, table_path)
    if raw is None:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"clientsTable must be a JSON array: {table_path}")
    return data


def save_amnezia_clients_table(
    server_path: Path,
    runtime: RuntimeOptions,
    entries: list[dict],
) -> None:
    table_path = resolve_clients_table_path(server_path, runtime)
    content = json.dumps(entries, indent=4, ensure_ascii=False) + "\n"
    write_sidecar_file(server_path, runtime, table_path, content)


def _amnezia_user_data(entry: dict) -> dict:
    user_data = entry.get("userData")
    if not isinstance(user_data, dict):
        return {}
    return user_data


def register_client(
    server_path: Path,
    runtime: RuntimeOptions,
    *,
    name: str,
    public_key: str,
    ip: str,
    config_path: Path,
) -> None:
    if uses_amnezia_clients_table(server_path, runtime):
        table = load_amnezia_clients_table(server_path, runtime)
        for entry in table:
            user_data = _amnezia_user_data(entry)
            if user_data.get("clientName") == name:
                raise ValueError(f"Client name already exists in clientsTable: {name}")
            if entry.get("clientId") == public_key:
                existing = user_data.get("clientName", public_key)
                raise ValueError(
                    f"Public key already registered in clientsTable as '{existing}'"
                )
        table.append(
            {
                "clientId": public_key,
                "userData": {
                    "allowedIps": f"{ip}/32",
                    "clientName": name,
                    "creationDate": amnezia_creation_date(),
                },
            }
        )
        save_amnezia_clients_table(server_path, runtime, table)
        return

    registry = load_clients_registry(server_path)
    if name in registry["clients"]:
        raise ValueError(f"Client name already exists: {name}")

    for existing_name, entry in registry["clients"].items():
        if entry.get("public_key") == public_key:
            raise ValueError(
                f"Public key already registered as '{existing_name}'"
            )

    registry["clients"][name] = {
        "public_key": public_key,
        "ip": ip,
        "config": config_path.name,
    }
    save_clients_registry(server_path, registry)


def unregister_client_by_public_key(
    server_path: Path,
    runtime: RuntimeOptions,
    public_key: str,
) -> str | None:
    if uses_amnezia_clients_table(server_path, runtime):
        table = load_amnezia_clients_table(server_path, runtime)
        removed_name: str | None = None
        kept: list[dict] = []
        for entry in table:
            if entry.get("clientId") == public_key:
                removed_name = _amnezia_user_data(entry).get("clientName")
                continue
            kept.append(entry)
        if removed_name is not None:
            save_amnezia_clients_table(server_path, runtime, kept)
        return removed_name

    registry = load_clients_registry(server_path)
    for name, entry in list(registry["clients"].items()):
        if entry.get("public_key") == public_key:
            del registry["clients"][name]
            save_clients_registry(server_path, registry)
            return name
    return None


def lookup_client_name(
    server_path: Path,
    runtime: RuntimeOptions,
    public_key: str,
) -> str:
    if uses_amnezia_clients_table(server_path, runtime):
        for entry in load_amnezia_clients_table(server_path, runtime):
            if entry.get("clientId") == public_key:
                return _amnezia_user_data(entry).get("clientName", "")
        return ""

    registry = load_clients_registry(server_path)
    for name, entry in registry["clients"].items():
        if entry.get("public_key") == public_key:
            return name
    return ""


def lookup_client_public_key(
    server_path: Path,
    runtime: RuntimeOptions,
    name: str,
) -> str:
    amnezia = uses_amnezia_clients_table(server_path, runtime)
    name = validate_client_name(name, amnezia=amnezia)

    if amnezia:
        matches: list[str] = []
        for entry in load_amnezia_clients_table(server_path, runtime):
            if _amnezia_user_data(entry).get("clientName") == name:
                client_id = entry.get("clientId")
                if client_id:
                    matches.append(client_id)
        if not matches:
            raise ValueError(f"Client name not found in clientsTable: {name}")
        if len(matches) > 1:
            raise ValueError(
                f"Client name '{name}' is ambiguous in clientsTable "
                f"({len(matches)} entries)"
            )
        return matches[0]

    registry = load_clients_registry(server_path)
    entry = registry["clients"].get(name)
    if not entry:
        raise ValueError(f"Client name not found: {name}")
    public_key = entry.get("public_key")
    if not public_key:
        raise ValueError(f"Registry entry for '{name}' has no public_key")
    return public_key


def lookup_client_config_path(
    server_path: Path,
    runtime: RuntimeOptions,
    name: str,
) -> Path | None:
    amnezia = uses_amnezia_clients_table(server_path, runtime)
    name = validate_client_name(name, amnezia=amnezia)

    if amnezia:
        return server_path.parent / client_config_filename(name)

    registry = load_clients_registry(server_path)
    entry = registry["clients"].get(name)
    if not entry:
        return None
    config_name = entry.get("config")
    if not config_name:
        return None
    return server_path.parent / config_name


def amnezia_clients_table_index(
    server_path: Path,
    runtime: RuntimeOptions,
) -> dict[str, dict]:
    index: dict[str, dict] = {}
    if not uses_amnezia_clients_table(server_path, runtime):
        return index
    for entry in load_amnezia_clients_table(server_path, runtime):
        client_id = entry.get("clientId")
        if client_id:
            index[client_id] = _amnezia_user_data(entry)
    return index


def read_client_name_from_config(client_config_path: Path) -> str | None:
    for line in client_config_path.read_text(encoding="utf-8").splitlines():
        match = CLIENT_NAME_COMMENT.match(line.strip())
        if match:
            return match.group(1).strip()
    return None


def prepend_client_name_comment(config_text: str, name: str) -> str:
    return f"# ClientName = {name}\n\n{config_text}"


def default_output_path(
    server_path: Path,
    client_name: str | None,
    runtime: RuntimeOptions,
) -> Path:
    if client_name:
        if uses_amnezia_clients_table(server_path, runtime):
            return server_path.parent / client_config_filename(client_name)
        return server_path.parent / f"{client_name}.conf"
    return server_path.parent / f"client-{_next_client_suffix(server_path)}.conf"


def _next_client_suffix(server_path: Path) -> int:
    pattern = re.compile(r"client-(\d+)\.conf$")
    max_index = 0
    for path in server_path.parent.glob("client-*.conf"):
        match = pattern.match(path.name)
        if match:
            max_index = max(max_index, int(match.group(1)))
    return max_index + 1


def peer_host_ip(peer: WgSection) -> str | None:
    allowed = peer.options.get("AllowedIPs", "")
    for part in allowed.split(","):
        part = part.strip()
        if not part:
            continue
        network = ipaddress.ip_network(part, strict=False)
        if network.prefixlen == network.max_prefixlen:
            return str(network.network_address)
    return None


def client_config_public_key(
    client_config_path: Path,
    runtime: RuntimeOptions | None = None,
) -> str:
    text = client_config_path.read_text(encoding="utf-8")
    config = parse_config(text)
    private_key = config.interface.options.get("PrivateKey")
    if not private_key:
        raise ValueError(f"Client config has no PrivateKey: {client_config_path}")
    return generate_public_key(private_key, runtime=runtime)


def find_peer_index(
    config: ServerConfig,
    *,
    public_key: str | None = None,
    ip: str | None = None,
    name: str | None = None,
) -> int:
    selectors = [public_key, ip, name]
    if sum(1 for value in selectors if value) > 1:
        raise ValueError("Specify only one of --public-key, --ip, or --name")

    if public_key:
        for index, peer in enumerate(config.peers):
            if peer.options.get("PublicKey") == public_key:
                return index
        raise ValueError(f"Peer with PublicKey not found: {public_key}")

    if ip:
        target = ipaddress.ip_address(ip)
        for index, peer in enumerate(config.peers):
            peer_ip = peer_host_ip(peer)
            if peer_ip and ipaddress.ip_address(peer_ip) == target:
                return index
        raise ValueError(f"Peer with IP not found: {ip}")

    raise ValueError("Specify --public-key, --ip, --name, or --client-config")


def list_clients(
    config: ServerConfig,
    server_path: Path,
    runtime: RuntimeOptions,
) -> list[tuple[int, str, str, str, str]]:
    amnezia_index = amnezia_clients_table_index(server_path, runtime)
    clients: list[tuple[int, str, str, str, str]] = []
    for index, peer in enumerate(config.peers, start=1):
        public_key = peer.options.get("PublicKey", "?")
        ip = peer_host_ip(peer) or "?"
        user_data = amnezia_index.get(public_key, {})
        name = user_data.get("clientName") or lookup_client_name(
            server_path,
            runtime,
            public_key,
        )
        handshake = user_data.get("latestHandshake", "")
        clients.append((index, name, ip, handshake, public_key))
    return clients


def delete_client(
    server_config_path: Path,
    *,
    public_key: str | None = None,
    ip: str | None = None,
    name: str | None = None,
    client_config: Path | None = None,
    remove_config: bool = False,
    update_server: bool = True,
    runtime: RuntimeOptions | None = None,
) -> tuple[WgSection, str | None, Path | None]:
    runtime = runtime or RuntimeOptions()
    config_to_remove: Path | None = client_config
    resolved_name = name

    if client_config:
        public_key = client_config_public_key(client_config, runtime=runtime)
        if resolved_name is None:
            resolved_name = read_client_name_from_config(client_config)
    elif resolved_name:
        public_key = lookup_client_public_key(
            server_config_path,
            runtime,
            resolved_name,
        )
        if remove_config and config_to_remove is None:
            config_to_remove = lookup_client_config_path(
                server_config_path,
                runtime,
                resolved_name,
            )

    text = read_server_config(server_config_path, runtime)
    config = parse_config(text)
    peer_index = find_peer_index(config, public_key=public_key, ip=ip)
    removed_peer = config.peers.pop(peer_index)
    removed_public_key = removed_peer.options.get("PublicKey", "")

    if update_server:
        write_server_config(
            server_config_path,
            runtime,
            serialize_config(server_config_to_sections(config)),
        )

    removed_name = unregister_client_by_public_key(
        server_config_path,
        runtime,
        removed_public_key,
    )

    deleted_config: Path | None = None
    if remove_config and config_to_remove and config_to_remove.is_file():
        deleted_config = config_to_remove
        config_to_remove.unlink()

    return removed_peer, removed_name or resolved_name, deleted_config


def create_client(
    server_config_path: Path,
    *,
    endpoint: str | None = None,
    dns: str = "1.1.1.1, 1.0.0.1",
    allowed_ips: str = "0.0.0.0/0, ::/0",
    output: Path | None = None,
    client_name: str | None = None,
    persistent_keepalive: int = 25,
    update_server: bool = True,
    runtime: RuntimeOptions | None = None,
) -> Path:
    runtime = runtime or RuntimeOptions()
    amnezia = uses_amnezia_clients_table(server_config_path, runtime)
    if client_name is not None:
        client_name = validate_client_name(client_name, amnezia=amnezia)

    text = read_server_config(server_config_path, runtime)
    config = parse_config(text)

    server_private_key = config.interface.options.get("PrivateKey")
    if not server_private_key:
        raise ValueError("Server [Interface] has no PrivateKey")

    endpoint_value = infer_endpoint(config, endpoint)
    client_ip = get_next_client_ip(config)
    client_private_key = generate_private_key(runtime=runtime)
    client_public_key = generate_public_key(client_private_key, runtime=runtime)
    server_public_key = generate_public_key(server_private_key, runtime=runtime)
    preshared_key = generate_preshared_key(runtime=runtime)

    if update_server:
        config.peers.append(
            WgSection(
                name="Peer",
                options={
                    "PublicKey": client_public_key,
                    "PresharedKey": preshared_key,
                    "AllowedIPs": f"{client_ip}/32",
                },
            )
        )
        write_server_config(
            server_config_path,
            runtime,
            serialize_config(server_config_to_sections(config)),
        )

    client_text = build_client_config(
        client_private_key=client_private_key,
        client_address=client_ip,
        server_public_key=server_public_key,
        preshared_key=preshared_key,
        server_interface=config.interface.options,
        endpoint=endpoint_value,
        dns=dns,
        allowed_ips=allowed_ips,
        persistent_keepalive=persistent_keepalive,
    )

    output_path = output or default_output_path(
        server_config_path,
        client_name,
        runtime,
    )
    if client_name:
        client_text = prepend_client_name_comment(client_text, client_name)
    output_path.write_text(client_text, encoding="utf-8")

    if client_name and update_server:
        register_client(
            server_config_path,
            runtime,
            name=client_name,
            public_key=client_public_key,
            ip=client_ip,
            config_path=output_path,
        )

    return output_path


def _add_server_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "server_config",
        type=Path,
        help="Path to server config on host (bind mount) or anchor path for outputs",
    )


def _add_docker_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("Docker")
    group.add_argument(
        "--docker-container",
        metavar="NAME",
        help="Docker container with AmneziaWG (env: AWG_DOCKER_CONTAINER). "
        "Uses awg/wg inside the container for key generation.",
    )
    group.add_argument(
        "--docker-config",
        metavar="PATH",
        type=Path,
        help="Server config path inside the container (read/write via docker exec). "
        "Use when the config is not available as a local file.",
    )
    group.add_argument(
        "--docker-wg-tool",
        choices=("awg", "wg"),
        help="Force awg or wg binary inside the container (default: auto-detect)",
    )
    group.add_argument(
        "--docker-interface",
        metavar="IFACE",
        help="Interface name for --reload (default: config filename without extension)",
    )
    group.add_argument(
        "--reload",
        action="store_true",
        help="Run awg-quick/wg-quick down && up in the container after changes",
    )
    group.add_argument(
        "--amnezia",
        action="store_true",
        help="Use Amnezia clientsTable (auto-enabled if the file exists)",
    )
    group.add_argument(
        "--clients-table",
        metavar="PATH",
        type=Path,
        help="Path to clientsTable (default: next to wg config, e.g. /etc/wireguard/clientsTable)",
    )


def _resolve_server_path(path: Path, runtime: RuntimeOptions) -> Path | None:
    resolved = path.expanduser().resolve()

    if runtime.docker_config_path and not runtime.docker_container:
        print(
            "Error: --docker-config requires --docker-container",
            file=sys.stderr,
        )
        return None

    if runtime.uses_docker_config():
        if not resolved.parent.is_dir():
            print(
                f"Error: parent directory does not exist: {resolved.parent}",
                file=sys.stderr,
            )
            return None
        return resolved

    if not resolved.is_file():
        print(f"Error: server config not found: {resolved}", file=sys.stderr)
        return None
    return resolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage AmneziaWG clients using a server config file.",
    )
    subparsers = parser.add_subparsers(dest="command")

    add_parser = subparsers.add_parser("add", help="Add a new client")
    _add_server_config_arg(add_parser)
    _add_docker_args(add_parser)
    add_parser.add_argument(
        "--endpoint",
        help="Server endpoint for the client (host:port). "
        "Alternatively set AWG_ENDPOINT or WG_ENDPOINT.",
    )
    add_parser.add_argument(
        "--dns",
        default="1.1.1.1, 1.0.0.1",
        help="DNS servers for the client (default: 1.1.1.1, 1.0.0.1)",
    )
    add_parser.add_argument(
        "--allowed-ips",
        default="0.0.0.0/0, ::/0",
        help="AllowedIPs on the client peer (default: full tunnel)",
    )
    add_parser.add_argument(
        "--output",
        type=Path,
        help="Output path for the client config (default: next to server config)",
    )
    add_parser.add_argument(
        "--name",
        help="Client name (saved to registry, output file <name>.conf, comment in config)",
    )
    add_parser.add_argument(
        "--keepalive",
        type=int,
        default=25,
        help="PersistentKeepalive value (default: 25)",
    )
    add_parser.add_argument(
        "--no-update-server",
        action="store_true",
        help="Do not append the new peer to the server config file",
    )

    delete_parser = subparsers.add_parser("delete", help="Remove a client from the server")
    _add_server_config_arg(delete_parser)
    _add_docker_args(delete_parser)
    delete_target = delete_parser.add_mutually_exclusive_group(required=True)
    delete_target.add_argument(
        "--ip",
        help="Client VPN IP (as in peer AllowedIPs, e.g. 10.8.1.2)",
    )
    delete_target.add_argument(
        "--public-key",
        help="Client public key from the server [Peer] section",
    )
    delete_target.add_argument(
        "--name",
        help="Client name from the registry (<server>.clients.json)",
    )
    delete_target.add_argument(
        "--client-config",
        type=Path,
        help="Path to the client .conf file (peer is matched by derived public key)",
    )
    delete_parser.add_argument(
        "--remove-config",
        action="store_true",
        help="Delete the client .conf file (with --name or --client-config)",
    )
    delete_parser.add_argument(
        "--no-update-server",
        action="store_true",
        help="Do not modify the server config file",
    )

    list_parser = subparsers.add_parser("list", help="List clients on the server")
    _add_server_config_arg(list_parser)
    _add_docker_args(list_parser)

    _add_docker_args(parser)

    # Backward compatibility: `generate_client.py server.conf` == `add server.conf`
    parser.add_argument(
        "legacy_server_config",
        nargs="?",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--endpoint", help=argparse.SUPPRESS)
    parser.add_argument("--dns", default="1.1.1.1, 1.0.0.1", help=argparse.SUPPRESS)
    parser.add_argument("--allowed-ips", default="0.0.0.0/0, ::/0", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--name", help=argparse.SUPPRESS)
    parser.add_argument("--keepalive", type=int, default=25, help=argparse.SUPPRESS)
    parser.add_argument("--no-update-server", action="store_true", help=argparse.SUPPRESS)

    return parser


def _server_config_label(server_path: Path, runtime: RuntimeOptions) -> str:
    if runtime.uses_docker_config():
        return f"{runtime.docker_container}:{runtime.docker_config_path}"
    return str(server_path)


def _run_add(server_path: Path, args: argparse.Namespace) -> int:
    runtime = RuntimeOptions.from_args(args)
    try:
        output_path = create_client(
            server_path,
            endpoint=args.endpoint,
            dns=args.dns,
            allowed_ips=args.allowed_ips,
            output=args.output,
            client_name=args.name,
            persistent_keepalive=args.keepalive,
            update_server=not args.no_update_server,
            runtime=runtime,
        )
        if not args.no_update_server:
            reload_docker_interface(server_path, runtime)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Client config written to: {output_path}")
    if args.name:
        print(f"Client name: {args.name}")
    if not args.no_update_server:
        print(f"Server config updated: {_server_config_label(server_path, runtime)}")
    if runtime.reload and runtime.docker_container:
        print(f"Interface reloaded in container: {runtime.docker_container}")
    return 0


def _run_delete(server_path: Path, args: argparse.Namespace) -> int:
    runtime = RuntimeOptions.from_args(args)
    if args.remove_config and not args.client_config and not args.name:
        print("Error: --remove-config requires --name or --client-config", file=sys.stderr)
        return 1

    client_config = args.client_config.expanduser().resolve() if args.client_config else None
    if client_config and not client_config.is_file():
        print(f"Error: client config not found: {client_config}", file=sys.stderr)
        return 1

    try:
        removed_peer, removed_name, deleted_config = delete_client(
            server_path,
            public_key=args.public_key,
            ip=args.ip,
            name=args.name,
            client_config=client_config,
            remove_config=args.remove_config,
            update_server=not args.no_update_server,
            runtime=runtime,
        )
        if not args.no_update_server:
            reload_docker_interface(server_path, runtime)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    ip = peer_host_ip(removed_peer) or "?"
    public_key = removed_peer.options.get("PublicKey", "?")
    name_part = f", Name={removed_name}" if removed_name else ""
    print(f"Removed client: IP={ip}, PublicKey={public_key}{name_part}")
    if not args.no_update_server:
        print(f"Server config updated: {_server_config_label(server_path, runtime)}")
    if runtime.reload and runtime.docker_container and not args.no_update_server:
        print(f"Interface reloaded in container: {runtime.docker_container}")
    if deleted_config:
        print(f"Client config deleted: {deleted_config}")
    return 0


def _run_list(server_path: Path, args: argparse.Namespace) -> int:
    runtime = RuntimeOptions.from_args(args)
    try:
        config = parse_config(read_server_config(server_path, runtime))
        clients = list_clients(config, server_path, runtime)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not clients:
        print("No clients configured.")
        return 0

    show_handshake = any(handshake for _, _, _, handshake, _ in clients)
    if show_handshake:
        print(f"{'#':<4} {'Name':<20} {'IP':<16} {'Handshake':<24} PublicKey")
        for index, name, ip, handshake, public_key in clients:
            display_name = name or "-"
            print(
                f"{index:<4} {display_name:<20} {ip:<16} "
                f"{handshake or '-':<24} {public_key}"
            )
    else:
        print(f"{'#':<4} {'Name':<20} {'IP':<16} PublicKey")
        for index, name, ip, _, public_key in clients:
            display_name = name or "-"
            print(f"{index:<4} {display_name:<20} {ip:<16} {public_key}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    runtime = RuntimeOptions.from_args(args)

    if args.command in ("add", "delete", "list"):
        server_path = _resolve_server_path(args.server_config, runtime)
        if server_path is None:
            return 1
        if args.command == "add":
            return _run_add(server_path, args)
        if args.command == "delete":
            return _run_delete(server_path, args)
        return _run_list(server_path, args)

    if args.legacy_server_config is None:
        build_parser().print_help()
        return 1

    server_path = _resolve_server_path(args.legacy_server_config, runtime)
    if server_path is None:
        return 1
    return _run_add(server_path, args)


if __name__ == "__main__":
    raise SystemExit(main())
