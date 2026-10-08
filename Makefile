.PHONY: test backend-test demo-test frontend-build live-verify abstract

PYTHON ?= python3

test: backend-test demo-test frontend-build

backend-test:
	cd backend && $(PYTHON) -m pytest

demo-test:
	cd demo-services && $(PYTHON) -m pytest

frontend-build:
	cd frontend && npm run build

live-verify:
	$(PYTHON) scripts/verify_live_stack.py

abstract:
	$(PYTHON) docs/generate_abstract.py
