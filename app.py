import json
import os

import pandas as pd
import plotly.express as px
import streamlit as st

from scraper import (
    CLASSES,
    calculer_points_moyens_talents,
)

st.set_page_config(page_title="ToME Stats", layout="wide")


def get_cache_file(class_name):
    return f"cache/results_{class_name}.json"


def save_cache(class_name, data):
    os.makedirs("cache", exist_ok=True)
    with open(get_cache_file(class_name), "w") as f:
        json.dump(data, f)


def load_cache(class_name):
    path = get_cache_file(class_name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def deserialize_results(data):
    df = pd.DataFrame(data["df"])
    df_prodigies = pd.DataFrame(data["prodigies"])
    df_artefacts = pd.DataFrame(data["artefacts"])
    df_details = pd.DataFrame(data["details"])
    return df, df_prodigies, df_artefacts, df_details


def serialize_results(df, df_prodigies, df_artefacts, df_details):
    return {
        "df": df.to_dict(orient="records"),
        "prodigies": df_prodigies.to_dict(orient="records"),
        "artefacts": df_artefacts.to_dict(orient="records"),
        "details": df_details.to_dict(orient="records"),
    }


def calculer_correlations_prodigies(df_details, index_valides):
    from itertools import combinations
    indices = set(index_valides)
    compteur_pairs = {}
    compteur_solo = {}

    for _, row in df_details.iterrows():
        if row["index_df"] not in indices:
            continue
        prodigies = list(set(row.get("prodigies") or []))
        for p in prodigies:
            compteur_solo[p] = compteur_solo.get(p, 0) + 1
        for p1, p2 in combinations(sorted(prodigies), 2):
            key = (p1, p2)
            compteur_pairs[key] = compteur_pairs.get(key, 0) + 1

    return compteur_pairs, compteur_solo


def get_game_version(addons):
    """Return (major, minor, patch) from the 'Ashes of Urh'Rok X.Y.Z' addon, or None."""
    PROXY_ADDONS = ("Ashes of Urh'Rok", "Embers of Rage", "Forbidden Cults", "Possessor Bonus Class")
    for addon in (addons or []):
        for name in PROXY_ADDONS:
            if addon.startswith(name):
                parts = addon.rsplit(" ", 1)
                if len(parts) == 2:
                    try:
                        return tuple(int(x) for x in parts[1].split("."))
                    except ValueError:
                        pass
    return None


def stats_depuis_indices(df_details, index_valides):
    indices = set(index_valides)
    compteur_prodigies = {}
    compteur_artefacts = {}

    for _, row in df_details.iterrows():
        if row["index_df"] not in indices:
            continue
        for prodigy in set(row.get("prodigies") or []):
            compteur_prodigies[prodigy] = compteur_prodigies.get(prodigy, 0) + 1
        for artefact in set(row.get("artefacts_jaunes") or []):
            compteur_artefacts[artefact] = compteur_artefacts.get(artefact, 0) + 1

    df_prod = (
        pd.DataFrame(compteur_prodigies.items(), columns=["prodigy", "count"])
        .sort_values("count", ascending=False).reset_index(drop=True)
    ) if compteur_prodigies else pd.DataFrame(columns=["prodigy", "count"])

    df_art = (
        pd.DataFrame(compteur_artefacts.items(), columns=["artefact", "count"])
        .sort_values("count", ascending=False).reset_index(drop=True)
    ) if compteur_artefacts else pd.DataFrame(columns=["artefact", "count"])

    return df_prod, df_art


# ── Session state init ────────────────────────────────────────────────────────
if "results_by_class" not in st.session_state:
    st.session_state.results_by_class = {}

if "class_selector" not in st.session_state:
    st.session_state.class_selector = list(CLASSES.keys())[0]

selected_class = st.session_state.class_selector

# ── Load disk cache for selected class if not already in memory ───────────────
if selected_class not in st.session_state.results_by_class:
    cached = load_cache(selected_class)
    if cached:
        st.session_state.results_by_class[selected_class] = deserialize_results(cached)

st.title(f"{selected_class} — Tales of Maj'Eyal")

# Available talent names for cross-filter
talent_names_disponibles = []
if selected_class in st.session_state.results_by_class:
    df_details_tmp = st.session_state.results_by_class[selected_class][3]
    noms = set()
    for talents in df_details_tmp.loc[~df_details_tmp["ignore"].astype(bool), "talents"]:
        for t in (talents or []):
            noms.add(t["talent"])
    talent_names_disponibles = sorted(noms)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Version")
    filtre_version_17 = st.checkbox("Only version ≥ 1.7", value=True)

    st.divider()
    st.subheader("Class")
    selected_class = st.selectbox("Class", list(CLASSES.keys()), key="class_selector")

    st.divider()
    st.subheader("Display")
    nb_min_personnages = st.slider("Min. characters (talents)", 1, 30, 10)

    st.divider()
    st.subheader("Cross-filter")
    if talent_names_disponibles:
        talent_filtre = st.selectbox("Talent", ["(none)"] + talent_names_disponibles)
        if talent_filtre != "(none)":
            points_filtre = st.slider("Minimum points", 1, 5, 1)
        else:
            points_filtre = 1
    else:
        st.caption("No data yet — run the Admin page locally to scrape.")
        talent_filtre = "(none)"
        points_filtre = 1

# ── Display ───────────────────────────────────────────────────────────────────
if selected_class not in st.session_state.results_by_class:
    st.info("No data available for this class — run the Admin page locally to scrape and push the results.")
    st.stop()

df, df_prodigies_base, df_artefacts_base, df_details = st.session_state.results_by_class[selected_class]

df["race"] = df["name"].str.extract(rf"level\s+\d+\s+(\w+)\s+{selected_class}", expand=False)

# Base indices (excluding cheats/language)
index_valides_base = df_details.loc[~df_details["ignore"].astype(bool), "index_df"].tolist()

# Apply version filter
if filtre_version_17:
    version_min = (1, 7)
    indices_v17 = {
        row["index_df"]
        for _, row in df_details.iterrows()
        if row["index_df"] in set(index_valides_base)
        and (v := get_game_version(row.get("addons") or [])) is not None
        and v[:2] >= version_min
    }
    index_valides_base = [i for i in index_valides_base if i in indices_v17]

# Apply cross-filter
filtre_actif = talent_filtre != "(none)"
if filtre_actif:
    indices_filtre = set()
    for _, row in df_details.loc[~df_details["ignore"].astype(bool)].iterrows():
        for t in (row["talents"] or []):
            if t["talent"] == talent_filtre and t["points"] >= points_filtre:
                indices_filtre.add(row["index_df"])
                break
    index_valides = [i for i in index_valides_base if i in indices_filtre]
else:
    index_valides = index_valides_base

df_filtre = df.loc[index_valides].reset_index(drop=True)
compte_par_race = df_filtre["race"].value_counts(dropna=False).reset_index(name="count")

# Recompute prodigies / artefacts if filter is active
if filtre_actif:
    df_prodigies, df_artefacts = stats_depuis_indices(df_details, index_valides)
else:
    df_prodigies, df_artefacts = df_prodigies_base, df_artefacts_base

# Talents computed on filtered subset
df_details_filtre = df_details[df_details["index_df"].isin(set(index_valides))] if filtre_actif else df_details
df_talents, df_talents_moyens = calculer_points_moyens_talents(df_details_filtre)
df_talents_top = (
    df_talents_moyens
    .loc[df_talents_moyens["nb_characters"] >= nb_min_personnages]
    .sort_values("avg_points", ascending=False)
    .reset_index(drop=True)
)

# Active filter banner
filtres_actifs = []
if filtre_version_17:
    filtres_actifs.append("version ≥ 1.7")
if filtre_actif:
    filtres_actifs.append(f"**{talent_filtre} ≥ {points_filtre} pts**")
if filtres_actifs:
    st.info(
        f"Active filter{'s' if len(filtres_actifs) > 1 else ''}: {' + '.join(filtres_actifs)} "
        f"— {len(df_filtre)} characters out of {len(df)}"
    )

# Global metrics
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total characters", len(df))
col2.metric("Valid characters", len(df_filtre))
col3.metric("Ignored / filtered", len(df) - len(df_filtre))
col4.metric("Distinct races", int(compte_par_race["race"].nunique()))

st.divider()

tab_races, tab_talents, tab_prodigies, tab_artefacts, tab_persos = st.tabs(
    ["Races", "Talents", "Prodigies", "Artefacts", "Characters"]
)

# ── Races ─────────────────────────────────────────────────────────────────────
with tab_races:
    st.subheader("Race distribution")
    df_races = compte_par_race.dropna(subset=["race"]).sort_values("count", ascending=True)
    fig = px.bar(
        df_races, x="count", y="race", orientation="h",
        color="count", color_continuous_scale="Blues",
        labels={"count": "# characters", "race": "Race"},
        text="count",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False, coloraxis_showscale=False,
                      height=max(300, len(df_races) * 28), yaxis_title="")
    st.plotly_chart(fig, use_container_width=True)

# ── Talents ───────────────────────────────────────────────────────────────────
with tab_talents:
    st.subheader("Average points per talent")

    col_filtre, col_metrique = st.columns([2, 1])
    with col_filtre:
        type_filtre = st.radio(
            "Type", ["Class Talents", "Generic Talents", "All"], horizontal=True, key="type_talent"
        )
    with col_metrique:
        metrique = st.selectbox("Metric", ["avg_points", "median_points", "mode_points"], key="metrique")

    df_display = df_talents_top.copy()
    if type_filtre != "All":
        df_display = df_display[df_display["talent_type"] == type_filtre]
    df_display = df_display.sort_values(metrique, ascending=True)

    if df_display.empty:
        st.info(f"No talent with ≥ {nb_min_personnages} characters.")
    else:
        fig = px.bar(
            df_display,
            x=metrique, y="talent",
            color="tree", orientation="h",
            facet_col="talent_type" if type_filtre == "All" else None,
            hover_data={"avg_points": ":.2f", "median_points": ":.2f",
                        "nb_characters": True, "points_max": True},
            labels={metrique: metrique.replace("_", " ").title(),
                    "talent": "", "tree": "Tree"},
        )
        fig.update_layout(height=max(400, len(df_display) * 22), legend_title="Tree")
        if type_filtre == "All":
            fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
        st.plotly_chart(fig, use_container_width=True)

    # Point distribution for the filtered talent
    if filtre_actif:
        st.divider()
        st.subheader(f"Point distribution — {talent_filtre}")
        pts_data = []
        for _, row in df_details.loc[~df_details["ignore"].astype(bool)].iterrows():
            for t in (row["talents"] or []):
                if t["talent"] == talent_filtre:
                    pts_data.append(t["points"])
                    break
        if pts_data:
            df_dist = pd.Series(pts_data).value_counts().sort_index().reset_index()
            df_dist.columns = ["points", "nb_characters"]
            fig_dist = px.bar(
                df_dist, x="points", y="nb_characters",
                color="nb_characters", color_continuous_scale="Purples",
                labels={"points": "Points invested", "nb_characters": "# characters"},
                text="nb_characters",
            )
            fig_dist.update_traces(textposition="outside")
            fig_dist.update_layout(coloraxis_showscale=False, showlegend=False,
                                   xaxis=dict(tickmode="linear", dtick=1))
            st.plotly_chart(fig_dist, use_container_width=True)

# ── Prodigies ─────────────────────────────────────────────────────────────────
with tab_prodigies:
    st.subheader("Most used prodigies")
    if df_prodigies.empty:
        st.info("No data available.")
    else:
        df_prod = df_prodigies.head(20).sort_values("count", ascending=True)
        fig = px.bar(
            df_prod, x="count", y="prodigy", orientation="h",
            color="count", color_continuous_scale="Reds",
            labels={"count": "# uses", "prodigy": "Prodigy"},
            text="count",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False, coloraxis_showscale=False,
                          height=max(300, len(df_prod) * 30), yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Prodigy correlations")

    col_seuil, col_mode = st.columns([1, 2])
    with col_seuil:
        min_count_corr = st.slider("Min. characters per prodigy", 2, 30, 5, key="min_corr")
    with col_mode:
        mode_corr = st.radio(
            "Display value",
            ["Co-occurrences (raw)", "% among takers of the rarest"],
            horizontal=True,
        )

    compteur_pairs, compteur_solo = calculer_correlations_prodigies(df_details, index_valides)

    prodigies_sel = [
        p for p, c in sorted(compteur_solo.items(), key=lambda x: -x[1])
        if c >= min_count_corr
    ]

    if len(prodigies_sel) < 2:
        st.info(f"Fewer than 2 prodigies with ≥ {min_count_corr} characters. Lower the threshold.")
    else:
        import numpy as np

        n = len(prodigies_sel)
        idx = {p: i for i, p in enumerate(prodigies_sel)}
        matrix = np.full((n, n), float("nan"))

        for (p1, p2), count in compteur_pairs.items():
            if p1 not in idx or p2 not in idx:
                continue
            i, j = idx[p1], idx[p2]
            if mode_corr.startswith("%"):
                val = round(100 * count / min(compteur_solo[p1], compteur_solo[p2]), 1)
            else:
                val = float(count)
            if i < j:
                matrix[i][j] = val
            else:
                matrix[j][i] = val

        df_matrix = pd.DataFrame(matrix, index=prodigies_sel, columns=prodigies_sel)

        fig_corr = px.imshow(
            df_matrix,
            color_continuous_scale="Blues",
            text_auto=True,
            aspect="auto",
            labels={"color": "%" if mode_corr.startswith("%") else "Count"},
        )
        fig_corr.update_traces(textfont_size=10)
        fig_corr.update_layout(
            height=max(400, n * 38 + 120),
            xaxis_tickangle=-35,
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig_corr, use_container_width=True)
        st.caption(
            "The diagonal is empty. "
            "In % mode: among characters who took the less frequent of the two prodigies, "
            "how many also took the other one."
        )

# ── Artefacts ─────────────────────────────────────────────────────────────────
with tab_artefacts:
    st.subheader("Most equipped artefacts")
    if df_artefacts.empty:
        st.info("No data available.")
    else:
        top_n = st.slider("Top N", 10, 100, 30, key="top_artefacts")
        df_art = df_artefacts.head(top_n).sort_values("count", ascending=True)
        fig = px.bar(
            df_art, x="count", y="artefact", orientation="h",
            color="count", color_continuous_scale="Greens",
            labels={"count": "# uses", "artefact": "Artefact"},
            text="count",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False, coloraxis_showscale=False,
                          height=max(400, len(df_art) * 22), yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

# ── Characters ────────────────────────────────────────────────────────────────
with tab_persos:
    st.subheader("Character list")

    details_idx = df_details.set_index("index_df")

    rows = []
    for i in index_valides:
        if i not in df.index:
            continue
        row_df = df.loc[i]
        detail = details_idx.loc[i] if i in details_idx.index else {}
        prodigies_str = ", ".join(detail.get("prodigies") or []) if isinstance(detail, pd.Series) else ""
        rows.append({
            "Name": row_df["name"],
            "Race": row_df.get("race", ""),
            "User": row_df["user"],
            "Prodigies": prodigies_str,
            "Last updated": row_df["last_updated"],
            "URL": row_df["character_url"],
        })

    df_persos = pd.DataFrame(rows)

    col_race, col_search, col_prodigy = st.columns([1, 2, 2])
    with col_race:
        races_dispo = ["(all)"] + sorted(df_persos["Race"].dropna().unique().tolist())
        race_sel = st.selectbox("Race", races_dispo, key="perso_race")
    with col_search:
        search = st.text_input("Search (name / user)", key="perso_search")
    with col_prodigy:
        prodigy_sel = st.text_input("Contains prodigy", key="perso_prodigy",
                                    placeholder="e.g. Cauterize")

    df_aff = df_persos.copy()
    if race_sel != "(all)":
        df_aff = df_aff[df_aff["Race"] == race_sel]
    if search:
        mask = (
            df_aff["Name"].str.contains(search, case=False, na=False)
            | df_aff["User"].str.contains(search, case=False, na=False)
        )
        df_aff = df_aff[mask]
    if prodigy_sel:
        df_aff = df_aff[df_aff["Prodigies"].str.contains(prodigy_sel, case=False, na=False)]

    st.caption(f"{len(df_aff)} characters displayed")

    st.dataframe(
        df_aff,
        column_config={
            "URL": st.column_config.LinkColumn("Link", display_text="↗"),
        },
        use_container_width=True,
        hide_index=True,
    )
