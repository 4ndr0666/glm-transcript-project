# Youtube Transcripts

> This repository houses several methods of aggregating the transcript to a YouTube video across a variety of languages.

1. Ingest all of the info and craft a singular userscript solution leveraging on the best-in-class engineering methodologies across all data points found in the repo.
   - **Data Extraction & API Interception:** Inspect and hook native YouTube client payloads (including `ytInitialPlayerResponse` and the internal `get_transcript` endpoint) to capture raw timed-text XML/JSON tracks directly from the player instance.
   - **Multilingual Support & Fallbacks:** Systematically parse available auto-generated captions, manually uploaded tracks, and translated alternatives across all supported ISO language codes, implementing fallback selection logic when preferred tracks are missing.
   - **DOM Integration & Lifecycle Management:** Mount an unobtrusive, accessible user interface within YouTube's modern Single Page Application (SPA) architecture, binding state handlers to player navigation events (`yt-navigate-finish`) to ensure persistent functionality across dynamic route changes.
   - **Sanitization & Formatting Pipeline:** Clean raw subtitle fragments by stripping internal XML/HTML tags, resolving timestamp drift, decoding HTML entities, and formatting the output into plain text, Markdown, VTT, or SRT schemas.
   - **Portability & Cross-Engine Compatibility:** Ensure standard userscript headers (`@match`, `@grant`, `@run-at`) maintain functional parity across Tampermonkey, Violentmonkey, and Greasemonkey engines without external network dependencies.
