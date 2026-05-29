import re
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

CSV_URL = "https://docs.google.com/spreadsheets/d/1weMRvvNVNgFDKypt-S-hl5YgbMy00dWsObGR5IgDrMw/gviz/tq?tqx=out:csv"

st.set_page_config(page_title="Climbing Training Dashboard", layout="centered")

INSIDE_LEGEND = dict(
    yanchor="top",
    y=0.99,
    xanchor="left",
    x=0.01,
    bgcolor="rgba(255,255,255,0.7)",
)


def applyMobileChartLayout(figure, title, yAxisTitle, **layoutOptions):
    """Apply compact, mobile-first Plotly defaults."""
    figure.update_layout(
        title=title,
        xaxis_title=None,
        yaxis_title=yAxisTitle,
        margin=dict(l=20, r=20, t=50, b=20),
        legend=INSIDE_LEGEND,
        **layoutOptions,
    )
    return figure


def parseVGrade(gradeValue):
    """Extract numeric V grade value from strings like 'V6' or just '6'."""
    if pd.isna(gradeValue):
        return 0.0
    gradeText = str(gradeValue).strip().upper()
    if gradeText == "":
        return 0.0
    
    # try to find 'V' followed by numbers (e.g., 'V6')
    match = re.search(r"V\s*(\d+)", gradeText)
    if match:
        return float(match.group(1))
        
    # if not, just extract the first number found (e.g., '6')
    match_num = re.search(r"(\d+)", gradeText)
    return float(match_num.group(1)) if match_num else 0.0

def triesMultiplier(triesValue):
    """Efficiency multiplier for sent attempts."""
    try:
        triesCount = int(float(triesValue))
    except (TypeError, ValueError):
        triesCount = 0

    if triesCount <= 1:
        return 1.0
    if triesCount == 2:
        return 0.9
    if 3 <= triesCount <= 5:
        return 0.8
    return 0.65

def computeClimbCSI(gradeValue, triesValue, sentValue):
    """Compute CSI for a single climb entry."""
    gradeScore = parseVGrade(gradeValue)
    if gradeScore <= 0:
        return 0.0

    sentText = str(sentValue).strip().lower() if not pd.isna(sentValue) else ""

    if sentText in ["yes", "Yes", "y", "true"]:
        return gradeScore * triesMultiplier(triesValue)
    return gradeScore * 0.25


def resolveSessionLabel(row):
    """Return Sub-Category Focus for General Session input rows, else Session Type."""
    session_type = str(row.get("Session Type", "")).strip()
    if session_type == "General Session input" or "Bouldering / Skill Work (e.g. comp sim, slab training)":
        sub_cat = str(row.get("Sub-Category Focus", "")).strip()
        if sub_cat:
            return sub_cat
    return session_type


@st.cache_data(ttl=300)
def loadData():
    dataFrame = pd.read_csv(CSV_URL)

    column_mapping = {
        "Protocol": "Hangboard Protocol",
        "Max Added Weight / Force (lbs)": "Hangboard Max Weight",
    }

    # translate names to variables
    for i in range(1, 11):
        column_mapping[f"Climb {i} Grade"] = f"MB_V{i}_Grade"
        column_mapping[f"Climb {i} Tries"] = f"MB_V{i}_Tries"
        column_mapping[f"Climb {i} Top (Y/N)"] = f"MB_V{i}_Sent"

    dataFrame = dataFrame.rename(columns=column_mapping)

    # standardize date formatting
    if "Date" in dataFrame.columns:
        dataFrame["Date"] = pd.to_datetime(dataFrame["Date"], errors="coerce")

    objectColumns = dataFrame.select_dtypes(include=["object"]).columns
    for columnName in objectColumns:
        dataFrame[columnName] = dataFrame[columnName].astype(str).str.rstrip()
        dataFrame[columnName] = dataFrame[columnName].replace("nan", "")

    dataFrame["Session Label"] = dataFrame.apply(resolveSessionLabel, axis=1)

    return dataFrame


