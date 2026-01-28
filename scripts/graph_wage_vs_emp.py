# /// script
# dependencies = ["pandas", "numpy", "plotly"]
# ///

import os
import tempfile
import urllib.request
import zipfile

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def read_msa_from_zip(zip_url):
    tf = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        tf.close()
        urllib.request.urlretrieve(zip_url, tf.name)
        with zipfile.ZipFile(tf.name) as zf:
            names = [
                name
                for name in zf.namelist()
                if name.lower().endswith(".csv")
                and "MSA" in os.path.basename(name)
            ]
            if not names:
                return pd.DataFrame()

            cols_keep = [
                "area_fips",
                "area_title",
                "year",
                "qtr",
                "size_code",
                "size_title",
                "annual_avg_estabs_count",
                "annual_avg_emplvl",
                "total_annual_wages",
                "avg_annual_pay",
                "annual_avg_wkly_wage",
                "agglvl_title",
            ]

            frames = []
            for name in names:
                with zf.open(name) as f:
                    df = pd.read_csv(f, dtype={"area_fips": str}, low_memory=False)
                keep = [c for c in cols_keep if c in df.columns]
                df = df.loc[:, keep]
                if "agglvl_title" in df.columns:
                    df = df[df["agglvl_title"] == "MSA, Total Covered"]
                frames.append(df)

            if not frames:
                return pd.DataFrame()
            return pd.concat(frames, ignore_index=True, sort=False)
    finally:
        try:
            os.remove(tf.name)
        except OSError:
            pass


def get_msa_cagr(years, drop_pr=True):
    urls = [
        f"https://data.bls.gov/cew/data/files/{y}/csv/{y}_annual_by_area.zip"
        for y in years
    ]

    frames = [read_msa_from_zip(url) for url in urls]
    if frames:
        msa = pd.concat(frames, ignore_index=True, sort=False)
    else:
        msa = pd.DataFrame()

    if msa.empty:
        return msa

    msa = msa.loc[
        :,
        [
            "area_fips",
            "area_title",
            "year",
            "qtr",
            "size_code",
            "size_title",
            "annual_avg_estabs_count",
            "annual_avg_emplvl",
            "total_annual_wages",
            "avg_annual_pay",
            "annual_avg_wkly_wage",
        ],
    ]
    msa["year"] = pd.to_numeric(msa["year"], errors="coerce").astype("Int64")

    area_names = msa[["area_fips", "area_title"]].drop_duplicates()
    out = msa.drop(columns=["area_title"]).merge(
        area_names, on="area_fips", how="left"
    )

    if drop_pr:
        out = out[
            ~out["area_title"].str.contains(r"\bPR\b", regex=True, na=False)
        ].copy()
        out["area_title"] = out["area_title"].str.replace(" MSA", "", regex=False)
        out["state"] = out["area_title"].str[-2:]
    return out


years = [2022, 2024]
total_msa = get_msa_cagr(years)

numeric_cols = [
    "annual_avg_estabs_count",
    "annual_avg_emplvl",
    "total_annual_wages",
    "avg_annual_pay",
    "annual_avg_wkly_wage",
]
for col in numeric_cols:
    if col in total_msa.columns:
        total_msa[col] = pd.to_numeric(total_msa[col], errors="coerce")

total_msa = total_msa.sort_values(["area_fips", "year"])
group = total_msa.groupby("area_fips")

total_msa_change = total_msa.assign(
    cagr_avg_pay=(total_msa["avg_annual_pay"] / group["avg_annual_pay"].shift(1))
    ** (1 / 4)
    - 1,
    cagr_estab=(
        total_msa["annual_avg_estabs_count"]
        / group["annual_avg_estabs_count"].shift(1)
    )
    ** (1 / 4)
    - 1,
    cagr_avg_weekwage=(
        total_msa["annual_avg_wkly_wage"]
        / group["annual_avg_wkly_wage"].shift(1)
    )
    ** (1 / 4)
    - 1,
    cagr_emp=(total_msa["annual_avg_emplvl"] / group["annual_avg_emplvl"].shift(1))
    ** (1 / 4)
    - 1,
)

se = ["SC", "NC", "GA", "TN", "VA", "AL"]

graph = total_msa_change.dropna().copy()
graph["southeast"] = np.where(graph["state"].isin(se), "Southeast", "Other")

x0 = graph["cagr_emp"].mean()
y0 = graph["cagr_avg_pay"].mean()

fig = px.scatter(
    graph,
    x="cagr_emp",
    y="cagr_avg_pay",
    size="annual_avg_emplvl",
    hover_name="area_title",
    hover_data={
        "cagr_emp": ":.2%",
        "cagr_avg_pay": ":.2%",
        "annual_avg_emplvl": ":,",
        "area_title": False,
        "southeast": False,
    },
    labels={
        "cagr_emp": "Employment Growth (CAGR), 2022-2024",
        "cagr_avg_pay": "Average Annual Pay Growth (CAGR), 2022-2024",
        "annual_avg_emplvl": "Employment (2024)",
    },
    size_max=30,
)
fig.update_traces(marker=dict(color="black"))

fig.add_vline(x=x0, line_color="darkgrey")
fig.add_hline(y=y0, line_color="darkgrey")

x_min, x_max = graph["cagr_emp"].min(), graph["cagr_emp"].max()
fig.add_shape(
    type="line",
    x0=x_min,
    x1=x_max,
    y0=x_min + (y0 - x0),
    y1=x_max + (y0 - x0),
    line=dict(color="darkgrey", dash="longdash"),
)
fig.add_shape(
    type="line",
    x0=x_min,
    x1=x_max,
    y0=(-x_min) + (y0 + x0),
    y1=(-x_max) + (y0 + x0),
    line=dict(color="darkgrey", dash="longdash"),
)

max_emp = graph["cagr_emp"].max()
max_pay = graph["cagr_avg_pay"].max()
min_emp = graph["cagr_emp"].min()
fig.add_annotation(
    x=max_emp,
    y=y0,
    text="Avg wage growth",
    showarrow=False,
    font=dict(color="darkgrey"),
    xanchor="right",
    yshift=6,
)
fig.add_annotation(
    x=x0,
    y=max_pay,
    text="Avg employment growth",
    showarrow=False,
    font=dict(color="darkgrey"),
    xanchor="left",
    yshift=6,
)
fig.add_annotation(
    x=max_emp * 0.9,
    y=(y0 - x0) + (max_emp * 0.9),
    text="Slope = 1",
    showarrow=False,
    font=dict(color="darkgrey"),
    textangle=45,
    yshift=6,
)
diag_x = min_emp + (max_emp - min_emp) * 0.1
fig.add_annotation(
    x=diag_x,
    y=(y0 + x0) - diag_x,
    text="Slope = -1",
    showarrow=False,
    font=dict(color="darkgrey"),
    textangle=-45,
    yshift=6,
)

fig.update_xaxes(tickformat=".0%")
fig.update_yaxes(tickformat=".0%")
fig.update_layout(showlegend=False, paper_bgcolor="white", plot_bgcolor="white")

out_path = "wage_vs_emp_growth.html"
fig.write_html(out_path, include_plotlyjs="cdn")
print(f"Saved plot to {out_path}")
