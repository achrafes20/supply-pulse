"""Tests du module de risque de retard (sans base de données)."""
import numpy as np
import pandas as pd
import pytest

from src.models import risque as R

# Colonnes interdites : connues seulement après expédition/livraison, ou qui fuient la cible.
VARIABLES_INTERDITES = {
    "jours_reels", "ecart_jours", "statut_livraison", "horodatage_expedition",
    "date_expedition_id", "statut_commande", "est_annulee", "est_en_retard",
}


def test_aucune_variable_qui_fuit():
    assert not VARIABLES_INTERDITES & set(R.VARIABLES)


def test_decoupage_temporel_sans_chevauchement():
    dates = pd.Series(pd.to_datetime(
        ["2016-12-31 23:59", "2017-01-01 00:00", "2017-06-30 23:59", "2017-07-01 00:00"]))
    assert R.attribuer_jeu(dates).tolist() == ["train", "validation", "validation", "test"]


def test_variables_temporelles():
    df = pd.DataFrame({"horodatage_commande": pd.to_datetime(["2017-01-07 13:45"])})  # un samedi
    out = R.ajouter_variables_temporelles(df).iloc[0]
    assert (out["heure"], out["jour_semaine"], out["mois"], out["est_weekend"]) == (13, 6, 1, 1)


def test_regle_par_mode():
    X = pd.DataFrame({"mode_expedition": ["A", "A", "B", "B"]})
    y = pd.Series([1, 1, 0, 1])
    regle = R.RegleParMode().fit(X, y)
    proba = regle.predict_proba(pd.DataFrame({"mode_expedition": ["A", "B", "inconnu"]}))[:, 1]
    assert proba.tolist() == pytest.approx([1.0, 0.5, 0.75])


def test_seuil_theorique_et_choix():
    couts = R.CoutsMetier(cout_fn=4, cout_fp=1)
    assert R.seuil_theorique(couts) == pytest.approx(0.2)
    # Probabilités regroupées : tous les seuils entre 0,11 et 0,40 sont équivalents.
    y = np.array([0, 0, 1, 1, 1, 0])
    p = np.array([0.1, 0.1, 0.9, 0.9, 0.41, 0.41])
    s = R.choisir_seuil(y, p, couts)
    assert 0.1 < s <= 0.41
    assert s == pytest.approx(0.2)


def test_niveaux_de_risque():
    niveaux = R.niveau_risque(np.array([0.05, 0.3, 0.85]), seuil=0.2)
    assert niveaux.tolist() == ["faible", "moyen", "élevé"]
