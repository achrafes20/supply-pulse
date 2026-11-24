"""Tests d'intégration des vues Power BI (schéma bi).

Ignorés si PostgreSQL n'est pas joignable (ex. Docker arrêté).
"""
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.config import ROOT_DIR
from src.etl.load import creer_moteur


@pytest.fixture(scope="module")
def conn():
    try:
        engine = creer_moteur()
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
            yield c
    except OperationalError:
        pytest.skip("PostgreSQL non joignable")


def scalaire(conn, requete):
    return conn.execute(text(requete)).scalar()


def test_vues_presentes(conn):
    attendues = {"dim_date", "dim_produit", "dim_categorie", "dim_groupe_prevision", "dim_client",
                 "dim_geographie", "dim_expedition", "fait_commandes", "fait_risque", "fait_demande_hebdo",
                 "fait_prevision"}
    presentes = {r[0] for r in conn.execute(text(
        "SELECT table_name FROM information_schema.views WHERE table_schema = 'bi'"))}
    assert attendues <= presentes


def test_cles_uniques_des_dimensions(conn):
    for vue, cle in [("dim_categorie", "categorie"), ("dim_groupe_prevision", "groupe_prevision"),
                     ("dim_date", "date_id"), ("dim_expedition", "expedition_id")]:
        doublons = scalaire(conn, f"SELECT COUNT(*) - COUNT(DISTINCT {cle}) FROM bi.{vue}")
        assert doublons == 0, vue


def test_demande_hebdo_reconciliee(conn):
    """La somme des unités hebdomadaires = la somme des unités du fait."""
    assert scalaire(conn, "SELECT SUM(quantite) FROM bi.fait_demande_hebdo") == \
        scalaire(conn, "SELECT SUM(quantite) FROM bi.fait_commandes")


def test_fait_risque_une_ligne_par_commande(conn):
    n = scalaire(conn, "SELECT COUNT(*) FROM bi.fait_risque")
    if n == 0:
        pytest.skip("prédictions absentes : exécuter le notebook 02_risque")
    assert n == scalaire(conn, "SELECT COUNT(DISTINCT commande_id) FROM bi.fait_commandes")


def test_theme_powerbi_valide():
    theme = json.loads((ROOT_DIR / "powerbi" / "theme_supply_pulse.json").read_text(encoding="utf-8"))
    assert len(theme["dataColors"]) == 8
    assert {"good", "neutral", "bad"} <= theme.keys()
