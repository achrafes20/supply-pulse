"""Génère les 3 pages du rapport (format PBIR) et les injecte dans SupplyPulse.pbix.

Usage (Power BI Desktop FERMÉ) :
    python powerbi/generer_pages.py

- Le fichier actuel est sauvegardé avant chaque exécution : SupplyPulse_sauvegarde.pbix
- Les pages existantes sont remplacées par : Performance, Prévision, Risque
  (une modification manuelle des visuels est donc écrasée ; celles du modèle sont conservées)
- Le modèle de données (relations, mesures, tris) n'est pas modifié.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent
PBIX = DOSSIER / "SupplyPulse.pbix"
SAUVEGARDE = DOSSIER / "SupplyPulse_sauvegarde.pbix"

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
SCHEMA_VISUEL = f"{SCHEMA}/visualContainer/1.0.0/schema.json"
SCHEMA_PAGE = f"{SCHEMA}/page/2.1.0/schema.json"
SCHEMA_PAGES = f"{SCHEMA}/pagesMetadata/1.1.0/schema.json"
LARGEUR, HAUTEUR = 1280, 720
MES = "_Mesures"


# =============================================================================
# Briques JSON
# =============================================================================
def ident(*parties: str) -> str:
    """Identifiant stable de 20 caractères (même entrée -> même id : regénération idempotente)."""
    return hashlib.sha1("|".join(parties).encode()).hexdigest()[:20]


def lit(valeur) -> dict:
    """Littéral Power BI : texte entre apostrophes, booléen true/false, nombre suffixé D."""
    if isinstance(valeur, bool):
        v = "true" if valeur else "false"
    elif isinstance(valeur, (int, float)):
        v = f"{valeur}D"
    else:
        v = "'" + str(valeur).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": v}}}


def mesure(nom: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": MES}}, "Property": nom}}


def colonne(table: str, nom: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": nom}}


def _ref(champ: dict) -> tuple[str, str]:
    cle = "Measure" if "Measure" in champ else "Column"
    return champ[cle]["Expression"]["SourceRef"]["Entity"], champ[cle]["Property"]


def projection(champ: dict, affichage: str | None = None) -> dict:
    table, nom = _ref(champ)
    p = {"field": champ, "queryRef": f"{table}.{nom}", "nativeQueryRef": nom}
    if affichage:
        p["displayName"] = affichage   # libellé affiché à la place du nom de la mesure
    return p


def filtre(table: str, nom: str, valeurs: list) -> dict:
    """Filtre de visuel « nom IN valeurs »."""
    return {
        "name": ident("filtre", table, nom, str(valeurs)),
        "field": colonne(table, nom),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "t", "Entity": table, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": nom}}],
                "Values": [[lit(v)["expr"]] for v in valeurs],
            }}}],
        },
    }


def visuel(page: str, type_: str, x, y, l, h, roles: dict | None = None, titre: str | None = None,
           objets: dict | None = None, tri: tuple | None = None, filtres: list | None = None, z: int = 0) -> dict:
    v: dict = {"visualType": type_}
    if roles:
        v["query"] = {"queryState": {role: {"projections": [projection(c) for c in champs]}
                                     for role, champs in roles.items()}}
        if tri:
            champ, sens = tri
            v["query"]["sortDefinition"] = {"sort": [{"field": champ, "direction": sens}], "isDefaultSort": True}
    if objets:
        v["objects"] = objets
    if titre:
        v["visualContainerObjects"] = {"title": [{"properties": {"show": lit(True), "text": lit(titre)}}],
                                       "subTitle": [{"properties": {"show": lit(False)}}]}
    v["drillFilterOtherVisuals"] = True
    conteneur = {
        "$schema": SCHEMA_VISUEL,
        "name": ident(page, type_, str(x), str(y)),
        "position": {"x": x, "y": y, "z": z, "width": l, "height": h, "tabOrder": z},
        "visual": v,
    }
    if filtres:
        conteneur["filterConfig"] = {"filters": filtres}
    return conteneur


def segment(page, x, y, l, champ, mode="Dropdown", z=0, defaut: str | None = None):
    objets = {"data": [{"properties": {"mode": lit(mode)}}]}
    if defaut is not None:   # valeur sélectionnée à l'ouverture du rapport
        table, nom = _ref(champ)
        objets["general"] = [{"properties": {"filter": {"filter": filtre(table, nom, [defaut])["filter"]}}}]
    return visuel(page, "slicer", x, y, l, 58, {"Values": [champ]}, objets=objets, z=z)


def sans_total() -> dict:
    return {"total": [{"properties": {"totals": lit(False)}}]}


def degrade(nom_mesure: str, mini="#CDE2FB", maxi="#2A78D6") -> dict:
    """Couleur de fond en dégradé (séquentiel bleu) sur les valeurs d'une mesure."""
    return {"values": [{
        "properties": {"backColor": {"solid": {"color": {"expr": {"FillRule": {
            "Input": mesure(nom_mesure),
            "FillRule": {"linearGradient2": {
                "min": {"color": lit(mini)["expr"]},
                "max": {"color": lit(maxi)["expr"]},
                "nullColoringStrategy": {"strategy": lit("asZero")["expr"]},
            }},
        }}}}}},
        "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": f"{MES}.{nom_mesure}"},
    }]}


