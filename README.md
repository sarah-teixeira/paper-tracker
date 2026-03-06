# Academic Paper Tracker

Sistema automatizado para monitorar artigos científicos novos em Computação/IA usando 4 APIs.

## Como funciona

```
OpenAlex ─────┐
Semantic S ───┤
Crossref ─────┼──▶ fetch_papers.py ──▶ papers.db (SQLite)
Elsevier ─────┘         ▲
                        │
                 GitHub Actions (diário)
```

O script busca artigos por palavras-chave em 4 APIs, deduplica por DOI, e armazena tudo em um banco SQLite.

## Dados capturados

| Campo       | Descrição                        |
|-------------|----------------------------------|
| title       | Título do artigo                 |
| authors     | Autores (separados por `;`)      |
| journal     | Revista / conferência            |
| doi         | Digital Object Identifier        |
| published   | Data de publicação               |
| abstract    | Resumo do artigo                 |
| keywords    | Palavras-chave / conceitos       |
| url         | Link de acesso                   |
| source_api  | Qual API encontrou o artigo      |
| search_term | Qual palavra-chave da busca      |
| fetched_at  | Quando foi coletado              |

## Setup rápido

### 1. Configurar palavras-chave

Edite `config.json`:

```json
{
    "keywords": [
        "image matting",
        "video matting",
        "semantic segmentation",
        "sua palavra-chave aqui"
    ],
    "email": "seu-email@exemplo.com"
}
```

### 2. Configurar a API key do Elsevier

O Elsevier/Scopus requer uma API key gratuita:
1. Acesse https://dev.elsevier.com/ e crie uma conta
2. Gere uma API key em "Create API Key"
3. Para rodar **localmente**, exporte como variável de ambiente:
   ```bash
   export ELSEVIER_API_KEY="sua-chave-aqui"
   ```
4. Para o **GitHub Actions**, adicione como Secret:
   - Vá em **Settings → Secrets and variables → Actions → New repository secret**
   - Nome: `ELSEVIER_API_KEY`
   - Valor: sua chave da API

### 3. Rodar localmente (testar)

```bash
python fetch_papers.py

python fetch_papers.py --days 3

python fetch_papers.py --keywords "attention mechanism"
```

### 4. Consultar o banco

```bash
python query_papers.py                          # 20 mais recentes
python query_papers.py --search "matting"       # Buscar por termo
python query_papers.py --since 2025-03-01       # Desde uma data
python query_papers.py --stats                  # Estatísticas
python query_papers.py --export csv             # Exportar CSV
python query_papers.py --export json            # Exportar JSON
```

### 5. Automatizar com GitHub Actions

```bash
git init
git add .
git commit -m "Setup inicial do paper tracker"
git remote add origin https://github.com/sarah-teixeira/paper-tracker.git
git push -u origin main
```

Depois no GitHub:
1. **Settings → Secrets → Actions** → Adicione `ELSEVIER_API_KEY`
2. **Settings → Actions → General** → Habilite "Read and write permissions"
3. O workflow roda automaticamente todo dia às 5h de Brasília
4. Também pode rodar manualmente em **Actions → Fetch New Papers → Run workflow**

## Personalização

### Alterar frequência do cron
Edite `.github/workflows/fetch_papers.yml`:
- `0 8 * * *` → Diário às 8h UTC
- `0 8 * * 1` → Semanal (segundas)
- `0 */6 * * *` → A cada 6 horas

### Desabilitar uma fonte
Remova do array `sources` no `config.json`:
```json
"sources": ["openalex", "crossref"]
```

## Limitações e rate limits

| Fonte             | Limite               | Autenticação        |
|-------------------|----------------------|---------------------|
| OpenAlex          | Ilimitado (com email)| Nenhuma             |
| Semantic Scholar  | ~100 req/5min        | Nenhuma             |
| Crossref          | ~50 req/s (com email)| Nenhuma             |
| Elsevier/Scopus   | ~2 req/s, 5000/semana| API key (gratuita)  |
