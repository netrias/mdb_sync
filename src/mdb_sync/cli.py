"""Command-line entry point for probing the STS API."""

import argparse
import json
import os
import sys
from collections.abc import Sequence

from mdb_sync.client import STSClient, STSClientError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read data from the MDB STS API.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("MDB_API_BASE_URL"),
        help="STS base URL. Defaults to MDB_API_BASE_URL.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    models_parser = subparsers.add_parser("models", help="List available MDB models.")
    models_parser.add_argument("--skip", type=int, default=0)
    models_parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum models to request; zero uses the API default.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.base_url:
        print(
            "error: provide --base-url or set MDB_API_BASE_URL",
            file=sys.stderr,
        )
        return 2

    try:
        with STSClient(args.base_url) as client:
            models = client.list_models(skip=args.skip, limit=args.limit)
    except (STSClientError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    payload = [model.model_dump(mode="json") for model in models]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
