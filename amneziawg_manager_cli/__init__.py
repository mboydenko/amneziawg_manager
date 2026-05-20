"""AmneziaWG client configuration manager.

This package exposes a small programmatic API so other projects can
import high-level functions directly from the package root, e.g.:

	from amneziawg_manager_cli import create_client, RuntimeOptions

The original CLI entry points remain available under
``amneziawg_manager_cli.cli``.
"""

__version__ = "0.1.0"

# Re-export public API from the CLI implementation for library use.
from .cli import (
	ServerConfig,
	RuntimeOptions,
	parse_config,
	serialize_config,
	create_client,
	delete_client,
	list_clients,
	build_client_config,
	generate_private_key,
	generate_public_key,
	generate_preshared_key,
	client_config_public_key,
	lookup_client_public_key,
	lookup_client_config_path,
	lookup_client_name,
)

__all__ = [
	"__version__",
	"ServerConfig",
	"RuntimeOptions",
	"parse_config",
	"serialize_config",
	"create_client",
	"delete_client",
	"list_clients",
	"build_client_config",
	"generate_private_key",
	"generate_public_key",
	"generate_preshared_key",
	"client_config_public_key",
	"lookup_client_public_key",
	"lookup_client_config_path",
	"lookup_client_name",
]