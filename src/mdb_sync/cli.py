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
DIAGNOSTIC_PATHS = (
    ("/v2/models/count", None),
    ("/v2/models/", None),
    ("/v2/models/", {"skip": 0}),
    ("/v2/models/", {"limit": 0}),
    ("/v2/models/", {"skip": 0, "limit": 0}),
    ("/v2/models/", {"skip": 0, "limit": 10}),
    ("/v2/tags/count", None),
    ("/docs", None),
    ("/openapi.json", None),
)


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
        default=None,
        help="Maximum models to request. Omit to use the API default.",
    )
    subparsers.add_parser(
        "diagnose",
        help="Probe STS endpoint shapes and print status/body snippets for troubleshooting.",
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
        "--profile",
        choices=("first-pass", "comprehensive"),
        default="first-pass",
        help=(
            "Capture depth. first-pass skips high-volume term-detail, tag, CDE PV, "
            "and id lookups; comprehensive attempts all discoverable endpoints."
        ),
    )
    capture_parser.add_argument(
        "--include-term-details",
        action="store_true",
        help="Fetch every /term/{value} detail. This can add hundreds of thousands of requests.",
    )
    capture_parser.add_argument(
        "--include-tags",
        action="store_true",
        help="Capture tags, tag values, and tagged entities.",
    )
    capture_parser.add_argument(
        "--include-ids",
        action="store_true",
        help="Fetch /v2/id/{nanoid} for every discovered nanoid.",
    )
    capture_parser.add_argument(
        "--include-cde-pvs",
        action="store_true",
        help="Capture CDE permissible values discovered from term origin IDs.",
    )
    capture_parser.add_argument(
        "--skip-model-pvs",
        action="store_true",
        help="Skip /v2/terms/model-pvs/{model}/{property} calls.",
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


def _body_snippet(response_text: str, *, limit: int = 500) -> str:
    compact = " ".join(response_text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _run_diagnostics(base_url: str) -> int:
    import httpx

    exit_code = 0
    with httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=30.0,
        follow_redirects=True,
        headers={"Accept": "application/json", "User-Agent": "mdb-sync/0.1.0"},
    ) as client:
        for path, params in DIAGNOSTIC_PATHS:
            try:
                response = client.get(path, params=params)
            except httpx.RequestError as error:
                exit_code = 1
                print(f"ERROR {path} params={params}: {type(error).__name__}: {error}")
                continue

            if response.status_code >= 500:
                exit_code = 1
            print(
                json.dumps(
                    {
                        "path": path,
                        "params": params,
                        "url": str(response.url),
                        "status_code": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "body_snippet": _body_snippet(response.text),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "diagnose":
            return _run_diagnostics(args.base_url)

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
            crawler: STSCrawler | None = None
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
                    comprehensive = args.profile == "comprehensive"
                    crawler = STSCrawler(
                        recording_client,
                        page_size=args.page_size,
                        capture_term_details=comprehensive or args.include_term_details,
                        capture_tags=comprehensive or args.include_tags,
                        capture_ids=comprehensive or args.include_ids,
                        capture_cde_pvs=comprehensive or args.include_cde_pvs,
                        capture_model_pvs=not args.skip_model_pvs,
                    )
                    inventory = crawler.run()
            except KeyboardInterrupt:
                reason = "Capture interrupted by the operator."
                writer.record_skip(
                    endpoint="capture",
                    reason=reason,
                )
                inventory = (
                    crawler.current_inventory(incomplete_reason=reason)
                    if crawler is not None
                    else {"incomplete": True, "reason": reason}
                )
                exit_code = 130
            except Exception as error:
                reason = f"{type(error).__name__}: {error}"
                writer.record_skip(
                    endpoint="capture",
                    reason=f"Fatal crawler error: {reason}",
                )
                inventory = (
                    crawler.current_inventory(incomplete_reason=reason)
                    if crawler is not None
                    else {"incomplete": True, "reason": reason}
                )
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
