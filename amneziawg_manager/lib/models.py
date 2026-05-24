from abc import ABC
from typing import ClassVar

from pydantic import BaseModel, model_serializer, model_validator, RootModel


class WgSection(ABC,BaseModel):

    __section_name__: ClassVar[str]

    @classmethod
    def from_str(cls, config_str: str) -> 'InterfaceBaseModel': # type: ignore
        if not config_str.startswith(cls.__section_name__):
            raise ValueError(f'Expected config to start with {cls.__section_name__}, got {config_str[:len(cls.__section_name__)]}')
        
        options = {}
        for line in config_str.splitlines():
            if '=' not in line:
                continue
            if line.startswith('#'):
                continue
            key, value = line.split('=', 1)
            options[key.strip()] = value.strip()
        return cls(**options) # type: ignore
    
    def dump_str(self) -> str:
        config_str = f'{self.__section_name__}\n'
        for key, value in self.model_dump().items():
            if value is None:
                continue
            config_str += f'{key} = {value}\n'
        return config_str

class InterfaceBaseModel(WgSection):

    __section_name__ = '[Interface]'

    Address: str
    PrivateKey: str
    Jc: int
    Jmin: int
    Jmax: int
    S1: int
    S2: int
    H1: int
    H2: int
    H3: int
    H4: int

class PeerBaseModel(WgSection):
    __section_name__ = '[Peer]'
    
    PublicKey: str
    PresharedKey: str
    AllowedIPs: str

class ServerInterface(InterfaceBaseModel):
    ListenPort: int

class ClientInterface(InterfaceBaseModel):
    DNS: str | None = None

class ServerConfigPeer(PeerBaseModel):
    ...

class ClientConfigPeer(PeerBaseModel):
    Endpoint: str
    PersistentKeepalive: int

class ServerConfig(BaseModel):
    interface: ServerInterface
    peers: list[ServerConfigPeer]

    @staticmethod    
    def from_str(config_str: str) -> 'ServerConfig': # type: ignore
        interface = None
        peers: list[ServerConfigPeer] = []
        items = config_str.split('\n\n')
        for item in items:
            for item_line in item.splitlines():
                if item_line.startswith('[Interface]'):
                    interface = ServerInterface.from_str(item)
                elif item_line.startswith('[Peer]'):
                    peer = ServerConfigPeer.from_str(item)
                    if not isinstance(peer, ServerConfigPeer):
                        raise ValueError(f'Expected ServerConfigPeer, got {type(peer)}')
                    peers.append(peer)
        return ServerConfig(interface=interface, peers=peers) # type: ignore

    def to_str(self) -> str:
        return "\n".join([self.interface.dump_str()] + [peer.dump_str() for peer in self.peers])

    def get_next_client_ip(self) -> str:
        current_clients: list[int] = []
        for peer in self.peers:
            last_octet = int(peer.AllowedIPs.split('/')[0].split('.')[3])
            current_clients.append(last_octet)
        client_last_octet = max(current_clients) + 1
        server_address_octets = self.interface.Address.split('/')[0].split('.')
        server_address_octets[-1] = str(client_last_octet)
        return '.'.join(server_address_octets)

class ClientConfig(BaseModel):

    interface: ClientInterface
    peer: ClientConfigPeer

    @staticmethod    
    def from_str(config_str: str) -> 'ClientConfig': # type: ignore
        interface = None
        peer = None
        items = config_str.split('\n\n')
        for item in items:
            for item_line in item.splitlines():
                if item_line.startswith('[Interface]'):
                    interface = ClientInterface.from_str(item)
                elif item_line.startswith('[Peer]'):
                    peer = ClientConfigPeer.from_str(item)
                    if not isinstance(peer, ClientConfigPeer):
                        raise ValueError(f'Expected ClientConfigPeer, got {type(peer)}')
        return ClientConfig(interface=interface, peer=peer) # type: ignore

    def to_str(self) -> str:
        return self.interface.dump_str() + '\n' + self.peer.dump_str()

class ClientsTableItem(BaseModel):
    client_id: str
    allowed_ips: str
    client_name: str
    creation_date: str
    data_received: str
    data_sent: str
    latest_handshake: str

    @model_validator(mode='before')
    @classmethod
    def flatten_user_data(cls, data: dict[str, str | int]) -> dict[str, str | int]:
        if not isinstance(data, dict): # type: ignore
            return data
        
        if 'userData' not in data:
            return data

        user_data = data.get('userData')

        return {
            'client_id': data.get('clientId'), # type: ignore
            'allowed_ips': user_data.get('allowedIps'), # type: ignore
            'client_name': user_data.get('clientName'), # type: ignore
            'creation_date': user_data.get('creationDate'), # type: ignore
            'data_received': user_data.get('dataReceived'), # type: ignore
            'data_sent': user_data.get('dataSent'), # type: ignore
            'latest_handshake': user_data.get('latestHandshake'), # type: ignore
        }

    @model_serializer(mode='wrap')
    def serialize(self, handler): # type: ignore
        return {
            'clientId': self.client_id,
            'userData': {
                'allowedIps': self.allowed_ips,
                'clientName': self.client_name,
                'creationDate': self.creation_date,
                'dataReceived': self.data_received,
                'dataSent': self.data_sent,
                'latestHandshake': self.latest_handshake,
            }
        } # type: ignore

ClientsTable = RootModel[list[ClientsTableItem]]
