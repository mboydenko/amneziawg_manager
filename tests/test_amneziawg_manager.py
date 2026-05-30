import os
from pathlib import Path
import shutil
import subprocess
from dataclasses import dataclass

import pytest
from pytest_mock import MockerFixture

from amneziawg_manager import AmneziaWgManager
from amneziawg_manager import CmdExecutorFactory
from amneziawg_manager.lib.models import ClientsTableItem, ServerConfigPeer

ADDRESS = "231.123.23.1"
CLIENT_PUBLIC_KEY = 'CLIENT_PUBLIC_KEY'
CLIENT_PRIVATE_KEY = 'CLIENT_PRIVATE_KEY'
SERVER_PRESHARED_KEY = 'SERVER_PRESHARED_KEY'
SERVER_PUBLIC_KEY = 'SERVER_PUBLIC_KEY'

@dataclass
class DockerContainer:
    name: str
    conf_path: str
    clients_table_path: str
    public_key_path: str
    preshared_key_path: str

@pytest.fixture
def tmp_path():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    tmp_dir = Path(current_dir) / 'tmp'
    tmp_dir.mkdir(exist_ok=True)
    yield tmp_dir
    shutil.rmtree(tmp_dir)

@pytest.fixture
def tmp_server_conf(tmp_path: Path):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    shutil.copyfile(Path(current_dir) / 'resources' / 'server.conf', tmp_path / 'server.conf')
    return tmp_path / 'server.conf'

@pytest.fixture
def tmp_clients_table(tmp_path: Path):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    shutil.copyfile(Path(current_dir) / 'resources' / 'clients_table', tmp_path / 'clients_table')
    return tmp_path / 'clients_table'

@pytest.fixture
def tmp_client_cfg_with_dns(tmp_path: Path):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        shutil.copyfile(Path(current_dir) / 'resources' /  'client_cfg_to_string'  / 'cfg_with_dns.conf', tmp_path / 'cfg_with_dns.conf')
        return tmp_path / 'cfg_with_dns.conf'

@pytest.fixture
def tmp_client_cfg_without_dns(tmp_path: Path):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        shutil.copyfile(Path(current_dir) / 'resources' /  'client_cfg_to_string'  / 'cfg_without_dns.conf', tmp_path / 'cfg_without_dns.conf')
        return tmp_path / 'cfg_without_dns.conf'

@pytest.fixture
def tmp_server_preshared_key_path(tmp_path: Path):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        shutil.copyfile(Path(current_dir) / 'resources' /  'server_preshared_key', tmp_path / 'server_preshared_key')
        return tmp_path / 'server_preshared_key'

@pytest.fixture
def tmp_server_public_key_path(tmp_path: Path):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        shutil.copyfile(Path(current_dir) / 'resources' /  'server_public_key', tmp_path / 'server_public_key')
        return tmp_path / 'server_public_key'
    

@pytest.fixture
def docker_container(request: pytest.FixtureRequest, 
                     tmp_clients_table: Path, 
                     tmp_server_conf: Path,
                     tmp_server_preshared_key_path: Path,
                     tmp_server_public_key_path: Path):
    container: str | None = request.config.getoption('--docker-container')
    if not container:
        yield
        return
    
    subprocess.run(
        [
            "docker",
            "run",
            "-dit",
            "--rm",
            "--name",
            container,
            "ubuntu:latest",
            "tail",
            "-f",
            "/dev/null",
        ],
        check=True,
    )

    try:
        clients_table_file_in_docker = (tmp_clients_table, '/tmp/clients_table_tmp')
        serve_conf_file_in_docker = (tmp_server_conf, '/tmp/test_conf.conf')
        server_public_key_path_in_docker = (tmp_server_public_key_path, '/tmp/public_key')
        server_preshared_key_path_in_docker = (tmp_server_preshared_key_path, '/tmp/preshared_key')

        for _path in [clients_table_file_in_docker, serve_conf_file_in_docker, 
                    server_public_key_path_in_docker, server_preshared_key_path_in_docker]:
            subprocess.run(
                [
                    "docker",
                    "cp",
                    str(_path[0]),
                    f"{container}:{_path[1]}",
                ],
                check=True,
            )

        yield DockerContainer(
            name=container,
            conf_path=serve_conf_file_in_docker[1],
            clients_table_path=clients_table_file_in_docker[1],
            preshared_key_path=server_preshared_key_path_in_docker[1],
            public_key_path=server_public_key_path_in_docker[1]
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container],
            check=True,
        )

