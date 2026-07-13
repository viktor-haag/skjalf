.PHONY: test test-coverage test-fast lint

test:
	python -m pytest tests/ -v --tb=short

test-coverage:
	python -m pytest tests/ -v --tb=short --cov=skjalf --cov-report=html --cov-report=term-missing

test-fast:
	python -m pytest tests/ -v --tb=short -m "not slow and not gui"

lint:
	python -m ruff check skjalf/ tests/
