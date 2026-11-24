# Plan du dashboard Power BI - Supply Pulse

Rapport de 3 pages : **Performance**, **Prévision**, **Risque**.
Format de page 16:9 (1280 x 720). Thème : `powerbi/theme_supply_pulse.json`.

---

## 0. Préparation (à faire une fois)

### 0.1 Connexion
1. Démarrer la base : `docker compose up -d` (puis `python -m src.etl.run_etl` si la base est vide).
2. Power BI Desktop > **Obtenir les données > Base de données PostgreSQL**.
   - Serveur : `localhost:5433` · Base : `supply_pulse` · Mode : **Importer**.
   - Identifiants : onglet *Base de données*, utilisateur `supply`, mot de passe `supply`.
   - Si Power BI signale qu'il ne peut pas chiffrer la connexion, accepter la connexion non chiffrée
     (base locale en Docker, sans certificat SSL).
3. Dans le navigateur, cocher **uniquement les vues du schéma `bi`** :
   `dim_date`, `dim_produit`, `dim_categorie`, `dim_groupe_prevision`, `dim_client`, `dim_geographie`,
   `dim_expedition`, `fait_commandes`, `fait_risque`, `fait_demande_hebdo`
   et `fait_prevision`.
4. Renommer les tables sans le préfixe `bi` (ex. `bi fait_commandes` -> `fait_commandes`).
5. Affichage > Thèmes > **Rechercher des thèmes** > `theme_supply_pulse.json`.

### 0.2 Option rapide : script TMDL (relations + 48 mesures en une fois)

Le fichier `powerbi/modele_supply_pulse.tmdl` crée les 16 relations du tableau ci-dessous et les 48 mesures
de `mesures_dax.md` (avec dossiers et formats).
1. **Supprimer les relations détectées automatiquement** : Modélisation > Gérer les relations,
   sélectionner toutes les lignes (Ctrl + clic), Supprimer.
2. **Créer la table `_Mesures`** : Accueil > Entrer des données > nommer la table `_Mesures` > Charger.
3. **Vue TMDL** (5e icône de la barre de gauche) > nouvel onglet > coller tout le contenu du fichier > **Appliquer**.
4. Dans le volet Données, masquer la colonne `Colonne 1` de `_Mesures`.
5. Faire ensuite les réglages manuels ci-dessous : table de dates, colonnes de tri, colonnes masquées.

En cas d'erreur à l'étape 3, noter le message exact (numéro de ligne) : le script se corrige ligne par ligne.

### 0.3 Modèle de données (vue Modèle)

Power BI détecte certaines relations seul : **vérifier la liste complète** ci-dessous et supprimer toute autre.

| De (côté 1) | Vers (côté plusieurs) | Clé | Active |
|---|---|---|---|
| `dim_date[date_id]` | `fait_commandes[date_commande_id]` | date de commande | oui |
| `dim_date[date_id]` | `fait_commandes[date_expedition_id]` | date d'expédition | **non** (USERELATIONSHIP) |
| `dim_produit[produit_id]` | `fait_commandes[produit_id]` | | oui |
| `dim_categorie[categorie]` | `dim_produit[categorie]` | | oui |
| `dim_groupe_prevision[groupe_prevision]` | `dim_categorie[groupe_prevision]` | | oui |
| `dim_client[client_id]` | `fait_commandes[client_id]` | | oui |
| `dim_geographie[geographie_id]` | `fait_commandes[geographie_id]` | | oui |
| `dim_expedition[expedition_id]` | `fait_commandes[expedition_id]` | | oui |
| `dim_date[date_id]` | `fait_risque[date_commande_id]` | | oui |
| `dim_client[client_id]` | `fait_risque[client_id]` | | oui |
| `dim_geographie[geographie_id]` | `fait_risque[geographie_id]` | | oui |
| `dim_expedition[expedition_id]` | `fait_risque[expedition_id]` | | oui |
| `dim_date[date_id]` | `fait_demande_hebdo[date_semaine_id]` | lundi de la semaine | oui |
| `dim_groupe_prevision[groupe_prevision]` | `fait_demande_hebdo[groupe_prevision]` | | oui |
| `dim_date[date_id]` | `fait_prevision[date_semaine_id]` | lundi de la semaine | oui |
| `dim_groupe_prevision[groupe_prevision]` | `fait_prevision[groupe_prevision]` | | oui |

Toutes les relations : cardinalité **1 à plusieurs**, filtrage **simple** (de la dimension vers le fait).
On évite le filtrage bidirectionnel : il rend les résultats ambigus quand plusieurs faits partagent des dimensions.

Réglages :
- `dim_date` : *Marquer comme table de dates* (colonne `date`).
- Colonnes de tri : `nom_mois` triée par `mois` · `mode_expedition` par `ordre_tri` ·
  `groupe_prevision` par `ordre_tri` · `niveau_risque` par `niveau_ordre`.
- Catégories de données : `dim_geographie[pays]` = Pays/Région, `[ville]` = Ville, `[etat]` = État ou province.
- Masquer toutes les clés techniques (`*_id`) côté faits et les colonnes `ordre_tri`.
- Créer la table `_Mesures` et y coller les mesures de `powerbi/mesures_dax.md`.
- **Contrôle** : poser les mesures dans des cartes et comparer au tableau « Valeurs de contrôle » de `mesures_dax.md`.

