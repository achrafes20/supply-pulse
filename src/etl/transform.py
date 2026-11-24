"""Transformation : nettoyage + construction du modèle en étoile.

Grain de la table de faits : **une ligne de commande** (Order Item Id),
soit un produit dans une commande. C'est le grain le plus fin disponible,
ce qui permet toutes les agrégations (commande, client, produit, jour...).

Choix de nettoyage (justifiés par le notebook 01_eda) :
- suppression des données personnelles : e-mail, mot de passe, prénom, nom, rue ;
- suppression des colonnes redondantes (copies exactes d'une autre colonne) ;
- suppression des colonnes vides ou constantes ;
- suppression de la latitude/longitude : selon le dictionnaire de données il
  s'agit du magasin, la sémantique est ambiguë et l'information n'est pas
  utilisée (la carte Power BI s'appuie sur le pays de destination).
"""
from __future__ import annotations

import pandas as pd

# --- Colonnes supprimées ------------------------------------------------------
COLONNES_PERSONNELLES = [
    "Customer Email",
    "Customer Password",
    "Customer Fname",
    "Customer Lname",
    "Customer Street",
]

# Copies exactes vérifiées dans 01_eda (égalité sur 100 % des lignes).
COLONNES_REDONDANTES = [
    "Benefit per order",         # == Order Profit Per Order
    "Sales per customer",        # == Order Item Total
    "Order Customer Id",         # == Customer Id
    "Product Category Id",       # == Category Id
    "Order Item Cardprod Id",    # == Product Card Id
    "Order Item Product Price",  # == Product Price
]

COLONNES_INUTILES = [
    "Product Description",  # 100 % de valeurs manquantes
    "Product Status",       # constante (0 partout)
    "Product Image",        # URL sans valeur analytique
    "Order Zipcode",        # 86 % de valeurs manquantes
    "Latitude",
    "Longitude",
]

# --- Renommage en snake_case français -----------------------------------------
RENOMMAGE = {
    "Type": "type_paiement",
    "Days for shipping (real)": "jours_reels",
    "Days for shipment (scheduled)": "jours_prevus",
    "Delivery Status": "statut_livraison",
    "Late_delivery_risk": "est_en_retard",
    "Category Id": "categorie_id",
    "Category Name": "categorie",
    "Customer City": "client_ville",
    "Customer Country": "client_pays",
    "Customer Id": "client_id",
    "Customer Segment": "segment",
    "Customer State": "client_etat",
    "Customer Zipcode": "client_code_postal",
    "Department Id": "departement_id",
    "Department Name": "departement",
    "Market": "marche",
    "Order City": "ville",
    "Order Country": "pays",
    "order date (DateOrders)": "date_commande",
    "Order Id": "commande_id",
    "Order Item Discount": "remise",
    "Order Item Discount Rate": "taux_remise",
    "Order Item Id": "ligne_id",
    "Order Item Profit Ratio": "ratio_profit",
    "Order Item Quantity": "quantite",
    "Sales": "montant_brut",
    "Order Item Total": "montant_net",
    "Order Profit Per Order": "profit",
    "Order Region": "region",
    "Order State": "etat",
    "Order Status": "statut_commande",
    "Product Card Id": "produit_id",
    "Product Name": "nom_produit",
    "Product Price": "prix_unitaire",
    "shipping date (DateOrders)": "date_expedition",
    "Shipping Mode": "mode_expedition",
}

FORMAT_DATE = "%m/%d/%Y %H:%M"


def nettoyer(brut: pd.DataFrame) -> pd.DataFrame:
    """Renvoie une table plate propre, sans données personnelles."""
    df = brut.drop(
        columns=COLONNES_PERSONNELLES + COLONNES_REDONDANTES + COLONNES_INUTILES,
        errors="ignore",
    ).rename(columns=RENOMMAGE)

    # Les libellés texte contiennent des espaces en fin de chaîne ("Baby ", "Smart watch ").
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    df["date_commande"] = pd.to_datetime(df["date_commande"], format=FORMAT_DATE)
    df["date_expedition"] = pd.to_datetime(df["date_expedition"], format=FORMAT_DATE)

    # "EE. UU." est l'abréviation espagnole des États-Unis.
    df["client_pays"] = df["client_pays"].replace({"EE. UU.": "États-Unis"})

    # Code postal : float dans le CSV (perte des zéros en tête, ex. 00725 à Porto Rico).
    df["client_code_postal"] = (
        df["client_code_postal"].astype("Int64").astype("string").str.zfill(5)
    )

    # Variables dérivées utiles au pilotage (pas au modèle de risque).
    df["ecart_jours"] = df["jours_reels"] - df["jours_prevus"]
    df["est_annulee"] = (df["statut_livraison"] == "Shipping canceled").astype("int8")
    return df


