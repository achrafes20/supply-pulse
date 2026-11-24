-- =============================================================================
-- Vues prêtes à importer dans Power BI (schéma "bi").
--
-- Pourquoi des vues ?
--   - Power BI n'importe que ce dont il a besoin, avec des noms lisibles ;
--   - la logique (jointures, regroupements) est versionnée en SQL, pas cachée dans Power Query ;
--   - si l'entrepôt évolue, on adapte la vue sans casser le rapport.
--
-- Modèle Power BI obtenu (« constellation » : 3 tables de faits partageant des dimensions) :
--   dim_groupe_prevision 1-* dim_categorie 1-* dim_produit 1-* fait_commandes
--   dim_date / dim_client / dim_geographie / dim_expedition 1-* fait_commandes et fait_risque
--   dim_groupe_prevision / dim_date 1-* fait_demande_hebdo
--
-- Recréées automatiquement à la fin de l'ETL (DROP SCHEMA dw CASCADE les supprime).
-- =============================================================================
DROP SCHEMA IF EXISTS bi CASCADE;
CREATE SCHEMA bi;

-- -----------------------------------------------------------------------------
-- Dimensions
-- -----------------------------------------------------------------------------
CREATE VIEW bi.dim_date AS
SELECT date_id, date, annee, trimestre, 'T' || trimestre AS libelle_trimestre,
       mois, nom_mois, annee_mois, annee_iso, semaine_iso, debut_semaine,
       jour_mois, jour_semaine, nom_jour, est_weekend
FROM dw.dim_date;

