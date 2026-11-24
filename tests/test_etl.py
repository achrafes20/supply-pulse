"""Tests de la transformation ETL (sans base de données).

Ils s'exécutent sur un échantillon du CSV réel ; ils sont ignorés si le
dataset n'est pas présent (il n'est pas versionné).
"""
import pandas as pd
import pytest

from src.config import RAW_FILE
from src.etl.extract import lire_csv_brut
from src.etl.transform import COLONNES_PERSONNELLES, construire_etoile, nettoyer

pytestmark = pytest.mark.skipif(not RAW_FILE.exists(), reason="dataset absent de data/raw/")


@pytest.fixture(scope="module")
def brut() -> pd.DataFrame:
    return lire_csv_brut().head(5000)


@pytest.fixture(scope="module")
def etoile(brut) -> dict[str, pd.DataFrame]:
    return construire_etoile(nettoyer(brut))


def test_aucune_donnee_personnelle(brut):
    propre = nettoyer(brut)
    for col in COLONNES_PERSONNELLES:
        assert col not in propre.columns
    # Aucune colonne renommée ne doit réintroduire ces informations.
    assert not any(m in c for c in propre.columns for m in ("mail", "password", "fname", "lname", "street"))


def test_grain_ligne_de_commande(brut, etoile):
    fait = etoile["fait_commandes"]
    assert len(fait) == len(brut)
    assert fait["ligne_id"].is_unique


def test_cles_primaires_uniques(etoile):
    cles = {"dim_date": "date_id", "dim_produit": "produit_id", "dim_client": "client_id",
            "dim_geographie": "geographie_id", "dim_expedition": "expedition_id"}
    for table, cle in cles.items():
        assert etoile[table][cle].is_unique, table


def test_integrite_referentielle(etoile):
    fait = etoile["fait_commandes"]
    assert fait["date_commande_id"].isin(etoile["dim_date"]["date_id"]).all()
    assert fait["date_expedition_id"].isin(etoile["dim_date"]["date_id"]).all()
    assert fait["produit_id"].isin(etoile["dim_produit"]["produit_id"]).all()
    assert fait["client_id"].isin(etoile["dim_client"]["client_id"]).all()
    assert fait["geographie_id"].notna().all()
    assert fait["expedition_id"].notna().all()


def test_calendrier_continu(etoile):
    dates = pd.to_datetime(etoile["dim_date"]["date"])
    assert (dates.diff().dropna() == pd.Timedelta(days=1)).all()


def test_montants_coherents(etoile):
    f = etoile["fait_commandes"]
    assert ((f["montant_net"] - (f["montant_brut"] - f["remise"])).abs() <= 0.02).all()
    assert (f["ecart_jours"] == f["jours_reels"] - etoile["dim_expedition"]
            .set_index("expedition_id").loc[f["expedition_id"], "jours_prevus"].values).all()
