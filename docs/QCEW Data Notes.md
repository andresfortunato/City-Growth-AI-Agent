QCEW data availability & suppression note

QCEW is a near-census of UI-covered employment and wages by industry, geography, and ownership, but it is systematically censored for confidentiality. Suppression is common for MSA × detailed NAICS, especially 3-digit+ industries and wages. Suppressed cells are flagged via disclosure codes and may appear as zero-filled values; zeros must never be assumed to be true zeros. Published higher-level totals include suppressed components and cannot be reconstructed by subtraction. Comparative analyses should default to 2-digit NAICS for MSAs, explicitly condition on disclosure flags, and avoid interpreting missingness as random. Analyzing within city industry composition at more detailed level is possible if employment and/or wage values are disclosed (might be the case for bigger MSAs). 

| Category        | Available | Reliability                   |
| --------------- | --------- | ----------------------------- |
| Employment      | ✅         | High                          |
| Total wages     | ✅         | Medium                        |
| Average wages   | ✅         | Medium–Low                    |
| Establishments  | ✅         | High                          |
| Ownership       | ✅         | High                          |
| Industry detail | ✅         | Declines sharply past 3-digit |
| MSA geography   | ✅         | Disclosure-sensitive          |
| Time series     | ✅         | Strong (with NAICS care)      |
