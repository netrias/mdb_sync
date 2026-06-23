set dotenv-load := true

sync:
    uv sync --all-extras --no-editable

fetch-models *args:
    uv run --no-editable mdb-sync models {{args}}

capture *args:
    uv run --no-editable mdb-sync capture {{args}}

lint:
    uv run --no-editable ruff check src tests

format:
    uv run --no-editable ruff format src tests

typecheck:
    uv run --no-editable basedpyright src tests

test:
    uv run --no-editable pytest tests -v

check: lint typecheck test

clean:
    rm -rf build/ dist/ .pytest_cache/ .ruff_cache/ .basedpyright/ htmlcov/