def computeAthleteAcwr(athleteDataFrame):
    """Rest-day aware ACWR timeline for a single athlete."""
    if athleteDataFrame.empty:
        return pd.DataFrame(columns=["Date", "Daily Workload", "Acute Workload", "Chronic Workload", "ACWR"])

    athleteDataFrame = athleteDataFrame.copy()
    athleteDataFrame["Date"] = pd.to_datetime(athleteDataFrame["Date"]).dt.date

    athleteDataFrame["Duration (mins)"] = pd.to_numeric(athleteDataFrame.get("Duration (mins)"), errors="coerce").fillna(0)
    athleteDataFrame["Session RPE"] = pd.to_numeric(athleteDataFrame.get("Session RPE"), errors="coerce").fillna(0)
    athleteDataFrame["Daily Workload"] = athleteDataFrame["Duration (mins)"] * athleteDataFrame["Session RPE"]

    dailyWorkload = athleteDataFrame.groupby("Date", as_index=False)["Daily Workload"].sum()

    startDate = dailyWorkload["Date"].min()
    endDate = date.today()
    fullDateRange = pd.date_range(start=startDate, end=endDate, freq="D")

    continuousDataFrame = pd.DataFrame({"Date": fullDateRange.date})
    continuousDataFrame = continuousDataFrame.merge(dailyWorkload, on="Date", how="left")
    continuousDataFrame["Daily Workload"] = continuousDataFrame["Daily Workload"].fillna(0)

    continuousDataFrame["Acute Workload"] = continuousDataFrame["Daily Workload"].rolling(window=7, min_periods=1).sum()
    continuousDataFrame["Chronic Workload"] = (
        continuousDataFrame["Acute Workload"].rolling(window=28, min_periods=1).mean()
    )

    chronic = continuousDataFrame["Chronic Workload"].replace(0, pd.NA)
    continuousDataFrame["ACWR"] = continuousDataFrame["Acute Workload"] / chronic
    continuousDataFrame["ACWR"] = pd.to_numeric(continuousDataFrame["ACWR"], errors="coerce")

    return continuousDataFrame


def extractMoonboardSets(columns):
    """Find MB_Vx_Grade/Tries/Sent triplets dynamically."""
    setIndexes = set()
    pattern = re.compile(r"^MB_V(\d+)_Grade$")
    for columnName in columns:
        match = pattern.match(columnName)
        if match:
            setIndexes.add(int(match.group(1)))
    return sorted(setIndexes)



def prepareFingerStrengthData(sourceDataFrame):
    """Return hangboard rows with total load normalized to a 20mm-edge comparison basis."""
    requiredColumns = ["Date", "Bodyweight", "Hangboard Protocol", "Grip Type", "Hangboard Max Weight"]
    if sourceDataFrame.empty or any(columnName not in sourceDataFrame.columns for columnName in requiredColumns):
        return pd.DataFrame(columns=["Date", "Bodyweight", "Hangboard Protocol", "Grip Type", "Hangboard Total Load"])

    fingerData = sourceDataFrame[
        sourceDataFrame["Session Type"].astype(str).str.strip().eq("Hangboard / Finger Strength")
    ].copy()
    if fingerData.empty:
        return pd.DataFrame(columns=["Date", "Bodyweight", "Hangboard Protocol", "Grip Type", "Hangboard Total Load"])

    fingerData["Bodyweight"] = pd.to_numeric(fingerData["Bodyweight"], errors="coerce")
    fingerData["Hangboard Max Weight"] = pd.to_numeric(fingerData["Hangboard Max Weight"], errors="coerce")
    fingerData["Hangboard Protocol"] = fingerData["Hangboard Protocol"].fillna("Unknown").replace("", "Unknown")
    fingerData["Grip Type"] = fingerData["Grip Type"].fillna("Unknown").replace("", "Unknown")

    isDensityHang = fingerData["Hangboard Protocol"].astype(str).str.strip().str.lower().eq("density hangs")
    fingerData["Hangboard Total Load"] = fingerData["Bodyweight"] + fingerData["Hangboard Max Weight"]
    fingerData.loc[isDensityHang, "Hangboard Total Load"] = fingerData.loc[isDensityHang, "Bodyweight"]

    return fingerData.dropna(subset=["Date", "Bodyweight", "Hangboard Total Load"])


