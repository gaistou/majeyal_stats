This project is a streamlit dashboard that presents statistics about the game Tales of Majeyal.

The structure is :
- cache/ folder contains json data scraped from official majeyal website
  - characters.json : all characters data
  - results_<ClassName>.json : per-class data with keys df, prodigies, artefacts, details
  - characters_preview.json : preview of characters.json (2 entries per list) to inspect the schema
  - results_preview.json : preview of a results_<ClassName>.json file (2 entries per list) to inspect the schema
- app.py contains the core of the app.
- scraper.py contains tools to scrape data.
- pages/admin.py contains the interface to scrape data, that is open only to administrator on a local environment.