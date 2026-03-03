"""Azure Retail Prices API — SKU-based monthly cost estimation.

No authentication required.  Uses the public Azure Retail Prices REST API
(https://prices.azure.com/api/retail/prices).

Falls back gracefully to None on any network or parsing error — governance
decisions still work correctly when cost data is unavailable; they simply
treat the resource's monthly cost as unknown.

Usage::

    from src.infrastructure.cost_lookup import get_sku_monthly_cost

    cost = get_sku_monthly_cost("Standard_B2ls_v2", "canadacentral")
    # Returns e.g. 36.47 (USD/month) or None if not found / API unreachable.

Async usage (non-blocking, for use inside async @af.tool callbacks)::

    from src.infrastructure.cost_lookup import get_sku_monthly_cost_async

    cost = await get_sku_monthly_cost_async("Standard_B2ls_v2", "canadacentral")
"""

import logging

import httpx

logger = logging.getLogger(__name__)

# In-memory cache keyed by "<sku_lower>::<location_lower>::<os_type_lower>".
# Persists for the process lifetime — one lookup per (sku, region, os_type) triple.
# Shared between sync and async variants — GIL-protected dict operations are safe.
_cache: dict[str, float | None] = {}

RETAIL_PRICES_URL = "https://prices.azure.com/api/retail/prices"


def _extract_monthly_cost(items: list[dict], os_type: str) -> float | None:
    """Shared PAYG/OS filtering logic for both sync and async cost lookup.

    Given the ``Items`` list from the Azure Retail Prices API response,
    applies pay-as-you-go and OS-aware filtering, then returns the estimated
    monthly cost (hourly_rate × 730 hours), or ``None`` if no qualifying
    meter is found.

    Called by both :func:`get_sku_monthly_cost` and
    :func:`get_sku_monthly_cost_async` so the filtering logic lives in
    exactly one place.

    Args:
        items:   List of price items from the API ``Items`` array.
        os_type: OS type string — ``"Windows"``, ``"Linux"``, or ``""``.

    Returns:
        Estimated monthly cost (rounded to 2 dp) or ``None``.
    """
    def _is_payg(item: dict) -> bool:
        """True for items with a positive retail price that are not Spot/Low-Priority."""
        sku_name = item.get("skuName") or ""
        return (
            item.get("retailPrice", 0) > 0
            and "Spot" not in sku_name
            and "Low Priority" not in sku_name
        )

    if os_type.lower() == "windows":
        # Prefer meters that carry an explicit Windows label so we price
        # the Windows OS license correctly.
        windows_prices = [
            i["retailPrice"]
            for i in items
            if _is_payg(i) and "Windows" in (i.get("skuName") or "")
        ]
        # Fallback: some SKUs have no OS-labelled meters at all; use any
        # PAYG meter in that case rather than returning None.
        payg_prices = windows_prices or [
            i["retailPrice"] for i in items if _is_payg(i)
        ]
    else:
        # Linux (explicit) or unknown: exclude Windows-labeled meters so
        # min() reliably returns the Linux base-tier price for dual-OS SKUs.
        payg_prices = [
            i["retailPrice"]
            for i in items
            if _is_payg(i) and "Windows" not in (i.get("skuName") or "")
        ]

    if payg_prices:
        return round(min(payg_prices) * 730, 2)
    return None


