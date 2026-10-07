# SPEC — Log Analyzer v0.1

**Status:** draft para implementação por agente de IA
**Versão do produto:** `0.1.0`
**Testes:** caixa-preta, escritos por outro agente de IA, independente do implementador, contra o executável `./app`
**Idioma:** explicações em português; identificadores, flags, campos e nomes técnicos em inglês.

---

## 1. Visão geral

`log-analyzer` é uma CLI que lê logs de acesso/serviço de três formatos (JSON lines, nginx combined, apache common), normaliza os registros para um modelo interno único e produz: resumo agregado, rankings, detecção de anomalias por janela temporal e um relatório Markdown.

O programa é *stream-friendly*: lê de arquivo ou de `stdin`, nunca aborta por causa de uma linha ruim e sempre reporta quantas linhas foram descartadas.

### 1.1 Modelo interno (normalized record)

Todo parser produz o mesmo objeto lógico. Campos ausentes são `null`.

| campo | tipo | origem |
|---|---|---|
| `timestamp_ms` | integer (epoch ms, UTC) | `timestamp` (JSONL) / `$time_local` (nginx, apache) |
| `level` | string lowercase (`debug`,`info`,`warn`,`error`,`fatal`) | `level` (JSONL) / derivado do status (nginx, apache) |
| `message` | string | `message` (JSONL) / request line (nginx, apache) |
| `status` | integer 100–599 | `status` (JSONL) / `$status` (nginx, apache) |
| `path` | string | `path` (JSONL) / path extraído do request (nginx, apache) |
| `latency_ms` | float ≥ 0 | `latency_ms` (JSONL) / campo estendido opcional (nginx, apache) |

Derivação de `level` a partir de `status` (nginx, apache):
`status >= 500` → `error`; `400 <= status < 500` → `warn`; `status < 400` → `info`.

---

## 2. Não-objetivos (fora do escopo da v0.1)

1. TUI interativa, paginação ou navegação por teclado.
2. Processamento em tempo real, `tail -f`, streaming contínuo ou daemon.
3. Parsing de formatos além dos três listados (syslog, CSV, GELF, logfmt).
4. Indexação persistente, banco de dados, cache entre execuções.
5. Envio de dados para serviços externos, telemetria, alertas por e-mail/webhook.
6. Autenticação, multiusuário, API HTTP.
7. Detecção de anomalias com modelos estatísticos além de média + k·desvio-padrão.
8. Suporte a Windows nativo (alvo: Linux/macOS; `./app` é executável POSIX).

---

## 3. Contrato de execução (CLI)

### 3.1 Invocação

Executável `./app` na raiz do repositório, com permissão de execução (`chmod +x`). Pode ser binário, script ou wrapper shell que delega para o runtime real.

```
./app <subcommand> [options] [FILE]
```

- `FILE` é opcional. Ausente ou `-` ⇒ lê de `stdin`.
- Flags podem vir antes ou depois do `FILE`.
- Flags não aceitam `--flag=valor`? **Aceitam**: tanto `--format nginx` quanto `--format=nginx` são válidos.

### 3.2 Subcomandos e flags

**Globais (aceitas por todos os subcomandos, exceto onde indicado):**

| flag | valores | default | efeito |
|---|---|---|---|
| `--format` | `auto`, `jsonl`, `nginx`, `apache` | `auto` | força o parser; com `auto` a detecção é por linha |
| `--json` | — | off | saída JSON em `stdout` |
| `--strict` | — | off | qualquer linha inválida ⇒ exit `3` |
| `--quiet` | — | off | suprime avisos em `stderr` |
| `--help` | — | — | ajuda (em `stdout` ou `stderr`, à escolha da implementação) e exit `0` |
| `--version` | — | — | imprime `log-analyzer 0.1.0` e exit `0` |

**`summary`**
```
./app summary [--top N] [--format F] [--json] [FILE]
```
`--top N` (default `10`, `N >= 1`) controla quantos itens em `top_paths`.

**`top`**
```
./app top --by <field> [--n N] [--format F] [--json] [FILE]
```
`--by` obrigatório, valores: `path`, `level`, `status`, `message`.
`--n N` default `10`, `N >= 1`.

**`anomalies`**
```
./app anomalies [--window DUR] [--k K] [--metric M] [--format F] [--json] [FILE]
```
`--window DUR` default `60s`; formato de duração: `<inteiro><s|m|h>`, ex. `30s`, `5m`, `1h`.
`--k K` default `2.0`, float `>= 0`.
`--metric M` valores `errors` (default), `errors_rate`, `count`.

**`report`**
```
./app report --out <path.md> [--top N] [--window DUR] [--k K] [--metric M] [--now ISO8601] [--format F] [FILE]
```
`--out` obrigatório; `-` escreve o Markdown **completo** em `stdout` (exit `0`, nenhum arquivo é criado).
`--now` sobrescreve o instante de geração (para testes determinísticos); default = relógio do sistema em UTC.
`--json` **não é permitido** com `report` ⇒ exit `1`.

