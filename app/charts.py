"""Small chart helpers (Altair, which ships with Streamlit).

Rules followed: thin marks, 2px lines, bars with rounded data ends, a hover
tooltip on every mark, one y-axis per chart, and each vendor keeps the same
color on every chart (color follows the vendor, not its rank).
"""

import altair as alt

# Validated categorical palette, used in this fixed order
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                 "#e87ba4", "#008300", "#6250d6", "#e34948"]
SINGLE_COLOR = SERIES_COLORS[0]


def vendor_color_scale(all_vendors):
    """Same vendor -> same color everywhere (by alphabetical position)."""
    return alt.Scale(domain=all_vendors, range=SERIES_COLORS[:len(all_vendors)])


def _money(field, title):
    return alt.Tooltip(field, title=title, format="$,.2f")


def bar_chart(data, category, value, value_title="Spend", horizontal=True, height=None):
    """One series of bars, sorted by value."""
    data = data.assign(**{value: data[value].astype(float)})
    bars = alt.Chart(data)
    if horizontal:
        bars = bars.mark_bar(color=SINGLE_COLOR, cornerRadiusEnd=4, size=14).encode(
            y=alt.Y(f"{category}:N", sort="-x", title=None),
            x=alt.X(f"{value}:Q", title=value_title, axis=alt.Axis(format="$,.0f", grid=True)),
        )
        height = height or max(120, 26 * len(data))
    else:
        bars = bars.mark_bar(color=SINGLE_COLOR, cornerRadiusEnd=4).encode(
            x=alt.X(f"{category}:N", title=None),
            y=alt.Y(f"{value}:Q", title=value_title, axis=alt.Axis(format="$,.0f")),
        )
        height = height or 280
    return bars.encode(tooltip=[alt.Tooltip(f"{category}:N", title=category.replace("_", " ")),
                                _money(f"{value}:Q", value_title)]).properties(height=height)


def stacked_month_bars(data, all_vendors):
    """Spend per month, split by vendor (stacked; legend shows vendor colors)."""
    data = data.assign(spend=data["spend"].astype(float))
    return alt.Chart(data).mark_bar().encode(
        x=alt.X("month:N", title=None),
        y=alt.Y("sum(spend):Q", title="Spend", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("vendor_name:N", title="Vendor", scale=vendor_color_scale(all_vendors),
                        legend=alt.Legend(orient="top")),
        order=alt.Order("vendor_name:N"),
        tooltip=[alt.Tooltip("month:N", title="Month"), alt.Tooltip("vendor_name:N", title="Vendor"),
                 _money("spend:Q", "Spend")],
    ).properties(height=300)


def price_lines(data, all_vendors, unit):
    """Price per standard unit over time, one 2px line per vendor."""
    data = data.assign(unit_price=data["unit_price"].astype(float))
    base = alt.Chart(data).encode(
        x=alt.X("purchase_date:T", title=None),
        y=alt.Y("unit_price:Q", title=f"Price per {unit}", scale=alt.Scale(zero=False),
                axis=alt.Axis(format="$,.2f")),
        color=alt.Color("vendor_name:N", title="Vendor", scale=vendor_color_scale(all_vendors),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("vendor_name:N", title="Vendor"),
                 alt.Tooltip("purchase_date:T", title="Date"),
                 alt.Tooltip("unit_price:Q", title=f"Price per {unit}", format="$,.4f"),
                 alt.Tooltip("pct_change:Q", title="Change vs previous (%)")],
    )
    lines = base.mark_line(strokeWidth=2)
    # Points >= 8px wide, so each purchase is easy to hover
    points = base.mark_point(size=64, filled=True, opacity=1)
    return (lines + points).properties(height=320)
