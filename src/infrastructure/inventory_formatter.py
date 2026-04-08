"""Inventory Formatter — converts an inventory document into a text block for LLM prompts.

Usage::

    from src.infrastructure.inventory_formatter import format_inventory_for_prompt

    text = format_inventory_for_prompt(inventory_doc)
    # Prepend ``text`` to the agent's user prompt.
"""

from __future__ import annotations


def format_inventory_for_prompt(inventory: dict) -> str:
    """Convert an inventory document into a formatted text block for LLM injection.

    Produces dynamic sections for every resource type present — no hardcoded
    type list.  Each section lists resources with their key properties.

    Args:
        inventory: Inventory document dict (from ``CosmosInventoryClient.get_latest``
                   or ``build_inventory``).

    Returns:
        Multi-line string suitable for prepending to an agent prompt.
    """
    resources: list[dict] = inventory.get("resources", [])
    refreshed_at: str = inventory.get("refreshed_at", "unknown")
    resource_count: int = inventory.get("resource_count", len(resources))

    # Group by type (preserve original dict, group dynamically)
    by_type: dict[str, list[dict]] = {}
    for r in resources:
        type_key = (r.get("type") or "unknown").lower()
        by_type.setdefault(type_key, []).append(r)

    type_count = len(by_type)
    lines: list[str] = [
        f"=== RESOURCE INVENTORY ({resource_count} resources, {type_count} types"
        f" — refreshed {refreshed_at}) ===",
        "",
    ]

    for type_key in sorted(by_type.keys()):
        items = by_type[type_key]
        lines.append(f"--- {type_key} ({len(items)}) ---")
        for idx, r in enumerate(items, start=1):
            lines.extend(_format_resource(idx, r, type_key))
        lines.append("")

    return "\n".join(lines)


def _format_resource(idx: int, r: dict, type_key: str) -> list[str]:
    """Format one resource entry as a list of indented lines."""
    name = r.get("name") or r.get("id", "").split("/")[-1] or "?"
    arm_id = r.get("id", "")
    rg = r.get("resourceGroup", "")
    location = r.get("location", "")
    sku = r.get("sku")
    tags: dict = r.get("tags") or {}
    props: dict = r.get("properties") or {}
    power_state: str | None = r.get("powerState")

    lines = [f"[{idx}] {name}"]
    if arm_id:
        lines.append(f"    ARM ID: {arm_id}")
    if rg or location:
        parts = []
        if rg:
            parts.append(f"Resource Group: {rg}")
        if location:
            parts.append(f"Location: {location}")
        lines.append("    " + " | ".join(parts))

    # SKU — may be a string or a dict with name/tier/size
    if sku:
        if isinstance(sku, dict):
            sku_parts = []
            for k in ("name", "tier", "size"):
                if sku.get(k):
                    sku_parts.append(str(sku[k]))
            if sku_parts:
                lines.append(f"    SKU: {' / '.join(sku_parts)}")
        elif isinstance(sku, str) and sku:
            lines.append(f"    SKU: {sku}")

    # Power state — enriched field, only for VMs
    if power_state:
        lines.append(f"    Power State: {power_state}")

    # Properties — only top-level scalar values (no nested objects/arrays)
    flat_props = _flatten_props(props)
    if flat_props:
        lines.append(f"    Properties: {flat_props}")

    # Tags
    if tags:
        tag_str = ", ".join(f"{k}={v}" for k, v in list(tags.items())[:8])
        lines.append(f"    Tags: {tag_str}")

    return lines


def _flatten_props(props: dict) -> str:
    """Return a compact one-liner of top-level scalar props (skip nested objects/lists)."""
    if not props:
        return ""
    parts: list[str] = []
    for k, v in props.items():
        if isinstance(v, (str, int, float, bool)) and v not in ("", None):
            # Skip very long strings (e.g. base64 blobs, PEM certs)
            sv = str(v)
            if len(sv) <= 80:
                parts.append(f"{k}={sv}")
        if len(parts) >= 8:
            break
    return ", ".join(parts)
