"""
Utilitário para consultar e exportar o banco de artigos.

Uso:
    python query_papers.py                          # Lista os 20 mais recentes
    python query_papers.py --search "attention"     # Busca por termo no título/abstract
    python query_papers.py --export csv             # Exporta tudo para CSV
    python query_papers.py --export json            # Exporta tudo para JSON
    python query_papers.py --stats                  # Mostra estatísticas do banco
    python query_papers.py --since 2025-03-01       # Artigos desde uma data
"""

import sqlite3
import csv
import json
import argparse
from pathlib import Path
from datetime import datetime


DB_PATH = Path(__file__).parent / "papers.db"


def get_connection():
    if not DB_PATH.exists():
        print("Banco de dados não encontrado. Rode fetch_papers.py primeiro.")
        exit(1)
    return sqlite3.connect(str(DB_PATH))


def list_recent(limit=20, since=None, search=None):
    """Lista artigos recentes com filtros opcionais."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM papers WHERE 1=1"
    params = []

    if since:
        query += " AND published >= ?"
        params.append(since)

    if search:
        query += " AND (title LIKE ? OR abstract LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    query += " ORDER BY published DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()

    if not rows:
        print("Nenhum artigo encontrado com esses filtros.")
        return

    for i, row in enumerate(rows, 1):
        print(f"\n{'─'*70}")
        print(f"  [{i}] {row['title']}")
        print(f"  Autores:   {row['authors'][:80]}..." if len(row['authors'] or '') > 80 else f"  Autores:   {row['authors']}")
        print(f"  Revista:   {row['journal']}")
        print(f"  Data:      {row['published']}")
        print(f"  DOI:       {row['doi']}")
        print(f"  Fonte:     {row['source_api']}")
        print(f"  Busca:     {row['search_term']}")
    print(f"\n{'─'*70}")
    print(f"Total: {len(rows)} artigos exibidos")

    conn.close()


def export_data(fmt="csv"):
    """Exporta todos os artigos para CSV ou JSON."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM papers ORDER BY published DESC").fetchall()

    if not rows:
        print("Banco vazio.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if fmt == "csv":
        out_path = Path(__file__).parent / f"papers_export_{timestamp}.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(rows[0].keys())
            for row in rows:
                writer.writerow(tuple(row))
        print(f"Exportado {len(rows)} artigos para {out_path}")

    elif fmt == "json":
        out_path = Path(__file__).parent / f"papers_export_{timestamp}.json"
        data = [dict(row) for row in rows]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Exportado {len(rows)} artigos para {out_path}")

    conn.close()


def show_stats():
    """Mostra estatísticas do banco."""
    conn = get_connection()

    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    by_source = conn.execute(
        "SELECT source_api, COUNT(*) as n FROM papers GROUP BY source_api ORDER BY n DESC"
    ).fetchall()
    by_keyword = conn.execute(
        "SELECT search_term, COUNT(*) as n FROM papers GROUP BY search_term ORDER BY n DESC"
    ).fetchall()
    by_journal = conn.execute(
        "SELECT journal, COUNT(*) as n FROM papers WHERE journal != '' GROUP BY journal ORDER BY n DESC LIMIT 10"
    ).fetchall()
    latest = conn.execute(
        "SELECT published FROM papers ORDER BY published DESC LIMIT 1"
    ).fetchone()

    print(f"\n📊 Estatísticas do Banco de Artigos")
    print(f"{'='*50}")
    print(f"  Total de artigos: {total}")
    print(f"  Artigo mais recente: {latest[0] if latest else 'N/A'}")

    print(f"\n  Por fonte:")
    for src, n in by_source:
        print(f"    {src}: {n}")

    print(f"\n  Por palavra-chave:")
    for kw, n in by_keyword:
        print(f"    {kw}: {n}")

    print(f"\n  Top 10 revistas:")
    for j, n in by_journal:
        print(f"    {j}: {n}")

    print()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consultar banco de artigos")
    parser.add_argument("--search", type=str, help="Buscar no título ou abstract")
    parser.add_argument("--since", type=str, help="Artigos desde data (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=20, help="Limite de resultados")
    parser.add_argument("--export", choices=["csv", "json"], help="Exportar dados")
    parser.add_argument("--stats", action="store_true", help="Mostrar estatísticas")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.export:
        export_data(args.export)
    else:
        list_recent(limit=args.limit, since=args.since, search=args.search)