@pytest.fixture
def amnezia_wg_mgr(request: pytest.FixtureRequest,
                   mocker: MockerFixture, 
                   tmp_server_conf: Path, 
                   tmp_clients_table: Path,
                   tmp_server_public_key_path: Path,
                   tmp_server_preshared_key_path: Path,
                   docker_container: DockerContainer | None,
    ) -> AmneziaWgManager:
    mgr = AmneziaWgManager(
        config_path=docker_container.conf_path if docker_container else str(tmp_server_conf),
        clients_table_path=docker_container.clients_table_path if docker_container else str(tmp_clients_table),
        address=ADDRESS,
        preshared_key_path=docker_container.preshared_key_path if docker_container else str(tmp_server_preshared_key_path),
        public_key_path=docker_container.public_key_path if docker_container else str(tmp_server_public_key_path),
        cmd_executer=CmdExecutorFactory().create_cmd_execptor(docker_container=docker_container.name if docker_container else None),
        restart_command='echo restart'
    )
    mocker.patch.object(mgr, AmneziaWgManager._gen_client_keys.__name__, return_value=(CLIENT_PUBLIC_KEY, CLIENT_PRIVATE_KEY)) # type: ignore
    return mgr

def test_read_server_config(amnezia_wg_mgr: AmneziaWgManager):
    
    config = amnezia_wg_mgr.read_server_config()
    assert config.interface.ListenPort == 42919
    assert config.interface.Address == '10.8.1.0/24'
    assert config.interface.PrivateKey == 'server_private_key'
    assert config.interface.Jc == 1
    assert config.interface.Jmin == 2
    assert config.interface.Jmax == 3
    assert config.interface.S1 == 4
    assert config.interface.S2 == 5
    assert config.interface.H1 == 6
    assert config.interface.H2 == 7
    assert config.interface.H3 == 8
    assert config.interface.H4 == 9
    assert len(config.peers) == 2
    assert config.peers[0].PublicKey == 'admin_public_key'
    assert config.peers[0].PresharedKey == 'admin_preshared_key'
    assert config.peers[0].AllowedIPs == '10.8.1.1/32'
    assert config.peers[1].PublicKey == 'client_1_public_key'
    assert config.peers[1].PresharedKey == 'client_1_preshared_key'
    assert config.peers[1].AllowedIPs == '10.8.1.2/32'

def test_write_server_config(amnezia_wg_mgr: AmneziaWgManager):
    config = amnezia_wg_mgr.read_server_config()
    config.interface.ListenPort = 12345

    new_peer = ServerConfigPeer(PublicKey=CLIENT_PUBLIC_KEY,
                                PresharedKey=SERVER_PRESHARED_KEY,
                                AllowedIPs='10.10.10.10/32')
    config.peers.append(new_peer)
    amnezia_wg_mgr.write_server_config(config)
    config = amnezia_wg_mgr.read_server_config()
    assert config.interface.ListenPort == 12345
    assert config.interface.Address == '10.8.1.0/24'
    assert config.interface.PrivateKey == 'server_private_key'
    assert config.interface.Jc == 1
    assert config.interface.Jmin == 2
    assert config.interface.Jmax == 3
    assert config.interface.S1 == 4
    assert config.interface.S2 == 5
    assert config.interface.H1 == 6
    assert config.interface.H2 == 7
    assert config.interface.H3 == 8
    assert config.interface.H4 == 9
    assert len(config.peers) == 3
    assert config.peers[0].PublicKey == 'admin_public_key'
    assert config.peers[0].PresharedKey == 'admin_preshared_key'
    assert config.peers[0].AllowedIPs == '10.8.1.1/32'
    assert config.peers[1].PublicKey == 'client_1_public_key'
    assert config.peers[1].PresharedKey == 'client_1_preshared_key'
    assert config.peers[1].AllowedIPs == '10.8.1.2/32'
    assert config.peers[2].AllowedIPs == '10.10.10.10/32'
    assert config.peers[2].PresharedKey == SERVER_PRESHARED_KEY
    assert config.peers[2].PublicKey == CLIENT_PUBLIC_KEY

