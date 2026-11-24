"""Modèle de risque de retard de livraison : données, variables, modèles, seuil, persistance.

Ce module est partagé par le notebook 02_risque (entraînement / analyse) et par
l'API (phase 5), pour garantir que les variables sont calculées de la même façon
à l'entraînement et en production.

Unité de prédiction : la COMMANDE (la cible est identique pour toutes ses lignes).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, confusion_matrix,
                             f1_score, precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import Engine
from xgboost import XGBClassifier

from src.config import MODELS_DIR, SEED, SQL_DIR

# --- Variables autorisées (toutes connues au moment de la commande) ------------
VARIABLES_CATEGORIELLES = [
    "mode_expedition", "marche", "region", "segment", "client_pays", "type_paiement",
    "categorie_principale", "departement_principal",
]
VARIABLES_NUMERIQUES = [
    "nb_lignes", "quantite_totale", "montant_net_total", "taux_remise_moyen",
    "ratio_profit_moyen", "prix_max",
    # dérivées de l'horodatage de commande
    "heure", "jour_semaine", "mois", "est_weekend",
]
VARIABLES = VARIABLES_CATEGORIELLES + VARIABLES_NUMERIQUES
CIBLE = "est_en_retard"

# --- Découpage temporel --------------------------------------------------------
FIN_TRAIN = pd.Timestamp("2017-01-01")       # train      : 2015-01-01 -> 2016-12-31
FIN_VALIDATION = pd.Timestamp("2017-07-01")  # validation : 2017-01-01 -> 2017-06-30
                                             # test       : 2017-07-01 -> 2018-01-31

CHEMIN_MODELE = MODELS_DIR / "risque_xgb.joblib"


# =============================================================================
# Données
# =============================================================================
def charger_commandes(engine: Engine) -> pd.DataFrame:
    """Charge une ligne par commande depuis l'entrepôt (sql/03_dataset_risque.sql)."""
    requete = (SQL_DIR / "03_dataset_risque.sql").read_text(encoding="utf-8")
    return pd.read_sql(requete, engine, parse_dates=["horodatage_commande"])


def ajouter_variables_temporelles(df: pd.DataFrame) -> pd.DataFrame:
    """Variables calendaires dérivées de l'horodatage de commande (connu à la commande)."""
    df = df.copy()
    h = pd.to_datetime(df["horodatage_commande"])
    df["heure"] = h.dt.hour
    df["jour_semaine"] = h.dt.weekday + 1
    df["mois"] = h.dt.month
    df["est_weekend"] = (h.dt.weekday >= 5).astype(int)
    return df


def attribuer_jeu(dates: pd.Series) -> pd.Series:
    """Étiquette train / validation / test selon la date de commande (jamais aléatoire)."""
    return pd.Series(
        np.select([dates < FIN_TRAIN, dates < FIN_VALIDATION], ["train", "validation"], "test"),
        index=dates.index,
    )


# =============================================================================
# Modèles
# =============================================================================
class RegleParMode(BaseEstimator, ClassifierMixin):
    """Baseline « métier » : probabilité de retard = taux observé du mode d'expédition.

    C'est la règle qu'un responsable logistique appliquerait sans modèle. Tout
    modèle plus complexe doit la battre pour justifier son existence.
    """

    def fit(self, X: pd.DataFrame, y: pd.Series):
        self.taux_ = y.groupby(X["mode_expedition"].values).mean()
        self.taux_global_ = float(y.mean())
        self.classes_ = np.array([0, 1])
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = X["mode_expedition"].map(self.taux_).fillna(self.taux_global_).to_numpy(float)
        return np.column_stack([1 - p, p])

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


def _preprocesseur(standardiser: bool) -> ColumnTransformer:
    # min_frequency : les modalités rares (< 50 commandes) sont regroupées ;
    # handle_unknown : une catégorie jamais vue (ex. nouveau catalogue fin 2017) ne fait pas planter.
    encodeur = OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=50,
                             sparse_output=False)
    numerique = StandardScaler() if standardiser else "passthrough"
    return ColumnTransformer(
        [("cat", encodeur, VARIABLES_CATEGORIELLES), ("num", numerique, VARIABLES_NUMERIQUES)],
        verbose_feature_names_out=True,
    )


def creer_regression_logistique(C: float = 1.0) -> Pipeline:
    return Pipeline([
        ("prep", _preprocesseur(standardiser=True)),
        ("modele", LogisticRegression(C=C, max_iter=2000, random_state=SEED)),
    ])


