"""
Projection Module

Computes compound growth projections from current NAV to 30 April 2030.
Supports multiple scenarios (pessimistic, base, optimistic).
Reproduces Excel projection boxes.
"""

import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd


def compute_projections(
    current_nav: float,
    monthly_contribution: float = 0,
    target_date: date = date(2030, 4, 30),
    scenarios: list[dict] = None,
) -> list[dict]:
    """
    Project portfolio growth with monthly contributions.

    Args:
        current_nav: current portfolio NAV in GBP
        monthly_contribution: fixed monthly contribution
        target_date: projection end date (default 30 April 2030)
        scenarios: list of {name, annual_return, annual_volatility}

    Returns:
        list of projection results per scenario
    """
    if scenarios is None:
        scenarios = [
            {"name": "pessimistic", "annual_return": 3.0, "annual_volatility": 15.0},
            {"name": "base", "annual_return": 8.0, "annual_volatility": 12.0},
            {"name": "optimistic", "annual_return": 13.0, "annual_volatility": 18.0},
        ]

    results = []

    for scenario in scenarios:
        monthly_return = scenario["annual_return"] / 100 / 12
        monthly_vol = scenario["annual_volatility"] / 100 / math.sqrt(12)

        # Monthly values
        monthly_values = []
        nav = current_nav
        total_contributed = current_nav

        current = date.today()
        end = target_date

        while current <= end:
            # Add monthly contribution (except for the first month)
            if current != date.today():
                nav += monthly_contribution
                total_contributed += monthly_contribution

            # Apply random drift for Monte Carlo (use deterministic for base)
            drift = monthly_return
            shock = 0  # deterministic

            nav *= (1 + drift + shock)
            nav = max(nav, 0)  # no negative NAV

            monthly_values.append({
                "date": current.isoformat(),
                "value": round(nav, 2),
            })

            # Move to next month
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

        final_value = monthly_values[-1]["value"] if monthly_values else current_nav
        total_gain = final_value - total_contributed

        results.append({
            "scenario_name": scenario["name"],
            "monthly_values": monthly_values,
            "final_value": round(final_value, 2),
            "total_contributed": round(total_contributed, 2),
            "total_gain": round(total_gain, 2),
            "annual_return": scenario["annual_return"],
            "annual_volatility": scenario["annual_volatility"],
        })

    return results


def reproduce_excel_projection(
    current_nav: float,
    monthly_contribution: float,
    expected_return: float,
    target_date: date = date(2030, 4, 30),
) -> dict:
    """
    Reproduce Excel projection box exactly.

    Uses the same compound interest formula as Excel:
    FV = PV * (1+r)^n + PMT * (((1+r)^n - 1) / r)

    Where:
    - PV = current NAV
    - PMT = monthly contribution
    - r = monthly return rate
    - n = number of months
    """
    monthly_rate = expected_return / 100 / 12

    # Count months
    months = (target_date.year - date.today().year) * 12 + (target_date.month - date.today().month)
    if months <= 0:
        months = 1

    # Future value of current NAV
    fv_nav = current_nav * ((1 + monthly_rate) ** months)

    # Future value of monthly contributions
    if monthly_rate > 0:
        fv_contrib = monthly_contribution * (((1 + monthly_rate) ** months - 1) / monthly_rate)
    else:
        fv_contrib = monthly_contribution * months

    total_fv = fv_nav + fv_contrib
    total_contributed = current_nav + (monthly_contribution * months)
    total_gain = total_fv - total_contributed

    return {
        "months": months,
        "final_value": round(total_fv, 2),
        "total_contributed": round(total_contributed, 2),
        "total_gain": round(total_gain, 2),
        "monthly_rate": monthly_rate,
    }
