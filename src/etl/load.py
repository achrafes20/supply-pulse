"""Chargement dans PostgreSQL.

On utilise COPY (chargement en masse natif de PostgreSQL) plutôt que des INSERT
ligne à ligne : un seul flux de données au lieu de 180 000 requêtes.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from src.config import get_database_url


def creer_moteur() -> Engine:
    return create_engine(get_database_url())


def executer_script_sql(engine: Engine, chemin: Path) -> None:
    """Exécute un fichier SQL complet (plusieurs instructions) dans une transaction.

    On passe par le curseur DBAPI sans paramètres : psycopg2 n'interprète alors pas
    les « % » du script (ex. « 80 % » dans un commentaire) comme des marqueurs de paramètres.
    """
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(chemin.read_text(encoding="utf-8"))
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def copier_dataframe(engine: Engine, df: pd.DataFrame, table: str, schema: str = "dw") -> None:
    """Charge un DataFrame dans une table existante via COPY ... FROM STDIN (CSV)."""
    tampon = io.StringIO()
    df.to_csv(tampon, index=False, header=False, na_rep="")
    tampon.seek(0)
    colonnes = ", ".join(df.columns)
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.copy_expert(
                f"COPY {schema}.{table} ({colonnes}) FROM STDIN WITH (FORMAT csv, NULL '')",
                tampon,
            )
        raw.commit()
    finally:
        raw.close()


def lire_controles(engine: Engine, chemin: Path) -> dict[str, float]:
    with engine.connect() as conn:
        lignes = conn.execute(text(chemin.read_text(encoding="utf-8"))).fetchall()
    return {controle: float(valeur) for controle, valeur in lignes}
