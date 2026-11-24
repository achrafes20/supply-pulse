-- =============================================================================
-- Prévisions de demande hebdomadaire (schéma "ml"), produites par 03_prevision.
-- Une ligne par semaine x groupe de prévision x modèle x type.
--   type_prevision = 'backtest' : semaines passées prévues sans les connaître (évaluation)
--   type_prevision = 'futur'    : 12 semaines après la fin de l'historique stable
-- Idempotent : créée si absente ; le notebook la vide (TRUNCATE) puis la recharge.
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS ml.pred_demande (
    debut_semaine     DATE         NOT NULL,          -- lundi
    groupe_prevision  VARCHAR(30)  NOT NULL,
    modele            VARCHAR(30)  NOT NULL,
    type_prevision    VARCHAR(10)  NOT NULL CHECK (type_prevision IN ('backtest', 'futur')),
    pli               SMALLINT,                       -- n° de pli du backtest (NULL pour le futur)
    horizon           SMALLINT     NOT NULL,          -- 1 à 12 semaines après l'origine
    quantite_prevue   NUMERIC(10,2) NOT NULL,
    borne_basse       NUMERIC(10,2),                  -- intervalle à 80 %
    borne_haute       NUMERIC(10,2),
    quantite_reelle   NUMERIC(10,2),                  -- NULL pour le futur
    est_modele_retenu BOOLEAN      NOT NULL,
    date_calcul       TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (debut_semaine, groupe_prevision, modele, type_prevision)
);
