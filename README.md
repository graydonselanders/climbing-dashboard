# Climbing Training Dashboard

I wanted a personal sports-science dashboard for tracking and visualising my training over time, so here it is.

**[Open Dashboard](https://climbing-dashboard.streamlit.app/)** &nbsp;|&nbsp; **[Log a Session](https://docs.google.com/forms/d/e/1FAIpQLScLSuWsQKgwPPPCpGRrLRI_Vn3U32Cev2sRsdWfdPyaAi2lpA/viewform?usp=dialog)**

---

## What it does

Sessions are logged via a Google Form and stored in a linked Google Sheet. The dashboard reads that sheet and presents two tabs:

**Fatigue & Load**
- Acute:Chronic Workload Ratio (ACWR) — a 7-day rolling load divided by a 28-day rolling average, shows daily training readiness
- Upcoming sessions pulled from Google Calendar
- Recent session log with workload units (Duration × RPE)

**Strength & Board Climbing**
- Finger strength progression by grip type and hangboard protocol, normalised to total load (bodyweight + added weight)
- Pull-up 1RM progression over time
- Relative strength benchmarks compared to targets
- Moonboard session CSI (Climbing Strength Index) and 14-day trend

## Stack

- **Python / Streamlit** — app framework
- **Google Sheets** (CSV export) — data source
- **Google Calendar** (iCal feed) — upcoming session scheduling
- **Plotly** — interactive charts