-- Groupes de prévision (phase 4) : les 9 catégories qui pèsent le plus dans le CA de la
-- période stable (avant la rupture d'octobre 2017, cf. 01_eda), les autres -> « Autres ».
CREATE VIEW bi.dim_groupe_prevision AS
WITH ca AS (
    SELECT p.categorie, SUM(f.montant_net) AS ca
    FROM dw.fait_commandes f JOIN dw.dim_produit p USING (produit_id)
    WHERE f.horodatage_commande < DATE '2017-10-01'
    GROUP BY p.categorie
), rang AS (
    SELECT categorie, ROW_NUMBER() OVER (ORDER BY ca DESC) AS rang FROM ca
)
SELECT DISTINCT CASE WHEN rang <= 9 THEN categorie ELSE 'Autres' END AS groupe_prevision,
                CASE WHEN rang <= 9 THEN rang ELSE 10 END        AS ordre_tri
FROM rang;

-- Catégorie (clé = nom : « Electronics » existe sous 2 identifiants dans la source)
CREATE VIEW bi.dim_categorie AS
WITH ca AS (
    SELECT p.categorie, SUM(f.montant_net) AS ca
    FROM dw.fait_commandes f JOIN dw.dim_produit p USING (produit_id)
    WHERE f.horodatage_commande < DATE '2017-10-01'
    GROUP BY p.categorie
), rang AS (
    SELECT categorie, ROW_NUMBER() OVER (ORDER BY ca DESC) AS rang FROM ca
)
SELECT p.categorie,
       STRING_AGG(DISTINCT p.departement, ', ' ORDER BY p.departement) AS departement,
       COALESCE(CASE WHEN r.rang <= 9 THEN p.categorie END, 'Autres')  AS groupe_prevision,
       (MIN(f_min.date_premiere_vente) >= DATE '2017-10-01')           AS est_nouveau_catalogue
FROM dw.dim_produit p
LEFT JOIN rang r USING (categorie)
LEFT JOIN (SELECT produit_id, MIN(horodatage_commande) AS date_premiere_vente
           FROM dw.fait_commandes GROUP BY produit_id) f_min USING (produit_id)
GROUP BY p.categorie, r.rang;

CREATE VIEW bi.dim_produit AS
SELECT produit_id, nom_produit, prix_catalogue, categorie
FROM dw.dim_produit;

CREATE VIEW bi.dim_client AS
SELECT client_id, segment, ville, etat, pays, code_postal
FROM dw.dim_client;

CREATE VIEW bi.dim_geographie AS
SELECT geographie_id, ville, etat, pays, region, marche
FROM dw.dim_geographie;

CREATE VIEW bi.dim_expedition AS
SELECT expedition_id, mode_expedition, jours_prevus,
       -- ordre logique pour les axes (du plus rapide au plus lent)
       CASE mode_expedition WHEN 'Same Day' THEN 1 WHEN 'First Class' THEN 2
                            WHEN 'Second Class' THEN 3 ELSE 4 END AS ordre_tri
FROM dw.dim_expedition;

-- -----------------------------------------------------------------------------
-- Faits
-- -----------------------------------------------------------------------------
-- Grain : ligne de commande
CREATE VIEW bi.fait_commandes AS
SELECT ligne_id, commande_id, date_commande_id, date_expedition_id,
       produit_id, client_id, geographie_id, expedition_id,
       type_paiement, statut_commande,
       quantite, prix_unitaire, montant_brut, remise, taux_remise, montant_net, profit,
       jours_reels, ecart_jours, statut_livraison, est_en_retard, est_annulee,
       EXTRACT(HOUR FROM horodatage_commande)::INT AS heure_commande
FROM dw.fait_commandes;

-- Grain : commande (prédiction du modèle de risque + clés vers les dimensions partagées)
CREATE VIEW bi.fait_risque AS
WITH commande AS (
    SELECT commande_id,
           MIN(client_id)      AS client_id,       -- constants par commande (vérifié en 01_eda)
           MIN(geographie_id)  AS geographie_id,
           MIN(expedition_id)  AS expedition_id,
           MIN(horodatage_commande) AS horodatage_commande,
           SUM(montant_net)    AS montant_net_commande
    FROM dw.fait_commandes
    GROUP BY commande_id
)
SELECT p.commande_id, p.date_commande_id, c.client_id, c.geographie_id, c.expedition_id,
       p.proba_retard, p.alerte_retard, p.niveau_risque,
       CASE p.niveau_risque WHEN 'faible' THEN 1 WHEN 'moyen' THEN 2 ELSE 3 END AS niveau_ordre,
       p.seuil, p.jeu, p.est_annulee, p.est_en_retard_reel, p.version_modele,
       EXTRACT(HOUR FROM c.horodatage_commande)::INT AS heure_commande,
       CASE WHEN EXTRACT(HOUR FROM c.horodatage_commande) < 12 THEN 'avant 12 h'
            ELSE 'à partir de 12 h' END AS creneau_commande,
       c.montant_net_commande
FROM ml.pred_risque_livraison p
JOIN commande c USING (commande_id);

-- Grain : semaine x groupe x modèle x type (prévisions de la phase 4)
CREATE VIEW bi.fait_prevision AS
SELECT debut_semaine,
       TO_CHAR(debut_semaine, 'YYYYMMDD')::INT AS date_semaine_id,
       groupe_prevision, modele,
       CASE modele WHEN 'moyenne_mobile_12' THEN 'Moyenne mobile 12 sem.'
                   WHEN 'naive_saisonniere' THEN 'Naïve saisonnière'
                   WHEN 'prophet' THEN 'Prophet' WHEN 'xgboost' THEN 'XGBoost'
                   ELSE modele END AS libelle_modele,
       type_prevision, pli, horizon,
       quantite_prevue::FLOAT AS quantite_prevue,
       borne_basse::FLOAT     AS borne_basse,
       borne_haute::FLOAT     AS borne_haute,
       quantite_reelle::FLOAT AS quantite_reelle,
       est_modele_retenu
FROM ml.pred_demande;

-- Grain : semaine x groupe de prévision (demande réelle, unités)
CREATE VIEW bi.fait_demande_hebdo AS
SELECT d.debut_semaine,
       TO_CHAR(d.debut_semaine, 'YYYYMMDD')::INT AS date_semaine_id,   -- lundi -> dim_date
       cat.groupe_prevision,
       SUM(f.quantite)    AS quantite,
       SUM(f.montant_net) AS montant_net,
       (d.debut_semaine >= DATE '2017-09-25') AS apres_rupture        -- 1re semaine touchée par la rupture
FROM dw.fait_commandes f
JOIN dw.dim_date d ON d.date_id = f.date_commande_id
JOIN dw.dim_produit p USING (produit_id)
JOIN bi.dim_categorie cat USING (categorie)
GROUP BY d.debut_semaine, cat.groupe_prevision;
