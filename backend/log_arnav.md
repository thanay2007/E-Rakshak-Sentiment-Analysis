# SENTINEL Backend Improvements (Law Enforcement Context)
Date: 2026-07-18

As requested, rather than adding a generic user login system, I have implemented powerful domain-specific intelligence features to help police and analysts monitor live threats more effectively.

## 1. Immutable Audit Logging (Chain of Custody)
- **Files Touched:** `app/models/models.py`, `app/services/audit.py`, `app/routers/alerts.py`, `app/routers/reports.py`, `app/routers/investigate.py`
- **What Changed:** Created an `AuditLog` model and a centralized logging service.
- **Why:** Every time an officer escalates an alert, generates a report, or runs an OSINT lookup on a handle, it is logged immutably in the database. This ensures strict chain-of-custody compliance for post-incident reviews or legal discovery.

## 2. Emerging Threat Auto-Discovery
- **Files Touched:** `app/services/trend_service.py`
- **What Changed:** Modified the trending engine to automatically discover "spiking" keywords and hashtags that are associated with a threat label.
- **Why:** Instead of officers having to manually predict and add hashtags to the watchlist, the system proactively detects emerging hostile hashtags and automatically pushes them to a "Suggested Watchlist" queue.

## 3. Automated "Intelligence Briefings" (LLM Summaries)
- **Files Touched:** `app/services/groq_verifier.py`, `app/routers/reports.py`
- **What Changed:** Added a `summarize_briefing` function powered by Groq, exposed via `/reports/briefing`.
- **Why:** Analysts can hit a button to generate an instant, 1-paragraph tactical briefing summarizing the last N hours of intelligence data for commanders.

## 4. Audio & Video Transcription Interception
- **Files Touched:** `app/osint/audio_analysis.py`, `app/routers/investigate.py`
- **What Changed:** Integrated the local `openai-whisper` AI model to transcribe audio and video files. 
- **Why:** Officers can upload intercepted audio files or social media videos straight to the OSINT toolkit to instantly transcribe spoken words into readable text.

## 5. WhatsApp Alert Routing
- **Files Touched:** `app/services/notifications.py`, `app/config.py`
- **What Changed:** Replaced the mock alerting system with a fully functional Twilio WhatsApp integration.
- **Why:** Critical threshold alerts (e.g., mob mobilization) are instantly pushed to the duty officer's phone via WhatsApp with a summary and location, meaning they don't have to be actively staring at the dashboard.

## 6. Street Slang & Dialect Preprocessor
- **Files Touched:** `app/ml/slang.py`, `app/ml/pipeline.py`
- **What Changed:** Added a fast preprocessor that translates local dialect and slang (e.g., "khatam kar") into standard terms before classification.
- **Why:** Social media chatter during riots heavily relies on local vernacular. This preprocessor ensures the NLP engine correctly detects violent intent even if it's veiled in local street slang.

## 7. Facial Recognition Forensics & Frontend UI
- **Files Touched:** `app/osint/image_analysis.py`, `frontend/src/services/api.ts`, `frontend/src/components/investigate/ImageTool.tsx`
- **What Changed:** Embedded the `face_recognition` pipeline into the Image OSINT toolkit. Counted faces, generated bounding box coordinates, hotfixed a bug in the AI model (`pkg_resources` missing in Python 3.13), and updated the React Frontend UI to draw cyan boxes over suspects' faces on-screen.
- **Why:** Uploading an image of a crowd or a riot now visually isolates the individuals, setting the groundwork for automatic suspect-database cross-referencing.

## 8. Dedicated Bot/Troll Network Classifier
- **Files Touched:** `app/ml/bot_classifier.py`, `app/services/ingestion.py`
- **What Changed:** Added a standalone `RandomForestClassifier` that trains on metadata heuristics (account age, follower ratio, post volume).
- **Why:** Precisely tags suspicious incoming data as `is_bot` during the initial ingestion phase, helping analysts separate organic public anger from coordinated troll farm campaigns.

## 9. Cleanup & Maintenance
- **What Changed:** Completely removed the Telegram scraper (`app/crawlers/telegram.py`, `app/crawlers/registry.py`) as another teammate took ownership of that component, keeping the codebase clean and free of conflicts.

## 10. Frontend Aesthetic Overhaul (E-RAKSHAK Branding)
- **Files Touched:** `frontend/src/index.css`, `frontend/tailwind.config.js`, `frontend/index.html`, `frontend/src/components/Sidebar.tsx`, `frontend/src/components/TopBar.tsx`, `frontend/src/pages/Landing.tsx`, `frontend/package.json`
- **What Changed:** Rebranded the entire application from "SENTINEL" to "E-RAKSHAK". Shifted the color palette from generic cyan to an authoritative Police Amber/Gold (`#F59E0B`) accent with a deep Navy Blue (`#04080F`) base background. Replaced the generic app logo and favicon with a dynamic SVG of the Ashoka Chakra (24 spokes). Updated terminology ("Analyst" -> "Inspector", "Clearance L3" -> "Cyber Cell HQ").
- **Why:** To make the application visually strike the judges as an official, premium Indian law enforcement cyber-command dashboard tailored perfectly for the hackathon.

