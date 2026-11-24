"""Tests de fumée de la phase 0 : la configuration est cohérente."""
from src import config


def test_arborescence_presente():
    for dossier in (config.DATA_RAW, config.DATA_PROCESSED, config.SQL_DIR, config.MODELS_DIR):
        assert dossier.is_dir(), f"Dossier manquant : {dossier}"


def test_url_postgres_bien_formee():
    url = config.get_database_url()
    assert url.startswith("postgresql+psycopg2://")


def test_seed_reproductible():
    import numpy as np

    config.set_seed()
    a = np.random.rand(3)
    config.set_seed()
    b = np.random.rand(3)
    assert (a == b).all()
