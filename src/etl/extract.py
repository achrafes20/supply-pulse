"""Extraction : lecture du CSV brut DataCo.

Le fichier Kaggle est encodé en latin-1 (vérifié en phase 1 : une lecture en
UTF-8 échoue sur les caractères accentués des villes et pays).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import RAW_ENCODING, RAW_FILE


def lire_csv_brut(chemin: Path = RAW_FILE) -> pd.DataFrame:
    """Lit le CSV DataCo tel quel (aucune transformation)."""
    if not chemin.exists():
        raise FileNotFoundError(
            f"Dataset introuvable : {chemin}. "
            "Placer DataCoSupplyChainDataset.csv dans data/raw/."
        )
    df = pd.read_csv(chemin, encoding=RAW_ENCODING)
    # Certains noms de colonnes du fichier Kaggle ont des espaces parasites.
    df.columns = df.columns.str.strip()
    return df
