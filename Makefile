.PHONY: install migrate migrate-test test test-unit test-integration test-concurrency \
        test-failure seed run dev simulate simulate-all load-test clean help

PYTHON := python
PYTEST := $(PYTHON) -m pytest
ALEMBIC := $(PYTHON) -m alembic
UVICORN := $(PYTHON) -m uvicorn

help:
	@echo "SmartDialer — available targets:"
	@echo "  install          Install dependencies"
	@echo "  migrate          Run alembic migrations on main DB"
	@echo "  migrate-test     Create smartdialer_test DB and run migrations"
	@echo "  test             Run all tests"
	@echo "  test-unit        Run unit tests only"
	@echo "  test-integration Run integration tests only"
	@echo "  test-concurrency Run concurrency tests only"
	@echo "  test-failure     Run failure scenario tests only"
	@echo "  seed             Seed demo data"
	@echo "  run              Start FastAPI server"
	@echo "  dev              Start server with hot reload"
	@echo "  simulate         Run all 4 scenarios (progressive + predictive)"
	@echo "  load-test        Run load test (10 workers, 30s, 50 agents)"
	@echo "  clean            Remove __pycache__ and .pyc files"

install:
	pip install -r requirements.txt

migrate:
	$(ALEMBIC) upgrade head

migrate-test:
	$(PYTHON) -c "import psycopg2; c = psycopg2.connect(host='localhost',port=5432,user='postgres',password='Sharkesh@#10',dbname='postgres'); c.autocommit=True; cur=c.cursor(); cur.execute(\"SELECT 1 FROM pg_database WHERE datname='smartdialer_test'\"); exists=cur.fetchone(); cur.execute('CREATE DATABASE smartdialer_test') if not exists else None; c.close(); print('smartdialer_test ready')"

test:
	$(PYTEST) tests/ -v --tb=short -x

test-unit:
	$(PYTEST) tests/unit/ -v --tb=short

test-integration:
	$(PYTEST) tests/integration/ -v --tb=short

test-concurrency:
	$(PYTEST) tests/concurrency/ -v --tb=short

test-failure:
	$(PYTEST) tests/failure/ -v --tb=short

seed:
	$(PYTHON) scripts/seed_demo.py

run:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000

dev:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

simulate:
	$(PYTHON) scripts/run_simulation.py --scenario all --mode progressive --agents 10 --ticks 120

simulate-a:
	$(PYTHON) scripts/run_simulation.py --scenario A --mode progressive --agents 10 --ticks 120

simulate-b:
	$(PYTHON) scripts/run_simulation.py --scenario B --mode predictive --agents 10 --ticks 120

simulate-c:
	$(PYTHON) scripts/run_simulation.py --scenario C --mode predictive --agents 10 --ticks 120

simulate-d:
	$(PYTHON) scripts/run_simulation.py --scenario D --mode predictive --agents 10 --ticks 120

load-test:
	$(PYTHON) scripts/run_load_test.py --workers 10 --duration 30 --agents 50

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null; true