def carte(page, x, y, l, nom_mesure, filtres=None, z=0, affichage=None):
    v = visuel(page, "card", x, y, l, 96, {"Values": [mesure(nom_mesure)]}, filtres=filtres, z=z)
    if affichage:
        v["visual"]["query"]["queryState"]["Values"]["projections"][0]["displayName"] = affichage
    return v


def etiquettes() -> dict:
    return {"labels": [{"properties": {"show": lit(True)}}]}


def texte(page, x, y, l, h, lignes: list[tuple[str, bool]], z=0) -> dict:
    """Zone de texte : liste de (texte, gras)."""
    paragraphes = [{"textRuns": [{"value": t, "textStyle": {"fontWeight": "bold" if gras else "normal",
                                                           "fontSize": "11pt"}}]} for t, gras in lignes]
    return visuel(page, "textbox", x, y, l, h, objets={"general": [{"properties": {"paragraphs": paragraphes}}]}, z=z)


def rangee_cartes(page, mesures: list, y=74, filtres_par_mesure: dict | None = None) -> list[dict]:
    """mesures : noms, ou tuples (nom_mesure, libellé affiché, filtres du visuel)."""
    n, marge = len(mesures), 10
    largeur = (LARGEUR - marge * (n + 1)) / n
    cartes = []
    for i, m in enumerate(mesures):
        nom, affichage, filtres = m if isinstance(m, tuple) else (m, None, (filtres_par_mesure or {}).get(m))
        cartes.append(carte(page, round(marge + i * (largeur + marge)), y, round(largeur), nom,
                            filtres=filtres, z=10 + i, affichage=affichage))
    return cartes


# =============================================================================
# Page 1 - Performance
# =============================================================================
def page_performance(p: str) -> list[dict]:
    v = [
        segment(p, 10, 8, 380, colonne("dim_date", "date"), mode="Between", z=1),
        segment(p, 400, 8, 280, colonne("dim_geographie", "marche"), z=2),
        segment(p, 690, 8, 290, colonne("dim_expedition", "mode_expedition"), z=3),
        segment(p, 990, 8, 280, colonne("dim_client", "segment"), z=4),
    ]
    v += rangee_cartes(p, ["CA net", "Commandes", "Panier moyen", "Marge %", "OTD %", "Retard moyen (j)"])
    v += [
        visuel(p, "lineChart", 10, 180, 760, 262,
               {"Category": [colonne("dim_date", "annee_mois")], "Y": [mesure("CA net")],
                "Tooltips": [mesure("Évolution CA %"), mesure("Commandes")]},
               titre="CA net par mois (rupture de catalogue à partir d'octobre 2017)", z=20),
        visuel(p, "clusteredBarChart", 780, 180, 490, 262,
               {"Category": [colonne("dim_expedition", "mode_expedition")], "Y": [mesure("OTD %")],
                "Tooltips": [mesure("Délai prévu moyen (j)"), mesure("Délai réel moyen (j)"),
                             mesure("Commandes expédiées")]},
               titre="OTD % par mode : First Class = 0 % (1 jour promis, 2 livrés)",
               objets=etiquettes(), tri=(mesure("OTD %"), "Ascending"), z=21),
        visuel(p, "pivotTable", 10, 452, 760, 258,
               {"Rows": [colonne("dim_geographie", "region")],
                "Columns": [colonne("dim_expedition", "mode_expedition")],
                "Values": [mesure("Taux de retard")]},
               titre="Taux de retard par région et mode d'expédition", objets=degrade("Taux de retard"), z=22),
        visuel(p, "clusteredBarChart", 780, 452, 490, 258,
               {"Category": [colonne("dim_groupe_prevision", "groupe_prevision")], "Y": [mesure("CA net")],
                "Tooltips": [mesure("Marge %"), mesure("Unités")]},
               titre="CA net par groupe de catégories (9 principales + Autres)",
               objets=etiquettes(), tri=(mesure("CA net"), "Descending"), z=23),
    ]
    return v


