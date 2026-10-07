PYTHON ?= python3
FIXTURE := tests/fixtures/ac1.jsonl

.PHONY: run lint fmt test smoke release

run: ## executa o analyzer sobre a fixture de exemplo
	./app summary $(FIXTURE)

lint: ## roda o linter (ruff, com fallback para compilação)
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check app src tests; \
	else \
		$(PYTHON) -m compileall -q app src tests; \
		echo "ruff ausente: apenas compileall executado"; \
	fi

fmt: ## formata o código
	@if command -v ruff >/dev/null 2>&1; then \
		ruff format app src tests && ruff check --fix app src tests; \
	else \
		echo "ruff ausente: nada a formatar"; \
	fi

test: ## roda os testes caixa-preta
	$(PYTHON) -m unittest discover -s tests/blackbox -t tests/blackbox -v

smoke: ## valida o caminho feliz end-to-end
	./app summary --json $(FIXTURE) | $(PYTHON) -c "import json,sys;\
d=json.load(sys.stdin);\
assert d['command']=='summary' and d['total']==5 and d['input']['format']=='jsonl',d;\
print('smoke ok')"

release: ## lembrete: tag/release são criados pelo mantenedor após o merge
	@echo "tag v0.1.0 e GitHub Release são criados pelo mantenedor após o merge"
