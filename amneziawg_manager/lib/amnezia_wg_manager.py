import json
from datetime import datetime

from amneziawg_manager.lib.utils.cmd_executer.protocols.cmd_executor import CmdExecutor
from amneziawg_manager.lib.utils.logger import Logger

from amneziawg_manager.lib.models import (
    ServerConfig, ClientsTable, ClientConfig, ClientInterface, 
    ClientConfigPeer, ClientsTableItem, ServerConfigPeer
)


_logger = Logger('AmneziaWgManager')


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

class AmneziaWgManager:

    def __init__(self, 
                 config_path: str, 
                 clients_table_path: str,
                 preshared_key_path: str,
                 address: str,
                 restart_command: str,
                 cmd_executer: CmdExecutor):
        self.clients_table_path = clients_table_path
        self.config_path = config_path
        self.cmd_executor = cmd_executer
        self.address = address
        self.restart_command = restart_command
        self.preshared_key_path = preshared_key_path

    @_logger.log_function()
    def read_server_config(self) -> ServerConfig:
        cmd = f'cat {self.config_path}'
        res = self.cmd_executor.exec_cmd(cmd)
        _logger.debug(f'Server config:\n{res.stdout}')
        return ServerConfig.from_str(res.stdout)

    @_logger.log_function()
    def write_server_config(self, config: ServerConfig):
        self.cmd_executor.exec_cmd(
            cmd=f'cat > {self.config_path}',
            stdin=config.to_str()
        )

    @_logger.log_function()
    def restart_server(self):
        self.cmd_executor.exec_cmd(self.restart_command)

    @_logger.log_function()
    def read_clients_table(self) -> ClientsTable:
        cmd = f'cat {self.clients_table_path}'
        result = self.cmd_executor.exec_cmd(cmd)
        _logger.debug(f'Clients table:\n{result.stdout}')
        return ClientsTable(json.loads(result.stdout))

    @_logger.log_function()
    def write_clients_table(self, clients_table: ClientsTable):
        self.cmd_executor.exec_cmd(
            cmd=f'cat > {self.clients_table_path}',
            stdin=json.dumps(clients_table.model_dump())
        )
        
    @_logger.log_function()
    def add_client(self, 
                   client_name: str, 
                   dns: str | None = None, 
                   allowed_ips: str = "0.0.0.0/0, ::/0",
                   presented_keep_alive: int = 25) -> ClientConfig:
        
        client_name = client_name.strip()

        if self._does_client_with_name_exist(client_name=client_name):
            raise RuntimeError(f'Client "{client_name}" already exist')

        server_config = self.read_server_config()
        server_address = f"{self.address}:{server_config.interface.ListenPort}"
        client_address = server_config.get_next_client_ip() + '/32'
        pub_key, private_key, presh_key = self._gen_keys()
        client_peer = ClientConfigPeer(
            AllowedIPs=allowed_ips,
            Endpoint=server_address,
            PersistentKeepalive=presented_keep_alive,
            PresharedKey=presh_key,
            PublicKey=pub_key
        )
        client_interface = ClientInterface(
            Address=client_address,
            DNS=dns,
            PrivateKey=private_key,
            Jc=server_config.interface.Jc,
            Jmin=server_config.interface.Jmin,
            Jmax=server_config.interface.Jmax,
            S1=server_config.interface.S1,
            S2=server_config.interface.S2,
            H1=server_config.interface.H1,
            H2=server_config.interface.H2,
            H3=server_config.interface.H3,
            H4=server_config.interface.H4
        )
        client_config = ClientConfig(
            interface=client_interface,
            peer=client_peer
        )
        clients_table = self.read_clients_table()
        creation_date = datetime.now()
        clients_table_item = ClientsTableItem(
            client_id=client_config.peer.PublicKey,
            allowed_ips=client_config.interface.Address,
            client_name=client_name,
            data_received="",
            data_sent="",
            latest_handshake="",
            creation_date="{} {} {} {} {}".format(
                _AMNEZIA_WEEKDAYS[creation_date.weekday()],
                _AMNEZIA_MONTHS[creation_date.month],
                creation_date.day,
                creation_date.strftime("%H:%M:%S"),
                creation_date.year
            )
        )
        server_confg_peer = ServerConfigPeer(
            PublicKey=pub_key,
            PresharedKey=presh_key,
            AllowedIPs=client_address
        )
        clients_table.root.append(clients_table_item)
        server_config.peers.append(server_confg_peer)
        self.write_server_config(config=server_config)
        self.write_clients_table(clients_table=clients_table)
        self.restart_server()
        return client_config

    @_logger.log_function()
    def delete_client(self, client_name_or_public_key: str) -> None:
        public_key = ""
        if self._does_client_with_name_exist(client_name_or_public_key):
            public_key = self._get_client_public_key_by_name(client_name_or_public_key)
        else:
            public_key = client_name_or_public_key
    
        if not self._does_client_with_key_exist(public_key=public_key):
            raise RuntimeError(f'Client "{client_name_or_public_key}" does not exist')
        
        server_config = self.read_server_config()
        server_clients_table = self.read_clients_table()

        for client_peer in server_config.peers:
            if client_peer.PublicKey == public_key:
                server_config.peers.remove(client_peer)
                break
        else:
            raise RuntimeError(f'Client with key "{public_key}" not found')
        
        for item in server_clients_table.root:
            if item.client_id == public_key:
                server_clients_table.root.remove(item)
                break
        else:
            raise RuntimeError("Error of Client inforamtion deletion")

        self.write_clients_table(clients_table=server_clients_table)
        self.write_server_config(config=server_config)

        self.restart_server()

    @_logger.log_function()
    def get_clients(self) -> list[dict]: # type: ignore
        clients = []
        server_config = self.read_server_config()
        clients_info = self.read_clients_table().root
        for peer in server_config.peers:
            data = {}
            data['PublicKey'] = peer.PublicKey
            data['AllowedIps'] = peer.AllowedIPs
            for info in clients_info:
                if info.client_id != peer.PublicKey:
                    continue
                data['clientName'] = info.client_name
                data['creationDate'] = info.creation_date
                data['dataReceived'] = info.data_received
                data['dataSent'] = info.data_sent
                data['latestHandshake'] = info.latest_handshake
            clients.append(data) # type: ignore
        return clients # type: ignore

    @_logger.log_function()
    def _does_client_with_name_exist(self, client_name: str) -> bool:
        for client in self.read_clients_table().root:
                if client.client_name == client_name:
                    return True
        return False

    @_logger.log_function()
    def _get_client_public_key_by_name(self, client_name: str) -> str:
        for client in self.read_clients_table().root:
            if client.client_name == client_name:
                return client.client_id
        raise RuntimeError(f'Client "{client_name}" not found')

    @_logger.log_function()
    def _does_client_with_key_exist(self, public_key: str) -> bool:
        for peer in self.read_server_config().peers:
            if peer.PublicKey == public_key:
                return True
        return False

    @_logger.log_function()
    def _get_client_info(self, public_key: str) -> ClientsTableItem | None:
        for item in self.read_clients_table().root:
            if item.client_id == public_key:
                return item
        return None

    @_logger.log_function()
    def _gen_keys(self) -> tuple[str,str,str]:
        """
        Return tuple: public, privet, preshared 
        """
        tmp_dir = f"~/{datetime.now().strftime('%Y%m%d%H%M%S')}_tmp"
        self.cmd_executor.exec_cmd(f'mkdir {tmp_dir}')
        try:
            self.cmd_executor.exec_cmd(f'umask 077 && wg genkey > {tmp_dir}/private.key')
            private_key = self.cmd_executor.exec_cmd(f'cat {tmp_dir}/private.key').stdout.strip()
            public_key = self.cmd_executor.exec_cmd(f'wg pubkey < {tmp_dir}/private.key').stdout.strip()
            preshared_key = self.cmd_executor.exec_cmd(f'cat {self.preshared_key_path}').stdout.strip()
            return (public_key, private_key, preshared_key)
        except Exception as e:
            _logger.error(str(e.__traceback__))
            raise e
        finally:
            self.cmd_executor.exec_cmd(f'rm -r {tmp_dir}')
