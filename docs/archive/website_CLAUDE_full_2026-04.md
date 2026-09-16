\# CLAUDE.md — Eco-Oil Website Project



\## Project Overview

Static website for Eco-Oil company (HTML / CSS / JavaScript).

The website will also host client portals that connect to the management system (`eco\_oil\_platform`).



\*\*Current pages:\*\* index, about, services-offered, industrial-consulting, eco-depot, export-of-waste, types-of-waste-water.



\## Development Environment — IMPORTANT

\- Development is currently done on \*\*Limor's personal laptop\*\*.

\- At the final stage, the entire project (website + management system) will be \*\*migrated to the CEO's main computer\*\* for full deployment.

\- When making decisions about paths, installations, configurations, or dependencies — always keep this future migration in mind and flag anything that might complicate it.



\## User Profile

\- \*\*Technical level: complete beginner.\*\* Limor does not read or write code.

\- She describes what she wants → Claude Code implements → she reviews the result in the browser.

\- Never assume technical knowledge. Explain everything at a 10–12-year-old level.



\## Working Style



\### Step-by-step, always

\- Give \*\*one step at a time\*\* and wait for explicit confirmation before continuing.

\- Do not proceed without clear approval or clarifying questions from Limor.

\- If something is unclear, \*\*simplify — do not add complexity.\*\*



\### Show results, not code

\- By default, \*\*do not show code blocks\*\* in responses.

\- Explain in plain words what was changed, then let Limor check the page in her browser.

\- Only show code if Limor explicitly asks for it.



\### Iteration loop

The standard work flow is:

1\. Claude Code makes a change.

2\. Limor opens the page in the browser and reviews.

3\. They iterate together on adjustments until Limor is satisfied.

4\. Only then move to the next task.



\### Listen first, critique later

In early-stage discussions, understand Limor's idea fully before suggesting changes or restructuring. Use a \*\*calm, collaborative, curious tone.\*\*



\## Communication Rules

\- \*\*Never tell Limor what she wants to hear.\*\* Be objective. Contradict when needed. Share strong opinions when you have them.

\- \*\*Do not invent features, options, or controls that do not exist\*\* in the actual files.

\- \*\*Be precise about where to act.\*\* If the file structure or location is unclear — ask for a screenshot before giving instructions.

\- When giving instructions that involve clicking or navigating (browser, terminal, software) — describe exactly what to click and where.

\- Limor may describe desired changes in \*\*words, screenshots, or a mix of both\*\* — adapt accordingly.



\## Responsive Design

\- Limor has \*\*not yet seen a visual demonstration\*\* of the site's responsiveness (unlike Framer, which shows breakpoints on screen).

\- Whenever a visual or layout change is made, \*\*provide clear instructions\*\* on how Limor can preview the page in Desktop / Tablet / Mobile views using Chrome DevTools (Right-click → Inspect → Toggle device toolbar).

\- Do not just state "it's responsive" — always give her a way to verify it herself.



\## Design Consistency

\- A visual design system has already been established in the project (colors, fonts, spacing, layout style, etc.).

\- \*\*Preserve the existing design\*\* as it currently appears in the code. Do not change colors, fonts, or visual elements on your own initiative.

\- If a design change seems necessary or beneficial, \*\*propose it first\*\* — explain what and why — and wait for Limor's explicit approval or rejection before applying it.

\- When adding new elements (new sections, new pages, new components), \*\*match the existing design language\*\* (same color palette, same fonts, same spacing style) rather than introducing new visual patterns.

\- If you are unsure what the existing style is for a specific element, \*\*check the current CSS files\*\* before building something new.



\## Testing Standard

\- When testing a change or a new feature: run a \*\*full, thorough simulation from the start\*\* of the relevant flow.

\- No half-tests, no shortcuts — even if it takes longer.

\- Work in an orderly, realistic manner, following the complete user flow.



\## Session Startup Checklist

At the start of every new session, before any development work, verify:

1\. Correct project folder is open (`website`).

2\. Any required local server / preview tool is running.

3\. Confirm with Limor which page or task is the focus for this session.



\## Client Portals — Key Principles

The website includes (or will include) \*\*two fully separate client portals\*\*:

1\. \*\*Eco-Oil client portal\*\* — for Eco-Oil's clients only.

2\. \*\*Eco-Depot client portal\*\* — for Eco-Depot's clients only.



\### Principles to follow

\- The two portals are \*\*completely separate\*\* — separate login pages, separate client bases, separate content and permissions.

\- Clients of one company cannot access the other portal.

\- Access is \*\*password-protected\*\* (exact authentication method to be clarified with Limor when relevant — do not assume or invent one).

\- Both portals will eventually connect to the `eco\_oil\_platform` management system (Flask + SQLite).



\### Working on portal-related tasks

\- Before making changes related to the portals, \*\*check the current state of the code\*\* and tell Limor what already exists, so she knows where things stand.

\- Do not assume a feature is built or not built — verify first.

\- When in doubt about portal-related details — \*\*ask Limor, do not assume.\*\*



\## Deployment (Going Live) — CRITICAL

\- Limor has \*\*zero experience\*\* with website deployment. She does not know what hosting is, what gets uploaded where, or which tools are involved. She has expressed anxiety about this stage.

\- When the time comes to put the website online:

&#x20; - Explain \*\*every single step\*\* in the simplest possible language.