# =============================================================================
# Page 2 - Prévision
# =============================================================================
def page_prevision(p: str) -> list[dict]:
    retenu = [filtre("fait_prevision", "est_modele_retenu", [True])]
    v = [
        segment(p, 10, 8, 400, colonne("dim_groupe_prevision", "groupe_prevision"), z=1),
        texte(p, 420, 8, 850, 58, [
            ("Modèle retenu : moyenne mobile 12 semaines", True),
            ("Statistiquement à égalité avec XGBoost (p = 0,50), plus simple. Backtest : 4 x 12 semaines, période stable.", False),
        ], z=2),
    ]
    v += rangee_cartes(p, ["Prévision 12 semaines (unités)", "MAPE", "Écart prévision/réel %",
                           "Demande réelle - période stable (unités)"],
                       filtres_par_mesure={m: retenu for m in ["Prévision 12 semaines (unités)", "MAPE",
                                                                "Écart prévision/réel %"]})
    v += [
        visuel(p, "lineChart", 10, 180, 1260, 300,
               {"Category": [colonne("dim_date", "debut_semaine")],
                "Y": [mesure("Demande réelle (unités)"), mesure("Prévision (unités)"),
                      mesure("Borne basse (unités)"), mesure("Borne haute (unités)")]},
               titre="Demande hebdomadaire réelle et prévue (backtest puis 12 semaines ; la rupture d'oct. 2017 n'était pas prévisible)",
               filtres=retenu, z=20),
        visuel(p, "clusteredBarChart", 10, 490, 620, 220,
               {"Category": [colonne("dim_groupe_prevision", "groupe_prevision")], "Y": [mesure("MAPE")]},
               titre="MAPE du backtest par groupe (modèle retenu)", objets=etiquettes(),
               tri=(mesure("MAPE"), "Descending"), filtres=retenu, z=21),
        visuel(p, "tableEx", 640, 490, 630, 220,
               {"Values": [colonne("fait_prevision", "libelle_modele"), mesure("MAPE"),
                           mesure("Écart prévision/réel %"), mesure("Prévision 12 semaines (unités)")]},
               titre="Comparaison des 4 modèles (backtest)", objets=sans_total(),
               tri=(mesure("MAPE"), "Ascending"), z=22),
    ]
    return v


# =============================================================================
# Page 3 - Risque
# =============================================================================
def couleurs_niveaux() -> dict:
    couleurs = {"faible": "#0CA30C", "moyen": "#FAB219", "élevé": "#D03B3B"}
    points = [{
        "properties": {"fill": {"solid": {"color": lit(c)}}},
        "selector": {"data": [{"scopeId": {"Comparison": {
            "ComparisonKind": 0,
            "Left": colonne("fait_risque", "niveau_risque"),
            "Right": lit(niveau)["expr"],
        }}}]},
    } for niveau, c in couleurs.items()]
    return {"dataPoint": points, **etiquettes()}


