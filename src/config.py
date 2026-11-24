"""Configuration centrale du projet : chemins, graine aléatoire, connexion PostgreSQL.

Tous les notebooks et scripts importent ce module pour éviter les chemins
et paramètres « en dur » dispersés dans le code.
"""
from __future__ import annotations

import os
import random
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

# --- Chemins ---------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT_DIR / "data" / "raw"
DATA_PROCESSED = ROOT_DIR / "data" / "processed"
MODELS_DIR = ROOT_DIR / "models"
SQL_DIR = ROOT_DIR / "sql"

RAW_FILE = DATA_RAW / "DataCoSupplyChainDataset.csv"
RAW_ENCODING = "latin-1"  # le CSV Kaggle n'est pas en UTF-8 (à confirmer en phase 1)

# --- Reproductibilité ------------------------------------------------------
SEED = 42


def set_seed(seed: int = SEED) -> None:
    """Fixe la graine de toutes les sources d'aléa utilisées dans le projet."""
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


# --- Base de données -------------------------------------------------------
load_dotenv(ROOT_DIR / ".env")


def get_database_url() -> str:
    """Construit l'URL SQLAlchemy à partir des variables d'environnement."""
    user = os.getenv("POSTGRES_USER", "supply")
    password = os.getenv("POSTGRES_PASSWORD", "supply")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5433")
    db = os.getenv("POSTGRES_DB", "supply_pulse")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
