-- =============================================================================
-- Contrôles qualité après chargement (exécutés automatiquement par l'ETL).
-- Chaque requête renvoie (controle, valeur) ; les attendus sont dans run_etl.py.
-- =============================================================================

SELECT 'lignes_fait' AS controle, COUNT(*)::NUMERIC AS valeur FROM dw.fait_commandes
UNION ALL
SELECT 'commandes_distinctes', COUNT(DISTINCT commande_id) FROM dw.fait_commandes
UNION ALL
SELECT 'ca_net_total', ROUND(SUM(montant_net), 2) FROM dw.fait_commandes
UNION ALL
-- Intégrité référentielle : doit valoir 0 (les FK l'imposent déjà, contrôle explicite)
SELECT 'orphelins_produit', COUNT(*) FROM dw.fait_commandes f
    LEFT JOIN dw.dim_produit p USING (produit_id) WHERE p.produit_id IS NULL
UNION ALL
SELECT 'orphelins_client', COUNT(*) FROM dw.fait_commandes f
    LEFT JOIN dw.dim_client c USING (client_id) WHERE c.client_id IS NULL
UNION ALL
-- Trous dans le calendrier : doit valoir 0
SELECT 'trous_calendrier',
       (MAX(date) - MIN(date) + 1) - COUNT(*) FROM dw.dim_date
UNION ALL
-- Cohérence montant : net = brut - remise (tolérance d'arrondi)
SELECT 'incoherences_montant', COUNT(*) FROM dw.fait_commandes
    WHERE ABS(montant_net - (montant_brut - remise)) > 0.02;