### 3.3 Códigos de saída

| código | condição |
|---|---|
| `0` | sucesso (inclui arquivo vazio e inclui linhas inválidas quando `--strict` está off) |
| `1` | erro de uso: subcomando desconhecido, flag desconhecida, valor inválido, flag obrigatória ausente, `--json` com `report` |
| `2` | erro de I/O: `FILE` inexistente/ilegível, `--out` não gravável |
| `3` | nenhuma linha válida foi parseada, **e** a entrada contém ≥ 1 linha não vazia; ou, com `--strict`, existe ≥ 1 linha inválida |
| `4` | erro interno inesperado (nunca deve ocorrer em uso normal; mensagem em `stderr`) |

Regras:
- Entrada com **0 bytes** ou só whitespace ⇒ `total = 0`, exit `0` (não é caso de exit `3`).
- Mistura de linhas válidas e inválidas ⇒ exit `0` (sem `--strict`).
- Em qualquer execução: mensagens de erro vão para `stderr`; dados vão para `stdout`.

### 3.4 Formatação de saída

- `stdout` de dados: UTF-8, terminado por `\n`.
- Cor ANSI apenas se `stdout` for TTY **e** `NO_COLOR` não estiver definida **e** `--json` ausente. Em pipe/redirect: sem cor. Testes caixa-preta sempre capturam via pipe ⇒ sem cor.
- Modo `--json`: **uma única linha compacta** (sem indentação), sem espaços supérfluos, terminada por `\n`.
- Números de ponto flutuante: arredondamento *half-up* para 6 casas decimais no JSON; contagens como inteiros.
- Chaves de objeto JSON podem vir em qualquer ordem; testes devem comparar estrutura, não strings.

---

## 4. Formatos de entrada

### 4.1 JSON lines (`jsonl`)

Uma linha = um objeto JSON. Campos conhecidos (todos opcionais):

| campo | tipo aceito | observações |
|---|---|---|
| `timestamp` | string ISO-8601 com offset, ou inteiro epoch ms | sem offset ⇒ interpretado como UTC |
| `level` | string | normalizado para lowercase |
| `message` | string | — |
| `status` | inteiro 100–599 ou string numérica equivalente | — |
| `path` | string | — |
| `latency_ms` | número ≥ 0 | — |

Regras de validade da linha:
1. Deve ser objeto JSON (`{...}`), não array, não escalar.
2. Deve conter **pelo menos um** campo conhecido.
3. Se um campo conhecido estiver presente, seu valor deve ter o tipo/faixa acima. Tipo inválido ⇒ linha inválida.
4. Chaves extras desconhecidas são ignoradas (compatibilidade futura).
5. Linha em branco é ignorada e **não** conta como inválida.

### 4.2 nginx combined (`nginx`)

```
$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"
```
Regex de reconhecimento (captura):
```
^(\S+) (\S+) (\S+) \[([^\]]+)\] "(\S+) (\S+) [^"]*" (\d{3}) (\S+) "[^"]*" "[^"]*"\s*$
```
Variante estendida aceita (latência explícita no final, opcional):
```
... "$http_user_agent" <latency_ms>
```
- `$time_local` = `%d/%b/%Y:%H:%M:%S %z` (ex. `10/Oct/2000:13:55:36 -0700`); meses em inglês (`Jan`…`Dec`).
- `path` = segundo token do `$request`, com query string removida (`?...` truncado).
- `message` = `$request` completo (ex. `GET /index.html HTTP/1.0`).
- `latency_ms` = campo estendido se presente; caso contrário `null`.

### 4.3 apache common (`apache`)

```
$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent
```
Regex:
```
^(\S+) (\S+) (\S+) \[([^\]]+)\] "(\S+) (\S+) [^"]*" (\d{3}) (\S+|-)\s*$
```
Mesmas regras de `path`, `message`, `level` e `time_local` do nginx.
`latency_ms` é sempre `null` (a menos que a variante estendida com latência no final seja detectada, com a mesma regra do nginx).

### 4.4 Auto-detecção (`--format auto`)

Detecção **por linha**, na ordem exata abaixo:

1. A linha, após `strip`, começa com `{` e faz parse como objeto JSON com ≥ 1 campo conhecido ⇒ `jsonl`.
2. Casa com o regex nginx combined ⇒ `nginx`.
3. Casa com o regex apache common ⇒ `apache`.
4. Caso contrário ⇒ linha inválida (contador `lines_invalid`).

Campo `input.format` no JSON = formato **dominante** (maior número de linhas válidas). Empate ⇒ desempate por prioridade `jsonl` > `nginx` > `apache`.
Campo `input.formats_seen` = mapa `{formato: contagem_de_linhas_válidas}` contendo apenas formatos com contagem > 0.

Com `--format` explícito (≠ `auto`): só o parser indicado é aplicado. Havendo ≥ 1 linha válida, `format` reflete o valor forçado e `formats_seen` contém apenas essa chave (contagem = nº de linhas válidas). Sem nenhuma linha válida, prevalece a regra "sem linhas válidas": `format = null` e `formats_seen = {}` — a chave forçada **não** aparece, pois o mapa contém apenas formatos com contagem > 0.