def preparePullupData(sourceDataFrame):
    """Return rows with total pull-up 1RM load."""
    requiredColumns = ["Date", "Bodyweight", "Pull-up 1RM Added Weight"]
    if sourceDataFrame.empty or any(columnName not in sourceDataFrame.columns for columnName in requiredColumns):
        return pd.DataFrame(columns=["Date", "Bodyweight", "Pull-up 1RM Added Weight", "Pull-up Total 1RM"])

    pullupData = sourceDataFrame.copy()
    pullupData["Bodyweight"] = pd.to_numeric(pullupData["Bodyweight"], errors="coerce")
    pullupData["Pull-up 1RM Added Weight"] = pd.to_numeric(pullupData["Pull-up 1RM Added Weight"], errors="coerce")
    pullupData["Pull-up Total 1RM"] = pullupData["Bodyweight"] + pullupData["Pull-up 1RM Added Weight"]
    return pullupData.dropna(subset=["Date", "Bodyweight", "Pull-up Total 1RM"])


def buildBenchmarkData(sourceDataFrame):
    """Compare all-time relative strength peaks against national-level targets."""
    allTimeFingerData = prepareFingerStrengthData(sourceDataFrame)
    allTimePullupData = preparePullupData(sourceDataFrame)

    benchmarkRows = []
    halfCrimpData = allTimeFingerData[
        allTimeFingerData["Grip Type"].astype(str).str.strip().str.lower().eq("half crimp")
    ].copy()
    if not halfCrimpData.empty:
        halfCrimpData["Relative Strength"] = halfCrimpData["Hangboard Total Load"] / halfCrimpData["Bodyweight"]
        bestHalfCrimp = halfCrimpData.loc[halfCrimpData["Relative Strength"].idxmax()]
        benchmarkRows.append(
            {
                "Metric": "20mm Half Crimp",
                "Current % Bodyweight": bestHalfCrimp["Relative Strength"] * 100,
                "National Target % Bodyweight": 140,
            }
        )

    if not allTimePullupData.empty:
        allTimePullupData["Relative Strength"] = allTimePullupData["Pull-up Total 1RM"] / allTimePullupData["Bodyweight"]
        bestPullup = allTimePullupData.loc[allTimePullupData["Relative Strength"].idxmax()]
        benchmarkRows.append(
            {
                "Metric": "Pull-up 1RM",
                "Current % Bodyweight": bestPullup["Relative Strength"] * 100,
                "National Target % Bodyweight": 155,
            }
        )

    return pd.DataFrame(benchmarkRows)

def buildSessionCSI(boardDataFrame):
    if boardDataFrame.empty:
        return pd.DataFrame(columns=["Date", "Session CSI", "Peak Grade Sent", "Best Efficiency Score"])

    boardDataFrame = boardDataFrame.copy()
    boardDataFrame["Date"] = pd.to_datetime(boardDataFrame["Date"]).dt.date
    setIndexes = extractMoonboardSets(boardDataFrame.columns)

    sessionRows = []
    for _, row in boardDataFrame.iterrows():
        sessionCsi = 0.0
        peakGradeSent = 0.0
        bestEfficiencyScore = 0.0

        for setIndex in setIndexes:
            gradeColumn = f"MB_V{setIndex}_Grade"
            triesColumn = f"MB_V{setIndex}_Tries"
            sentColumn = f"MB_V{setIndex}_Sent"

            climbScore = computeClimbCSI(row.get(gradeColumn), row.get(triesColumn), row.get(sentColumn))
            sessionCsi += climbScore

            gradeValue = parseVGrade(row.get(gradeColumn))
            sentText = str(row.get(sentColumn)).strip().lower() if not pd.isna(row.get(sentColumn)) else ""
            if sentText in ["yes", "Yes", "y", "true"]:
                peakGradeSent = max(peakGradeSent, gradeValue)
                if gradeValue > 0:
                    bestEfficiencyScore = max(bestEfficiencyScore, climbScore / gradeValue)

        sessionRows.append(
            {
                "Date": row["Date"],
                "Session CSI": sessionCsi,
                "Peak Grade Sent": peakGradeSent,
                "Best Efficiency Score": bestEfficiencyScore,
            }
        )

    sessionDataFrame = pd.DataFrame(sessionRows)
    sessionDataFrame = sessionDataFrame.groupby("Date", as_index=False).agg(
        {
            "Session CSI": "sum",
            "Peak Grade Sent": "max",
            "Best Efficiency Score": "max",
        }
    )

    sessionDataFrame["Rolling 14-Day CSI"] = sessionDataFrame["Session CSI"].rolling(window=14, min_periods=1).mean()
    return sessionDataFrame


