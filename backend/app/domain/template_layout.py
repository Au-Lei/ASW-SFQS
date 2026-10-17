"""Pure layout planning; no workbook I/O, database access or price updates."""
from __future__ import annotations


def plan_sheet(rows: list[dict], *, first_row: int = 3) -> dict:
    """Input must already be ordered by route, country block, destination and quote.

    Repeated destinations are legitimate quotation rows. Merge only column A;
    country suppression affects display, never the complete input records.
    """
    planned, separators, merges = [], [], []
    cursor = first_row
    previous_route = previous_country = None
    closed_routes, closed_countries = set(), set()
    route_start = None
    for record in rows:
        route, country = record["route_group_id"], record["country_region_id"]
        new_route = route != previous_route
        new_country = new_route or country != previous_country
        if new_route:
            if route in closed_routes:
                raise ValueError("NONCONTIGUOUS_ROUTE")
            if previous_route is not None:
                merges.append({"route_group_id": previous_route, "start_row": route_start, "end_row": cursor - 1})
                closed_routes.add(previous_route)
            closed_countries = set()
        elif new_country:
            closed_countries.add(previous_country)
            if country in closed_countries:
                raise ValueError("NONCONTIGUOUS_COUNTRY_BLOCK")
        if planned and new_country:
            separators.append(cursor)
            cursor += 1
        if new_route:
            route_start = cursor
        planned.append({"row": cursor, "destination_id": record["id"], "route_group_id": route,
                        "country_region_id": country, "show_country": new_country,
                        "show_route": new_route})
        cursor += 1
        previous_route, previous_country = route, country
    if planned:
        merges.append({"route_group_id": previous_route, "start_row": route_start, "end_row": cursor - 1})
    return {"rows": planned, "separator_rows": separators, "route_spans": merges,
            "merges": ["A1:R1"] + [f"A{r['start_row']}:A{r['end_row']}" for r in merges if r["end_row"] > r["start_row"]],
            "last_data_row": cursor - 1 if planned else 2}