### 4.5 Linhas inválidas

- Nunca lançam exceção, nunca interrompem o processo.
- Contadas em `lines_invalid`.
- Em modo texto e se `lines_invalid > 0` e `--quiet` ausente, imprime em `stderr`:
  `warning: 3 invalid line(s) skipped`
- O número total de linhas lidas (não vazias) = `lines_valid + lines_invalid`.

### 4.6 Normalização temporal

- Todo timestamp é convertido para `timestamp_ms` (inteiro, epoch em milissegundos, UTC). Frações de segundo são preservadas até ms; sub-ms é truncado.
- Offsets (`+02:00`, `-0700`) são aplicados antes da conversão.
- Timestamps fora de ordem **não** são reordenados nem descartados; cada agregação é responsável por ordenar internamente quando necessário.
- Linha cujo `timestamp` esteja presente mas não faça parse ⇒ linha inválida.

---

## 5. Funcionalidades

### 5.1 `summary`

Calcula:
- `total`: número de registros válidos.
- `levels`: contagem por `level` (registros com `level = null` não entram).
- `statuses`: contagem por `status` (chaves são strings numéricas, ex. `"500"`).
- `top_paths`: até `--top` paths por contagem; ordenação: contagem **desc**, empate ⇒ `path` **asc** (ordenação lexicográfica byte a byte). Registros com `path = null` não entram.
- `latency_ms`: apenas sobre registros com `latency_ms != null`. Se não houver nenhum, o campo é `null` no JSON e `latency_ms: null` no texto. Caso contrário:
  - `count`, `min`, `max`, `mean`
  - `p50`, `p95`, `p99` pelo método **nearest-rank**: com os valores ordenados ascendentemente em índice 1-based e `n = count`, o percentil `q` é `sorted[max(1, ceil(q/100 * n))]`.

### 5.2 `top`

Ranking por um único campo (`--by`), top `--n`.
- Agrupa pelo valor do campo; registros com valor `null` são ignorados.
- `status` é agrupado pelo valor inteiro, e o `value` na saída é a string numérica.
- Ordenação: contagem **desc**, empate ⇒ `value` **asc** (lexicográfico; para `status`, comparar como string).
- Cada entrada: `{ "value": <string>, "count": <int> }`.

### 5.3 `anomalies`

**Definição de janela:**
Seja `W` a duração da janela em milissegundos (`--window`).
Após filtrar registros com `timestamp_ms != null` (registros sem timestamp são ignorados e contados em `skipped_no_timestamp`):
- `w_first = floor(min_ts / W)`, `w_last = floor(max_ts / W)` — índices de janela por divisão inteira de `timestamp_ms`.
- O conjunto de janelas analisadas é **contíguo e inclusivo**: `w_first .. w_last`. Janelas sem nenhum registro recebem valor `0`.
- `windows_total = w_last - w_first + 1`. Se não houver nenhum registro com timestamp, `windows_total = 0` e a lista de anomalias é vazia (exit `0`).

**Valor por janela `x_i`** conforme `--metric`:
- `errors`: número de registros com `status` em `[500, 599]` na janela.
- `errors_rate`: `5xx_count / total_count` da janela; se `total_count == 0`, valor `0.0`.
- `count`: número total de registros na janela.

**Estatísticas (sobre os `windows_total` valores, incluindo janelas vazias):**
```
μ = (Σ x_i) / N
σ = sqrt( Σ (x_i - μ)² / N )        # desvio-padrão populacional (dividir por N)
threshold = μ + k * σ
```
Anomalia ⇔ `x_i > threshold` (**estritamente maior**).
`σ == 0` ⇒ nenhuma anomalia, sempre. `windows_total == 0` ⇒ nenhuma anomalia.
`μ`, `σ`, `threshold` são calculados com precisão double e **arredondados para 6 casas** somente na serialização; o teste de anomalia usa os valores não arredondados.

**Saída por anomalia:** `start` e `end` da janela em ISO-8601 UTC com sufixo `Z` e precisão de segundos (`YYYY-MM-DDTHH:MM:SSZ`), `value`, `threshold`.
`start = (w_first + i) * W`, `end = start + W`, ambos expressos em epoch ms convertidos para ISO-8601 UTC.
Ordenação: por `start` asc.

### 5.4 `report --out arquivo.md`

Gera Markdown com exatamente esta estrutura de headings (nível 2), na ordem:

```
# Log Analyzer report

- Input: `<path ou "stdin">`
- Format: `<format>`
- Generated at: `<ISO-8601 UTC, segundos, Z>`
- Lines: `<total> valid, <invalid> invalid`

## Summary
<total, tabela de levels, tabela de statuses, tabela de latências (ou "no latency data")>

## Top paths
<tabela Markdown: | Path | Count | com até --top linhas>

## Anomalies
<parâmetros usados (window, metric, k) e tabela | Start | End | Value | Threshold |>
<se vazio: "No anomalies detected.">
```

