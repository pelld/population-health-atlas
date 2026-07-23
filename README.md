# Population Health Atlas

An exploratory static web dashboard showing how recorded long-term-condition prevalence may cluster geographically across England.

## Important

The current figures are fabricated demonstration data. They are included to test the design and interactions while the reproducible QOF/ONS/IMD data pipeline is developed.

Practice-level geographic association is not patient-level multimorbidity. The site identifies conditions recorded at high rates in the same places; it cannot show that the same people have both conditions.

## GitHub Pages

The site uses plain HTML, CSS and JavaScript and requires no build step, server or API key.

1. Open **Settings → Pages**.
2. Under **Build and deployment**, select **Deploy from a branch**.
3. Select `main` and `/ (root)`, then save.
4. The published site will be available at `https://pelld.github.io/population-health-atlas/`.

## Planned data pipeline

The eventual Python pipeline will:

1. download the latest NHS QOF practice-level prevalence data;
2. join practices to geography and deprivation;
3. calculate condition prevalence and deprivation-adjusted residuals;
4. calculate geographic condition-pair correlations;
5. export static CSV/GeoJSON files consumed by this site.
