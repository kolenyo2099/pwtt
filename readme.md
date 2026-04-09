# FlightWatch

FlightWatch is a non-technical wizard around the upstream PWTT workflow. It wraps Google Earth Engine authentication, AOI drawing, PWTT execution, results review, and KML export in a local FastAPI + SvelteKit app.

## Stack

- Backend: FastAPI, SQLite, APScheduler, Earth Engine, PWTT
- Frontend: SvelteKit in SPA mode, Leaflet, Leaflet Draw
- Data: plain SQL migrations with a local SQLite database

## Quickstart

```bash
cp .env.example .env
./setup.sh
./run.sh
```

The backend defaults to `http://127.0.0.1:8000` and the frontend defaults to `http://127.0.0.1:5173`.

## Earth Engine Login

This app now follows the same pattern as `changewatch`: it uses the normal
local Earth Engine user credentials stored on your machine instead of asking
for a service-account JSON file. You can either launch the browser login from
the first step in the app or run `earthengine authenticate` manually inside the
virtual environment.