## 11. Frontend UI Bug Fixes (Light/Dark Mode Support)
- **Files Touched:** `frontend/src/index.css`, `frontend/tailwind.config.js`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/StatTile.tsx`, `frontend/src/pages/Landing.tsx`, `frontend/src/pages/Reports.tsx`
- **What Changed:** Fixed a visibility issue where Recharts tooltips (e.g. Threat Levels Pie Chart) rendered black text on dark backgrounds by manually injecting payload `fill` colors and overriding inline styles using custom CSS variables. Fixed a bug where KPI numbers were invisible in Light Mode by dynamically aliasing `text-slate-100` to `text-slate-200` and propagating the changes globally.
- **Why:** Ensures that the command center dashboard remains perfectly readable and fully accessible whether the duty officer is viewing it in dark mode at night or light mode during the day.

## 12. Frontend UI Select Dropdown Overlap Fix
- **Files Touched:** `frontend/src/components/TopBar.tsx`, `frontend/src/pages/Alerts.tsx`, `frontend/src/pages/Watchlist.tsx`, `frontend/src/pages/ThreatFeed.tsx`, `frontend/src/pages/Reports.tsx`
- **What Changed:** Adjusted right padding (`pr-8`) on all `<select>` tags across the application.
- **Why:** To prevent text from overlapping with the native drop-down arrows, ensuring a cleaner and fully legible interface.

## 13. Frontend Architecture Audit & Roadmap
- **Files Touched:** N/A (Audit Phase)
- **What Changed:** Conducted a comprehensive audit of the React frontend and generated a roadmap for scalability (`frontend_improvement_analysis.md`).
- **Why:** To outline next steps for making the dashboard production-ready. Identified key areas for improvement including adopting TanStack Query for state management, implementing React.lazy() for code-splitting, adding virtualization (react-virtuoso) for live feeds, setting up Vitest/Playwright for testing, and introducing Storybook for UI component documentation.

---
Date: 2026-07-27

## 14. Synced with `main` & Dependency Environment Hardening
- **Files Touched:** `backend/requirements.txt`
- **What Changed:** Fast-forwarded the `balodi` branch onto `origin/main`, pulling in the teammate-owned Telegram crawler (MTProto + keyless preview), the LLM fallback chain, watchlist packs, the ops console and the emerging-threats service. Installed the one genuinely missing dependency (`telethon`). Pinned two entries that were silently absent from the requirements file: `face_recognition_models` (its weights are not published on PyPI and must come from git) and `setuptools>=77.0.3,<81`.
- **Why:** The `setuptools` upper bound is the load-bearing part. Version 81 deprecated `pkg_resources` and 83 removed it outright, which is what `face_recognition_models` imports — so a clean install on a fresh machine silently produced a broken face pipeline. The lower bound is Torch's own floor, so the pin cannot conflict with the ML stack. This makes the "hotfix" noted in section 7 reproducible instead of machine-local.

## 15. Face Recognition Crash Fix (`SystemExit` Escaping Its Handler)
- **Files Touched:** `app/osint/image_analysis.py`
- **What Changed:** Widened the guard around the `face_recognition` import from `except ImportError` to `except (ImportError, SystemExit)`.
- **Why:** When its model weights are missing, `face_recognition` calls `quit()` at import time. That raises `SystemExit`, which inherits from `BaseException` — so it slipped past *both* the `except ImportError` and the broader `except Exception` beneath it. Instead of degrading to `faces_detected: 0` as the fallback intended, any image uploaded to the OSINT toolkit would tear down the worker process. Reproduced by forcing the import to raise `SystemExit`; the analysis now completes and returns a zero face count.

## 16. Frontend Build & Test Infrastructure Fixes
- **Files Touched:** `frontend/vite.config.ts`, `frontend/src/components/StatTile.test.tsx`
- **What Changed:** Switched `defineConfig` to import from `vitest/config` instead of `vite`, and made the `StatTile` test await its assertion via `findByText`.
- **Why:** Vitest 4 removed the `/// <reference types="vitest" />` mechanism, so the `test` block in the Vite config no longer typechecked (`TS2769`) — and since the build script is `tsc -b && vite build`, that error broke `npm run build` outright. Separately, the `StatTile` test asserted on the final figure synchronously while `useCountUp` animates the value from 0 over 1.1s via GSAP, so it raced the animation and always read `0`. The component was correct; the assertion needed to wait.