def get_sku_monthly_cost(
    sku: str,
    location: str,
    *,
    os_type: str = "",
) -> float | None:
    """Return estimated monthly USD cost for a given Azure SKU and region.

    Queries the Azure Retail Prices REST API for the Consumption retail price
    of the SKU, then multiplies by 730 hours (average hours in a month).

    When ``os_type`` is supplied the meter selection is OS-aware:

    * ``"Windows"`` — selects meters whose ``skuName`` contains ``"Windows"``;
      falls back to any non-Spot/non-LP meter when no Windows-labeled meter
      exists (some SKUs report all tiers under a single unlabelled meter name).
    * ``"Linux"`` — explicitly excludes Windows-labeled meters so ``min()``
      reliably returns the Linux base-tier price.
    * ``""`` (default / unknown) — same exclusion as Linux; ``min()`` picks the
      cheapest PAYG meter, which is the Linux base tier for dual-OS SKUs.
      This is an acknowledged approximation for resources whose OS is not
      known at call time.

    Results are cached in memory so each (sku, region, os_type) triple is only
    fetched once per process run.  Transient API/network failures are NOT
    cached so the next call can retry; "SKU not found" (API succeeded, no
    matching meters) IS cached to avoid repeated no-op requests.

    The cache is shared with :func:`get_sku_monthly_cost_async` — a result
    populated by either variant is immediately visible to the other.

    Args:
        sku:      Azure VM SKU name, e.g. ``"Standard_B2ls_v2"``.
        location: Azure region ARM name, e.g. ``"canadacentral"``.
        os_type:  OS type string from Azure Resource Graph
                  (``"Windows"``, ``"Linux"``, or ``""``).

    Returns:
        Estimated monthly cost in USD (rounded to 2 decimal places),
        or ``None`` if the SKU is unknown or the API call fails.
    """
    if not sku or not location:
        return None

    # os_type is included in the key so Windows and Linux VMs with the same
    # SKU/region are cached and priced independently.
    key = f"{sku.lower()}::{location.lower()}::{os_type.lower()}"
    if key in _cache:
        return _cache[key]

    try:
        # unitOfMeasure='1 Hour' excludes non-compute meters (storage, egress,
        # etc.) that share the same armSkuName but are priced per GB or per
        # operation.  priceType/type both set to Consumption excludes reserved
        # capacity rows.
        filter_str = (
            f"armRegionName eq '{location}' "
            f"and armSkuName eq '{sku}' "
            f"and priceType eq 'Consumption' "
            f"and type eq 'Consumption' "
            f"and unitOfMeasure eq '1 Hour'"
        )
        resp = httpx.get(
            RETAIL_PRICES_URL,
            params={"$filter": filter_str},
            timeout=5.0,
        )
        resp.raise_for_status()
        items = resp.json().get("Items", [])

        monthly = _extract_monthly_cost(items, os_type)
        if monthly is not None:
            _cache[key] = monthly
            return monthly

        # API call succeeded but no matching PAYG hourly meters exist for this
        # SKU/region/os combination.  Cache None so we don't repeatedly query
        # the API for an unknown or unsupported SKU.
        _cache[key] = None
        return None

    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cost_lookup: failed for sku=%s location=%s: %s", sku, location, exc
        )
        # Transient failure (network error, API timeout, etc.) — do NOT cache
        # None so the next governance evaluation can retry the lookup.
        return None


async def get_sku_monthly_cost_async(
    sku: str,
    location: str,
    *,
    os_type: str = "",
) -> float | None:
    """Async variant of :func:`get_sku_monthly_cost` — non-blocking HTTP call.

    Uses ``httpx.AsyncClient`` instead of ``httpx.get`` so the event loop is
    not blocked while waiting for the Azure Retail Prices API response.
    Intended for use inside ``async def`` ``@af.tool`` callbacks in the
    Microsoft Agent Framework, where sync HTTP calls would block all other
    concurrent governance agent evaluations.

    Shares the same ``_cache`` dict as the sync variant — a result populated
    by either function is immediately visible to the other (GIL-protected dict
    operations are safe in CPython without additional locking).

    Args and return value are identical to :func:`get_sku_monthly_cost`.
    """
    if not sku or not location:
        return None

    key = f"{sku.lower()}::{location.lower()}::{os_type.lower()}"
    if key in _cache:
        return _cache[key]

    try:
        filter_str = (
            f"armRegionName eq '{location}' "
            f"and armSkuName eq '{sku}' "
            f"and priceType eq 'Consumption' "
            f"and type eq 'Consumption' "
            f"and unitOfMeasure eq '1 Hour'"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                RETAIL_PRICES_URL,
                params={"$filter": filter_str},
                timeout=5.0,
            )
        resp.raise_for_status()
        items = resp.json().get("Items", [])

        monthly = _extract_monthly_cost(items, os_type)
        if monthly is not None:
            _cache[key] = monthly
            return monthly

        # API succeeded but no qualifying meters — cache None to suppress retries.
        _cache[key] = None
        return None

    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cost_lookup(async): failed for sku=%s location=%s: %s", sku, location, exc
        )
        # Transient failure — do NOT cache so the next call can retry.
        return None
