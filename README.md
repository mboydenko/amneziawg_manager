# amneziawg-manager-cli

CLI for managing AmneziaWG clients: add, remove, and list peers in the server config and Amnezia `clientsTable`.

## Install

```bash
poetry install
```

Or install the console script globally:

```bash
poetry build
pip install dist/amneziawg_manager_cli-*.whl
```

## Usage

```bash
poetry run amneziawg-manager-cli add /path/to/wg0.conf --endpoint vpn.example.com:51820 --name user1
poetry run amneziawg-manager-cli list /path/to/wg0.conf
poetry run amneziawg-manager-cli delete /path/to/wg0.conf --name user1 --remove-config
```

With Docker:

```bash
poetry run amneziawg-manager-cli add /opt/amnezia/wg0.conf \
  --docker-container amnezia-awg \
  --endpoint vpn.example.com:51820 \
  --name maxim.iphone \
  --reload
```

Full documentation: [doc.txt](doc.txt).
