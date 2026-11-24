"""Point d'entrée de l'ETL : CSV brut -> modèle en étoile PostgreSQL.

Usage (depuis la racine du projet, base démarrée) :
    python -m src.etl.run_etl
"""
from __future__ import annotations

import logging
import time

from src.config import DATA_PROCESSED, SQL_DIR
from src.etl.extract import lire_csv_brut
from src.etl.load import copier_dataframe, creer_moteur, executer_script_sql, lire_controles
from src.etl.transform import construire_etoile, nettoyer

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("etl")

# Ordre de chargement : dimensions d'abord, faits ensuite (contraintes de clés étrangères).
ORDRE_CHARGEMENT = ["dim_date", "dim_produit", "dim_client", "dim_geographie",
                    "dim_expedition", "fait_commandes"]


def main() -> dict[str, float]:
    debut = time.perf_counter()

    brut = lire_csv_brut()
    log.info("Extraction : %d lignes x %d colonnes", *brut.shape)

    propre = nettoyer(brut)
    # Copie plate nettoyée (sans données personnelles) pour les notebooks.
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    propre.to_parquet(DATA_PROCESSED / "commandes_propres.parquet", index=False)
    log.info("Nettoyage : %d colonnes conservées -> data/processed/commandes_propres.parquet",
             propre.shape[1])

    etoile = construire_etoile(propre)
    for nom in ORDRE_CHARGEMENT:
        log.info("  %-16s %7d lignes", nom, len(etoile[nom]))

    engine = creer_moteur()
    executer_script_sql(engine, SQL_DIR / "01_schema_etoile.sql")
    log.info("Schéma dw recréé")
    for nom in ORDRE_CHARGEMENT:
        copier_dataframe(engine, etoile[nom], nom)
    log.info("Chargement COPY terminé")

    # Contrôles qualité : réconciliation avec la source + intégrité.
    controles = lire_controles(engine, SQL_DIR / "02_controles_qualite.sql")
    attendus = {
        "lignes_fait": len(brut),
        "commandes_distinctes": brut["Order Id"].nunique(),
        "ca_net_total": round(propre["montant_net"].round(2).sum(), 2),
        "orphelins_produit": 0,
        "orphelins_client": 0,
        "trous_calendrier": 0,
        "incoherences_montant": 0,
    }
    erreurs = []
    for nom, attendu in attendus.items():
        obtenu = controles[nom]
        ok = abs(obtenu - attendu) <= 0.05
        log.info("  [%s] %-22s obtenu=%s attendu=%s", "OK" if ok else "KO", nom, obtenu, attendu)
        if not ok:
            erreurs.append(nom)
    if erreurs:
        raise RuntimeError(f"Contrôles qualité en échec : {erreurs}")

    # Tables de prédictions (créées vides si absentes, jamais écrasées) puis vues Power BI.
    # Les vues sont recréées ici car "DROP SCHEMA dw CASCADE" les a supprimées.
    executer_script_sql(engine, SQL_DIR / "04_pred_risque.sql")
    executer_script_sql(engine, SQL_DIR / "07_pred_demande.sql")
    executer_script_sql(engine, SQL_DIR / "05_vues_powerbi.sql")
    log.info("Schéma ml vérifié, vues Power BI (schéma bi) recréées")

    log.info("ETL terminé en %.1f s", time.perf_counter() - debut)
    return controles


if __name__ == "__main__":
    main()
