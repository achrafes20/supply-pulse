# Mesures DAX - Supply Pulse

Toutes les mesures s'appuient sur les vues du schéma `bi` (voir `sql/05_vues_powerbi.sql`)
importées et renommées sans le préfixe `bi` (`fait_commandes`, `dim_date`...).

**Organisation conseillée** : créer une table vide `_Mesures` (Accueil > Entrer des données > OK)
et y ranger toutes les mesures, par dossier d'affichage (Ventes, Livraison, Risque, Prévision).

**Règle de grain à retenir** : `fait_commandes` est au grain *ligne de commande*. Les KPI logistiques
(OTD, retard) se calculent au niveau *commande*, d'où l'usage de `DISTINCTCOUNT` et d'itérateurs sur
`VALUES(commande_id)`. Sinon, une commande de 5 lignes compterait 5 fois.

---

## 1. Ventes

```dax
CA net = SUM ( fait_commandes[montant_net] )                       -- format : # ##0 $

CA brut = SUM ( fait_commandes[montant_brut] )

Remises = SUM ( fait_commandes[remise] )

Taux de remise = DIVIDE ( [Remises], [CA brut] )                    -- format : 0,0 %

Profit = SUM ( fait_commandes[profit] )

Marge % = DIVIDE ( [Profit], [CA net] )                             -- format : 0,0 %

Commandes = DISTINCTCOUNT ( fait_commandes[commande_id] )

Lignes = COUNTROWS ( fait_commandes )

Unités = SUM ( fait_commandes[quantite] )

Clients actifs = DISTINCTCOUNT ( fait_commandes[client_id] )

Panier moyen = DIVIDE ( [CA net], [Commandes] )                     -- format : # ##0,00 $
```

### Intelligence temporelle
Prérequis : `dim_date` marquée comme table de dates (colonne `date`).

```dax
CA N-1 = CALCULATE ( [CA net], SAMEPERIODLASTYEAR ( dim_date[date] ) )

Évolution CA % =
VAR ca_n1 = [CA N-1]
RETURN
    IF ( NOT ISBLANK ( ca_n1 ), DIVIDE ( [CA net] - ca_n1, ca_n1 ) )  -- format : +0,0 %;-0,0 %

CA cumul annuel = TOTALYTD ( [CA net], dim_date[date] )
```

> `IF(NOT ISBLANK(...))` évite d'afficher -100 % ou +∞ sur une période sans historique (2015).

---

## 2. Livraison

```dax
Commandes expédiées =
CALCULATE ( [Commandes], fait_commandes[est_annulee] = 0 )

Commandes en retard =
CALCULATE ( [Commandes], fait_commandes[est_annulee] = 0, fait_commandes[est_en_retard] = 1 )

Taux de retard = DIVIDE ( [Commandes en retard], [Commandes expédiées] )   -- format : 0,0 %

OTD % =
-- On-Time Delivery : part des commandes expédiées livrées à temps ou en avance.
IF ( NOT ISBLANK ( [Commandes expédiées] ), 1 - [Taux de retard] )         -- format : 0,0 %

Retard moyen (j) =
-- Écart moyen (réel - prévu) des seules commandes en retard, une valeur par commande.
AVERAGEX (
    CALCULATETABLE (
        VALUES ( fait_commandes[commande_id] ),
        fait_commandes[est_annulee] = 0,
        fait_commandes[est_en_retard] = 1
    ),
    CALCULATE ( MAX ( fait_commandes[ecart_jours] ) )
)                                                                           -- format : 0,00

Délai réel moyen (j) =
AVERAGEX (
    CALCULATETABLE ( VALUES ( fait_commandes[commande_id] ), fait_commandes[est_annulee] = 0 ),
    CALCULATE ( MAX ( fait_commandes[jours_reels] ) )
)

Délai prévu moyen (j) =
-- prévu = réel - écart (évite de dépendre d'un filtre bidirectionnel vers dim_expedition)
AVERAGEX (
    CALCULATETABLE ( VALUES ( fait_commandes[commande_id] ), fait_commandes[est_annulee] = 0 ),
    CALCULATE ( MAX ( fait_commandes[jours_reels] ) - MAX ( fait_commandes[ecart_jours] ) )
)

Taux d'annulation =
DIVIDE ( CALCULATE ( [Commandes], fait_commandes[est_annulee] = 1 ), [Commandes] )

CA des commandes en retard =
CALCULATE ( [CA net], fait_commandes[est_annulee] = 0, fait_commandes[est_en_retard] = 1 )

Commandes expédiées (date d'expédition) =
-- Utilise la relation INACTIVE fait_commandes[date_expedition_id] -> dim_date[date_id]
CALCULATE ( [Commandes expédiées], USERELATIONSHIP ( fait_commandes[date_expedition_id], dim_date[date_id] ) )
```