---

## Page 1 - Performance

**Question à laquelle la page répond** : « Comment vont les ventes et les livraisons, et où se situent les retards ? »

```
+--------------------------------------------------------------------------------------+
| [Période (dim_date[date])] [Marché] [Mode d'expédition] [Segment]        <- segments  |
+-----------+-----------+-----------+-----------+-----------+--------------------------+
| CA net    | Commandes | Panier    | Marge %   | OTD %     | Retard moyen (j)         |
| ±Évol. %  |           | moyen     |           |           |                          |
+-----------+-----------+-----------+-----------+-----------+--------------------------+
| (A) CA net par mois (courbe)                  | (B) OTD % par mode d'expédition        |
|                                               |     (barres horizontales)              |
+-----------------------------------------------+----------------------------------------+
| (C) Taux de retard : région x mode (matrice)  | (D) CA net et marge par catégorie      |
|     mise en forme conditionnelle              |     (barres, top 10)                   |
+-----------------------------------------------+----------------------------------------+
```

| Visuel | Type | Champs | Mesures | Remarques |
|---|---|---|---|---|
| Segments | Segment (liste déroulante) | `dim_date[date]` (entre), `dim_geographie[marche]`, `dim_expedition[mode_expedition]`, `dim_client[segment]` | - | sur une seule ligne en haut ; synchroniser *Période* et *Marché* avec les pages 2 et 3 |
| Cartes KPI | Carte (nouvelle carte, plusieurs valeurs) | - | `CA net` (+ `Évolution CA %` en libellé de référence), `Commandes`, `Panier moyen`, `Marge %`, `OTD %`, `Retard moyen (j)` | `Évolution CA %` en vert/rouge **avec flèche ▲▼**, jamais la couleur seule |
| (A) | Graphique en courbes | Axe : `dim_date[annee_mois]` | `CA net` ; ligne secondaire facultative : `CA N-1` en gris | ligne d'annotation verticale (« Rupture catalogue oct. 2017 ») via *Analytique > ligne X* ou zone de texte |
| (B) | Barres groupées horizontales | Axe : `dim_expedition[mode_expedition]` | `OTD %` ; info-bulle : `Délai prévu moyen (j)`, `Délai réel moyen (j)`, `Commandes expédiées` | étiquettes de données activées ; titre : « First Class : 0 % à l'heure - 1 jour promis, 2 jours réels » |
| (C) | Matrice | Lignes : `dim_geographie[region]` ; colonnes : `dim_expedition[mode_expedition]` | `Taux de retard` | mise en forme conditionnelle *Couleur d'arrière-plan* en dégradé bleu séquentiel (thème) ; valeurs affichées |
| (D) | Barres groupées | Axe : `dim_categorie[categorie]` (Top N = 10 par `CA net`) | `CA net` ; info-bulle : `Marge %`, `Unités` | |

Interactions : (B) filtre (A), (C) et (D). Les cartes restent filtrées par tous les visuels.

---

## Page 2 - Prévision

**Question** : « Combien d'unités allons-nous vendre par groupe de catégories dans les 12 prochaines semaines, et avec quelle fiabilité ? »

> Modèle retenu au backtest : **Moyenne mobile 12 semaines** (`fait_prevision[est_modele_retenu]` = Vrai), choisi
> parce qu'il est statistiquement équivalent à XGBoost et plus simple (notebook 03, section 3). Les prévisions
> « futur » couvrent le 25/09/2017 -> 11/12/2017 : la courbe réelle s'effondre à cause de la rupture de catalogue,
> à commenter dans une zone de texte (« la rupture n'était pas prévisible depuis l'historique »).

```
+--------------------------------------------------------------------------------------+
| [Groupe de prévision] [Modèle (libelle_modele)]                   <- segments   |
+------------------+-------------------+-------------------+---------------------------+
| Prévision 12 sem.| MAPE (backtest)   | Écart prév./réel %| Demande réelle (stable)   |
+------------------+-------------------+-------------------+---------------------------+
| (A) Demande réelle et prévision hebdomadaires, avec intervalle (courbes)             |
|                                                                                      |
+-----------------------------------------------+--------------------------------------+
| (B) MAPE par groupe de prévision (barres)     | (C) Tableau : groupe, prévu, réel,   |
|                                               |     écart %, MAPE                    |
+-----------------------------------------------+--------------------------------------+
```

