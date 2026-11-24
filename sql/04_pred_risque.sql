-- =============================================================================
-- Table des prédictions du modèle de risque de retard (schéma "ml").
-- Schéma séparé de "dw" : relancer l'ETL (qui recrée dw) n'efface pas les prédictions.
-- Script idempotent : la table est créée si elle n'existe pas. Le scoring la vide
-- (TRUNCATE) puis la recharge, ce qui préserve les vues Power BI qui en dépendent.
-- Une ligne par commande ; jointure avec dw.fait_commandes sur commande_id.
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS ml.pred_risque_livraison (
    commande_id          INTEGER PRIMARY KEY,
    date_commande_id     INTEGER      NOT NULL,         -- clé vers dw.dim_date
    proba_retard         NUMERIC(5,4) NOT NULL,         -- probabilité prédite (0-1)
    alerte_retard        SMALLINT     NOT NULL CHECK (alerte_retard IN (0, 1)),  -- proba >= seuil
    niveau_risque        VARCHAR(6)   NOT NULL,         -- faible / moyen / élevé
    seuil                NUMERIC(4,2) NOT NULL,
    jeu                  VARCHAR(10)  NOT NULL,         -- train / validation / test
    est_annulee          SMALLINT     NOT NULL,
    est_en_retard_reel   SMALLINT,                      -- NULL si commande annulée
    version_modele       VARCHAR(40)  NOT NULL,
    date_scoring         TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_pred_risque_date ON ml.pred_risque_livraison (date_commande_id);
