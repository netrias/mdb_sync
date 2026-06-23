"""Command-line entry point for probing the STS API."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from mdb_sync.capture import CaptureResult, CaptureWriter, RecordingSTSClient
from mdb_sync.client import STSClient, STSClientError
from mdb_sync.crawler import STSCrawler

DEFAULT_BASE_URL = "https://sts.cancer.gov"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read data from the MDB STS API.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("MDB_API_BASE_URL", DEFAULT_BASE_URL),
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
    capture_parser = subparsers.add_parser(
        "capture",
        help="Traverse discoverable v2 resources and create an offline capture archive.",
    )
    capture_parser.add_argument(
        "--output",
        type=Path,
        default=Path("captures"),
        help="Parent directory for the timestamped capture and ZIP archive.",
    )
    capture_parser.add_argument("--page-size", type=int, default=100)
    capture_parser.add_argument("--timeout", type=float, default=120.0)
    capture_parser.add_argument("--retries", type=int, default=3)
    capture_parser.add_argument(
        "--retry-backoff",
        type=float,
        default=1.0,
        help="Initial exponential retry delay in seconds.",
    )
    capture_parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Optional delay in seconds after every request.",
    )
    capture_parser.add_argument(
        "--openapi",
        type=Path,
        default=Path("openapi.json"),
        help="OpenAPI file copied into the capture when present.",
    )
    capture_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-request progress output.",
    )
    return parser


def _print_progress(result: CaptureResult) -> None:
    status = result.status_code if result.status_code is not None else "ERROR"
    print(
        f"[{result.sequence:06d}] {status} {result.endpoint} {result.path}",
        file=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "models":
            with STSClient(args.base_url) as client:
                models = client.list_models(skip=args.skip, limit=args.limit)
            payload = [model.model_dump(mode="json") for model in models]
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if args.command == "capture":
            writer = CaptureWriter(
                args.output,
                base_url=args.base_url,
                page_size=args.page_size,
                source_openapi=args.openapi,
            )
            print(f"Capturing STS v2 responses under {writer.root}", file=sys.stderr)
            exit_code = 0
            try:
                with STSClient(args.base_url, timeout_seconds=args.timeout) as client:
                    recording_client = RecordingSTSClient(
                        client,
                        writer,
                        retries=args.retries,
                        retry_backoff_seconds=args.retry_backoff,
                        delay_seconds=args.delay,
                        progress=None if args.quiet else _print_progress,
                    )
                    inventory = STSCrawler(
                        recording_client,
                        page_size=args.page_size,
                    ).run()
            except KeyboardInterrupt:
                writer.record_skip(
                    endpoint="capture",
                    reason="Capture interrupted by the operator.",
                )
                inventory = {
                    "incomplete": True,
                    "reason": "Capture interrupted by the operator.",
                }
                exit_code = 130
            except Exception as error:
                writer.record_skip(
                    endpoint="capture",
                    reason=f"Fatal crawler error: {type(error).__name__}: {error}",
                )
                inventory = {
                    "incomplete": True,
                    "reason": f"{type(error).__name__}: {error}",
                }
                exit_code = 1
            writer.write_inventory(inventory)
            capture_dir, archive = writer.finalize()
            print(f"Capture directory: {capture_dir}")
            print(f"Return this archive: {archive}")
            return exit_code
    except (STSClientError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