def main():
    st.title("Climbing Sports Science Dashboard")

    dataFrame = loadData()

    if dataFrame.empty:
        st.info("No workouts have been logged yet.")
        st.stop()

    requiredColumns = ["Date", "Athlete Name", "Session Type", "Duration (mins)", "Session RPE"]
    missingColumns = [col for col in requiredColumns if col not in dataFrame.columns]
    if missingColumns:
        st.error(f"Missing required columns: {', '.join(missingColumns)}")
        st.stop()

    dataFrame = dataFrame.dropna(subset=["Date"]).copy()
    if dataFrame.empty:
        st.info("No valid workout dates are available yet.")
        st.stop()

    dataFrame["Date"] = pd.to_datetime(dataFrame["Date"]).dt.date

    athleteOptions = sorted([name for name in dataFrame["Athlete Name"].dropna().unique() if str(name).strip() != ""])
    selectedAthletes = st.multiselect("Athlete Name", athleteOptions, default=athleteOptions)

    minDate = dataFrame["Date"].min()
    maxDate = dataFrame["Date"].max()

    preset_options = ["1 Week", "2 Weeks", "1 Month (4 Weeks)", "1 Year", "All Time", "Custom"]
    
    # default to 1 month
    selected_preset = st.selectbox("Timeframe", preset_options, index=2) 

    if selected_preset == "1 Week":
        startDate = maxDate - timedelta(days=7)
        endDate = maxDate
    elif selected_preset == "2 Weeks":
        startDate = maxDate - timedelta(days=14)
        endDate = maxDate
    elif selected_preset == "1 Month (4 Weeks)":
        startDate = maxDate - timedelta(days=28)
        endDate = maxDate
    elif selected_preset == "1 Year":
        startDate = maxDate - timedelta(days=365)
        endDate = maxDate
    elif selected_preset == "All Time":
        startDate = minDate
        endDate = maxDate
    else:
        selectedDateRange = st.date_input(
            "Custom Date Range", 
            value=(minDate, maxDate), 
            min_value=minDate, 
            max_value=maxDate
        )
        if isinstance(selectedDateRange, tuple) and len(selectedDateRange) == 2:
            startDate, endDate = selectedDateRange
        else:
            startDate, endDate = minDate, maxDate

    startDate = max(startDate, minDate)

    selectedAthleteData = dataFrame.copy()
    if selectedAthletes:
        selectedAthleteData = selectedAthleteData[selectedAthleteData["Athlete Name"].isin(selectedAthletes)]

    filteredData = selectedAthleteData[(selectedAthleteData["Date"] >= startDate) & (selectedAthleteData["Date"] <= endDate)]

    if filteredData.empty:
        st.info("No workouts match the current filters.")
        st.stop()

    tabs = st.tabs(["Fatigue & Load", "Strength & Board Climbing"])

    with tabs[0]:
        st.subheader("Rest-Day Aware ACWR")

        acwrFigure = go.Figure()
        acwrSummaries = []
        for athleteName in sorted(filteredData["Athlete Name"].dropna().unique()):
            athleteSlice = filteredData[filteredData["Athlete Name"] == athleteName]
            acwrData = computeAthleteAcwr(athleteSlice)

            acwrFigure.add_trace(
                go.Scatter(
                    x=acwrData["Date"],
                    y=acwrData["ACWR"],
                    mode="lines",
                    name=str(athleteName),
                )
            )

            latestAcwr = acwrData["ACWR"].dropna()
            acwrSummaries.append((athleteName, latestAcwr.iloc[-1] if not latestAcwr.empty else None))

        for athleteName, currentAcwr in acwrSummaries:
            if currentAcwr is None:
                continue
            if currentAcwr < 0.8:
                color = "#b8860b"
                verdict = "Undertrained — consider adding load today"
            elif currentAcwr <= 1.3:
                color = "#2e7d32"
                verdict = "Optimal zone — good to train today"
            else:
                color = "#c62828"
                verdict = "High load — rest or easy session today"

            prefix = f"<b>{athleteName}:</b> " if len(acwrSummaries) > 1 else ""
            st.markdown(
                f"<div style='text-align:center;margin-bottom:0.25rem'>"
                f"<span style='font-size:1.4rem;font-weight:600;color:{color}'>"
                f"{prefix}ACWR {currentAcwr:.2f} — {verdict}"
                f"</span></div>",
                unsafe_allow_html=True,
            )

        acwrFigure.add_hrect(y0=0, y1=0.79, fillcolor="yellow", opacity=0.12, line_width=0)
        acwrFigure.add_hrect(y0=0.8, y1=1.3, fillcolor="green", opacity=0.12, line_width=0)
        acwrFigure.add_hrect(y0=1.31, y1=3, fillcolor="red", opacity=0.12, line_width=0)
        applyMobileChartLayout(acwrFigure, "Acute:Chronic Workload Ratio", "ACWR")
        st.plotly_chart(acwrFigure, use_container_width=True)

        upcomingContainer = st.container(border=True)
        with upcomingContainer:
            st.markdown("### Upcoming Sessions")
            st.caption("Planned workouts will appear here once scheduling data is connected.")

        st.subheader("Recent Sessions")
        recentSessions = selectedAthleteData.sort_values("Date", ascending=False).head(5).copy()
        recentSessions["Duration (mins)"] = pd.to_numeric(recentSessions["Duration (mins)"], errors="coerce")
        recentSessions["Session RPE"] = pd.to_numeric(recentSessions["Session RPE"], errors="coerce")
        recentSessions["Workload (AU)"] = (
            recentSessions["Duration (mins)"] * recentSessions["Session RPE"]
        ).round(0).astype("Int64")
        recentColumns = [
            columnName
            for columnName in ["Date", "Athlete Name", "Session Label", "Duration (mins)", "Session RPE", "Workload (AU)"]
            if columnName in recentSessions.columns
        ]
        recentSessions = (
            recentSessions[recentColumns]
            .rename(columns={"Session Label": "Session Type"})
        )
        st.dataframe(recentSessions, use_container_width=True, hide_index=True)

    with tabs[1]:
        st.subheader("Strength & Board Climbing")

        st.markdown("#### Finger Strength Progression")
        st.caption("All hangboard data normalized to a 20mm edge.")
        fingerData = prepareFingerStrengthData(filteredData)

        if fingerData.empty:
            st.info("No hangboard data available for the selected filters.")
        else:
            fingerFigure = go.Figure()
            for gripType in sorted(fingerData["Grip Type"].fillna("Unknown").unique()):
                gripSlice = fingerData[fingerData["Grip Type"].fillna("Unknown") == gripType].sort_values("Date")

                fingerFigure.add_trace(
                    go.Scatter(
                        x=gripSlice["Date"],
                        y=gripSlice["Hangboard Total Load"],
                        mode="lines+markers",
                        name=str(gripType),
                        customdata=gripSlice[["Hangboard Protocol", "Bodyweight"]],
                        hovertemplate=(
                            "Date: %{x}<br>"
                            "Total Load: %{y:.1f} lbs<br>"
                            "Protocol: %{customdata[0]}<br>"
                            "Bodyweight: %{customdata[1]:.1f} lbs<extra></extra>"
                        ),
                    )
                )

            applyMobileChartLayout(fingerFigure, "Hangboard Total Load by Grip Type", "Total Load (lbs)")
            st.plotly_chart(fingerFigure, use_container_width=True)

        st.markdown("#### Pull-up 1RM Progression")
        pullupData = preparePullupData(filteredData)
        if pullupData.empty:
            st.info("No pull-up 1RM data available for the selected filters.")
        else:
            pullupFigure = go.Figure()
            for athleteName in sorted(pullupData["Athlete Name"].dropna().unique()):
                athletePullups = pullupData[pullupData["Athlete Name"] == athleteName].sort_values("Date")
                pullupFigure.add_trace(
                    go.Scatter(
                        x=athletePullups["Date"],
                        y=athletePullups["Pull-up Total 1RM"],
                        mode="lines+markers",
                        name=str(athleteName),
                        customdata=athletePullups[["Bodyweight", "Pull-up 1RM Added Weight"]],
                        hovertemplate=(
                            "Date: %{x}<br>"
                            "Total 1RM: %{y:.1f} lbs<br>"
                            "Bodyweight: %{customdata[0]:.1f} lbs<br>"
                            "Added: %{customdata[1]:.1f} lbs<extra></extra>"
                        ),
                    )
                )

            applyMobileChartLayout(pullupFigure, "Pull-up Total 1RM Over Time", "Total 1RM (lbs)")
            st.plotly_chart(pullupFigure, use_container_width=True)

        st.markdown("#### National Benchmark Comparison")
        benchmarkData = buildBenchmarkData(selectedAthleteData)
        if benchmarkData.empty:
            st.info("No half-crimp or pull-up max data available for benchmark comparison.")
        else:
            benchmarkFigure = go.Figure()
            benchmarkFigure.add_trace(
                go.Bar(
                    y=benchmarkData["Metric"],
                    x=benchmarkData["National Target % Bodyweight"],
                    orientation="h",
                    name="Canadian National V10-V11 Target",
                    marker_color="rgba(80, 80, 80, 0.25)",
                    hovertemplate="Target: %{x:.0f}% bodyweight<extra></extra>",
                )
            )
            benchmarkFigure.add_trace(
                go.Bar(
                    y=benchmarkData["Metric"],
                    x=benchmarkData["Current % Bodyweight"],
                    orientation="h",
                    name="Athlete Peak",
                    marker_color="#2E86AB",
                    text=benchmarkData["Current % Bodyweight"].round(0).astype(int).astype(str) + "%",
                    textposition="inside",
                    hovertemplate="Peak: %{x:.1f}% bodyweight<extra></extra>",
                )
            )
            applyMobileChartLayout(
                benchmarkFigure,
                "Relative Strength vs Canadian National V10-V11 Targets",
                "Metric",
                barmode="overlay",
            )
            benchmarkFigure.update_xaxes(range=[0, max(170, benchmarkData["National Target % Bodyweight"].max() + 10)])
            st.plotly_chart(benchmarkFigure, use_container_width=True)

        st.markdown("#### Board Climbing Performance & Strength Index")
        boardData = filteredData[
            filteredData["Session Type"].astype(str).str.strip().eq("Board Climbing")
        ].copy()

        if boardData.empty:
            st.info("No board sessions available for the selected filters.")
        else:
            csiData = buildSessionCSI(boardData)
            if csiData.empty:
                st.info("No valid board climb entries were found.")
            else:
                csiData = csiData.sort_values("Date")

                csiFigure = go.Figure()
                csiFigure.add_trace(
                    go.Scatter(
                        x=csiData["Date"],
                        y=csiData["Session CSI"],
                        mode="lines+markers",
                        name="Session CSI",
                    )
                )
                csiFigure.add_trace(
                    go.Scatter(
                        x=csiData["Date"],
                        y=csiData["Rolling 14-Day CSI"],
                        mode="lines",
                        name="14-Day Trend",
                    )
                )
                applyMobileChartLayout(csiFigure, "Session CSI Over Time", "CSI")
                st.plotly_chart(csiFigure, use_container_width=True)

                peakGradeSent = csiData["Peak Grade Sent"].max()
                maxEfficiency = csiData["Best Efficiency Score"].max()

                metricContainer = st.container(border=True)
                with metricContainer:
                    st.markdown("##### Board Session Summary")
                    st.metric("Highest Grade Sent", f"V{int(peakGradeSent)}" if peakGradeSent > 0 else "N/A")
                    st.metric("Max Efficiency Score", round(maxEfficiency, 2))


if __name__ == "__main__":
    main()