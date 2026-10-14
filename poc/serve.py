"""Deployment launcher with explicit proxy trust and privacy-preserving logs."""

import argparse
import ipaddress

import uvicorn

from .runtime import RuntimeConfig
from .server import create_app


LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"default": {"format": "%(levelname)s %(name)s %(message)s"}},
    "handlers": {"stderr": {"class": "logging.StreamHandler", "formatter": "default"}},
    "loggers": {
        "arm_search": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
        "uvicorn": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
        # HTTP client informational logs contain KB URLs including user queries.
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}


def trusted_proxies(value):
    parts = value.split(",") if value else []
    for part in parts:
        try:
            network = ipaddress.ip_network(part.strip(), strict=False)
            if network.prefixlen == 0:
                raise ValueError(
                    "All-address networks are not trusted proxy boundaries"
                )
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                "Proxy trust requires explicit IPs/CIDRs; wildcard trust is forbidden"
            ) from exc
    return ",".join(part.strip() for part in parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root-path", default="")
    parser.add_argument("--proxy-allow-ips", type=trusted_proxies, default="")
    args = parser.parse_args()
    config = RuntimeConfig.from_env()
    if args.host not in ("127.0.0.1", "localhost", "::1") and not config.public_origin:
        parser.error("Non-loopback listeners require ARM_SEARCH_PUBLIC_ORIGIN")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    if args.root_path and (
        not args.root_path.startswith("/") or args.root_path.endswith("/")
    ):
        parser.error("Root path must start with / and have no trailing /")
    uvicorn.run(
        create_app(config=config),
        host=args.host,
        port=args.port,
        root_path=args.root_path,
        proxy_headers=bool(args.proxy_allow_ips),
        forwarded_allow_ips=args.proxy_allow_ips,
        workers=1,
        access_log=False,
        log_config=LOG_CONFIG,
        server_header=False,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=15,
        h11_max_incomplete_event_size=16384,
    )


if __name__ == "__main__":
    main()