def test_read_clients_table(amnezia_wg_mgr: AmneziaWgManager):
    clients_table = amnezia_wg_mgr.read_clients_table()
    assert len(clients_table.root) == 2

    assert clients_table.root[0].client_id == 'admin_public_key'
    assert clients_table.root[0].allowed_ips == '10.8.1.1/32'
    assert clients_table.root[0].client_name == 'Admin [macOS 26.1]'
    assert clients_table.root[0].creation_date == 'Tue Dec 23 02:17:49 2025'
    assert clients_table.root[0].data_received == '193.93 GiB'
    assert clients_table.root[0].data_sent == '12.10 GiB'
    assert clients_table.root[0].latest_handshake == '5s ago'
    
    assert clients_table.root[1].client_id == 'client_1_public_key'
    assert clients_table.root[1].allowed_ips == '10.8.1.2/32'
    assert clients_table.root[1].client_name == 'client.1'
    assert clients_table.root[1].creation_date == 'Tue Dec 23 02:26:04 2025'
    assert clients_table.root[1].data_received == '171.52 GiB'
    assert clients_table.root[1].data_sent == '17.81 GiB'
    assert clients_table.root[1].latest_handshake == '1m, 59s ago'

def test_write_clients_table(amnezia_wg_mgr: AmneziaWgManager):
    clients_table = amnezia_wg_mgr.read_clients_table()
    
    clients_table.root[0].client_id = 'admin_public_key_changed'
    clients_table.root[0].data_sent = '12.15 GiB'
    clients_table.root[1].client_id = 'client_1_public_key_changed'
    clients_table.root[1].data_sent = '12.20 GiB'

    added_user = ClientsTableItem(
        client_id=CLIENT_PUBLIC_KEY,
        allowed_ips='10.10.10.12/32',
        client_name='added_client',
        creation_date='Creation date text',
        latest_handshake='Latest handshake text',
        data_received='data received text',
        data_sent='data sent text'
    )
    clients_table.root.append(added_user)

    amnezia_wg_mgr.write_clients_table(clients_table=clients_table)
    clients_table = amnezia_wg_mgr.read_clients_table()

    assert len(clients_table.root) == 3

    assert clients_table.root[0].client_id == 'admin_public_key_changed'
    assert clients_table.root[0].allowed_ips == '10.8.1.1/32'
    assert clients_table.root[0].client_name == 'Admin [macOS 26.1]'
    assert clients_table.root[0].creation_date == 'Tue Dec 23 02:17:49 2025'
    assert clients_table.root[0].data_received == '193.93 GiB'
    assert clients_table.root[0].data_sent == '12.15 GiB'
    assert clients_table.root[0].latest_handshake == '5s ago'
    
    assert clients_table.root[1].client_id == 'client_1_public_key_changed'
    assert clients_table.root[1].allowed_ips == '10.8.1.2/32'
    assert clients_table.root[1].client_name == 'client.1'
    assert clients_table.root[1].creation_date == 'Tue Dec 23 02:26:04 2025'
    assert clients_table.root[1].data_received == '171.52 GiB'
    assert clients_table.root[1].data_sent == '12.20 GiB'
    assert clients_table.root[1].latest_handshake == '1m, 59s ago'

    assert clients_table.root[2].client_id == CLIENT_PUBLIC_KEY
    assert clients_table.root[2].allowed_ips == '10.10.10.12/32'
    assert clients_table.root[2].client_name == 'added_client'
    assert clients_table.root[2].creation_date == 'Creation date text'
    assert clients_table.root[2].data_received == 'data received text'
    assert clients_table.root[2].data_sent == 'data sent text'
    assert clients_table.root[2].latest_handshake == 'Latest handshake text'

