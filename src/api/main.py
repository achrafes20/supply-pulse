"""API Supply Pulse.

Endpoints :
- GET  /health           : état du service (modèle chargé, base joignable)
- POST /predict/risque   : probabilité de retard d'une commande, calculée en direct par le modèle XGBoost
- GET  /forecast         : prévisions de demande sur 12 semaines, lues dans ml.pred_demande
- GET  /forecast/groupes : groupes de prévision disponibles

Choix d'architecture :
- le risque est calculé **à la demande** (une commande arrive, on la score immédiatement) ;
- la prévision est calculée **en lot** par le notebook 03 (hebdomadaire) puis servie depuis la base :
  inutile de ré-entraîner Prophet/XGBoost à chaque appel.

Lancement local : uvicorn src.api.main:app --reload   (documentation : http://localhost:8000/docs)
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from src.config import MODELS_DIR, get_database_url
from src.models import risque as R

log = logging.getLogger("api")

# Valeurs autorisées (issues du dataset) : une valeur inconnue est rejetée avec un message clair (422).
ModeExpedition = Literal["Standard Class", "Second Class", "First Class", "Same Day"]
Marche = Literal["Africa", "Europe", "LATAM", "Pacific Asia", "USCA"]
Segment = Literal["Consumer", "Corporate", "Home Office"]
TypePaiement = Literal["DEBIT", "TRANSFER", "PAYMENT", "CASH"]

ETAT: dict = {}   # modèle et connexion, initialisés au démarrage


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    """Charge le modèle une seule fois au démarrage (et non à chaque requête)."""
    try:
        ETAT["risque"] = R.charger()
        log.info("Modèle de risque chargé : %s", ETAT["risque"]["version"])
    except FileNotFoundError:
        ETAT["risque"] = None
        log.warning("Modèle de risque absent (%s) : exécuter le notebook 02_risque", R.CHEMIN_MODELE)
    chemin_meta = MODELS_DIR / "prevision.json"
    ETAT["prevision"] = json.loads(chemin_meta.read_text(encoding="utf-8")) if chemin_meta.exists() else None
    ETAT["engine"] = create_engine(get_database_url(), pool_pre_ping=True)
    yield
    ETAT["engine"].dispose()


app = FastAPI(
    title="Supply Pulse API",
    version="1.0.0",
    description="Risque de retard de livraison et prévision de la demande (dataset DataCo).",
    lifespan=cycle_de_vie,
)


# =============================================================================
# Schémas
# =============================================================================
class CommandeRisque(BaseModel):
    """Une commande, décrite uniquement par des informations connues au moment de la commande."""

    horodatage_commande: datetime = Field(description="Date et heure de la commande")
    mode_expedition: ModeExpedition
    marche: Marche
    region: str = Field(min_length=2, examples=["Western Europe"])
    segment: Segment
    client_pays: Literal["États-Unis", "Puerto Rico"] = "États-Unis"
    type_paiement: TypePaiement
    categorie_principale: str = Field(min_length=2, examples=["Cleats"])
    departement_principal: str = Field(min_length=2, examples=["Apparel"])
    nb_lignes: int = Field(ge=1, le=50)
    quantite_totale: int = Field(ge=1, le=500)
    montant_net_total: float = Field(gt=0)
    taux_remise_moyen: float = Field(ge=0, le=1)
    ratio_profit_moyen: float = Field(ge=-5, le=1)
    prix_max: float = Field(gt=0)

    model_config = ConfigDict(json_schema_extra={"example": {
        "horodatage_commande": "2017-11-14T15:30:00", "mode_expedition": "Same Day", "marche": "Europe",
        "region": "Western Europe", "segment": "Consumer", "client_pays": "États-Unis",
        "type_paiement": "DEBIT", "categorie_principale": "Cleats", "departement_principal": "Apparel",
        "nb_lignes": 3, "quantite_totale": 4, "montant_net_total": 420.5, "taux_remise_moyen": 0.1,
        "ratio_profit_moyen": 0.12, "prix_max": 199.99}})


class ReponseRisque(BaseModel):
    proba_retard: float = Field(description="Probabilité de retard (0-1)")
    alerte_retard: bool = Field(description="Vrai si proba >= seuil métier")
    niveau_risque: Literal["faible", "moyen", "élevé"]
    seuil: float
    version_modele: str


class SemainePrevision(BaseModel):
    debut_semaine: date
    groupe_prevision: str
    quantite_prevue: float
    borne_basse: float | None
    borne_haute: float | None


class ReponsePrevision(BaseModel):
    modele: str
    est_modele_retenu: bool
    nb_semaines: int
    total_prevu: float
    semaines: list[SemainePrevision]


# =============================================================================
# Endpoints
# =============================================================================
@app.get("/health", tags=["service"])
def health() -> dict:
    try:
        with ETAT["engine"].connect() as conn:
            conn.execute(text("SELECT 1"))
        base_ok = True
    except SQLAlchemyError:
        base_ok = False
    modele = ETAT.get("risque")
    return {
        "status": "ok" if (modele and base_ok) else "degrade",
        "modele_risque": modele["version"] if modele else None,
        "modele_prevision_retenu": (ETAT.get("prevision") or {}).get("modele_retenu"),
        "base_de_donnees": base_ok,
    }


@app.post("/predict/risque", response_model=ReponseRisque, tags=["risque"])
def predict_risque(commande: CommandeRisque) -> ReponseRisque:
    modele = ETAT.get("risque")
    if modele is None:
        raise HTTPException(503, "Modèle de risque non disponible : exécuter le notebook 02_risque.")
    # Mêmes transformations qu'à l'entraînement (fonction partagée du module risque).
    df = R.ajouter_variables_temporelles(pd.DataFrame([commande.model_dump()]))
    proba = float(modele["pipeline"].predict_proba(df[R.VARIABLES])[0, 1])
    seuil = float(modele["seuil"])
    return ReponseRisque(
        proba_retard=round(proba, 4),
        alerte_retard=proba >= seuil,
        niveau_risque=str(R.niveau_risque([proba], seuil)[0]),
        seuil=seuil,
        version_modele=modele["version"],
    )


def _lire(requete: str, **params) -> pd.DataFrame:
    try:
        with ETAT["engine"].connect() as conn:
            return pd.read_sql(text(requete), conn, params=params)
    except SQLAlchemyError as e:
        raise HTTPException(503, "Base de données indisponible.") from e


@app.get("/forecast/groupes", tags=["prévision"])
def forecast_groupes() -> list[str]:
    return _lire("SELECT DISTINCT groupe_prevision FROM ml.pred_demande ORDER BY 1")["groupe_prevision"].tolist()


@app.get("/forecast", response_model=ReponsePrevision, tags=["prévision"])
def forecast(
    groupe: str | None = Query(None, description="Groupe de prévision (vide = tous)"),
    modele: Literal["moyenne_mobile_12", "naive_saisonniere", "prophet", "xgboost"] | None = Query(
        None, description="Modèle (vide = modèle retenu au backtest)"),
) -> ReponsePrevision:
    if modele is None:
        meta = ETAT.get("prevision")
        if meta is None:
            raise HTTPException(503, "Prévisions non disponibles : exécuter le notebook 03_prevision.")
        modele = meta["modele_retenu"]
    df = _lire(
        """SELECT debut_semaine, groupe_prevision, quantite_prevue::FLOAT AS quantite_prevue,
                  borne_basse::FLOAT AS borne_basse, borne_haute::FLOAT AS borne_haute, est_modele_retenu
           FROM ml.pred_demande
           WHERE type_prevision = 'futur' AND modele = :modele
             AND (CAST(:groupe AS TEXT) IS NULL OR groupe_prevision = :groupe)
           ORDER BY groupe_prevision, debut_semaine""",
        modele=modele, groupe=groupe,
    )
    if df.empty:
        raise HTTPException(404, f"Aucune prévision pour groupe={groupe!r}, modele={modele!r}. "
                                 "Voir /forecast/groupes.")
    df = df.astype(object).where(df.notna(), None)   # NaN -> null en JSON
    return ReponsePrevision(
        modele=modele,
        est_modele_retenu=bool(df["est_modele_retenu"].iloc[0]),
        nb_semaines=int(df["debut_semaine"].nunique()),
        total_prevu=round(float(sum(df["quantite_prevue"])), 1),
        semaines=[SemainePrevision(**r) for r in df.drop(columns="est_modele_retenu").to_dict("records")],
    )
