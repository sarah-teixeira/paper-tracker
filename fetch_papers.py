"""
Academic Paper Tracker
=====================
Busca automática de artigos científicos por palavras-chave usando APIs
(OpenAlex, Semantic Scholar, Crossref, Elsevier/Scopus) e armazena em banco SQLite.

Uso:
    python fetch_papers.py                    # Busca com config padrão
    python fetch_papers.py --days 3           # Artigos dos últimos 3 dias
    python fetch_papers.py --keywords "LLM"   # Override de palavras-chave
"""

import sqlite3
import json
import urllib.request
import urllib.parse
import urllib.error
import argparse
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

# ─── Configuração ───────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "keywords": [
        "image matting",
        "video matting",
        "semantic segmentation",
        "object detection",
        "image inpainting",
        "neural radiance field",
        "3D reconstruction",
        "visual grounding",
        "depth estimation",
        "image super resolution"
    ],
    "days_lookback": 7,
    "db_path": "papers.db",
    "sources": ["openalex", "semantic_scholar", "crossref", "elsevier"],
    "max_results_per_source": 50,
    "email": "seu-email@exemplo.com"
}

# ─── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ─── Database ───────────────────────────────────────────────────────────────

def init_db(db_path: str) -> sqlite3.Connection:
    """Cria o banco SQLite e a tabela de artigos se não existirem."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            doi         TEXT UNIQUE,
            title       TEXT NOT NULL,
            authors     TEXT,
            journal     TEXT,
            published   TEXT,
            abstract    TEXT,
            keywords    TEXT,
            url         TEXT,
            source_api  TEXT,
            fetched_at  TEXT DEFAULT (datetime('now')),
            search_term TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_doi ON papers(doi)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_published ON papers(published)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_search_term ON papers(search_term)")
    conn.commit()
    return conn


def insert_paper(conn: sqlite3.Connection, paper: dict) -> bool:
    """Insere um artigo no banco. Retorna True se inseriu, False se já existia."""
    try:
        conn.execute("""
            INSERT OR IGNORE INTO papers
                (doi, title, authors, journal, published, abstract, keywords, url, source_api, search_term)
            VALUES
                (:doi, :title, :authors, :journal, :published, :abstract, :keywords, :url, :source_api, :search_term)
        """, paper)
        conn.commit()
        return conn.total_changes > 0
    except sqlite3.Error as e:
        logger.error(f"Erro ao inserir artigo: {e}")
        return False


# ─── Helpers ────────────────────────────────────────────────────────────────

def safe_request(url: str, headers: dict = None, max_retries: int = 3) -> dict | None:
    """Faz requisição HTTP com retry e tratamento de erros."""
    if headers is None:
        headers = {"User-Agent": "AcademicTracker/1.0 (mailto:user@example.com)"}

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Rate limited. Aguardando {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"HTTP {e.code} ao acessar {url}")
                return None
        except Exception as e:
            logger.error(f"Erro na requisição (tentativa {attempt+1}): {e}")
            time.sleep(1)
    return None


def format_authors(authors_list) -> str:
    """Formata lista de autores em string separada por ; """
    if not authors_list:
        return ""
    if isinstance(authors_list, str):
        return authors_list
    names = []
    for a in authors_list:
        if isinstance(a, dict):
            name = a.get("display_name") or a.get("name") or a.get("given", "") + " " + a.get("family", "")
            names.append(name.strip())
        elif isinstance(a, str):
            names.append(a)
    return "; ".join(names)


# ═══════════════════════════════════════════════════════════════════════════
#  FONTES DE DADOS
# ═══════════════════════════════════════════════════════════════════════════

# ─── 1. OpenAlex (gratuita, sem chave) ─────────────────────────────────────

def fetch_openalex(keyword: str, from_date: str, max_results: int, email: str) -> list[dict]:
    papers = []
    encoded = urllib.parse.quote(keyword)
    url = (
        f"https://api.openalex.org/works?"
        f"search={encoded}"
        f"&filter=from_publication_date:{from_date}"
        f"&sort=publication_date:desc"
        f"&per_page={min(max_results, 50)}"
        f"&mailto={email}"
    )

    data = safe_request(url)
    if not data or "results" not in data:
        return papers

    for item in data["results"]:
        doi = item.get("doi", "")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "")

        primary = item.get("primary_location") or {}
        source = primary.get("source") or {}
        journal = source.get("display_name", "")

        concepts = item.get("concepts") or []
        kw_list = [c.get("display_name", "") for c in concepts[:5]]

        papers.append({
            "doi": doi or None,
            "title": item.get("title", "Sem título"),
            "authors": format_authors(item.get("authorships", [])),
            "journal": journal,
            "published": item.get("publication_date", ""),
            "abstract": reconstruct_abstract(item.get("abstract_inverted_index")),
            "keywords": "; ".join(kw_list),
            "url": item.get("id", ""),
            "source_api": "openalex",
            "search_term": keyword
        })

    logger.info(f"[OpenAlex] '{keyword}': {len(papers)} artigos encontrados")
    return papers


def reconstruct_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


# ─── 2. Semantic Scholar (gratuita, sem chave) ─────────────────────────────

def fetch_semantic_scholar(keyword: str, from_date: str, max_results: int) -> list[dict]:
    papers = []
    encoded = urllib.parse.quote(keyword)
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search?"
        f"query={encoded}"
        f"&limit={min(max_results, 100)}"
        f"&fields=title,authors,externalIds,venue,publicationDate,abstract,url"
        f"&publicationDateOrYear={from_date}:"
    )

    data = safe_request(url)
    if not data or "data" not in data:
        return papers

    for item in data["data"]:
        ext_ids = item.get("externalIds") or {}
        doi = ext_ids.get("DOI", "")
        pub_date = item.get("publicationDate") or ""

        authors_list = item.get("authors") or []
        authors = "; ".join(a.get("name", "") for a in authors_list)

        papers.append({
            "doi": doi or None,
            "title": item.get("title", "Sem título"),
            "authors": authors,
            "journal": item.get("venue", ""),
            "published": pub_date,
            "abstract": item.get("abstract", "") or "",
            "keywords": "",
            "url": item.get("url", ""),
            "source_api": "semantic_scholar",
            "search_term": keyword
        })

    logger.info(f"[Semantic Scholar] '{keyword}': {len(papers)} artigos encontrados")
    return papers


# ─── 3. Crossref (gratuita, sem chave) ─────────────────────────────────────

def fetch_crossref(keyword: str, from_date: str, max_results: int, email: str) -> list[dict]:
    papers = []
    encoded = urllib.parse.quote(keyword)
    url = (
        f"https://api.crossref.org/works?"
        f"query={encoded}"
        f"&filter=from-pub-date:{from_date}"
        f"&sort=published&order=desc"
        f"&rows={min(max_results, 50)}"
        f"&mailto={email}"
    )

    data = safe_request(url)
    if not data or "message" not in data:
        return papers

    items = data["message"].get("items", [])
    for item in items:
        doi = item.get("DOI", "")

        authors_raw = item.get("author", [])
        authors = "; ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in authors_raw
        )

        container = item.get("container-title", [])
        journal = container[0] if container else ""

        date_parts = item.get("published", {}).get("date-parts", [[]])
        if date_parts and date_parts[0]:
            parts = date_parts[0]
            pub_date = "-".join(str(p).zfill(2) for p in parts)
        else:
            pub_date = ""

        abstract = item.get("abstract", "") or ""
        abstract = abstract.replace("<jats:p>", "").replace("</jats:p>", "")
        abstract = abstract.replace("<jats:italic>", "").replace("</jats:italic>", "")

        papers.append({
            "doi": doi or None,
            "title": item.get("title", ["Sem título"])[0] if item.get("title") else "Sem título",
            "authors": authors,
            "journal": journal,
            "published": pub_date,
            "abstract": abstract,
            "keywords": "",
            "url": f"https://doi.org/{doi}" if doi else "",
            "source_api": "crossref",
            "search_term": keyword
        })

    logger.info(f"[Crossref] '{keyword}': {len(papers)} artigos encontrados")
    return papers


# ─── 4. Elsevier / Scopus (requer API key) ─────────────────────────────────

def fetch_elsevier(keyword: str, from_date: str, max_results: int) -> list[dict]:
    """
    Busca artigos na API Elsevier/Scopus.
    Requer a variável de ambiente ELSEVIER_API_KEY.
    Docs: https://dev.elsevier.com/documentation/ScopusSearchAPI.wadl
    """
    papers = []

    # API key via variável de ambiente (seguro para GitHub Actions)
    api_key = os.environ.get("ELSEVIER_API_KEY", "")
    if not api_key:
        logger.warning("[Elsevier] API key não encontrada. Defina ELSEVIER_API_KEY.")
        return papers

    # Scopus usa query TITLE-ABS-KEY para buscar em título, abstract e keywords
    query = f'TITLE-ABS-KEY("{keyword}") AND PUBYEAR > {int(from_date[:4]) - 1}'
    encoded = urllib.parse.quote(query)
    url = (
        f"https://api.elsevier.com/content/search/scopus?"
        f"query={encoded}"
        f"&count={min(max_results, 25)}"
        f"&sort=-coverDate"
    )

    headers = {
        "X-ELS-APIKey": api_key,
        "Accept": "application/json",
        "User-Agent": "AcademicTracker/1.0"
    }

    data = safe_request(url, headers=headers)
    if not data:
        return papers

    search_results = data.get("search-results", {})
    entries = search_results.get("entry", [])

    if not entries:
        logger.info(f"[Elsevier] '{keyword}': 0 artigos encontrados")
        return papers

    for item in entries:
        # Pular entradas de erro
        if item.get("@_fa") == "false" or "error" in item:
            continue

        doi = item.get("prism:doi", "")

        # Autores
        authors_list = item.get("author", [])
        if authors_list and isinstance(authors_list, list):
            authors = "; ".join(
                a.get("authname", "") or f"{a.get('given-name', '')} {a.get('surname', '')}".strip()
                for a in authors_list
            )
        else:
            authors = item.get("dc:creator", "")

        # Keywords do autor
        auth_keywords = item.get("authkeywords", "") or ""

        # Data de publicação
        pub_date = item.get("prism:coverDate", "")

        # Abstract
        abstract = item.get("dc:description", "") or ""

        # URL — pegar link do Scopus
        scopus_url = ""
        links = item.get("link", [])
        for link in links:
            if isinstance(link, dict) and link.get("@ref") == "scopus":
                scopus_url = link.get("@href", "")
                break
        if not scopus_url:
            scopus_url = f"https://doi.org/{doi}" if doi else ""

        papers.append({
            "doi": doi or None,
            "title": item.get("dc:title", "Sem título"),
            "authors": authors,
            "journal": item.get("prism:publicationName", ""),
            "published": pub_date,
            "abstract": abstract,
            "keywords": auth_keywords,
            "url": scopus_url,
            "source_api": "elsevier",
            "search_term": keyword
        })

    logger.info(f"[Elsevier] '{keyword}': {len(papers)} artigos encontrados")
    return papers


# ═══════════════════════════════════════════════════════════════════════════
#  ORQUESTRADOR
# ═══════════════════════════════════════════════════════════════════════════

def load_config() -> dict:
    """Carrega configuração do arquivo JSON ou usa padrão."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
            cfg = {**DEFAULT_CONFIG, **user_cfg}
            return cfg
    return DEFAULT_CONFIG.copy()