def test_add_client(amnezia_wg_mgr: AmneziaWgManager):
    new_clients: list[tuple[str,str|None,int, str]] = [
        ('client_1', '1.1.1.1', 10, '10.8.1.3/32'),
        ('client_2', None, 25, '10.8.1.4/32'),
        ('client_3', '8.8.8.8', 30, '10.8.1.5/32')
    ]
    server_config = amnezia_wg_mgr.read_server_config()
    for i in range(len(new_clients)):
        client_name, dns, presented_keep_alive, expected_address = new_clients[i][0], new_clients[i][1], new_clients[i][2], new_clients[i][3]
        client_config = amnezia_wg_mgr.add_client(client_name=client_name, dns=dns, presented_keep_alive=presented_keep_alive)
        assert client_config.interface.Address == expected_address
        assert client_config.interface.Jc == 1
        assert client_config.interface.Jmin == 2
        assert client_config.interface.Jmax == 3
        assert client_config.interface.S1 == 4
        assert client_config.interface.S2 == 5
        assert client_config.interface.H1 == 6
        assert client_config.interface.H2 == 7
        assert client_config.interface.H3 == 8
        assert client_config.interface.H4 == 9
        assert client_config.interface.PrivateKey == CLIENT_PRIVATE_KEY
        assert client_config.interface.DNS == dns

        assert client_config.peer.PublicKey == SERVER_PUBLIC_KEY
        assert client_config.peer.AllowedIPs == '0.0.0.0/0, ::/0'
        assert client_config.peer.PresharedKey == SERVER_PRESHARED_KEY
        assert client_config.peer.PersistentKeepalive == presented_keep_alive
        assert client_config.peer.Endpoint == f"{amnezia_wg_mgr.address}:{server_config.interface.ListenPort}"

    server_config = amnezia_wg_mgr.read_server_config()
    clients_table = amnezia_wg_mgr.read_clients_table()
    
    assert len(server_config.peers) == 5
    assert len(clients_table.root) == 5

    for i in range(len(new_clients)):
        index = 2 + i
        client_name, dns, presented_keep_alive, expected_address = new_clients[i][0], new_clients[i][1], new_clients[i][2], new_clients[i][3]
        
        assert server_config.peers[index].AllowedIPs == expected_address
        assert server_config.peers[index].PublicKey == CLIENT_PUBLIC_KEY
        assert server_config.peers[index].PresharedKey == SERVER_PRESHARED_KEY

        assert clients_table.root[index].client_id == CLIENT_PUBLIC_KEY
        assert clients_table.root[index].allowed_ips == expected_address
        assert clients_table.root[index].client_name == client_name

def test_add_client_with_existed_name(amnezia_wg_mgr: AmneziaWgManager):
    with pytest.raises(RuntimeError, match='Client "client.1" already exist'):
        amnezia_wg_mgr.add_client(client_name='client.1')

def test_delete_client_by_name(amnezia_wg_mgr: AmneziaWgManager):
    amnezia_wg_mgr.delete_client(client_name_or_public_key='client.1')
    server_config = amnezia_wg_mgr.read_server_config()
    clients_table = amnezia_wg_mgr.read_clients_table()
    assert len(server_config.peers) == 1
    assert len(clients_table.root) == 1
    assert server_config.peers[0].PublicKey == 'admin_public_key'

def test_delete_client_by_icorrect_name(amnezia_wg_mgr: AmneziaWgManager):
    with pytest.raises(RuntimeError, match=f'Client "client..1" does not exist'):
        amnezia_wg_mgr.delete_client(client_name_or_public_key='client..1')
    
    server_config = amnezia_wg_mgr.read_server_config()
    clients_table = amnezia_wg_mgr.read_clients_table()
    assert len(server_config.peers) == 2
    assert len(clients_table.root) == 2

def test_delete_client_by_icorrect_key(amnezia_wg_mgr: AmneziaWgManager):
    with pytest.raises(RuntimeError, match=f'Client "admni_public_key" does not exist'):
        amnezia_wg_mgr.delete_client(client_name_or_public_key='admni_public_key')
    
    server_config = amnezia_wg_mgr.read_server_config()
    clients_table = amnezia_wg_mgr.read_clients_table()
    assert len(server_config.peers) == 2
    assert len(clients_table.root) == 2

def test_delete_client_by_public_key(amnezia_wg_mgr: AmneziaWgManager):
    amnezia_wg_mgr.delete_client('admin_public_key')
    server_config = amnezia_wg_mgr.read_server_config()
    clients_table = amnezia_wg_mgr.read_clients_table()
    assert len(server_config.peers) == 1
    assert len(clients_table.root) == 1
    assert server_config.peers[0].PublicKey == 'client_1_public_key'

@pytest.mark.parametrize('dns', ['10.10.10.10', None])
def test_client_config_to_string(amnezia_wg_mgr: AmneziaWgManager, dns: str | None, tmp_client_cfg_with_dns: Path, tmp_client_cfg_without_dns: Path):
    config = amnezia_wg_mgr.add_client(client_name='client_1', dns=dns)
    res = config.to_str()
    if dns:
        with open(tmp_client_cfg_with_dns) as f:
            data = f.read()
            assert data == res
    else:
        with open(tmp_client_cfg_without_dns) as f:
            data = f.read()
            assert data == res
