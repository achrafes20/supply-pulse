# Supply Pulse

**Data Analytics et IA pour la Supply Chain** : prévision de la demande, anticipation des risques de
retard de livraison et pilotage de la performance via Power BI.

Projet de bout en bout sur le dataset public **DataCo Smart Supply Chain** (180 519 lignes de commande,
2015-2018) : entrepôt PostgreSQL en étoile, modèle de risque de retard (XGBoost + SHAP), prévision
hebdomadaire de la demande (baseline, Prophet, XGBoost), kit Power BI et API FastAPI conteneurisée.

> Tous les chiffres de ce README sont ceux réellement obtenus par les notebooks et scripts du dépôt.

---

## Résultats clés

| Sujet | Résultat |
|---|---|
| Performance logistique | **OTD 42,7 %** des commandes expédiées. First Class : 0 % à l'heure (1 jour promis, toujours 2 livrés) ; Second Class : 20 % ; Same Day : 51,6 % ; Standard Class : 60,2 % |
| Risque de retard (test, 13 071 commandes futures) | XGBoost **ROC-AUC 0,778** contre 0,746 pour la règle « taux de retard du mode » ; recall 99,97 %, précision 59,1 % au seuil métier 0,20 |
| Ce que le modèle a découvert (SHAP) | une **heure limite à midi pour le Same Day** : commandé avant 12 h, 0 % de retard (1 759 commandes) ; après 12 h, 100 % (1 648) |
| Prévision de la demande (backtest 4 x 12 semaines) | **MAPE 10,2 %** (moyenne mobile 12 sem., retenue) ; XGBoost 10,1 % (écart non significatif, p = 0,50) ; Prophet 11,2 % ; naïve saisonnière 14,2 % |
| Limite assumée | rupture de catalogue en octobre 2017 : la demande réelle des 12 semaines suivantes est **74 % sous** la prévision. Aucun modèle fondé sur l'historique ne pouvait l'anticiper |

**Message métier** : le retard est d'abord un problème de **promesse de délai** (First Class, Second Class) et
d'**heure limite** non affichée (Same Day), plus qu'un problème de prédiction. Pour Second et Standard Class
(~80 % des commandes), rien d'observable à la commande ne permet de faire mieux que le mode d'expédition.

---

## Architecture

```
 data/raw/DataCo...csv (Kaggle, non versionné)
          │
          ▼  src/etl  (extract -> transform -> load, COPY, contrôles qualité)
 ┌──────────────────────────── PostgreSQL 16 (Docker) ────────────────────────────┐
 │  dw  : modèle en étoile    fait_commandes + dim_date / produit / client /       │
 │                            geographie / expedition                              │
 │  ml  : prédictions         pred_risque_livraison   pred_demande                 │
 │  bi  : vues Power BI       11 vues (constellation 4 faits / 7 dimensions)       │
 └──────────▲───────────────────────────▲──────────────────────────┬──────────────┘
            │ notebooks 02 / 03          │ GET /forecast            │ import
            │ (entraînement, scoring)    │                          ▼
   models/risque_xgb.joblib ──► API FastAPI (Docker) ◄── POST   Power BI Desktop
   models/prevision.json         /health /predict/risque        3 pages : Performance,
                                 /forecast                      Prévision, Risque
```

**Deux modes de service**
- **Risque** : calculé **à la demande** par l'API (une commande arrive, elle est scorée immédiatement)
  et **en lot** dans `ml.pred_risque_livraison` pour Power BI.
- **Prévision** : calculée **en lot** (hebdomadaire) par le notebook 03 et servie depuis `ml.pred_demande` :
  inutile de ré-entraîner Prophet ou XGBoost à chaque appel.

---

## Démarrage

Prérequis : Python 3.11, Docker Desktop, le fichier `DataCoSupplyChainDataset.csv` dans `data/raw/`.

