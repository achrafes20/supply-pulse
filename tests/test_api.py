"""Tests de l'API FastAPI (client de test, sans serveur)."""
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.models import risque as R

COMMANDE = {
    "horodatage_commande": "2017-11-14T15:30:00", "mode_expedition": "Same Day", "marche": "Europe",
    "region": "Western Europe", "segment": "Consumer", "client_pays": "États-Unis",
    "type_paiement": "DEBIT", "categorie_principale": "Cleats", "departement_principal": "Apparel",
    "nb_lignes": 3, "quantite_totale": 4, "montant_net_total": 420.5, "taux_remise_moyen": 0.1,
    "ratio_profit_moyen": 0.12, "prix_max": 199.99,
}
modele_present = pytest.mark.skipif(not R.CHEMIN_MODELE.exists(), reason="modèle non entraîné (notebook 02)")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:   # "with" déclenche le chargement du modèle (lifespan)
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in {"ok", "degrade"}


@modele_present
def test_predict_risque_format(client):
    r = client.post("/predict/risque", json=COMMANDE)
    assert r.status_code == 200
    corps = r.json()
    assert 0 <= corps["proba_retard"] <= 1
    assert corps["niveau_risque"] in {"faible", "moyen", "élevé"}
    assert corps["alerte_retard"] == (corps["proba_retard"] >= corps["seuil"])


@modele_present
def test_heure_limite_same_day(client):
    """La règle découverte en phase 2 : Same Day commandé l'après-midi -> risque bien plus élevé."""
    apres_midi = client.post("/predict/risque", json=COMMANDE).json()["proba_retard"]
    matin = client.post("/predict/risque", json={**COMMANDE, "horodatage_commande": "2017-11-14T09:00:00"}).json()["proba_retard"]
    assert apres_midi > 0.8 and matin < 0.2


@modele_present
def test_first_class_toujours_a_risque(client):
    r = client.post("/predict/risque", json={**COMMANDE, "mode_expedition": "First Class"}).json()
    assert r["niveau_risque"] == "élevé"


def test_entree_invalide_rejetee(client):
    assert client.post("/predict/risque", json={**COMMANDE, "mode_expedition": "Drone"}).status_code == 422
    assert client.post("/predict/risque", json={**COMMANDE, "nb_lignes": 0}).status_code == 422
    sans_mode = {k: v for k, v in COMMANDE.items() if k != "mode_expedition"}
    assert client.post("/predict/risque", json=sans_mode).status_code == 422


def test_forecast(client):
    if not client.get("/health").json()["base_de_donnees"]:
        pytest.skip("PostgreSQL non joignable")
    r = client.get("/forecast", params={"groupe": "Cleats"})
    if r.status_code == 503:
        pytest.skip("prévisions non calculées (notebook 03)")
    assert r.status_code == 200
    corps = r.json()
    assert corps["nb_semaines"] == 12 and len(corps["semaines"]) == 12
    assert corps["est_modele_retenu"] is True
    assert all(s["groupe_prevision"] == "Cleats" for s in corps["semaines"])


def test_forecast_groupe_inconnu(client):
    if not client.get("/health").json()["base_de_donnees"]:
        pytest.skip("PostgreSQL non joignable")
    assert client.get("/forecast", params={"groupe": "Inexistant"}).status_code == 404