---

## 3. Risque de retard (table `fait_risque`, une ligne par commande)

```dax
Commandes scorées = COUNTROWS ( fait_risque )

Probabilité moyenne de retard = AVERAGE ( fait_risque[proba_retard] )     -- le « taux de risque », 0,0 %

Commandes alertées = CALCULATE ( [Commandes scorées], fait_risque[alerte_retard] = 1 )

% commandes alertées = DIVIDE ( [Commandes alertées], [Commandes scorées] )

Commandes risque élevé = CALCULATE ( [Commandes scorées], fait_risque[niveau_risque] = "élevé" )

% risque élevé = DIVIDE ( [Commandes risque élevé], [Commandes scorées] )

CA à risque élevé =
CALCULATE ( SUM ( fait_risque[montant_net_commande] ), fait_risque[niveau_risque] = "élevé" )

Taux de retard réel (scorées) =
-- AVERAGE ignore les vides : les commandes annulées (retard réel NULL) sont exclues.
AVERAGE ( fait_risque[est_en_retard_reel] )

Écart de calibration =
-- Proche de 0 = les probabilités annoncées correspondent à la réalité.
CALCULATE ( [Probabilité moyenne de retard], fait_risque[est_annulee] = 0 ) - [Taux de retard réel (scorées)]
```

### Qualité des alertes, uniquement sur le jeu de test (hors échantillon)
Le filtre `jeu = "test"` est imposé dans la mesure : les prédictions train/validation ont été
vues pendant l'apprentissage et donneraient des scores trop optimistes.

```dax
Vrais positifs (test) =
CALCULATE ( [Commandes scorées], fait_risque[jeu] = "test",
            fait_risque[alerte_retard] = 1, fait_risque[est_en_retard_reel] = 1 )

Retards non anticipés (test) =
CALCULATE ( [Commandes scorées], fait_risque[jeu] = "test",
            fait_risque[alerte_retard] = 0, fait_risque[est_en_retard_reel] = 1 )

Fausses alertes (test) =
-- "==" et non "=" : en DAX, BLANK() = 0 est VRAI, ce qui compterait les commandes
-- annulées (retard réel vide) comme des fausses alertes.
CALCULATE ( [Commandes scorées], fait_risque[jeu] = "test",
            fait_risque[alerte_retard] = 1, fait_risque[est_en_retard_reel] == 0 )

Recall des alertes (test) =
DIVIDE ( [Vrais positifs (test)], [Vrais positifs (test)] + [Retards non anticipés (test)] )

Précision des alertes (test) =
DIVIDE ( [Vrais positifs (test)], [Vrais positifs (test)] + [Fausses alertes (test)] )
```

---

## 4. Prévision de la demande

### Disponible dès maintenant (table `fait_demande_hebdo`)
```dax
Demande réelle (unités) = SUM ( fait_demande_hebdo[quantite] )

Demande réelle - période stable (unités) =
CALCULATE ( [Demande réelle (unités)], fait_demande_hebdo[apres_rupture] = FALSE () )
```