def run(args=None):
    """Execução principal do tracker."""
    config = load_config()

    parser = argparse.ArgumentParser(description="Academic Paper Tracker")
    parser.add_argument("--days", type=int, default=config["days_lookback"],
                        help="Buscar artigos dos últimos N dias")
    parser.add_argument("--keywords", type=str, default=None,
                        help="Palavras-chave separadas por vírgula (override)")
    parser.add_argument("--db", type=str, default=config["db_path"],
                        help="Caminho do banco SQLite")
    opts = parser.parse_args(args)

    from_date = (datetime.now() - timedelta(days=opts.days)).strftime("%Y-%m-%d")
    logger.info(f"Buscando artigos desde {from_date}")

    keywords = config["keywords"]
    if opts.keywords:
        keywords = [k.strip() for k in opts.keywords.split(",")]

    logger.info(f"Palavras-chave: {keywords}")

    db_path = Path(__file__).parent / opts.db
    conn = init_db(str(db_path))

    total_new = 0
    total_found = 0

    source_funcs = {
        "openalex": lambda kw: fetch_openalex(kw, from_date, config["max_results_per_source"], config["email"]),
        "semantic_scholar": lambda kw: fetch_semantic_scholar(kw, from_date, config["max_results_per_source"]),
        "crossref": lambda kw: fetch_crossref(kw, from_date, config["max_results_per_source"], config["email"]),
        "elsevier": lambda kw: fetch_elsevier(kw, from_date, config["max_results_per_source"]),
    }

    for keyword in keywords:
        for source_name in config["sources"]:
            if source_name not in source_funcs:
                continue

            papers = source_funcs[source_name](keyword)
            total_found += len(papers)

            for paper in papers:
                if not paper["doi"] and paper["title"] == "Sem título":
                    continue
                if insert_paper(conn, paper):
                    total_new += 1

            time.sleep(1)

    conn.close()

    logger.info(f"{'='*50}")
    logger.info(f"Busca finalizada!")
    logger.info(f"  Artigos encontrados: {total_found}")
    logger.info(f"  Novos inseridos:     {total_new}")
    logger.info(f"  Banco de dados:      {db_path}")
    logger.info(f"{'='*50}")

    return total_new


if __name__ == "__main__":
    run()
