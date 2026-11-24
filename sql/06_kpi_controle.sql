-- =============================================================================
-- Valeurs de contrôle des mesures DAX (powerbi/mesures_dax.md).
-- Chaque KPI est recalculé ici en SQL avec la même définition que la mesure DAX :
-- dans Power BI, une carte sans filtre doit afficher exactement la même valeur.
-- =============================================================================
WITH cmd AS (   -- une ligne par commande
    SELECT commande_id, MAX(est_annulee) AS annulee, MAX(est_en_retard) AS retard,
           MAX(ecart_jours) AS ecart, MAX(jours_reels) AS jours_reels
    FROM bi.fait_commandes GROUP BY commande_id
), annee AS (
    SELECT d.annee, SUM(f.montant_net) AS ca
    FROM bi.fait_commandes f JOIN bi.dim_date d ON d.date_id = f.date_commande_id
    GROUP BY d.annee
)
SELECT 'CA net'                    AS kpi, ROUND(SUM(montant_net), 2)::TEXT AS valeur FROM bi.fait_commandes
UNION ALL SELECT 'Commandes',       COUNT(DISTINCT commande_id)::TEXT FROM bi.fait_commandes
UNION ALL SELECT 'Lignes',          COUNT(*)::TEXT FROM bi.fait_commandes
UNION ALL SELECT 'Unités',          SUM(quantite)::TEXT FROM bi.fait_commandes
UNION ALL SELECT 'Clients actifs',  COUNT(DISTINCT client_id)::TEXT FROM bi.fait_commandes
UNION ALL SELECT 'Panier moyen',    ROUND(SUM(montant_net) / COUNT(DISTINCT commande_id), 2)::TEXT FROM bi.fait_commandes
UNION ALL SELECT 'Profit',          ROUND(SUM(profit), 2)::TEXT FROM bi.fait_commandes
UNION ALL SELECT 'Marge %',         ROUND(100 * SUM(profit) / SUM(montant_net), 2)::TEXT FROM bi.fait_commandes
UNION ALL SELECT 'Taux de remise %', ROUND(100 * SUM(remise) / SUM(montant_brut), 2)::TEXT FROM bi.fait_commandes
UNION ALL SELECT 'Évolution CA 2016 vs 2015 %',
          ROUND(100 * (MAX(ca) FILTER (WHERE annee = 2016) / MAX(ca) FILTER (WHERE annee = 2015) - 1), 2)::TEXT FROM annee
UNION ALL SELECT 'Commandes expédiées', COUNT(*) FILTER (WHERE annulee = 0)::TEXT FROM cmd
UNION ALL SELECT 'Commandes en retard', COUNT(*) FILTER (WHERE annulee = 0 AND retard = 1)::TEXT FROM cmd
UNION ALL SELECT 'OTD %', ROUND(100 * (1 - AVG(retard::NUMERIC) FILTER (WHERE annulee = 0)), 2)::TEXT FROM cmd
UNION ALL SELECT 'Retard moyen (j, commandes en retard)',
          ROUND(AVG(ecart) FILTER (WHERE annulee = 0 AND retard = 1), 3)::TEXT FROM cmd
UNION ALL SELECT 'Délai réel moyen (j, expédiées)',
          ROUND(AVG(jours_reels) FILTER (WHERE annulee = 0), 3)::TEXT FROM cmd
UNION ALL SELECT 'Taux d''annulation %', ROUND(100 * AVG(annulee::NUMERIC), 2)::TEXT FROM cmd
UNION ALL SELECT 'Probabilité moyenne de retard %', ROUND(100 * AVG(proba_retard), 2)::TEXT FROM bi.fait_risque
UNION ALL SELECT '% commandes alertées', ROUND(100 * AVG(alerte_retard::NUMERIC), 2)::TEXT FROM bi.fait_risque
UNION ALL SELECT 'Commandes risque élevé', COUNT(*) FILTER (WHERE niveau_risque = 'élevé')::TEXT FROM bi.fait_risque
UNION ALL SELECT 'Recall des alertes (test) %',
          ROUND(100 * COUNT(*) FILTER (WHERE alerte_retard = 1 AND est_en_retard_reel = 1)::NUMERIC
                / NULLIF(COUNT(*) FILTER (WHERE est_en_retard_reel = 1), 0), 2)::TEXT
          FROM bi.fait_risque WHERE jeu = 'test'
UNION ALL SELECT 'Précision des alertes (test) %',
          ROUND(100 * COUNT(*) FILTER (WHERE alerte_retard = 1 AND est_en_retard_reel = 1)::NUMERIC
                / NULLIF(COUNT(*) FILTER (WHERE alerte_retard = 1 AND est_annulee = 0), 0), 2)::TEXT
          FROM bi.fait_risque WHERE jeu = 'test'
UNION ALL SELECT 'Retards non anticipés (test)',
          COUNT(*) FILTER (WHERE alerte_retard = 0 AND est_en_retard_reel = 1)::TEXT
          FROM bi.fait_risque WHERE jeu = 'test';
