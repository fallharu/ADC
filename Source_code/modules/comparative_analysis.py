import os
import json
import pandas as pd
import numpy as np
from scipy import stats
import matplotlib.pyplot as plt
import seaborn as sns


def load_overtake_data(folder_path: str) -> pd.DataFrame:
    """Load all CSV/JSON files in the given folder and concatenate them into a DataFrame.
    Expected columns: ['year', 'road_type', 'overtake_distance', 'vehicle_speed', 'overtake_speed', 'inner_overtake', 'outer_overtake']
    """
    data_frames = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            if f.lower().endswith('.csv'):
                df = pd.read_csv(os.path.join(root, f))
                data_frames.append(df)
            elif f.lower().endswith('.json'):
                df = pd.read_json(os.path.join(root, f))
                data_frames.append(df)
    if not data_frames:
        raise FileNotFoundError(f"No CSV/JSON data files found in {folder_path}")
    return pd.concat(data_frames, ignore_index=True)


def compute_statistics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute summary statistics for each (year, road_type) group.
    Returns a DataFrame with columns: year, road_type, count, mean_speed, mean_overtake_speed, inner_ratio, outer_ratio
    """
    grouped = df.groupby(['year', 'road_type'])
    summary = grouped.agg(
        count=('overtake_distance', 'size'),
        mean_speed=('vehicle_speed', 'mean'),
        mean_overtake_speed=('overtake_speed', 'mean'),
        inner_overtake=('inner_overtake', 'sum'),
        outer_overtake=('outer_overtake', 'sum')
    ).reset_index()
    summary['inner_ratio'] = summary['inner_overtake'] / summary['count']
    summary['outer_ratio'] = summary['outer_overtake'] / summary['count']
    return summary


def run_tests(df: pd.DataFrame) -> dict:
    """Run statistical tests between groups.
    Returns a dict with keys: 't_test', 'mann_whitney', 'anova' each containing a sub‑dict with p‑value and description.
    """
    results = {}
    # Example: compare vehicle_speed between road_type groups for each year
    for year, sub in df.groupby('year'):
        groups = [g['vehicle_speed'].dropna() for _, g in sub.groupby('road_type')]
        if len(groups) == 2:
            t_res = stats.ttest_ind(groups[0], groups[1], equal_var=False)
            mw_res = stats.mannwhitneyu(groups[0], groups[1], alternative='two-sided')
            results[f"year_{year}_speed"] = {
                't_test_p': float(t_res.pvalue),
                'mann_whitney_p': float(mw_res.pvalue)
            }
    # ANOVA across all years for vehicle_speed
    if not df.empty:
        anova_res = stats.f_oneway(*[g['vehicle_speed'].dropna() for _, g in df.groupby('year')])
        results['anova_speed'] = {'anova_p': float(anova_res.pvalue)}
    return results


def generate_plots(df: pd.DataFrame, output_dir: str):
    """Create and save plots to the output directory.
    - Box plot of vehicle_speed by year
    - Violin plot of overtaking_distance by road_type
    - Scatter plot of vehicle_speed vs overtaking_distance
    """
    os.makedirs(output_dir, exist_ok=True)
    plt.figure(figsize=(8, 6))
    sns.boxplot(x='year', y='vehicle_speed', data=df)
    plt.title('Vehicle Speed by Year')
    plt.savefig(os.path.join(output_dir, 'box_speed_by_year.png'))
    plt.close()

    plt.figure(figsize=(8, 6))
    sns.violinplot(x='road_type', y='overtake_distance', data=df)
    plt.title('Overtake Distance by Road Type')
    plt.savefig(os.path.join(output_dir, 'violin_distance_by_road.png'))
    plt.close()

    plt.figure(figsize=(8, 6))
    sns.scatterplot(x='vehicle_speed', y='overtake_distance', hue='road_type', data=df)
    plt.title('Speed vs Overtake Distance')
    plt.savefig(os.path.join(output_dir, 'scatter_speed_distance.png'))
    plt.close()
