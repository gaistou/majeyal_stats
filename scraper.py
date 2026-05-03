import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
from bs4 import BeautifulSoup

CHAR_CACHE_FILE = "cache/characters.json"


def charger_cache_chars():
    if os.path.exists(CHAR_CACHE_FILE):
        with open(CHAR_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def sauver_cache_chars(cache):
    os.makedirs("cache", exist_ok=True)
    with open(CHAR_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)

BASE_URL = "https://te4.org/characters-vault"
SITE_URL = "https://te4.org"

# Mapping classe → code tag_class[] utilisé par te4.org
# Seules les classes officielles (data-official="1") sont listées ici.
# Les races (Halfling, Higher, Ogre, Orc, Shalore, Skeleton, Yeek) sont exclues.
CLASSES = {
    "Adventurer":        "104",
    "Alchemist":         "19",
    "Annihilator":       "326744",
    "Anorithil":         "20",
    "Arcane Blade":      "22",
    "Archer":            "14",
    "Archmage":          "7",
    "Berserker":         "16",
    "Brawler":           "56",
    "Bulwark":           "80",
    "Corruptor":         "34",
    "Cultist of Entropy":"133921",
    "Cursed":            "10",
    "Demonologist":      "23297",
    "Doombringer":       "23313",
    "Doomed":            "29",
    "Ghoul":             "103389",
    "Gunslinger":        "208",
    "Lich":              "1257832",
    "Marauder":          "71",
    "Mindslayer":        "48",
    "Necromancer":       "68",
    "Oozemancer":        "179",
    "Paradox Mage":      "43",
    "Possessor":         "95691",
    "Psyshot":           "67509",
    "Reaver":            "31",
    "Rogue":             "12",
    "Sawbutcher":        "67403",
    "Shadowblade":       "23",
    "Skirmisher":        "12400",
    "Solipsist":         "102",
    "Stone Warden":      "70",
    "Summoner":          "17",
    "Sun Paladin":       "27",
    "Temporal Warden":   "49",
    "Wanderer":          "699245",
    "Writhing One":      "104071",
    "Wyrmic":            "4",
}

MOTS_CLES_INTERDITS = {
    "god", "godmode", "cheat", "experience", "tougher escorts",
    "generous", "starting prodigy", "overpowered", "homosuperior",
    "superhuman", "expanded shop", "no more rare monsters",
    "softcore death", "hulk", "no prodigy requirement",
    "select your escorts", "exponential leveling",
}

PARAMS_BASE = {
    "tag_name": "",
    "tag_level_min": "",
    "tag_level_max": "",
    "tag_winner": "winner",
    "tag_permadeath[]": "66",
    "tag_difficulty[]": "36",
    "tag_campaign[]": "2",
    # tag_class[] est ajouté dynamiquement depuis CLASSES[selected_class]
}


def get_html(url, params=None, timeout=30):
    reponse = requests.get(url, params=params, timeout=timeout)
    reponse.raise_for_status()
    return reponse.text


def contient_mot_interdit(textes):
    texte = " ".join(textes).lower()
    for mot in MOTS_CLES_INTERDITS:
        if mot.lower() in texte:
            return True, mot
    return False, None


def supprimer_tooltips(bloc):
    for tooltip in bloc.find_all(class_="qtip-tooltip"):
        tooltip.decompose()


def extraire_artefacts_jaunes(html):
    soup = BeautifulSoup(html, "html.parser")
    for titre in soup.find_all("h4"):
        if titre.get_text(strip=True) != "Equipment":
            continue
        tableau = titre.find_next("table")
        if tableau is None:
            return []
        supprimer_tooltips(tableau)
        artefacts = []
        for span in tableau.select('span[style*="#FFD700"]'):
            nom = span.get_text(" ", strip=True)
            if nom:
                artefacts.append(nom)
        return artefacts
    return []


def extraire_page(html):
    soup = BeautifulSoup(html, "html.parser")
    lignes = soup.select("table.sticky-enabled tbody tr")
    donnees = []
    for ligne in lignes:
        cellules = ligne.find_all("td")
        if len(cellules) < 8:
            continue
        lien = cellules[1].find("a")
        url = lien.get("href") if lien else None
        if url and url.startswith("/"):
            url = SITE_URL + url
        donnees.append({
            "user": cellules[0].get_text(strip=True),
            "name": cellules[1].get_text(strip=True),
            "character_url": url,
            "class": cellules[2].get_text(strip=True),
            "difficulty": cellules[3].get_text(strip=True),
            "permadeath": cellules[4].get_text(strip=True),
            "campaign": cellules[5].get_text(strip=True),
            "winner": cellules[6].get_text(strip=True),
            "last_updated": cellules[7].get_text(strip=True),
        })
    return pd.DataFrame(donnees)


def scraper_pages(nb_pages=50, params=None, on_page=None):
    if params is None:
        params = PARAMS_BASE
    tableaux = []
    for page in range(nb_pages):
        html = get_html(BASE_URL, params=params | {"page": page})
        df_page = extraire_page(html)
        if df_page.empty:
            break
        tableaux.append(df_page)
        if on_page:
            on_page(page, len(df_page))
    return pd.concat(tableaux, ignore_index=True) if tableaux else pd.DataFrame()


def extraire_addons(html):
    soup = BeautifulSoup(html, "html.parser")
    for cellule in soup.find_all("td"):
        if cellule.get_text(strip=True) != "Addons":
            continue
        cellule_addons = cellule.find_next_sibling("td")
        if cellule_addons is None:
            return []
        supprimer_tooltips(cellule_addons)
        addons = []
        for bloc in cellule_addons.find_all("div", class_="addon"):
            nom = bloc.get_text(" ", strip=True)
            if nom:
                addons.append(nom)
        return sorted(set(addons))
    return []


def extraire_prodigies(html):
    soup = BeautifulSoup(html, "html.parser")
    for titre in soup.find_all("h4"):
        if titre.get_text(strip=True) != "Prodigies":
            continue
        tableau = titre.find_next("table", class_="talents")
        if tableau is None:
            return []
        prodigies = []
        for ligne in tableau.find_all("tr"):
            cellule = ligne.find("td")
            if cellule is None:
                continue
            supprimer_tooltips(cellule)
            nom = cellule.get_text(" ", strip=True)
            if nom:
                prodigies.append(nom)
        return prodigies
    return []


def extraire_talents(html, titre_talents):
    soup = BeautifulSoup(html, "html.parser")
    talents = []
    titre = soup.find("h4", string=lambda texte: texte and texte.strip() == titre_talents)
    if titre is None:
        return talents
    tableau = titre.find_next("table", class_="talents")
    if tableau is None:
        return talents
    arbre_courant = None
    multiplicateur_arbre = None
    for ligne in tableau.find_all("tr"):
        cellules = ligne.find_all("td")
        if len(cellules) == 2 and cellules[0].find("strong"):
            arbre_courant = cellules[0].get_text(" ", strip=True)
            multiplicateur_arbre = cellules[1].get_text(strip=True)
            continue
        if len(cellules) < 2:
            continue
        valeur = cellules[-1].get_text(strip=True)
        match = re.search(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", valeur)
        if not match:
            continue
        cellule_nom = cellules[0]
        supprimer_tooltips(cellule_nom)
        nom = cellule_nom.get_text(" ", strip=True)
        talents.append({
            "type_talent": titre_talents,
            "arbre": arbre_courant,
            "multiplicateur_arbre": multiplicateur_arbre,
            "talent": nom,
            "points": float(match.group(1)),
            "points_max": float(match.group(2)),
        })
    return talents


def extraire_class_et_generic_talents(html):
    return (
        extraire_talents(html, "Class Talents")
        + extraire_talents(html, "Generic Talents")
    )


MARQUEUR_ANGLAIS = "Well done! You have won the Tales of Maj'Eyal: The Age of Ascendancy"


def analyser_personnage(url):
    html = get_html(url, timeout=10)
    addons = extraire_addons(html)
    ignore, mot = contient_mot_interdit(addons)
    resultat = {
        "url": url,
        "ignore": ignore,
        "mot_interdit": mot,
        "addons": addons,
        "prodigies": [],
        "artefacts_jaunes": [],
        "talents": [],
    }
    if ignore:
        return resultat
    if MARQUEUR_ANGLAIS not in html:
        resultat["ignore"] = True
        resultat["mot_interdit"] = "langue_non_anglaise"
        return resultat
    resultat["talents"] = extraire_class_et_generic_talents(html)
    resultat["prodigies"] = extraire_prodigies(html)
    resultat["artefacts_jaunes"] = extraire_artefacts_jaunes(html)
    return resultat


def compter_prodigies_et_artefacts(df, on_progress=None, nb_workers=4):
    cache = charger_cache_chars()
    resultats = {}
    urls_a_fetcher = []
    total = len(df)

    for i, url in enumerate(df["character_url"]):
        if url in cache:
            r = dict(cache[url])
            r["index_df"] = i
            resultats[i] = r
        else:
            urls_a_fetcher.append((i, url))

    if on_progress and resultats:
        on_progress(len(resultats), total)

    nouveaux_resultats = {}

    def fetcher(args):
        i, url = args
        try:
            r = analyser_personnage(url)
        except Exception:
            r = {"url": url, "ignore": True, "mot_interdit": "erreur",
                 "addons": [], "prodigies": [], "artefacts_jaunes": [], "talents": []}
        r["index_df"] = i
        return i, r

    if urls_a_fetcher:
        with ThreadPoolExecutor(max_workers=nb_workers) as executor:
            futures = {executor.submit(fetcher, args): args for args in urls_a_fetcher}
            done_count = len(resultats)
            for future in as_completed(futures):
                i, r = future.result()
                resultats[i] = r
                nouveaux_resultats[r["url"]] = {k: v for k, v in r.items() if k != "index_df"}
                done_count += 1
                if on_progress:
                    on_progress(done_count, total)  # appelé depuis le thread principal
        cache.update(nouveaux_resultats)
        sauver_cache_chars(cache)

    # Reconstruire dans l'ordre original
    details = [resultats[i] for i in sorted(resultats)]

    compteur_prodigies = {}
    compteur_artefacts = {}
    for r in details:
        if r["ignore"]:
            continue
        for prodigy in set(r["prodigies"]):
            compteur_prodigies[prodigy] = compteur_prodigies.get(prodigy, 0) + 1
        for artefact in set(r["artefacts_jaunes"]):
            compteur_artefacts[artefact] = compteur_artefacts.get(artefact, 0) + 1

    df_prodigies = (
        pd.DataFrame(compteur_prodigies.items(), columns=["prodigy", "count"])
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )
    df_artefacts = (
        pd.DataFrame(compteur_artefacts.items(), columns=["artefact", "count"])
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )
    return df_prodigies, df_artefacts, pd.DataFrame(details)


def calculer_points_moyens_talents(df_details):
    lignes = []
    for _, ligne in df_details.loc[~df_details["ignore"].astype(bool)].iterrows():
        for talent in (ligne["talents"] or []):
            lignes.append({"index_df": ligne["index_df"], **talent})

    colonnes = ["index_df", "type_talent", "arbre", "multiplicateur_arbre", "talent", "points", "points_max"]
    df_talents = pd.DataFrame(lignes, columns=colonnes) if lignes else pd.DataFrame(columns=colonnes)

    if df_talents.empty:
        return df_talents, pd.DataFrame(columns=[
            "type_talent", "arbre", "talent",
            "points_moyens", "points_medians", "points_mode", "nb_personnages", "points_max",
        ])

    df_moyennes = (
        df_talents
        .groupby(["type_talent", "arbre", "talent"], dropna=False)
        .agg(
            points_moyens=("points", "mean"),
            points_medians=("points", "median"),
            points_mode=("points", lambda x: x.mode().iloc[0] if not x.mode().empty else None),
            nb_personnages=("points", "count"),
            points_max=("points_max", "max"),
        )
        .sort_values(["type_talent", "points_moyens"], ascending=[True, False])
        .reset_index()
    )
    return df_talents, df_moyennes
