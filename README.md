# Big Ten Survivor Football 2026

A mobile-first survivor pool application for Big Ten college football, letting players sign up, submit weekly picks, and track live standings — fully self-service, with every eligibility rule and deadline enforced server-side rather than trusted to the browser.

The project demonstrates an end-to-end application built on **Supabase (PostgreSQL, Auth, Row-Level Security)** for identity and business logic, **GitHub Actions** for automated score ingestion, and a **vanilla JavaScript** front end deployed on **GitHub Pages**.

The application provides participants with self-serve account creation, a dynamically filtered weekly pick menu, live standings, automatic elimination tracking, and a commissioner administration panel.

**Live Demo:** <https://pollackelliott.github.io/big-ten-survivor-football-2026>

---

## Technologies

**Backend & Data**
- Supabase (PostgreSQL)
- Supabase Auth
- Row-Level Security (RLS)
- PL/pgSQL (stored procedures)

**Automation**
- GitHub Actions (scheduled workflows)
- Python

**Application Development**
- JavaScript
- HTML
- CSS

**Deployment**
- GitHub Pages

---

## Overview

Big Ten Survivor is a season-long "survivor" pick 'em application: each week, players pick one Big Ten team to win outright, and a loss means elimination. Player accounts, pick submission, schedule and score ingestion, and every eligibility rule are enforced by the database itself, not by client-side logic that could be bypassed.

This is a companion project to the SEC Survivor pool, built on the same underlying rules engine and architecture — separated into its own Supabase project and repository so the two leagues never share data, credentials, or risk of one affecting the other.

---

## Architecture

```
ESPN Scoreboard Data
        │
        ▼
GitHub Actions (scheduled scraper)
        │
        ▼
Supabase (PostgreSQL)
        │
        ▼
Server-Side Business Logic (PL/pgSQL)
        │
        ▼
JavaScript Front End
        │
        ▼
GitHub Pages Deployment
```

---

## Features

### Player Accounts

- Self-serve email/password signup (Supabase Auth)
- Password reset via email
- Commissioner administration mode

### Pick Management

- Dynamically filtered weekly pick menu, unique to each player's own history
- Enforced pick limits: one team per season, capped non-conference and G5 selections
- FBS-only opponent eligibility
- Server-enforced lock times and a Saturday-morning reveal window

### Live Standings

- Full-season picks grid
- Player-by-player pick history and elimination tracking
- Weekly schedule and score view

---

## Engineering Concepts Demonstrated

- Relational schema design
- Row-Level Security & server-side authorization
- Stored procedures for business-rule enforcement
- Real authentication & session management
- Scheduled data pipelines (GitHub Actions)
- Idempotent upserts
- Client/server rule mirroring — UX filtering vs. actual enforcement
- Automated, unattended data ingestion

---

## Future Enhancements

- Expanded historical season archives
- Additional standings visualizations
- Notifications for approaching pick deadlines