&#x20; - Explain \*\*what\*\* each tool/service is and \*\*why\*\* it is needed, before asking her to do anything with it.

&#x20; - Give \*\*one action at a time\*\* and wait for confirmation.

&#x20; - Never assume she knows terms like "domain," "hosting," "FTP," "DNS," "repository," etc. — define each one when it first appears.

&#x20; - Pause after every step and let her confirm it worked before moving on.



\## Certificates (Cleaning & Release) — Built April 2026

Two A4-format certificate templates were built as standalone HTML files. They are designed to work in two modes: \*\*manual fill\*\* (via browser) now, and \*\*system-generated\*\* (from the management system) later.



\### Files

\- `cleaning_certificate.html` — \*\*English\*\*, EFTCO-inspired design.

\- `release_certificate.html` — \*\*Hebrew (RTL)\*\*, same design language.

\- Shared assets in `images/cert/`: `eco-oil-logo.png`, `stamp.png`, `signature-yoav.png`, `footer-contact.png`.



\### Design language (shared)

\- Decorative diagonal-stripe side borders (mimicking EFTCO's certificates).

\- Black header bar with title + certificate number prominently displayed.

\- Numbered fields in a bordered table.

\- "Eco Oil" diagonal watermark.

\- Footer with contact info \*\*inside\*\* the same black frame (not outside).

\- Bottom-right: CEO signature (image of Yoav Toueg's signature) + Company stamp, each with a horizontal divider above and a caption below ("CEO Signature – Eco Oil" / "Company Stamp" — or Hebrew equivalents).

\- QR code top-right (top-left in RTL).



\### Key decisions

\- \*\*Cleaning certificate\*\* mimics the EFTCO international format because Eco Oil plans to apply for EFTCO membership later. Visual similarity now means smooth transition when membership is approved.

\- \*\*Compliancy score / stars block from EFTCO is intentionally removed\*\* — only relevant once Eco Oil is an EFTCO member. Add it back at that point.

\- \*\*Cleaning codes\*\* use the format `F02 - Hot water` (EFTCO code + description). Codes used: F01, F02, F08, E95, F60, F61, F95, T45 — these should be verified against the official EFTCO code list before going live.

\- \*\*Certificate numbering:\*\* `ECO-YYYY-NNNN` for cleaning, `ECO-REL-YYYY-NNNN` for release. Tank/equipment number is shown separately (Equipment N° field on cleaning, prominent block on release).

\- \*\*QR code\*\* currently links to `https://www.eco-oil.co.il` (static). When the management system is live, switch to per-certificate URLs like `https://www.eco-oil.co.il/cert/<cert_number>` (cleaning) or `/release/<cert_number>`. The placeholder pattern is already in the JS comment in each file.

\- \*\*Two different addresses are correct, do not "fix" them:\*\*

&#x20;  - Cleaning certificate: \*\*27 Haashlag St., Haifa\*\* (cleaning facility location).

&#x20;  - Release certificate: \*\*1 Hamesila St., Nesher\*\* (storage yard location).

\- \*\*Phone in section 1\*\* on release cert intentionally matches the footer: `+972-54-323-2617`.

\- \*\*Cleaning cert language: English\*\* (international transport context). \*\*Release cert language: Hebrew\*\* (handed to Israeli truck drivers).



\### Cleaning certificate fields (13 numbered)

1\. Cleaning station, 2. Customer ref. number, 3. Internal ref., 4. Customer, 5. Identification numbers (Equipment type + N°), 6. Nature of product, 7. Previous load (Comp / UN N° / Name), 8. Cleaning procedures (EFTCO codes), 9. Additional services (Transportation, Polish, Repair, Test, Maintenance, Photo set, Vacuum test, Storage), 10. Comments, 11. Date Time in / End of Cleaning, 12. Cleaning station signature + stamp.



Note: original EFTCO sections 7 (Next load) and 12 (Cleaner name) and 16 (Compliancy score) were intentionally removed at the CEO's request. Numbering is renumbered 1–12 (sequential, no gaps).



\### Release certificate fields (Hebrew, 6 numbered)

1\. תחנת שחרור (release station), 2. חברת ההובלה (transport company), 3. צפי יציאה (expected departure), 4. באחסון מתאריך (in storage from date), 5. יעד (destination), 6. הערות (comments). Then section 7 = signature + stamp (matching cleaning cert's pattern).



\### Manual fill mode

Both files include a top toolbar (`.no-print`) with two buttons: "Print / Save as PDF" and "Toggle edit". When edit mode is on, every value field becomes `contenteditable` and checkboxes toggle ✓ on click. The toolbar is hidden in print.



\### When integrating with the management system

Each fillable field has a `data-field="..."` attribute (e.g. `data-field="customer_ref"`, `data-field="tank_number"`). The system can target these by selector and replace the inner text. Checkbox states are toggled by setting the `.chk` element's text content to `'✓'` or `''`.



\### Image preparation note

The signature and stamp PNGs originally had large transparent margins, which made them appear tiny inside the layout. They were auto-cropped to their content bounding box (with 15px padding) using PIL/numpy. If new versions of these images are added, they should be cropped the same way for consistent visual proportion.



\## Golden Rules

1\. One step at a time. Wait for confirmation.

2\. No code in responses unless asked.

3\. Explain like talking to a 10-year-old.

4\. Never invent features, options, or file locations.

5\. Always consider the future migration to the CEO's computer.

6\. For deployment — assume zero prior knowledge and guide gently.