Regras:
- Tabelas Markdown com cabeçalho e separador `|---|`.
- `--now` fixa o `Generated at` (testes determinísticos). Sem `--now`, usa o relógio do sistema em UTC.
- `--strict` **não** é definido para `report` na v0.1: comportamento não especificado e não coberto por AC.
- Se `--out` não for gravável ⇒ exit `2`, nada é escrito.
- Escrita atômica recomendada (arquivo temporário + rename); não é requisito testável. Único efeito observável exigido: após a execução, o diretório de destino contém apenas o arquivo `--out` (nenhum temporário remanescente).

---

## 6. Esquema JSON exato

Todo objeto JSON emitido tem `"version": "0.1"` e `"command"` iguais ao subcomando.

**`summary`:**
```json
{
  "version": "0.1",
  "command": "summary",
  "input": {
    "source": "file",
    "path": "tests/fixtures/ac1.jsonl",
    "format": "jsonl",
    "formats_seen": {"jsonl": 5},
    "lines_total": 5,
    "lines_valid": 5,
    "lines_invalid": 0
  },
  "total": 5,
  "levels": {"error": 2, "info": 3},
  "statuses": {"200": 3, "500": 1, "503": 1},
  "top_paths": [{"value": "/a", "count": 3}, {"value": "/b", "count": 2}],
  "latency_ms": {"count": 5, "min": 10.0, "max": 50.0, "mean": 30.0, "p50": 30.0, "p95": 50.0, "p99": 50.0}
}
```
- `input.source`: `"file"` ou `"stdin"`. `input.path`: o argumento `FILE` **literalmente como passado** (caminho absoluto permanece absoluto, relativo permanece relativo); `null` quando `source == "stdin"`.
- `latency_ms`: `null` (JSON null) quando não há latências.

**`top`:**
```json
{
  "version": "0.1",
  "command": "top",
  "by": "path",
  "n": 10,
  "input": { "...": "mesmo objeto input do summary" },
  "entries": [{"value": "/a", "count": 3}]
}
```

**`anomalies`:**
```json
{
  "version": "0.1",
  "command": "anomalies",
  "input": { "...": "mesmo objeto input" },
  "window_seconds": 60,
  "metric": "errors",
  "k": 2.0,
  "windows_total": 6,
  "skipped_no_timestamp": 0,
  "mean": 1.666667,
  "stddev": 2.867442,
  "anomalies": [
    {"start": "2026-01-01T00:05:00Z", "end": "2026-01-01T00:06:00Z", "value": 8, "threshold": 7.401550}
  ]
}
```
- `window_seconds` é inteiro; `k` é serializado como float (ex.: `--k 2` ⇒ `2.0`), eco do valor efetivo.
- `mean`, `stddev` são `null` quando `windows_total == 0`; nesse caso `anomalies` é a lista vazia `[]` (`anomalies: none` no texto).
- `threshold` presente apenas dentro de cada item de `anomalies`.

**`input` (objeto comum):** `source`, `path`, `format`, `formats_seen`, `lines_total`, `lines_valid`, `lines_invalid`.

---

## 7. Saída em modo texto (sem `--json`)

Blocos separados por `\n`, indentação de 2 espaços em seções aninhadas, separador `\t` entre contagem e valor.

Ordenação das listas: `levels` em ordem **lexicográfica crescente** do nome; `statuses` em ordem **numérica crescente** do código; `top_paths`, `entries` e `anomalies` conforme a seção 5 (contagem desc / `start` asc).

Casas decimais no modo texto: `latency_ms.min/max/mean/p50/p95/p99` com **2 casas**; `mean`, `stddev` e `threshold` (anomalias) com **6 casas**; `k` ecoado como float (ex.: `2.0`).

**`summary`:**
```
total: 5
invalid_lines: 0
format: jsonl
levels:
  error\t2
  info\t3
statuses:
  200\t3
  500\t1
  503\t1
top_paths:
  3\t/a
  2\t/b
latency_ms:
  count\t5
  min\t10.00
  max\t50.00
  mean\t30.00
  p50\t30.00
  p95\t50.00
  p99\t50.00
```
Sem latências: a seção inteira é substituída pela linha `latency_ms: null`.
Listas vazias: a seção é omitida.

**`top`:** uma linha por entrada, `<count>\t<value>`.

**`anomalies`:**
```
window_seconds: 60
metric: errors
k: 2.0
windows_total: 6
mean: 1.666667
stddev: 2.867442
anomalies:
  <start>\t<end>\tvalue=<n>\tthreshold=<f>
```
Sem anomalias: `anomalies: none`. Sem janelas: `mean: null`, `stddev: null`, `anomalies: none`.

---

## 8. Casos de borda (numerados)

