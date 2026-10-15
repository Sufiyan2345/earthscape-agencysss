#!/usr/bin/env python3
"""
Correlation analysis module for climate data.
Computes correlations between climate variables and identifies significant relationships.
"""

import numpy as np
import pickle
import os
from datetime import datetime


class CorrelationAnalyzer:
    """Analyze correlations between climate variables."""

    def __init__(self):
        self.data = None
        self.correlation_matrix = None
        self.variables = ['temperature', 'rainfall', 'humidity', 'wind_speed', 'pressure', 'air_quality_index', 'co2_level']

    def load_data(self, climate_data):
        """Load climate data for analysis."""
        self.data = {}
        for var in self.variables:
            if var in climate_data:
                self.data[var] = np.array(climate_data[var], dtype=float)

    def compute_correlation_matrix(self):
        """Compute full correlation matrix between all variables."""
        if not self.data:
            return None

        var_names = [k for k in self.variables if k in self.data]
        n_vars = len(var_names)
        matrix = np.zeros((n_vars, n_vars))

        for i in range(n_vars):
            for j in range(n_vars):
                x = self.data[var_names[i]]
                y = self.data[var_names[j]]
                min_len = min(len(x), len(y))
                if min_len > 1:
                    matrix[i][j] = self._pearson_correlation(x[:min_len], y[:min_len])

        self.correlation_matrix = {
            'variables': var_names,
            'matrix': matrix.tolist(),
            'computed_at': datetime.now().isoformat()
        }
        return self.correlation_matrix

    def compute_pairwise_correlations(self):
        """Compute pairwise correlations with statistical significance."""
        if not self.data:
            return []

        results = []
        var_names = [k for k in self.variables if k in self.data]

        for i in range(len(var_names)):
            for j in range(i + 1, len(var_names)):
                x = self.data[var_names[i]]
                y = self.data[var_names[j]]
                min_len = min(len(x), len(y))

                if min_len > 2:
                    r = self._pearson_correlation(x[:min_len], y[:min_len])
                    p_value = self._estimate_p_value(r, min_len)
                    significant = p_value < 0.05

                    results.append({
                        'variable_1': var_names[i],
                        'variable_2': var_names[j],
                        'correlation': round(r, 4),
                        'p_value': round(p_value, 4),
                        'significant': significant,
                        'strength': self._classify_strength(r),
                        'direction': 'positive' if r > 0 else 'negative',
                        'sample_size': min_len,
                        'interpretation': self._interpret(r, var_names[i], var_names[j])
                    })

        results.sort(key=lambda x: abs(x['correlation']), reverse=True)
        return results

    def find_strongest_correlations(self, top_n=5):
        """Find the strongest correlations."""
        pairwise = self.compute_pairwise_correlations()
        return pairwise[:top_n]

    def regional_correlation(self, data_by_region):
        """Compute correlations per region and compare."""
        regional_results = {}

        for region, data in data_by_region.items():
            analyzer = CorrelationAnalyzer()
            analyzer.load_data(data)
            pairwise = analyzer.compute_pairwise_correlations()
            regional_results[region] = pairwise

        # Find correlations that differ significantly between regions
        comparison = self._compare_regional_correlations(regional_results)

        return {
            'regional_correlations': regional_results,
            'comparison': comparison,
            'computed_at': datetime.now().isoformat()
        }

    def temporal_correlation(self, data, window_size=30):
        """Compute rolling window correlations over time."""
        if not self.data:
            return []

        var_names = [k for k in self.variables if k in self.data]
        if len(var_names) < 2:
            return []

        results = []
        n = min(len(self.data[v]) for v in var_names)

        for start in range(0, n - window_size, window_size // 2):
            end = start + window_size
            window_data = {v: self.data[v][start:end] for v in var_names}

            analyzer = CorrelationAnalyzer()
            analyzer.load_data(window_data)
            matrix = analyzer.compute_correlation_matrix()

            results.append({
                'window_start': start,
                'window_end': end,
                'correlation_matrix': matrix
            })

        return results

    def _pearson_correlation(self, x, y):
        """Compute Pearson correlation coefficient."""
        n = len(x)
        if n < 2:
            return 0

        mean_x = np.mean(x)
        mean_y = np.mean(y)
        std_x = np.std(x)
        std_y = np.std(y)

        if std_x == 0 or std_y == 0:
            return 0

        correlation = np.sum((x - mean_x) * (y - mean_y)) / (n * std_x * std_y)
        return max(-1, min(1, correlation))

    def _estimate_p_value(self, r, n):
        """Estimate p-value for correlation using t-distribution approximation."""
        if n < 3 or abs(r) >= 1:
            return 0.001

        t = r * np.sqrt((n - 2) / (1 - r ** 2))
        # Approximate p-value using normal distribution for large n
        p_value = 2 * np.exp(-0.717 * abs(t) - 0.416 * t ** 2)
        return max(0.0001, min(1.0, p_value))

    def _classify_strength(self, r):
        """Classify correlation strength."""
        abs_r = abs(r)
        if abs_r >= 0.8:
            return 'very strong'
        elif abs_r >= 0.6:
            return 'strong'
        elif abs_r >= 0.4:
            return 'moderate'
        elif abs_r >= 0.2:
            return 'weak'
        return 'very weak'

    def _interpret(self, r, var1, var2):
        """Generate interpretation of correlation."""
        strength = self._classify_strength(r)
        direction = 'positive' if r > 0 else 'negative'

        interpretations = {
            ('temperature', 'rainfall'): f"A {strength} {direction} correlation suggests that {'higher' if r < 0 else 'lower'} temperatures are associated with {'more' if r > 0 else 'less'} rainfall.",
            ('temperature', 'humidity'): f"A {strength} {direction} correlation between temperature and humidity.",
            ('temperature', 'air_quality_index'): f"A {strength} {direction} correlation suggests temperature {'increases' if r > 0 else 'decreases'} air pollution levels.",
            ('rainfall', 'humidity'): f"A {strength} {direction} correlation between rainfall and humidity is expected.",
        }

        key = tuple(sorted([var1, var2]))
        return interpretations.get(key, f"A {strength} {direction} correlation ({r:.4f}) exists between {var1} and {var2}.")

    def _compare_regional_correlations(self, regional_results):
        """Compare correlations across regions."""
        differences = []
        regions = list(regional_results.keys())

        if len(regions) < 2:
            return []

        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                r1_data = {(p['variable_1'], p['variable_2']): p['correlation'] for p in regional_results[regions[i]]}
                r2_data = {(p['variable_1'], p['variable_2']): p['correlation'] for p in regional_results[regions[j]]}

                common_pairs = set(r1_data.keys()) & set(r2_data.keys())
                for pair in common_pairs:
                    diff = abs(r1_data[pair] - r2_data[pair])
                    if diff > 0.3:
                        differences.append({
                            'region_1': regions[i],
                            'region_2': regions[j],
                            'variables': list(pair),
                            'correlation_1': r1_data[pair],
                            'correlation_2': r2_data[pair],
                            'difference': round(diff, 4)
                        })

        return differences


if __name__ == '__main__':
    # Test correlation analysis
    np.random.seed(42)
    n = 100
    temp = 20 + np.random.normal(0, 5, n)
    rainfall = 50 - 0.5 * (temp - 20) * 10 + np.random.normal(0, 15, n)
    humidity = 60 + 0.3 * rainfall + np.random.normal(0, 8, n)

    data = {'temperature': temp, 'rainfall': rainfall, 'humidity': humidity}

    analyzer = CorrelationAnalyzer()
    analyzer.load_data(data)

    print("Correlation matrix:", analyzer.compute_correlation_matrix())
    print("\nPairwise correlations:")
    for p in analyzer.compute_pairwise_correlations():
        print(f"  {p['variable_1']} <-> {p['variable_2']}: {p['correlation']} ({p['strength']}, {p['direction']})")
