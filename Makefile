.PHONY: test test-coverage test-fast lint build check publish-test publish clean-dist

test:
	python -m pytest tests/ -v --tb=short

test-coverage:
	python -m pytest tests/ -v --tb=short --cov=skjalf --cov-report=html --cov-report=term-missing

test-fast:
	python -m pytest tests/ -v --tb=short -m "not slow and not gui"

lint:
	python -m ruff check skjalf/ tests/

build:
	rm -rf dist/ build/ skjalf.egg-info
	python3 -m build

check:
	python3 -m twine check dist/*

publish-test:
	python3 -m twine upload --repository testpypi dist/*

publish:
	python3 -m twine upload dist/*

clean-dist:
	rm -rf dist/ build/ skjalf.egg-info