1. **Arquivo vazio (0 bytes).** `total = 0`, `lines_total = 0`, `lines_invalid = 0`, `formats_seen = {}`, `latency_ms = null`, exit `0`. Sem nenhuma linha válida, `format` é sempre `null` — inclusive quando `--format` foi forçado (≠ `auto`).
2. **Apenas linhas em branco / whitespace.** Igual ao caso 1 (linhas em branco não contam como inválidas nem válidas); exit `0`.
3. **Todas as linhas inválidas.** `lines_valid = 0`, `lines_invalid > 0`, exit `3`.
4. **Mistura válidas + inválidas.** Exit `0` (ou `3` com `--strict`); contadores exatos.
5. **Timestamps fora de ordem.** Nenhum registro é reordenado ou descartado; `summary` e `top` independem da ordem; `anomalies` usa min/max para o range de janelas.
6. **Fusos diferentes no mesmo arquivo.** Cada timestamp é normalizado para UTC antes de qualquer agregação.
7. **Sem offset no timestamp JSONL.** Interpretado como UTC.
8. **Linhas em formatos mistos** (`jsonl` + `nginx` + `apache` no mesmo arquivo, com `--format auto`). Cada linha usa seu parser; `format` = dominante; `formats_seen` lista todos.
9. **`--format` forçado incompatível.** Linhas que não casam com o parser forçado viram inválidas (não caem em fallback).
10. **Registros sem `timestamp`.** Ignorados em `anomalies` e contados em `skipped_no_timestamp`; contam normalmente em `summary` e `top`.
11. **Campos `null` ou ausentes.** Não entram nas agregações correspondentes (ex.: `path = null` fora de `top_paths`); não invalidam a linha.
12. **`status` fora de 100–599, `latency_ms` negativo ou tipo errado em campo conhecido.** Linha inválida.
13. **`latency_ms` presente em nenhum registro.** `latency_ms = null`; percentis não são calculados.
14. **Janela de anomalia sem registros.** Valor `0` para `errors`/`count` e `0.0` para `errors_rate`; participa de μ e σ.
15. **`σ == 0`.** Nenhuma anomalia, mesmo com `k = 0`.
16. **`--window` maior que o intervalo total.** `windows_total = 1`; a única janela nunca é anomalia (x > μ + k·σ é impossível com N=1, pois σ=0).
17. **`--top 0` ou `--n 0`.** Erro de uso, exit `1`.
18. **`FILE` inexistente, ou `--out` em diretório sem permissão.** Exit `2`, mensagem em `stderr`, nada em `stdout`.
19. **`stdin` via pipe sem `FILE`.** Funciona normalmente; `input.source = "stdin"`, `input.path = null`.
20. **Linha JSONL gigante ou JSON malformado** (`{` sem fechar). Linha inválida; processo continua.

---

## 9. Critérios de aceite (AC)

Fixtures referenciadas ficam em `tests/fixtures/`. Comparações de float em JSON usam tolerância `1e-6`. Comparações de texto são exatas (após normalizar `\t`).

---

### AC-1 — `summary --json` com JSONL puro

**Entrada** `tests/fixtures/ac1.jsonl`:
```jsonl
{"timestamp":"2026-01-01T00:00:00Z","level":"info","status":200,"path":"/a","latency_ms":10}
{"timestamp":"2026-01-01T00:00:05Z","level":"error","status":500,"path":"/b","latency_ms":20}
{"timestamp":"2026-01-01T00:00:10Z","level":"info","status":200,"path":"/a","latency_ms":30}
{"timestamp":"2026-01-01T00:00:15Z","level":"error","status":503,"path":"/b","latency_ms":40}
{"timestamp":"2026-01-01T00:00:20Z","level":"info","status":200,"path":"/a","latency_ms":50}
```

**Comando:** `./app summary --json tests/fixtures/ac1.jsonl`

**Esperado:** exit `0`; JSON igual ao da seção 6 (`summary`), com `input.path = "tests/fixtures/ac1.jsonl"`, `input.format = "jsonl"`, `lines_total = 5`, `lines_valid = 5`, `lines_invalid = 0`.
Cálculo manual: percentis nearest-rank sobre `[10,20,30,40,50]` ⇒ `p50 = sorted[ceil(0.50*5)=3] = 30`, `p95 = sorted[ceil(4.75)=5] = 50`, `p99 = sorted[ceil(4.95)=5] = 50`.

---

### AC-2 — `summary` modo texto

**Comando:** `./app summary tests/fixtures/ac1.jsonl`

**Esperado:** exit `0`; saída idêntica ao bloco `summary` da seção 7, com `invalid_lines: 0`, `format: jsonl`.

---

### AC-3 — Parsing nginx combined

**Entrada** `tests/fixtures/ac3.log` (uma linha):
```
127.0.0.1 - - [10/Oct/2000:13:55:36 -0700] "GET /index.html HTTP/1.0" 200 2326 "-" "curl/8.0"
```

**Comando:** `./app top --by path --json tests/fixtures/ac3.log`

