-- =============================================================================
-- Jeu de données du modèle de risque de retard : UNE LIGNE PAR COMMANDE.
--
-- Seules les informations connues AU MOMENT DE LA COMMANDE servent de variables.
-- Les colonnes "cible" et "filtre" (est_en_retard, est_annulee) ne sont utilisées
-- que pour l'apprentissage et l'évaluation, jamais comme variables explicatives.
-- Exclues volontairement : jours_reels, ecart_jours, statut_livraison,
-- horodatage_expedition, statut_commande (voir README, section fuite de données).
-- =============================================================================
WITH lignes AS (
    SELECT f.*, p.categorie, p.departement
    FROM dw.fait_commandes f
    JOIN dw.dim_produit p USING (produit_id)
),
-- Catégorie "principale" de la commande = celle de la ligne au montant le plus élevé
principale AS (
    SELECT DISTINCT ON (commande_id)
           commande_id, categorie AS categorie_principale, departement AS departement_principal
    FROM lignes
    ORDER BY commande_id, montant_net DESC, ligne_id
),
agregats AS (
    SELECT commande_id,
           MIN(horodatage_commande)        AS horodatage_commande,
           MIN(expedition_id)              AS expedition_id,   -- constant par commande
           MIN(geographie_id)              AS geographie_id,   -- constant par commande
           MIN(client_id)                  AS client_id,       -- constant par commande
           MIN(type_paiement)              AS type_paiement,   -- constant par commande
           COUNT(*)                        AS nb_lignes,
           SUM(quantite)                   AS quantite_totale,
           SUM(montant_net)                AS montant_net_total,
           AVG(taux_remise)                AS taux_remise_moyen,
           AVG(ratio_profit)               AS ratio_profit_moyen,
           MAX(prix_unitaire)              AS prix_max,
           MAX(est_en_retard)              AS est_en_retard,   -- CIBLE
           MAX(est_annulee)                AS est_annulee      -- FILTRE
    FROM lignes
    GROUP BY commande_id
)
SELECT a.commande_id,
       a.horodatage_commande,
       e.mode_expedition,
       g.marche,
       g.region,
       c.segment,
       c.pays                AS client_pays,
       a.type_paiement,
       pr.categorie_principale,
       pr.departement_principal,
       a.nb_lignes,
       a.quantite_totale,
       a.montant_net_total::FLOAT   AS montant_net_total,
       a.taux_remise_moyen::FLOAT   AS taux_remise_moyen,
       a.ratio_profit_moyen::FLOAT  AS ratio_profit_moyen,
       a.prix_max::FLOAT            AS prix_max,
       a.est_en_retard,
       a.est_annulee
FROM agregats a
JOIN dw.dim_expedition e USING (expedition_id)
JOIN dw.dim_geographie g USING (geographie_id)
JOIN dw.dim_client     c USING (client_id)
JOIN principale       pr USING (commande_id)
ORDER BY a.horodatage_commande, a.commande_id;
