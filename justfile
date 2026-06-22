set dotenv-load := true

sync:
    uv sync --all-extras

fetch-models *args:
    uv run mdb-sync models {{args}}

lint:
    uv run ruff check src tests

format:
    uv run ruff format src tests

typecheck:
    uv run basedpyright src tests

test:
    uv run pytest tests -v

check: lint typecheck test

clean:
    rm -rf build/ dist/ .pytest_cache/ .ruff_cache/ .basedpyright/ htmlcov/

