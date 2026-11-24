"""Tests du module de prévision (séries synthétiques, sans base de données)."""
import numpy as np
import pandas as pd
import pytest

from src.models import prevision as P


@pytest.fixture
def series():
    """2 séries hebdomadaires de 120 semaines : une constante, une croissante."""
    idx = pd.date_range("2015-01-05", periods=120, freq="W-MON")
    return pd.DataFrame({"A": np.full(120, 100.0), "B": np.arange(120, dtype=float) + 50}, index=idx)


def test_origines_sans_chevauchement():
    o = P.origines_backtest(142)
    assert o == [94, 106, 118, 130]
    assert all(b - a == P.HORIZON for a, b in zip(o, o[1:]))
    assert o[-1] + P.HORIZON == 142          # le dernier pli finit exactement à la fin


def test_semaines_futures_sont_des_lundis(series):
    futur = P.semaines_futures(series.index[-1])
    assert len(futur) == P.HORIZON and (futur.weekday == 0).all()
    assert futur[0] == series.index[-1] + pd.Timedelta(weeks=1)


def test_naive_saisonniere(series):
    prev, _, _ = P.prevoir_naive_saisonniere(series)
    # semaine t+1 prévue par la valeur de t+1-52
    assert prev["B"].iloc[0] == series["B"].iloc[-52]


def test_moyenne_mobile(series):
    prev, _, _ = P.prevoir_moyenne_mobile(series)
    assert prev["A"].eq(100).all()
    assert prev["B"].iloc[0] == pytest.approx(series["B"].iloc[-12:].mean())


def test_xgboost_forme_et_echelle(series):
    prev, _, _ = P.prevoir_xgboost(series)
    assert prev.shape == (P.HORIZON, 2)
    assert list(prev.columns) == ["A", "B"]
    assert prev["A"].between(90, 110).all()  # une série constante doit rester proche de sa valeur


def test_backtest_n_utilise_que_le_passe(series):
    """Modifier le futur d'un pli ne doit pas changer les prévisions de ce pli."""
    bt1 = P.backtest(series, modeles=["moyenne_mobile_12", "xgboost"])
    altere = series.copy()
    altere.iloc[-12:] *= 10                   # on change uniquement le dernier pli
    bt2 = P.backtest(altere, modeles=["moyenne_mobile_12", "xgboost"])
    dernier = bt1["pli"] == P.N_PLIS
    assert np.allclose(bt1.loc[dernier, "quantite_prevue"], bt2.loc[dernier, "quantite_prevue"])


def test_metriques():
    df = pd.DataFrame({"m": ["x", "x"], "quantite_prevue": [110.0, 90.0], "quantite_reelle": [100.0, 100.0]})
    r = P.metriques(df, ["m"]).loc["x"]
    assert r["MAPE"] == pytest.approx(0.10)
    assert r["RMSE"] == pytest.approx(10.0)
    assert r["biais"] == pytest.approx(0.0)