```bash
# 1. Environnement Python
py -3.11 -m venv .venv
.venv\Scripts\activate                 # Linux/macOS : source .venv/bin/activate
pip install -r requirements.txt
python -m ipykernel install --user --name supply-pulse --display-name "Python 3.11 (supply-pulse)"

# 2. Base PostgreSQL (port 5433 côté machine, pour ne pas gêner un PostgreSQL local)
copy .env.example .env                 # Linux/macOS : cp .env.example .env
docker compose up -d postgres

# 3. ETL : CSV -> schéma dw + vues Power BI (bi), contrôles qualité inclus (~1 min)
python -m src.etl.run_etl

# 4. Notebooks, ré-exécutables de bout en bout (seed fixée)
jupyter nbconvert --to notebook --execute --inplace notebooks/01_eda.ipynb
jupyter nbconvert --to notebook --execute --inplace notebooks/02_risque.ipynb     # modèle + ml.pred_risque_livraison
jupyter nbconvert --to notebook --execute --inplace notebooks/03_prevision.ipynb  # ml.pred_demande + models/prevision.json

# 5. Tests (34 tests ; ceux qui demandent la base ou un modèle sont ignorés s'ils manquent)
pytest

# 6. API conteneurisée (à reconstruire après un ré-entraînement)
docker compose up -d --build api
# Documentation interactive : http://localhost:8000/docs
```

### Exemples d'appels

```bash
curl http://localhost:8000/health
# {"status":"ok","modele_risque":"risque-xgb-...","modele_prevision_retenu":"moyenne_mobile_12","base_de_donnees":true}

curl -X POST http://localhost:8000/predict/risque -H "Content-Type: application/json" -d '{
  "horodatage_commande": "2017-11-14T15:30:00", "mode_expedition": "Same Day", "marche": "Europe",
  "region": "Western Europe", "segment": "Consumer", "type_paiement": "DEBIT",
  "categorie_principale": "Cleats", "departement_principal": "Apparel", "nb_lignes": 3,
  "quantite_totale": 4, "montant_net_total": 420.5, "taux_remise_moyen": 0.1,
  "ratio_profit_moyen": 0.12, "prix_max": 199.99}'
# {"proba_retard":0.9408,"alerte_retard":true,"niveau_risque":"élevé","seuil":0.2,...}
# La même commande passée à 09:00 : {"proba_retard":0.0656,"alerte_retard":false,"niveau_risque":"faible",...}

curl "http://localhost:8000/forecast?groupe=Cleats"
# {"modele":"moyenne_mobile_12","est_modele_retenu":true,"nb_semaines":12,"total_prevu":6158.0,"semaines":[...]}
```