**Esperado:** exit `0`; `input.format = "nginx"`, `lines_valid = 1`, `formats_seen = {"nginx": 1}`;
`entries = [{"value": "/index.html", "count": 1}]`.
Cálculo manual: timestamp `2000-10-10T20:55:36Z`; status 200 ⇒ `level = "info"`.

---

### AC-4 — Parsing apache common e derivação de level

**Entrada** `tests/fixtures/ac4.log`:
```
10.0.0.1 - alice [10/Oct/2000:13:55:36 -0700] "POST /login?next=/home HTTP/1.1" 500 128
10.0.0.2 - - [10/Oct/2000:13:55:37 -0700] "GET /health HTTP/1.1" 404 0
```

**Comando:** `./app top --by status --json tests/fixtures/ac4.log`

**Esperado:** exit `0`; `input.format = "apache"`;
`entries = [{"value": "404", "count": 1}, {"value": "500", "count": 1}]` (empate ⇒ ordenação `value` asc).

**Comando 2:** `./app top --by path --json tests/fixtures/ac4.log`

**Esperado:** `entries = [{"value": "/health", "count": 1}, {"value": "/login", "count": 1}]` (query string removida).

---

### AC-5 — Linhas inválidas não derrubam o programa

**Entrada** `tests/fixtures/ac5.jsonl`:
```jsonl
{"level":"info","status":200}

not json at all
{"level":"error","status":9999}

```
(linha 1 válida; linha 2 inválida; linha 3 inválida por `status` fora da faixa; linha 4 vazia)

**Comando:** `./app summary --json tests/fixtures/ac5.jsonl`

**Esperado:** exit `0`; `lines_total = 3`, `lines_valid = 1`, `lines_invalid = 2`, `total = 1`;
`stderr` contém `warning: 2 invalid line(s) skipped`.

---

### AC-6 — Todas inválidas ⇒ exit 3

**Comando:** `./app summary --json tests/fixtures/ac5_all_invalid.txt` (conteúdo: `foo\nbar\n`)

**Esperado:** exit `3`; `lines_valid = 0`, `lines_invalid = 2`; `summary` ainda é impresso em `stdout` com `total = 0`.

---

### AC-7 — Arquivo vazio ⇒ exit 0

**Comando:** `printf '' | ./app summary --json`

**Esperado:** exit `0`; `input.source = "stdin"`, `input.path = null`, `lines_total = 0`, `total = 0`, `format = null`, `latency_ms = null`.

---

### AC-8 — Anomalias (fórmula exata)

**Entrada** `tests/fixtures/ac8.jsonl` (16 registros; `--window 60s`, `--k 2`):

| janela | timestamps | status |
|---|---|---|
| w0 | `00:00:10` | 200 |
| w1 | `00:01:10` 500, `00:01:20` 200 | — |
| w2 | `00:02:10` 200 | — |
| w3 | `00:03:10` 503, `00:03:20` 200 | — |
| w4 | `00:04:10` 200 | — |
| w5 | `00:05:10` 500, `00:05:20` 500, `00:05:30` 500, `00:05:40` 500, `00:05:50` 500, `00:05:60`→`00:05:59` 500, `00:05:11` 500, `00:05:12` 500, `00:05:13` 200 | — |

> Na fixture, `w5` contém **9 linhas**: 8 com status `500` e 1 com status `200`, todas com timestamps dentro de `00:05:00Z`–`00:06:00Z`.

**Comando:** `./app anomalies --window 60s --k 2 --metric errors --json tests/fixtures/ac8.jsonl`

**Esperado:** exit `0`; `windows_total = 6`;
`x = [0, 1, 0, 1, 0, 8]`; `μ = 10/6 = 1.666667`; `σ = sqrt(49.333333/6) = 2.867442`; `threshold = 7.401550`.
`anomalies = [{"start":"2026-01-01T00:05:00Z","end":"2026-01-01T00:06:00Z","value":8,"threshold":7.401550}]` — **apenas uma** anomalia (`8 > 7.401550`; as demais janelas têm valor `0` ou `1`, abaixo do threshold).
`skipped_no_timestamp = 0`.

---

### AC-9 — `σ == 0` ⇒ nenhuma anomalia

**Entrada:** 3 registros, todos 5xx, todos na mesma janela de `60s`, `--window 60s --k 0`.

**Esperado:** `windows_total = 1`, `σ = 0.0`, `anomalies = []` (mesmo com `k = 0`, a comparação é estrita).

---

### AC-10 — Timestamps fora de ordem e fusos

**Entrada:** 3 registros JSONL com timestamps `2026-01-01T03:00:00+02:00`, `2026-01-01T00:30:00Z`, `2026-01-01T01:00:00Z` (ordem embaralhada no arquivo), todos status `500`, `--window 1h --k 2`.

**Esperado:** normalização para UTC dá `01:00:00Z`, `00:30:00Z`, `01:00:00Z`; range de janelas `w_first = 0`, `w_last = 1` ⇒ `windows_total = 2`; `x = [1, 2]` (janela `00:00–01:00` contém `00:30`, janela `01:00–02:00` contém os dois `01:00`); a ordem das linhas no arquivo não altera o resultado.

