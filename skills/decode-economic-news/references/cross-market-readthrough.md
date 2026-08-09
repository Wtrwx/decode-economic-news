# Cross-Market Read-Through for A-Shares

Read this file whenever the user asks about “大A”, A-shares, a Chinese sector outlook or named A-share candidates. Use U.S. and Korean peers as evidence overlays, not automatic predictors.

## Blogger-derived reasoning pattern

The transcript corpus uses overseas markets in a layered way: identify why the overseas leader moved, connect that driver to a shared industry constraint, then inspect whether A-shares accept or reject the signal. For example, an overseas AI rebound matters more when hyperscaler earnings change the expected return on capital expenditure; an A-share gap-up that fades is evidence that local positioning, policy or valuation may be blocking the transmission.

Apply this chain:

```text
overseas event or earnings
-> shared structural variable
-> U.S./Korean sector and leader reaction
-> product/customer/supplier linkage to China
-> A-share opening and closing acceptance/rejection
-> local policy, liquidity and positioning modifier
-> conditional A-share conclusion
```

## Mandatory separation

1. Separate a global common factor from a sector shock. Compare every overseas peer with its own broad-market benchmark before calling the move sector-specific.
2. Separate sector proxies from event leaders. An ETF measures breadth; a company earnings report can reveal the mechanism.
3. Separate industrial linkage from label similarity. Memory/HBM, batteries, autos and shipbuilding often have stronger China–Korea read-through than liquor, property developers or agriculture.
4. Separate timing from prediction. The previous U.S. close is observable before the next A-share session. A Korean daily close is not a same-morning leading input; use the previous close unless intraday timestamps are collected separately.
5. Separate price evidence from causal evidence. A correlation is a research lead, not proof that one market caused another.

## Named ETF mapping

Resolve a named ETF's live constituents and industry weights before selecting a cross-market preset. A broad or mixed ETF may require several preset overlays. Apply these rules:

1. Keep only exposures above the configured materiality threshold and with a real product, customer, supplier, commodity or discount-rate linkage.
2. Date index constituents separately from the fund's latest disclosed holdings.
3. Weight overseas overlays only when industry weights refer to the same observation date. Otherwise report each overlay separately.
4. Do not map a broad technology or innovation ETF to one semiconductor proxy merely because of its name.
5. Calculate technical state on the traded ETF, but trace causal transmission through the earnings and valuation variables of its important constituents.

## Acceptance and rejection tests

Classify the combination rather than quoting foreign returns alone:

| Overseas sector-relative move | A-share sector-relative move | Research interpretation |
|---|---|---|
| Positive | Positive | Possible common driver; verify earnings/order transmission and crowding |
| Positive | Negative | `foreign_positive_a_rejected`: test local policy, valuation, positioning or broken supply-chain linkage |
| Negative | Positive | `foreign_negative_a_resilient`: test domestic stimulus, import substitution or local supply constraints |
| Negative | Negative | Possible common shock; distinguish global de-risking from sector fundamentals |

Require an explicit answer to: “What changed overseas, which variable is actually shared, and why should that variable reach this A-share company’s orders, margins or valuation?”

## Evidence and forecast rules

- Load mappings from `cross-market-presets.json`. Respect `mapping_strength` and every caveat; omit a market when no clean proxy exists.
- Fetch daily histories with `fetch_cross_market_history.py`, then calculate the overlay with `compute_cross_market_signal.py`.
- Treat Yahoo Finance chart data as an undocumented public-market auxiliary source. Cache, rate-limit and disclose gaps or 429 responses.
- Use the overseas overlay to change research priority or scenario weights. Do not add it mechanically to the A-share direction score until a point-in-time walk-forward test validates that exact rule.
- Do not name an A-share as a buy solely because an overseas ETF or leader rose.
- For a material recommendation, open the overseas leader's original earnings release/filing and verify the operational driver; price alone cannot establish capital-expenditure, demand or pricing transmission.

## Minimum output block

```text
Cross-market as of:
U.S. sector/leader move vs U.S. market:
Korean sector/leader move vs Korean market:
Shared variable and industrial linkage:
A-share acceptance/rejection:
Local modifier:
Historical lead/lag sample and limitation:
What would invalidate the read-through:
```