def _cle_date(serie: pd.Series) -> pd.Series:
    """Clé entière AAAAMMJJ (format standard des dimensions date)."""
    return serie.dt.strftime("%Y%m%d").astype("int32")


def construire_dim_date(debut: pd.Timestamp, fin: pd.Timestamp) -> pd.DataFrame:
    """Calendrier continu (sans trou), indispensable à l'intelligence temporelle DAX."""
    jours = pd.date_range(debut.normalize(), fin.normalize(), freq="D")
    noms_mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                 "août", "septembre", "octobre", "novembre", "décembre"]
    noms_jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    iso = jours.isocalendar()
    return pd.DataFrame({
        "date_id": _cle_date(pd.Series(jours)).values,
        "date": jours.date,
        "annee": jours.year,
        "trimestre": jours.quarter,
        "mois": jours.month,
        "nom_mois": [noms_mois[m - 1] for m in jours.month],
        "annee_mois": jours.strftime("%Y-%m"),
        "annee_iso": iso["year"].values,
        "semaine_iso": iso["week"].values,
        "debut_semaine": (jours - pd.to_timedelta(jours.weekday, unit="D")).date,
        "jour_mois": jours.day,
        "jour_semaine": jours.weekday + 1,  # 1 = lundi
        "nom_jour": [noms_jours[d] for d in jours.weekday],
        "est_weekend": jours.weekday >= 5,
    })


def construire_etoile(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Découpe la table propre en 5 dimensions + 1 table de faits."""
    dim_date = construire_dim_date(df["date_commande"].min(), df["date_expedition"].max())

    dim_produit = (
        df[["produit_id", "nom_produit", "prix_unitaire", "categorie_id", "categorie",
            "departement_id", "departement"]]
        .drop_duplicates("produit_id")
        .rename(columns={"prix_unitaire": "prix_catalogue"})
        .sort_values("produit_id")
        .reset_index(drop=True)
    )

    dim_client = (
        df[["client_id", "segment", "client_ville", "client_etat", "client_pays",
            "client_code_postal"]]
        .drop_duplicates("client_id")
        .rename(columns={"client_ville": "ville", "client_etat": "etat",
                         "client_pays": "pays", "client_code_postal": "code_postal"})
        .sort_values("client_id")
        .reset_index(drop=True)
    )

    # Géographie de destination : pas d'identifiant source -> clé de substitution.
    cols_geo = ["ville", "etat", "pays", "region", "marche"]
    dim_geographie = (
        df[cols_geo].drop_duplicates().sort_values(cols_geo).reset_index(drop=True)
    )
    dim_geographie.insert(0, "geographie_id", dim_geographie.index + 1)

    # Le délai prévu est entièrement déterminé par le mode d'expédition (vérifié en EDA).
    dim_expedition = (
        df[["mode_expedition", "jours_prevus"]]
        .drop_duplicates()
        .sort_values("jours_prevus")
        .reset_index(drop=True)
    )
    dim_expedition.insert(0, "expedition_id", dim_expedition.index + 1)

    fait = df.merge(dim_geographie, on=cols_geo, how="left").merge(
        dim_expedition, on=["mode_expedition", "jours_prevus"], how="left"
    )
    fait_commandes = pd.DataFrame({
        "ligne_id": fait["ligne_id"],
        "commande_id": fait["commande_id"],
        "date_commande_id": _cle_date(fait["date_commande"]),
        "date_expedition_id": _cle_date(fait["date_expedition"]),
        "horodatage_commande": fait["date_commande"],
        "horodatage_expedition": fait["date_expedition"],
        "produit_id": fait["produit_id"],
        "client_id": fait["client_id"],
        "geographie_id": fait["geographie_id"],
        "expedition_id": fait["expedition_id"],
        "type_paiement": fait["type_paiement"],
        "statut_commande": fait["statut_commande"],
        "quantite": fait["quantite"],
        "prix_unitaire": fait["prix_unitaire"].round(2),
        "montant_brut": fait["montant_brut"].round(2),
        "remise": fait["remise"].round(2),
        "taux_remise": fait["taux_remise"].round(4),
        "montant_net": fait["montant_net"].round(2),
        "profit": fait["profit"].round(2),
        "ratio_profit": fait["ratio_profit"].round(4),
        "jours_reels": fait["jours_reels"],
        "ecart_jours": fait["ecart_jours"],
        "statut_livraison": fait["statut_livraison"],
        "est_en_retard": fait["est_en_retard"],
        "est_annulee": fait["est_annulee"],
    }).sort_values("ligne_id").reset_index(drop=True)

    return {
        "dim_date": dim_date,
        "dim_produit": dim_produit,
        "dim_client": dim_client,
        "dim_geographie": dim_geographie,
        "dim_expedition": dim_expedition,
        "fait_commandes": fait_commandes,
    }
