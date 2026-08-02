.PHONY: install test coverage format lint typecheck quality security schemas fixtures package-manifest doctor build verify clean

install:
	python -m pip install -e '.[recorder,evaluator,test,dev]'

test:
	pytest

coverage:
	pytest --cov=daybreak --cov=daybreak_analytics --cov=daybreak_contracts --cov=daybreak_evaluator --cov=daybreak_execution --cov=daybreak_features --cov=daybreak_operations --cov=daybreak_orchestration --cov=daybreak_recorder --cov=daybreak_release --cov=daybreak_risk --cov-branch --cov-report=term-missing --cov-fail-under=80

format:
	ruff format .

lint:
	ruff format --check .
	ruff check .

typecheck:
	mypy daybreak daybreak_*

quality: lint typecheck test

security:
	bandit -r daybreak daybreak_analytics daybreak_contracts daybreak_evaluator daybreak_execution daybreak_features daybreak_operations daybreak_orchestration daybreak_recorder daybreak_release daybreak_risk --severity-level medium --confidence-level medium
	python scripts/check_secrets.py
	pip-audit --skip-editable

schemas:
	python scripts/generate_schemas.py

fixtures:
	python scripts/generate_fixtures.py

package-manifest:
	python scripts/generate_package_manifest.py

doctor:
	daybreak doctor --config config/daybreak.example.toml

build:
	python -m build
	python -m twine check dist/*

verify: quality coverage security build

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