---

### AC-11 — Formatos mistos com auto-detecção

**Entrada:** 2 linhas JSONL + 1 linha nginx + 1 linha apache.

**Comando:** `./app summary --json tests/fixtures/ac11.mixed`

**Esperado:** exit `0`; `lines_valid = 4`; `input.format = "jsonl"` (dominante, 2 > 1 > 1);
`input.formats_seen = {"jsonl": 2, "nginx": 1, "apache": 1}`.

---

### AC-12 — `top` com empate ordena por `value` asc

**Entrada:** paths `/b`, `/a`, `/c` com contagens `2`, `2`, `1`.

**Comando:** `./app top --by path --n 3 --json tests/fixtures/ac12.jsonl`

**Esperado:** `entries = [{"value":"/a","count":2},{"value":"/b","count":2},{"value":"/c","count":1}]`.

---

### AC-13 — `report --out` determinístico

**Comando:** `./app report --out out.md --now 2026-10-06T12:00:00Z tests/fixtures/ac1.jsonl`

**Esperado:** exit `0`; `out.md` contém, nesta ordem, as linhas:
```
# Log Analyzer report
...
## Summary
...
## Top paths
...
## Anomalies
```
e a linha `- Generated at: 2026-10-06T12:00:00Z`. O conteúdo do diretório antes/depois difere apenas por `out.md`.

---

### AC-14 — Erros de uso e de I/O

| comando | exit | `stdout` |
|---|---|---|
| `./app frobnicate` | `1` | vazio |
| `./app top tests/fixtures/ac1.jsonl` (sem `--by`) | `1` | vazio |
| `./app report tests/fixtures/ac1.jsonl` (sem `--out`) | `1` | vazio |
| `./app report --out x.md --json tests/fixtures/ac1.jsonl` | `1` | vazio |
| `./app summary --format xml tests/fixtures/ac1.jsonl` | `1` | vazio |
| `./app summary --top 0 tests/fixtures/ac1.jsonl` | `1` | vazio |
| `./app summary tests/fixtures/does-not-exist.log` | `2` | vazio |

Diagnóstico correspondente em `stderr` em todos os casos.

---

### AC-15 — `--strict`

**Comando:** `./app summary --strict tests/fixtures/ac5.jsonl`

**Esperado:** exit `3`; `stdout` com o resumo normalmente (`lines_invalid = 2`).

---

## 10. Requisitos de portfólio

### 10.1 README (em inglês)