Une entrée invalide (mode d'expédition inconnu, quantité nulle, champ manquant) est rejetée avec un code **422**
et un message explicite ; une base indisponible renvoie **503**.

---

## Arborescence

```
supply-pulse/
├── data/raw/                 CSV Kaggle (non versionné)
├── data/processed/           table plate nettoyée (Parquet), régénérée par l'ETL
├── notebooks/                01_eda · 02_risque · 03_prevision
├── src/
│   ├── config.py             chemins, seed, connexion
│   ├── etl/                  extract · transform · load · run_etl
│   ├── models/               risque.py · prevision.py (partagés notebooks / API)
│   └── api/main.py           API FastAPI
├── sql/                      01 schéma étoile · 02 contrôles · 03 dataset risque · 04/07 tables ml
│                             05 vues Power BI · 06 KPI de contrôle
├── powerbi/                  mesures_dax.md · plan_dashboard.md · theme_supply_pulse.json · captures/
├── models/                   modèles entraînés (non versionnés)
├── tests/                    34 tests pytest
├── Dockerfile · requirements-api.txt · .dockerignore
└── docker-compose.yml        postgres + api
```

---

## 1. Données et entrepôt (notebook `01_eda`, `src/etl`)

### Ce que dit le dataset
- 180 519 lignes de commande, 65 752 commandes, 20 652 clients, 118 produits, du 01/01/2015 au 31/01/2018.
- Grain : la **ligne de commande** (`Order Item Id` unique, aucune ligne dupliquée).
- 6 colonnes sont des copies exactes d'autres colonnes ; `Product Description` est vide, `Product Status`
  constante, `Order Zipcode` manquant à 86 %.
- `Late_delivery_risk` est **calculée** comme `jours réels > jours prévus` (les 4 423 exceptions sont toutes
  des expéditions annulées, forcées à 0).
- Le délai prévu est entièrement déterminé par le mode d'expédition. En Second et Standard Class, le délai réel
  est réparti uniformément entre 2 et 6 jours.
- Le taux de retard des commandes expédiées (57,3 %) varie surtout avec le mode : 100 % en First Class, 79,8 %
  en Second Class, 47,9 % en Same Day, 39,8 % en Standard Class. À mode fixé, région et segment ont un effet
  statistiquement significatif (khi-deux) mais faible.
- **Rupture en octobre 2017** : catalogue presque entièrement remplacé, une seule ligne par commande, volumes
  erratiques. Avant, la demande hebdomadaire est très régulière (coefficient de variation 5,5 %) et sans
  saisonnalité annuelle. Les marchés couverts changent d'un trimestre à l'autre.

### Modèle en étoile (schéma `dw`)

```
                 dim_date (1 133 jours, calendrier continu)
                     |  date_commande_id / date_expedition_id
dim_produit (118) -- fait_commandes (180 519 lignes) -- dim_client (20 652)
                     |                    |
         dim_geographie (3 772)     dim_expedition (4)
```

### Choix de nettoyage
- **Données personnelles supprimées** : e-mail, mot de passe, prénom, nom, rue.
- Colonnes redondantes, vides ou constantes supprimées ; latitude/longitude supprimées (localisation du
  magasin selon le dictionnaire de données, sémantique ambiguë).
- Libellés nettoyés, `EE. UU.` -> `États-Unis`, codes postaux remis sur 5 caractères.
- ETL **idempotent**, chargement par `COPY`, **contrôles qualité** en fin d'exécution : lignes et CA réconciliés
  avec le CSV (33 054 402,04 $), zéro orphelin, calendrier sans trou, montants cohérents.

---

## 2. Risque de retard de livraison (notebook `02_risque`)

**Question** : au moment de la commande, quelle est la probabilité qu'elle arrive en retard ?

### Protocole
- **Unité = la commande** : la cible est identique pour toutes ses lignes ; modéliser à la ligne dupliquerait
  les exemples et gonflerait les métriques.
- **Commandes expédiées uniquement** (2 855 annulées retirées).
- **Découpage temporel** : train 2015-2016 (39 950 commandes) -> validation S1 2017 (9 876 ; hyperparamètres et
  seuil) -> test 01/07/2017-31/01/2018 (13 071 ; évalué une seule fois après ré-entraînement sur train +
  validation). Taux de retard stable : 57,4 % / 56,7 % / 57,6 %.

### Fuite de données : revue des colonnes

| Colonne | Décision | Raison |
|---|---|---|
| `Days for shipping (real)`, écart de jours | exclue | mesurée après livraison ; la cible en est calculée |
| `Delivery Status` | exclue | contient la réponse |
| `shipping date (DateOrders)` | exclue | connue à l'expédition seulement |
| `Order Status` | exclue | évolue après la commande ; `CANCELED`/`SUSPECTED_FRAUD` ont 0 % de retard |
| annulation | filtre uniquement | inconnue à la commande |
| identifiants (ligne, commande, client, produit) | exclus | aucune information généralisable |
| pays / ville / état de destination | exclus | trop fins (164 pays, 3 600 villes), résumés par la région |
| mode d'expédition | gardée | choisi à la commande |
| marché, région de destination | gardées | adresse connue à la commande |
| segment, pays du client, moyen de paiement | gardées | connus à la commande |
| catégorie et département principaux, nb de lignes, quantité, montant, remise, ratio de profit, prix max | gardés (agrégés par commande) | contenu du panier |
| heure, jour de semaine, mois, week-end | gardés | dérivés de l'horodatage de commande |

`tests/test_risque.py::test_aucune_variable_qui_fuit` vérifie automatiquement cette liste.

### Résultats sur le test (13 071 commandes, seuil 0,20)

| Modèle | ROC-AUC | PR-AUC | Brier | Recall | Précision | Commandes alertées |
|---|---|---|---|---|---|---|
| Règle par mode (baseline métier) | 0,746 | 0,788 | 0,187 | 100 % | 57,6 % | 100 % |
| Régression logistique (C = 10) | 0,752 | 0,842 | 0,187 | 100 % | 57,6 % | 100 % |
| **XGBoost** (profondeur 3, 500 arbres, lr 0,05) | **0,778** | **0,859** | **0,175** | 99,97 % | 59,1 % | 97,4 % |
| Règle « mode + heure limite Same Day » | 0,777 | - | - | - | - | - |

Matrice de confusion XGBoost : 7 522 VP, 5 210 FP, 2 FN, 337 VN.

| Sous-population du test | Commandes | AUC règle par mode | AUC XGBoost |
|---|---|---|---|
| Hors First Class | 11 097 | 0,656 | 0,700 |
| Standard + Second Class | 10 366 | 0,654 | 0,656 |
| Avant la rupture (juil.-sept. 2017) | 5 028 | 0,748 | 0,776 |
| Après la rupture (oct. 2017-janv. 2018) | 8 043 | 0,745 | 0,779 |

### Lecture
- Le gain de XGBoost vient d'une règle qu'il a découverte (SHAP global et local) : l'**heure limite de midi du
  Same Day**. Une règle simple « mode + heure limite » atteint presque la même AUC.
- Pour Second et Standard Class, aucun modèle ne fait mieux que le mode. Les performances sont stables après la
  rupture d'octobre 2017 (le modèle ne dépend pas du catalogue).

### Choix du seuil
- Hypothèse (à valider par le métier) : un retard non anticipé coûte **4 fois** une fausse alerte.
- Seuil de coût minimal sur la validation : plage 0,12-0,20 équivalente ; retenu **0,20** = seuil théorique
  `C_FP / (C_FP + C_FN)`. Conséquence : on alerte tout sauf les Same Day du matin.
- Sensibilité : ratio 1,5 -> seuil 0,43, 47 % des commandes alertées (recall 65 %, précision 79 %) ;
  ratio 1 -> 37 % alertées (recall 58 %, précision 89 %). Le vrai arbitrage : alerter ou non sur Standard Class.

---

## 3. Kit Power BI (`powerbi/`, `sql/05_vues_powerbi.sql`)

Le rapport se construit dans Power BI Desktop à partir du kit (le `.pbix` n'est pas versionné).

| Fichier | Contenu |
|---|---|
| `sql/05_vues_powerbi.sql` | 11 vues du schéma `bi`, seule source importée (recréées par l'ETL) |
| `powerbi/plan_dashboard.md` | connexion, modèle (16 relations, tris, table de dates), 3 pages détaillées visuel par visuel |
| `powerbi/mesures_dax.md` | 48 mesures (ventes, OTD, retard, risque, prévision) + **valeurs de contrôle** |
| `powerbi/modele_supply_pulse.tmdl` | script à coller dans la vue TMDL : 16 relations + 48 mesures en une fois |
| `powerbi/theme_supply_pulse.json` | palette accessible (daltonisme), couleurs de statut réservées |
| `sql/06_kpi_controle.sql` | recalcule les KPI en SQL pour vérifier les mesures DAX |

Modèle en **constellation** : `fait_commandes` (ligne), `fait_risque` (commande), `fait_demande_hebdo` et
`fait_prevision` (semaine x groupe) partagent les dimensions ; relations 1-plusieurs à filtrage simple ; la date
d'expédition est une relation inactive activée par `USERELATIONSHIP`.

Valeurs de référence (sans filtre) : CA net 33 054 402 $, 65 752 commandes, panier moyen 502,71 $,
marge 12,0 %, OTD 42,7 %, retard moyen des commandes en retard 1,62 jour, taux d'annulation 4,3 %.

### Captures (à ajouter)
| Page | Fichier |
|---|---|
| Performance | `powerbi/captures/01_performance.png` |
| Prévision | `powerbi/captures/02_prevision.png` |
| Risque | `powerbi/captures/03_risque.png` |

<!-- Remplacer par : ![Performance](powerbi/captures/01_performance.png) une fois les captures exportées -->

---

## 4. Prévision de la demande (notebook `03_prevision`)

### Périmètre
- **Période stable uniquement** : 142 semaines complètes (05/01/2015 -> 18/09/2017). Après la rupture
  d'octobre 2017, l'historique ne décrit plus le catalogue vendu : on ne force pas de modèle dessus.
- **Par catégorie** (les marchés changent chaque trimestre) : les 9 catégories qui font ~95 % du CA + « Autres »,
  soit 10 séries hebdomadaires en unités.

### Protocole
Backtest à origine glissante : 4 plis de 12 semaines sans chevauchement (24/10/2016 -> 18/09/2017), chaque pli
n'utilisant que le passé (vérifié par `tests/test_prevision.py::test_backtest_n_utilise_que_le_passe`).

### Résultats (480 prévisions par modèle)

| Modèle | MAPE | RMSE | WAPE | Biais |
|---|---|---|---|---|
| XGBoost global (lags 1-4 et 52, moyennes 4/12 sem., semaine ISO, récursif) | 10,1 % | 34,8 | 9,2 % | +0,8 % |
| **Moyenne mobile 12 semaines (retenu)** | 10,2 % | 34,9 | 9,3 % | +1,6 % |
| Prophet (un modèle par série) | 11,2 % | 37,4 | 9,9 % | +1,0 % |
| Naïve saisonnière (s = 52) | 14,2 % | 46,6 | 12,4 % | +1,7 % |

- **Choix du modèle** : la règle, fixée avant de comparer, est de retenir le plus simple quand l'écart n'est pas
  significatif. XGBoost contre moyenne mobile : +0,12 point, p = 0,50 (t apparié) et 0,69 (Wilcoxon)
  -> **moyenne mobile retenue**. Prophet et la naïve saisonnière sont significativement moins bons (p < 0,003).
- La naïve saisonnière est la plus faible : il n'y a pas de saisonnalité annuelle à exploiter.
- « Autres » concentre l'erreur (MAPE 24 % contre 7-10 % pour les 9 catégories) : série hétérogène, en déclin de 27 %.
- **Prévision des 12 semaines suivantes** (25/09 -> 11/12/2017, modèle retenu) : 29 799 unités, intervalle 80 %
  issu des erreurs du backtest. La réalité (après rupture) : 7 775 unités, soit -74 %. Ce chiffre n'entre pas
  dans l'évaluation : il illustre la limite de toute prévision fondée sur l'historique.

### Alternatives proposées après la rupture
1. Prévoir au niveau **total** ou **département** le temps d'accumuler 6 à 12 mois sur le nouveau catalogue.
2. Prévision **par analogie** : rattacher chaque nouveau produit à des produits existants comparables.
3. Intégrer l'information **planifiée** (lancements, promotions) au lieu de l'apprendre a posteriori.

---

## 5. Industrialisation

| Élément | Choix |
|---|---|
| API | FastAPI, schémas Pydantic (valeurs autorisées, bornes), modèle chargé une fois au démarrage, documentation OpenAPI sur `/docs` |
| Code partagé | `src/models/risque.py` calcule les variables pour l'entraînement **et** pour l'API : pas d'écart entre les deux |
| Image Docker | `python:3.11-slim`, dépendances minimales (`requirements-api.txt`), XGBoost en version CPU (**799 Mo** au lieu de 1,96 Go), utilisateur non root, `HEALTHCHECK` |
| Orchestration | `docker compose` : l'API attend que PostgreSQL soit prêt (`service_healthy`) |
| Tests | 34 tests pytest : ETL (données personnelles, clés, intégrité), fuite de données, seuil, backtest sans fuite, vues Power BI, API (formats, règle Same Day, entrées invalides, 404/503) |
| Reproductibilité | versions figées, seed 42, chaîne complète ré-exécutée (ETL puis notebooks 01 à 03) ; KPI et métriques identiques d'une exécution à l'autre |

---

## Limites et pistes

- **Données probablement simulées** (délais uniformes, marchés tournants, rupture brutale) : les conclusions
  valent pour ce dataset ; la démarche, elle, est transposable.
- Le ratio de coûts 4:1 est une **hypothèse** à faire valider par le métier ; le notebook 02 en donne la sensibilité.
- Pistes : planifier le scoring et la prévision (cron / Airflow), suivre la dérive des données et des performances,
  ajouter une explication SHAP par prédiction dans l'API, assistant en langage naturel sur les KPI (phase bonus).

## Données et licence

Dataset **DataCo Smart Supply Chain for Big Data Analysis** (Kaggle), non redistribué dans ce dépôt.