def creer_xgboost(**params) -> Pipeline:
    defauts = dict(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                   colsample_bytree=0.8, min_child_weight=5, tree_method="hist",
                   eval_metric="logloss", random_state=SEED, n_jobs=-1)
    defauts.update(params)
    return Pipeline([
        ("prep", _preprocesseur(standardiser=False)),  # inutile de standardiser pour des arbres
        ("modele", XGBClassifier(**defauts)),
    ])


# =============================================================================
# Évaluation et seuil
# =============================================================================
def metriques(y_vrai, proba, seuil: float) -> dict[str, float]:
    pred = (proba >= seuil).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_vrai, pred, labels=[0, 1]).ravel()
    return {
        "roc_auc": roc_auc_score(y_vrai, proba),
        "pr_auc": average_precision_score(y_vrai, proba),
        "brier": brier_score_loss(y_vrai, proba),
        "seuil": seuil,
        "recall": recall_score(y_vrai, pred, zero_division=0),
        "precision": precision_score(y_vrai, pred, zero_division=0),
        "f1": f1_score(y_vrai, pred, zero_division=0),
        "taux_alerte": pred.mean(),
        "vp": int(tp), "fp": int(fp), "fn": int(fn), "vn": int(tn),
    }


@dataclass
class CoutsMetier:
    """Hypothèse de coûts relatifs (à faire valider par le métier).

    cout_fn : retard non anticipé (client mécontent, pénalité, réclamation)
    cout_fp : fausse alerte (action préventive inutile : appel transporteur, surclassement)
    """
    cout_fn: float = 4.0
    cout_fp: float = 1.0


def cout_par_seuil(y_vrai, proba, couts: CoutsMetier, seuils=None) -> pd.DataFrame:
    """Coût total (et recall/précision) pour une grille de seuils."""
    seuils = np.round(np.arange(0.05, 0.96, 0.01), 2) if seuils is None else seuils
    y_vrai = np.asarray(y_vrai)
    lignes = []
    for s in seuils:
        pred = proba >= s
        fn = int(((~pred) & (y_vrai == 1)).sum())
        fp = int((pred & (y_vrai == 0)).sum())
        tp = int((pred & (y_vrai == 1)).sum())
        lignes.append({
            "seuil": s, "fn": fn, "fp": fp,
            "cout": couts.cout_fn * fn + couts.cout_fp * fp,
            "recall": tp / max(int((y_vrai == 1).sum()), 1),
            "precision": tp / max(int(pred.sum()), 1),
        })
    return pd.DataFrame(lignes)


def seuil_theorique(couts: CoutsMetier) -> float:
    """Seuil de Bayes : alerter si p x C_FN > (1 - p) x C_FP, soit p > C_FP / (C_FP + C_FN)."""
    return couts.cout_fp / (couts.cout_fp + couts.cout_fn)


def choisir_seuil(y_vrai, proba, couts: CoutsMetier) -> float:
    """Seuil qui minimise le coût métier total (choisi sur la VALIDATION, jamais sur le test).

    Les probabilités se regroupent par profil de commande : une large plage de seuils
    donne souvent le même coût minimal. Parmi ces seuils équivalents, on prend le plus
    proche du seuil théorique, plutôt que la borne de la plage, plus fragile.
    """
    table = cout_par_seuil(y_vrai, proba, couts)
    optimaux = table[table["cout"] == table["cout"].min()]
    ecart = (optimaux["seuil"] - seuil_theorique(couts)).abs()
    return float(optimaux.loc[ecart.idxmin(), "seuil"])


def niveau_risque(proba: np.ndarray, seuil: float) -> np.ndarray:
    """Trois niveaux lisibles pour le métier et Power BI (accepte liste ou tableau)."""
    proba = np.asarray(proba, dtype=float)
    return np.select([proba >= 0.8, proba >= seuil], ["élevé", "moyen"], "faible")


# =============================================================================
# Persistance
# =============================================================================
def sauvegarder(pipeline: Pipeline, seuil: float, infos: dict) -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "pipeline": pipeline,
        "seuil": seuil,
        "variables": VARIABLES,
        "version": datetime.now().strftime("risque-xgb-%Y%m%d-%H%M"),
        **infos,
    }, CHEMIN_MODELE)


def charger() -> dict:
    return joblib.load(CHEMIN_MODELE)
