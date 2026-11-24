"""Prévision hebdomadaire de la demande (unités) par groupe de catégories.

Périmètre (justifié par 01_eda) :
- période STABLE uniquement : semaines du 05/01/2015 au 18/09/2017 (142 semaines).
  La 1re semaine (29/12/2014) est incomplète ; à partir du 25/09/2017 le catalogue change
  (rupture) et l'historique ne permet plus de prévoir.
- 10 séries : les 9 catégories principales (~95 % du CA) + « Autres ».

Modèles comparés (tous produisent 12 semaines à partir d'une date d'origine) :
- naïve saisonnière (s = 52) : valeur de la même semaine un an plus tôt (baseline demandée) ;
- moyenne mobile 12 semaines : baseline adaptée à une série sans saisonnalité ;
- Prophet : un modèle par série (tendance + saisonnalité annuelle) ;
- XGBoost : un modèle global pour les 10 séries, avec retards (lags), prévision récursive.

Évaluation : backtest à origine glissante, 4 plis de 12 semaines sans chevauchement
(les 48 dernières semaines stables), chaque pli n'utilisant que le passé.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sqlalchemy import Engine
from xgboost import XGBRegressor

from src.config import SEED

DEBUT_STABLE = pd.Timestamp("2015-01-05")
FIN_STABLE = pd.Timestamp("2017-09-18")   # lundi de la dernière semaine stable
HORIZON = 12
N_PLIS = 4
MODELES = ["naive_saisonniere", "moyenne_mobile_12", "prophet", "xgboost"]


# =============================================================================
# Données
# =============================================================================
def charger_series(engine: Engine) -> pd.DataFrame:
    """Tableau large : une ligne par semaine (lundi), une colonne par groupe, en unités."""
    d = pd.read_sql("SELECT debut_semaine, groupe_prevision, quantite FROM bi.fait_demande_hebdo",
                    engine, parse_dates=["debut_semaine"])
    large = d.pivot(index="debut_semaine", columns="groupe_prevision", values="quantite")
    return large.sort_index().fillna(0).astype(float)


def periode_stable(series: pd.DataFrame) -> pd.DataFrame:
    stable = series.loc[DEBUT_STABLE:FIN_STABLE]
    # Contrôle : semaines contiguës, sans trou
    assert (stable.index.to_series().diff().dropna() == pd.Timedelta(weeks=1)).all()
    return stable


def origines_backtest(n_semaines: int) -> list[int]:
    """Indices d'origine des plis : on prévoit [o, o + 12[ avec l'historique [0, o[."""
    return [n_semaines - HORIZON * k for k in range(N_PLIS, 0, -1)]


def semaines_futures(derniere: pd.Timestamp, h: int = HORIZON) -> pd.DatetimeIndex:
    return pd.date_range(derniere + pd.Timedelta(weeks=1), periods=h, freq="W-MON")


# =============================================================================
# Modèles : chacun prend l'historique (tableau large) et renvoie
# (prévision, borne_basse, borne_haute) au format large sur les 12 semaines suivantes.
# Les bornes valent NaN quand le modèle ne fournit pas d'intervalle natif.
# =============================================================================
def prevoir_naive_saisonniere(hist: pd.DataFrame, h: int = HORIZON):
    futur = semaines_futures(hist.index[-1], h)
    prev = pd.DataFrame(hist.iloc[-52:-52 + h].to_numpy(), index=futur, columns=hist.columns)
    return prev, None, None


def prevoir_moyenne_mobile(hist: pd.DataFrame, h: int = HORIZON, fenetre: int = 12):
    futur = semaines_futures(hist.index[-1], h)
    moyenne = hist.iloc[-fenetre:].mean()
    prev = pd.DataFrame([moyenne.to_numpy()] * h, index=futur, columns=hist.columns)
    return prev, None, None


def prevoir_prophet(hist: pd.DataFrame, h: int = HORIZON):
    from prophet import Prophet  # import local : dépendance lourde, inutile pour l'API

    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
    logging.getLogger("prophet").setLevel(logging.WARNING)
    futur = semaines_futures(hist.index[-1], h)
    prev, bas, haut = (pd.DataFrame(index=futur, columns=hist.columns, dtype=float) for _ in range(3))
    for groupe in hist.columns:
        df = pd.DataFrame({"ds": hist.index, "y": hist[groupe].to_numpy()})
        m = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False,
                    interval_width=0.8, uncertainty_samples=500)
        m.fit(df)
        np.random.seed(SEED)  # l'intervalle est simulé : graine fixée pour la reproductibilité
        p = m.predict(pd.DataFrame({"ds": futur}))
        prev[groupe], bas[groupe], haut[groupe] = p["yhat"].to_numpy(), p["yhat_lower"].to_numpy(), p["yhat_upper"].to_numpy()
    return prev, bas, haut


class PrevisionXGB:
    """Modèle global (10 séries) à retards, prévision récursive.

    La cible est normalisée par la moyenne de chaque série sur l'historique
    d'entraînement : un seul modèle apprend des séries d'échelles différentes
    sans que les grosses séries dominent la fonction de perte.
    """

    RETARDS = [1, 2, 3, 4, 52]

    def __init__(self, **params):
        defauts = dict(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8,
                       colsample_bytree=0.8, random_state=SEED, n_jobs=1)
        defauts.update(params)
        self.params = defauts

    def _variables(self, valeurs: np.ndarray, t: int, semaine: int, groupe: str) -> dict:
        """Variables pour prévoir l'indice t à partir de valeurs[:t] (rien du futur)."""
        v = {f"lag_{k}": valeurs[t - k] for k in self.RETARDS}
        v["moy_4"] = valeurs[t - 4:t].mean()
        v["moy_12"] = valeurs[t - 12:t].mean()
        v["semaine_iso"] = semaine
        for g in self.groupes_:
            v[f"groupe_{g}"] = int(g == groupe)
        return v

    def fit(self, hist: pd.DataFrame):
        self.groupes_ = list(hist.columns)
        self.echelle_ = hist.mean()
        norm = hist / self.echelle_
        semaines = hist.index.isocalendar().week.to_numpy()
        X, y = [], []
        for g in self.groupes_:
            valeurs = norm[g].to_numpy()
            for t in range(52, len(valeurs)):
                X.append(self._variables(valeurs, t, semaines[t], g))
                y.append(valeurs[t])
        self.colonnes_ = list(X[0].keys())
        self.modele_ = XGBRegressor(**self.params).fit(pd.DataFrame(X)[self.colonnes_], np.array(y))
        self.hist_ = norm
        return self

    def predict(self, h: int = HORIZON) -> pd.DataFrame:
        futur = semaines_futures(self.hist_.index[-1], h)
        semaines = futur.isocalendar().week.to_numpy()
        sortie = {}
        for g in self.groupes_:
            valeurs = list(self.hist_[g].to_numpy())
            for i in range(h):  # récursif : chaque prévision devient un retard de la suivante
                x = pd.DataFrame([self._variables(np.array(valeurs), len(valeurs), semaines[i], g)])[self.colonnes_]
                valeurs.append(float(self.modele_.predict(x)[0]))
            sortie[g] = np.array(valeurs[-h:]) * self.echelle_[g]
        return pd.DataFrame(sortie, index=futur)[self.groupes_]


def prevoir_xgboost(hist: pd.DataFrame, h: int = HORIZON):
    return PrevisionXGB().fit(hist).predict(h), None, None


FONCTIONS = {
    "naive_saisonniere": prevoir_naive_saisonniere,
    "moyenne_mobile_12": prevoir_moyenne_mobile,
    "prophet": prevoir_prophet,
    "xgboost": prevoir_xgboost,
}


# =============================================================================
# Backtest et métriques
# =============================================================================
def _en_long(prev, bas, haut, modele: str) -> pd.DataFrame:
    long = prev.rename_axis("debut_semaine").reset_index().melt(
        id_vars="debut_semaine", var_name="groupe_prevision", value_name="quantite_prevue")
    for nom, tab in [("borne_basse", bas), ("borne_haute", haut)]:
        long[nom] = (np.nan if tab is None else
                     tab.rename_axis("debut_semaine").reset_index()
                     .melt(id_vars="debut_semaine", value_name=nom)[nom].to_numpy())
    long.insert(2, "modele", modele)
    return long


def backtest(stable: pd.DataFrame, modeles=MODELES) -> pd.DataFrame:
    """Prévisions de chaque modèle sur les 4 plis, avec la valeur réelle."""
    lignes = []
    for pli, o in enumerate(origines_backtest(len(stable)), start=1):
        hist = stable.iloc[:o]
        for nom in modeles:
            long = _en_long(*FONCTIONS[nom](hist), nom)
            long["pli"] = pli
            long["horizon"] = long.groupby("groupe_prevision").cumcount() + 1
            lignes.append(long)
    res = pd.concat(lignes, ignore_index=True)
    reel = stable.rename_axis("debut_semaine").reset_index().melt(
        id_vars="debut_semaine", var_name="groupe_prevision", value_name="quantite_reelle")
    return res.merge(reel, on=["debut_semaine", "groupe_prevision"], how="left")


def metriques(df: pd.DataFrame, par: list[str]) -> pd.DataFrame:
    """MAPE, RMSE, WAPE et biais par groupe de colonnes."""
    def calc(g):
        e = g["quantite_prevue"] - g["quantite_reelle"]
        return pd.Series({
            "MAPE": (e.abs() / g["quantite_reelle"]).mean(),
            "RMSE": np.sqrt((e ** 2).mean()),
            "WAPE": e.abs().sum() / g["quantite_reelle"].sum(),
            "biais": e.sum() / g["quantite_reelle"].sum(),
        })
    return df.groupby(par).apply(calc, include_groups=False)


def intervalles_empiriques(bt: pd.DataFrame, modele: str, prev: pd.DataFrame,
                           niveau: float = 0.8) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bornes à partir des erreurs relatives observées en backtest (par groupe)."""
    b = bt[bt["modele"] == modele]
    rel = (b["quantite_reelle"] / b["quantite_prevue"] - 1).groupby(b["groupe_prevision"])
    q_bas, q_haut = rel.quantile((1 - niveau) / 2), rel.quantile(1 - (1 - niveau) / 2)
    return prev * (1 + q_bas[prev.columns]), prev * (1 + q_haut[prev.columns])