`README.md` deve conter, nesta ordem:
1. Título `# Log Analyzer` + one-line pitch.
2. GIF de terminal no topo, gerado com [vhs](https://github.com/charmbracelet/vhs) a partir de `demo/demo.tape`. O `.tape` fica versionado; o GIF (`docs/demo.gif`) também, para renderizar no GitHub sem depender de CI.
3. `## Install` (clone + `./app --version`, sem dependências obrigatórias de build quando possível).
4. `## Usage` com todos os subcomandos e **saída real colada** (não inventada), incluindo pelo menos um exemplo `--json`.
5. `## Input formats` com exemplo de cada formato e a explicação da auto-detecção.
6. `## Anomaly detection` com a fórmula (μ, σ populacional, threshold = μ + k·σ, comparação estrita).
7. `## Exit codes` (tabela da seção 3.3).
8. `## How this was built` — narrativa honesta: o agente de IA implementou; os testes caixa-preta foram escritos por outro agente de IA, independente do implementador; como a spec foi usada como contrato; o que o agente errou na primeira rodada e como os testes pegaram.
9. `## Testing` (como rodar os testes caixa-preta).
10. `## License`.

### 10.2 Testes públicos

- Diretório `tests/blackbox/`, executados com `make test`.
- Os testes **não importam** módulos internos: invocam `./app` via subprocesso (`subprocess.run`/equivalente), com `stdin`/`stdout`/`stderr` capturados.
- Table-driven, um arquivo por subcomando, fixtures em `tests/fixtures/`.
- Cada AC da seção 9 mapeia para, no mínimo, um teste nomeado `test_ac_<n>_...`.
- Determinismo: nenhum teste depende de relógio do sistema (usa `--now`) nem de cor (pipe ⇒ sem cor).

### 10.3 CI

GitHub Actions, workflow `.github/workflows/ci.yml`, disparado em `push` e `pull_request`, matriz Linux + macOS, passos:
1. checkout; 2. instalar runtime; 3. `make lint`; 4. `make test`; 5. `make smoke` (roda `./app summary --json tests/fixtures/ac1.jsonl` e valida o JSON).

### 10.4 Lint

- `make lint` executa o linter do runtime escolhido (ex. `ruff`/`shellcheck`), com configuração versionada.
- `make fmt` aplica formatação automática.
- Lint deve passar sem warnings no código entregue.

### 10.5 Licença e release

- `LICENSE` com texto MIT completo, ano `2026`.
- `CHANGELOG.md` no formato Keep a Changelog, com entrada `## [0.1.0] - 2026-10-06`.
- Tag git `v0.1.0` e GitHub Release `v0.1.0` com notas derivadas do changelog.
- `./app --version` imprime exatamente `log-analyzer 0.1.0`.

---

## 11. Estrutura de repositório

```
.
├── app                     # executável (binário ou wrapper)
├── src/                    # código-fonte do runtime escolhido
├── tests/
│   ├── blackbox/           # testes caixa-preta (subprocess)
│   └── fixtures/           # entradas .jsonl/.log/.mixed
├── demo/
│   └── demo.tape           # script vhs
├── docs/
│   └── demo.gif
├── .github/workflows/ci.yml
├── Makefile                # targets: run, lint, fmt, test, smoke, release
├── README.md
├── CHANGELOG.md
├── LICENSE
└── SPEC.md                 # este documento
```

---

## 12. Definições e convenções

- **linha vazia:** após `strip()`, string de comprimento zero. Ignorada, não contada em nenhum contador.
- **linha inválida:** linha não vazia que não foi parseada por nenhum parser aplicável.
- **formato dominante:** formato com mais linhas válidas; empate ⇒ `jsonl` > `nginx` > `apache`.
- **percentil nearest-rank:** `sorted[max(1, ceil(q/100 * n))]`, 1-based, com `sorted` asc.
- **janela contígua:** todas as janelas entre a primeira e a última que contêm registros, inclusive as vazias.
- **desvio-padrão populacional:** dividir por `N` (não `N-1`).
- **comparação estrita de anomalia:** `x_i > threshold`, nunca `>=`.
- **arredondamento:** half-up, 6 casas decimais, aplicado somente na serialização.
- **tolerância de comparação numérica nos testes:** `1e-6`.

---

## Esclarecimentos v0.1.1

Revisão que elimina ambiguidades/internalidades apontadas pelos testes caixa-preta independentes.

1. `--help` pode imprimir a ajuda em `stdout` **ou** `stderr` (implementação escolhe); exit `0` inalterado.
2. `--out -` no `report` grava o Markdown completo em `stdout`, exit `0`, sem criar arquivo.
3. `--format` forçado + 0 linhas válidas: prevalece a regra "sem linhas válidas" ⇒ `format = null` e `formats_seen = {}` (a chave forçada não aparece).
4. Caso de borda 1 reescrito: `format = null` **mesmo com `--format` forçado**; `formats_seen = {}`, `latency_ms = null`.
5. `input.path` ecoa o argumento `FILE` **literalmente** (absoluto permanece absoluto; relativo permanece relativo); `null` só em `stdin`.
6. Modo texto: `levels` em ordem lexicográfica crescente e `statuses` em ordem numérica crescente.
7. Modo texto: `latency_ms.min/max/mean/p50/p95/p99` com **2 casas**; `mean`/`stddev`/`threshold` com **6 casas**.
8. `k` é serializado como float (ex.: `--k 2` ⇒ `2.0`), tanto no JSON quanto no texto; floats comparados com tolerância `1e-6`.
9. Apenas linhas em branco equivale ao caso 1: `lines_total = 0`, `formats_seen = {}`, exit `0`.
10. `windows_total == 0` ⇒ `mean`/`stddev` `null` e `anomalies = []` (`anomalies: none` no texto).
11. `report` não deixa temporários: ao final, o diretório de destino contém apenas o arquivo `--out`.
12. `--strict` com `report` é declaradamente **não especificado** na v0.1 (sem AC, sem efeito normativo).

---

## Apêndice — Contrato de entrega do corpus (v0.1.2)

Vale para todos os casos do lote e prevalece sobre qualquer trecho acima em caso de conflito.

1. **Divulgação honesta (README › How this was built).** A spec foi escrita primeiro. A implementação foi feita por um agente de IA autônomo de um harness interno (sem edição humana do código). Os testes caixa-preta de aceite foram escritos por **outro agente de IA, independente do implementador**, a partir só da spec; ficam fora deste repositório e são rodados pelo harness. Não afirmar que foram escritos por uma pessoa.
2. **Diagrama.** O README tem pelo menos um bloco ```mermaid com a arquitetura ou o fluxo principal.
3. **Dependências.** Se o projeto precisar de pacotes de terceiros, a raiz tem um executável `./setup` (shebang, idempotente) que os instala localmente (ex.: `.venv` ou `node_modules`). O avaliador o roda **uma vez** antes dos testes, sem segredos no ambiente e com rede só para pypi.org/files.pythonhosted.org/registry.npmjs.org. `./app` / `./serve` usam o que o `./setup` instalou. Biblioteca padrão é preferível; sem dependências, não crie `./setup`.
4. **Tag e Release.** A tag `v0.1.0` e o GitHub Release são criados pelo mantenedor **depois do merge**. O PR não cria tag.
5. **GIF de terminal.** O GIF (vhs) é opcional nesta versão: se a ferramenta não estiver disponível no ambiente, deixe o `.tape` versionado e não bloqueie a entrega.