| Visuel | Type | Champs | Mesures | Remarques |
|---|---|---|---|---|
| Segments | Segment | `dim_groupe_prevision[groupe_prevision]` (sélection multiple), `fait_prevision[libelle_modele]` (**sélection unique obligatoire**, valeur par défaut : Moyenne mobile 12 sem.) | - | sélection unique : sinon les prévisions de plusieurs modèles s'additionnent |
| Cartes | Carte | - | `Prévision 12 semaines (unités)`, `MAPE`, `Écart prévision/réel %`, `Demande réelle - période stable (unités)` | |
| (A) | Graphique en courbes | Axe : `dim_date[debut_semaine]` (axe continu) | `Demande réelle (unités)` (bleu), `Prévision (unités)` (orange, pointillé) ; *barres d'erreur* : `Borne basse` / `Borne haute` | zone grisée ou ligne verticale à la date de fin de l'historique ; marquer la rupture d'octobre 2017 |
| (B) | Barres horizontales | Axe : `dim_groupe_prevision[groupe_prevision]` | `MAPE` | trier par MAPE décroissant ; ligne constante = MAPE global |
| (C) | Tableau | `dim_groupe_prevision[groupe_prevision]` | `Prévision (unités)`, `Réel en backtest (unités)`, `Écart prévision/réel %`, `MAPE` | mise en forme conditionnelle de `Écart prévision/réel %` : icônes ▲▼ + couleur |

Filtre de page : `fait_demande_hebdo[apres_rupture]` = Faux pour (B) et (C) si l'on veut comparer sur la période stable.

---

## Page 3 - Risque

**Question** : « Quelles commandes risquent d'arriver en retard, et peut-on se fier aux alertes ? »

```
+--------------------------------------------------------------------------------------+
| [Jeu (défaut : test)] [Mode d'expédition] [Marché] [Niveau de risque]   <- segments  |
+-------------+-------------+-------------+-------------+-------------+----------------+
| Probabilité | % commandes | Commandes   | CA à risque | Recall      | Précision      |
| moyenne     | alertées    | risque élevé| élevé       | (test)      | (test)         |
+-------------+-------------+-------------+-------------+-------------+----------------+
| (A) Probabilité prédite vs taux réel          | (B) Same Day : taux réel par créneau  |
|     par mode d'expédition (barres groupées)   |     de commande (avant/après 12 h)    |
+-----------------------------------------------+---------------------------------------+
| (C) Répartition des commandes par niveau      | (D) Liste d'action : commandes à      |
|     de risque et mode (barres empilées 100 %) |     risque élevé (tableau)            |
+-----------------------------------------------+---------------------------------------+
```

| Visuel | Type | Champs | Mesures | Remarques |
|---|---|---|---|---|
| Segments | Segment | `fait_risque[jeu]` (valeur par défaut `test`), `dim_expedition[mode_expedition]`, `dim_geographie[marche]`, `fait_risque[niveau_risque]` | - | les mesures « (test) » forcent déjà `jeu = test` |
| Cartes | Carte | - | `Probabilité moyenne de retard`, `% commandes alertées`, `Commandes risque élevé`, `CA à risque élevé`, `Recall des alertes (test)`, `Précision des alertes (test)` | ajouter `Retards non anticipés (test)` en sous-titre de la carte Recall |
| (A) | Barres groupées | Axe : `dim_expedition[mode_expedition]` | `Probabilité moyenne de retard` (bleu), `Taux de retard réel (scorées)` (gris) | même échelle (%) : montre que le modèle est bien calibré ; info-bulle : `Écart de calibration` |
| (B) | Barres groupées | Axe : `fait_risque[creneau_commande]` ; filtre du visuel : `mode_expedition = Same Day` | `Taux de retard réel (scorées)`, `Probabilité moyenne de retard` | titre : « Same Day : heure limite à midi » ; c'est la règle découverte par SHAP (notebook 02) |
| (C) | Barres empilées 100 % | Axe : `dim_expedition[mode_expedition]` ; légende : `fait_risque[niveau_risque]` | `Commandes scorées` | couleurs : faible = vert *good*, moyen = jaune *neutral*, élevé = rouge *bad* **+ libellés de données** (ne pas compter sur la couleur seule) |
| (D) | Tableau | `fait_risque[commande_id]`, `dim_date[date]`, `dim_expedition[mode_expedition]`, `dim_geographie[region]`, `fait_risque[creneau_commande]` | `Probabilité moyenne de retard`, `CA à risque élevé` | filtre du visuel : `niveau_risque = élevé` ; tri par `CA à risque élevé` décroissant : priorise les grosses commandes |

Zone de texte (encadré « À retenir ») :
- Le mode d'expédition explique l'essentiel du risque ; First Class est toujours en retard (promesse 1 j, réel 2 j).
- Same Day commandé après 12 h part le lendemain : afficher l'heure limite au client.
- Second/Standard Class : délai réel peu prévisible, le levier est la promesse de délai.
- Seuil d'alerte 0,20 = hypothèse « rater un retard coûte 4 fois une fausse alerte » (notebook 02, section 6).

---

## Accessibilité et lisibilité
- Jamais d'information portée par la couleur seule : libellés de données, flèches ▲▼, titres explicites.
- Pas de graphique à double axe : deux mesures d'échelles différentes -> deux visuels.
- Texte alternatif (*Général > Texte de remplacement*) renseigné sur chaque visuel.
- Ordre de tabulation : segments, puis cartes, puis visuels de gauche à droite.

## Captures pour le README
Exporter chaque page (Fichier > Exporter > PDF, ou capture d'écran) dans `powerbi/captures/` :
`01_performance.png`, `02_prevision.png`, `03_risque.png`.
