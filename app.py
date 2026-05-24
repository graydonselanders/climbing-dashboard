import re
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

CSV_URL = "https://docs.google.com/spreadsheets/d/1weMRvvNVNgFDKypt-S-hl5YgbMy00dWsObGR5IgDrMw/gviz/tq?tqx=out:csv"

st.set_page_config(page_title="Climbing Training Dashboard", layout="centered")


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


@st.cache_data(ttl=300)
def loadData():
    dataFrame = pd.read_csv(CSV_URL)

    column_mapping = {
        "Protocol": "Hangboard Protocol",
        "Max Added Weight / Force (kg)": "Hangboard Max Weight", 
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

    filteredData = dataFrame.copy()
    if selectedAthletes:
        filteredData = filteredData[filteredData["Athlete Name"].isin(selectedAthletes)]

    filteredData = filteredData[(filteredData["Date"] >= startDate) & (filteredData["Date"] <= endDate)]

    if filteredData.empty:
        st.info("No workouts match the current filters.")
        st.stop()

    tabs = st.tabs(["Fatigue & Load", "Finger Metrics", "Board Performance"])

    with tabs[0]:
        st.subheader("Rest-Day Aware ACWR")

        acwrFigure = go.Figure()
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

        acwrFigure.add_hrect(y0=0.8, y1=1.3, fillcolor="green", opacity=0.12, line_width=0)
        acwrFigure.add_hrect(y0=1.5, y1=5, fillcolor="red", opacity=0.12, line_width=0)
        acwrFigure.update_layout(
            title="Acute:Chronic Workload Ratio",
            xaxis_title="Date",
            yaxis_title="ACWR",
            margin=dict(l=20, r=20, t=50, b=20),
            legend_title="Athlete",
        )
        st.plotly_chart(acwrFigure, use_container_width=True)

    with tabs[1]:
        st.subheader("Finger Strength Progression")
        fingerData = filteredData[
            filteredData["Session Type"].astype(str).str.strip().eq("Hangboard / Finger Strength")
        ].copy()

        if fingerData.empty or "Hangboard Max Weight" not in fingerData.columns:
            st.info("No hangboard data available for the selected filters.")
        else:
            fingerData["Hangboard Max Weight"] = pd.to_numeric(fingerData["Hangboard Max Weight"], errors="coerce")
            fingerData = fingerData.dropna(subset=["Hangboard Max Weight"])

            if fingerData.empty:
                st.info("No valid hangboard max weight values found.")
            else:
                protocolColumn = "Hangboard Protocol" if "Hangboard Protocol" in fingerData.columns else None
                if protocolColumn is None:
                    fingerData["Hangboard Protocol"] = "Unknown"
                    protocolColumn = "Hangboard Protocol"

                fingerFigure = go.Figure()
                for protocolName in sorted(fingerData[protocolColumn].fillna("Unknown").unique()):
                    protocolSlice = fingerData[fingerData[protocolColumn].fillna("Unknown") == protocolName]
                    protocolSlice = protocolSlice.sort_values("Date")

                    fingerFigure.add_trace(
                        go.Scatter(
                            x=protocolSlice["Date"],
                            y=protocolSlice["Hangboard Max Weight"],
                            mode="lines+markers",
                            name=str(protocolName),
                        )
                    )

                fingerFigure.update_layout(
                    title="Hangboard Max Weight by Protocol",
                    xaxis_title="Date",
                    yaxis_title="Max Weight",
                    margin=dict(l=20, r=20, t=50, b=20),
                )
                st.plotly_chart(fingerFigure, use_container_width=True)

    with tabs[2]:
        st.subheader("Board Climbing Performance & Strength Index")
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
            csiFigure.update_layout(
                title="Session CSI Over Time",
                xaxis_title="Date",
                yaxis_title="CSI",
                margin=dict(l=20, r=20, t=50, b=20),
            )
            st.plotly_chart(csiFigure, use_container_width=True)

            peakGradeSent = csiData["Peak Grade Sent"].max()
            maxEfficiency = csiData["Best Efficiency Score"].max()

            summaryData = pd.DataFrame(
                {
                    "Metric": ["Highest Grade Sent", "Max Efficiency Score"],
                    "Value": [f"V{int(peakGradeSent)}" if peakGradeSent > 0 else "N/A", round(maxEfficiency, 2)],
                }
            )
            st.dataframe(summaryData, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()