### Prévisions (table `fait_prevision`, produite par le notebook 03)
Une ligne par `debut_semaine` x `groupe_prevision` x `modele` x `type_prevision`
(`backtest` = 48 semaines passées prévues sans les connaître, `futur` = 12 semaines après l'historique stable),
avec `quantite_prevue`, `borne_basse`, `borne_haute` (intervalle 80 %), `quantite_reelle` (vide pour le futur),
`libelle_modele` (nom lisible) et `est_modele_retenu`.

```dax
Prévision (unités) = SUM ( fait_prevision[quantite_prevue] )

Borne basse (unités) = SUM ( fait_prevision[borne_basse] )

Borne haute (unités) = SUM ( fait_prevision[borne_haute] )

Prévision 12 semaines (unités) =
CALCULATE ( [Prévision (unités)], fait_prevision[type_prevision] = "futur" )

Réel en backtest (unités) =
CALCULATE ( SUM ( fait_prevision[quantite_reelle] ), fait_prevision[type_prevision] = "backtest" )

Écart prévision/réel (unités) =
CALCULATE ( [Prévision (unités)], fait_prevision[type_prevision] = "backtest" ) - [Réel en backtest (unités)]

Écart prévision/réel % =
-- Biais : > 0 = sur-prévision, < 0 = sous-prévision.
DIVIDE ( [Écart prévision/réel (unités)], [Réel en backtest (unités)] )          -- format : +0,0 %

MAPE =
-- Erreur absolue moyenne en %, calculée semaine par semaine et groupe par groupe.
AVERAGEX (
    FILTER (
        fait_prevision,
        fait_prevision[type_prevision] = "backtest" && fait_prevision[quantite_reelle] > 0
    ),
    ABS ( fait_prevision[quantite_prevue] - fait_prevision[quantite_reelle] ) / fait_prevision[quantite_reelle]
)                                                                                  -- format : 0,0 %
```

> Toujours filtrer un seul `modele` (segment de page) : sinon les prévisions des différents modèles s'additionnent.

---

## 5. Valeurs de contrôle

Calculées en SQL avec les mêmes définitions (`sql/06_kpi_controle.sql`), **sans aucun filtre**.
Après avoir créé les mesures, placer chacune dans une carte : la valeur doit être identique.
Un écart signale une relation mal configurée ou une mesure mal recopiée.

| Mesure | Valeur attendue |
|---|---|
| CA net | 33 054 402,04 $ |
| Commandes | 65 752 |
| Lignes | 180 519 |
| Unités | 384 079 |
| Clients actifs | 20 652 |
| Panier moyen | 502,71 $ |
| Profit | 3 966 902,97 $ |
| Marge % | 12,0 % |
| Taux de remise | 10,1 % |
| Évolution CA % (année 2016 sélectionnée) | -0,3 % |
| Commandes expédiées | 62 897 |
| Commandes en retard | 36 048 |
| OTD % | 42,7 % |
| Retard moyen (j) | 1,62 |
| Délai réel moyen (j) | 3,50 |
| Taux d'annulation | 4,3 % |
| Probabilité moyenne de retard | 57,3 % |
| % commandes alertées | 97,2 % |
| Commandes risque élevé | 17 603 |
| Recall des alertes (test) | 99,97 % |
| Précision des alertes (test) | 59,1 % |
| Retards non anticipés (test) | 2 |

Prévision (segment `libelle_modele` sur un seul modèle, tous groupes) :

| Modèle | Prévision 12 semaines (unités) | MAPE | Écart prévision/réel % |
|---|---|---|---|
| Moyenne mobile 12 sem. (**retenu**) | 29 799 | 10,2 % | +1,6 % |
| XGBoost | 29 714 | 10,1 % | +0,8 % |
| Prophet | 30 191 | 11,2 % | +1,0 % |
| Naïve saisonnière | 32 091 | 14,2 % | +1,7 % |

OTD % par mode d'expédition (commandes expédiées) : First Class 0,0 % · Same Day 51,6 % ·
Second Class 20,0 % · Standard Class 60,2 %.

> Les valeurs « risque » dépendent du modèle entraîné en phase 2 (version enregistrée dans
> `fait_risque[version_modele]`). Si le notebook 02 est ré-exécuté, relancer `sql/06_kpi_controle.sql`.
