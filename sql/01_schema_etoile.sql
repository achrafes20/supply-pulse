-- =============================================================================
-- Supply Pulse - Modèle en étoile (schéma "dw" = data warehouse)
-- Grain de fait_commandes : une ligne de commande (un produit dans une commande).
-- Script idempotent : il recrée le schéma à chaque exécution de l'ETL.
-- =============================================================================

DROP SCHEMA IF EXISTS dw CASCADE;
CREATE SCHEMA dw;

-- -----------------------------------------------------------------------------
-- Dimension date : calendrier continu (requis par l'intelligence temporelle DAX)
-- -----------------------------------------------------------------------------
CREATE TABLE dw.dim_date (
    date_id        INTEGER PRIMARY KEY,      -- AAAAMMJJ
    date           DATE        NOT NULL UNIQUE,
    annee          SMALLINT    NOT NULL,
    trimestre      SMALLINT    NOT NULL,
    mois           SMALLINT    NOT NULL,
    nom_mois       VARCHAR(12) NOT NULL,
    annee_mois     CHAR(7)     NOT NULL,     -- 'AAAA-MM'
    annee_iso      SMALLINT    NOT NULL,
    semaine_iso    SMALLINT    NOT NULL,
    debut_semaine  DATE        NOT NULL,     -- lundi de la semaine
    jour_mois      SMALLINT    NOT NULL,
    jour_semaine   SMALLINT    NOT NULL,     -- 1 = lundi
    nom_jour       VARCHAR(10) NOT NULL,
    est_weekend    BOOLEAN     NOT NULL
);

-- -----------------------------------------------------------------------------
-- Dimension produit (hiérarchie produit -> catégorie -> département)
-- -----------------------------------------------------------------------------
CREATE TABLE dw.dim_produit (
    produit_id      INTEGER PRIMARY KEY,
    nom_produit     VARCHAR(100)  NOT NULL,
    prix_catalogue  NUMERIC(10,2) NOT NULL,
    categorie_id    INTEGER       NOT NULL,
    categorie       VARCHAR(50)   NOT NULL,
    departement_id  INTEGER       NOT NULL,
    departement     VARCHAR(50)   NOT NULL
);

-- -----------------------------------------------------------------------------
-- Dimension client : AUCUNE donnée personnelle (ni nom, ni e-mail, ni rue)
-- -----------------------------------------------------------------------------
CREATE TABLE dw.dim_client (
    client_id    INTEGER PRIMARY KEY,
    segment      VARCHAR(20) NOT NULL,
    ville        VARCHAR(60) NOT NULL,
    etat         VARCHAR(10) NOT NULL,
    pays         VARCHAR(30) NOT NULL,
    code_postal  CHAR(5)                 -- 3 valeurs manquantes dans la source
);

-- -----------------------------------------------------------------------------
-- Dimension géographie de destination (clé de substitution)
-- -----------------------------------------------------------------------------
CREATE TABLE dw.dim_geographie (
    geographie_id  INTEGER PRIMARY KEY,
    ville          VARCHAR(80) NOT NULL,
    etat           VARCHAR(80) NOT NULL,
    pays           VARCHAR(60) NOT NULL,
    region         VARCHAR(30) NOT NULL,
    marche         VARCHAR(20) NOT NULL,
    UNIQUE (ville, etat, pays, region, marche)
);

-- -----------------------------------------------------------------------------
-- Dimension expédition : le délai prévu dépend uniquement du mode
-- -----------------------------------------------------------------------------
CREATE TABLE dw.dim_expedition (
    expedition_id    SMALLINT PRIMARY KEY,
    mode_expedition  VARCHAR(20) NOT NULL UNIQUE,
    jours_prevus     SMALLINT    NOT NULL
);

-- -----------------------------------------------------------------------------
-- Table de faits
-- -----------------------------------------------------------------------------
CREATE TABLE dw.fait_commandes (
    ligne_id               INTEGER PRIMARY KEY,
    commande_id            INTEGER   NOT NULL,             -- dimension dégénérée
    date_commande_id       INTEGER   NOT NULL REFERENCES dw.dim_date(date_id),
    date_expedition_id     INTEGER   NOT NULL REFERENCES dw.dim_date(date_id),
    horodatage_commande    TIMESTAMP NOT NULL,
    horodatage_expedition  TIMESTAMP NOT NULL,
    produit_id             INTEGER   NOT NULL REFERENCES dw.dim_produit(produit_id),
    client_id              INTEGER   NOT NULL REFERENCES dw.dim_client(client_id),
    geographie_id          INTEGER   NOT NULL REFERENCES dw.dim_geographie(geographie_id),
    expedition_id          SMALLINT  NOT NULL REFERENCES dw.dim_expedition(expedition_id),
    type_paiement          VARCHAR(10) NOT NULL,
    statut_commande        VARCHAR(20) NOT NULL,
    -- Mesures financières
    quantite               SMALLINT      NOT NULL,
    prix_unitaire          NUMERIC(10,2) NOT NULL,
    montant_brut           NUMERIC(12,2) NOT NULL,   -- prix x quantité
    remise                 NUMERIC(12,2) NOT NULL,
    taux_remise            NUMERIC(6,4)  NOT NULL,
    montant_net            NUMERIC(12,2) NOT NULL,   -- brut - remise (= CA)
    profit                 NUMERIC(12,2) NOT NULL,
    ratio_profit           NUMERIC(6,4)  NOT NULL,
    -- Mesures logistiques (connues APRÈS expédition : jamais utilisées par le modèle de risque)
    jours_reels            SMALLINT    NOT NULL,
    ecart_jours            SMALLINT    NOT NULL,     -- réel - prévu (> 0 = retard)
    statut_livraison       VARCHAR(20) NOT NULL,
    est_en_retard          SMALLINT    NOT NULL CHECK (est_en_retard IN (0, 1)),
    est_annulee            SMALLINT    NOT NULL CHECK (est_annulee IN (0, 1))
);

-- Index sur les clés étrangères (jointures Power BI / requêtes analytiques)
CREATE INDEX ix_fait_date_commande ON dw.fait_commandes (date_commande_id);
CREATE INDEX ix_fait_produit       ON dw.fait_commandes (produit_id);
CREATE INDEX ix_fait_client        ON dw.fait_commandes (client_id);
CREATE INDEX ix_fait_geographie    ON dw.fait_commandes (geographie_id);
CREATE INDEX ix_fait_expedition    ON dw.fait_commandes (expedition_id);
CREATE INDEX ix_fait_commande      ON dw.fait_commandes (commande_id);