def page_risque(p: str) -> list[dict]:
    v = [
        segment(p, 10, 8, 300, colonne("fait_risque", "jeu"), z=1, defaut="test"),
        segment(p, 320, 8, 310, colonne("dim_expedition", "mode_expedition"), z=2),
        segment(p, 640, 8, 310, colonne("dim_geographie", "marche"), z=3),
        segment(p, 960, 8, 310, colonne("fait_risque", "niveau_risque"), z=4),
    ]
    # Précision = taux de retard réel parmi les commandes alertées du jeu de test.
    # « Taux de retard réel (scorées) » ignore les commandes annulées (retard réel vide),
    # ce qui évite le piège DAX BLANK() = 0 de la mesure « Fausses alertes (test) ».
    precision = ("Taux de retard réel (scorées)", "Précision des alertes (test)",
                 [filtre("fait_risque", "jeu", ["test"]), filtre("fait_risque", "alerte_retard", [1])])
    v += rangee_cartes(p, ["Probabilité moyenne de retard", "% commandes alertées", "Commandes risque élevé",
                           "CA à risque élevé", "Recall des alertes (test)", precision])
    v += [
        visuel(p, "clusteredColumnChart", 10, 180, 410, 262,
               {"Category": [colonne("dim_expedition", "mode_expedition")],
                "Y": [mesure("Probabilité moyenne de retard"), mesure("Taux de retard réel (scorées)")],
                "Tooltips": [mesure("Écart de calibration")]},
               titre="Probabilité prédite vs taux réel par mode", objets=etiquettes(), z=20),
        visuel(p, "clusteredColumnChart", 430, 180, 380, 262,
               {"Category": [colonne("fait_risque", "creneau_commande")],
                "Y": [mesure("Taux de retard réel (scorées)"), mesure("Probabilité moyenne de retard")]},
               titre="Same Day : heure limite à midi", objets=etiquettes(),
               filtres=[filtre("dim_expedition", "mode_expedition", ["Same Day"])], z=21),
        texte(p, 820, 180, 450, 262, [
            ("À retenir", True),
            ("- Le mode d'expédition explique l'essentiel du risque : First Class est toujours en retard (1 jour promis, 2 réels).", False),
            ("- Same Day commandé après 12 h part le lendemain : afficher l'heure limite au client.", False),
            ("- Second et Standard Class : délai réel peu prévisible, le levier est la promesse de délai.", False),
            ("- Seuil d'alerte 0,20 : hypothèse « rater un retard coûte 4 fois une fausse alerte ».", False),
            ("- Recall et précision sont mesurés sur le jeu de test uniquement.", False),
        ], z=22),
        visuel(p, "hundredPercentStackedBarChart", 10, 452, 560, 258,
               {"Category": [colonne("dim_expedition", "mode_expedition")],
                "Series": [colonne("fait_risque", "niveau_risque")],
                "Y": [mesure("Commandes scorées")]},
               titre="Répartition des commandes par niveau de risque", objets=couleurs_niveaux(), z=23),
        visuel(p, "tableEx", 580, 452, 690, 258,
               {"Values": [colonne("fait_risque", "commande_id"), colonne("dim_date", "date"),
                           colonne("dim_expedition", "mode_expedition"), colonne("dim_geographie", "region"),
                           colonne("fait_risque", "creneau_commande"), mesure("Probabilité moyenne de retard"),
                           mesure("CA à risque élevé")]},
               titre="Liste d'action : commandes à risque élevé (les plus grosses d'abord)", objets=sans_total(),
               tri=(mesure("CA à risque élevé"), "Descending"),
               filtres=[filtre("fait_risque", "niveau_risque", ["élevé"])], z=24),
    ]
    return v


# =============================================================================
# Injection dans le .pbix
# =============================================================================
PAGES = [("Performance", page_performance), ("Prévision", page_prevision), ("Risque", page_risque)]


def fichiers_rapport() -> dict[str, bytes]:
    fichiers, ordre = {}, []
    for nom_page, fabrique in PAGES:
        p = ident("page", nom_page)
        ordre.append(p)
        base = f"Report/definition/pages/{p}"
        fichiers[f"{base}/page.json"] = {"$schema": SCHEMA_PAGE, "name": p, "displayName": nom_page,
                                         "displayOption": "FitToPage", "height": HAUTEUR, "width": LARGEUR}
        for vis in fabrique(p):
            fichiers[f"{base}/visuals/{vis['name']}/visual.json"] = vis
    fichiers["Report/definition/pages/pages.json"] = {"$schema": SCHEMA_PAGES, "pageOrder": ordre,
                                                       "activePageName": ordre[0]}
    return {k: json.dumps(v, ensure_ascii=False, indent=2).encode("utf-8") for k, v in fichiers.items()}


def main() -> None:
    shutil.copy2(PBIX, SAUVEGARDE)   # on repart toujours du fichier actuel (modèle modifié inclus)
    print("Sauvegarde :", SAUVEGARDE.name)
    nouveaux = fichiers_rapport()
    temporaire = PBIX.with_suffix(".tmp")
    with zipfile.ZipFile(SAUVEGARDE) as src, zipfile.ZipFile(temporaire, "w") as dst:
        for info in src.infolist():
            nom = info.filename
            if nom.startswith("Report/definition/pages/") or nom == "SecurityBindings":
                continue  # anciennes pages remplacées ; SecurityBindings invalide après modification
            donnees = src.read(nom)
            if nom == "[Content_Types].xml":
                donnees = donnees.replace(b'<Override PartName="/SecurityBindings" ContentType="" />', b"")
            dst.writestr(info, donnees, compress_type=info.compress_type)
        for nom, donnees in nouveaux.items():
            dst.writestr(nom, donnees, compress_type=zipfile.ZIP_DEFLATED)
    temporaire.replace(PBIX)   # échoue si Power BI a le fichier ouvert
    n_visuels = sum(1 for k in nouveaux if k.endswith("visual.json"))
    print(f"{len(PAGES)} pages, {n_visuels} visuels écrits dans {PBIX.name}")


if __name__ == "__main__":
    main()
