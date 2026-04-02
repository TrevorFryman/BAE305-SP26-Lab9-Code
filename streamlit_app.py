import pandas as pd
import streamlit as st

st.set_page_config(page_title='Water Quality Station Explorer', layout='wide')

@st.cache_data
def load_data():
    stations = pd.read_csv('station.csv', low_memory=False)
    results = pd.read_csv('narrowresult.csv', low_memory=False)

    stations['LatitudeMeasure'] = pd.to_numeric(stations['LatitudeMeasure'], errors='coerce')
    stations['LongitudeMeasure'] = pd.to_numeric(stations['LongitudeMeasure'], errors='coerce')

    results['ActivityStartDate'] = pd.to_datetime(results['ActivityStartDate'], errors='coerce')

    # use published column values as-is; numeric conversion is done only for comparison/plotting
    # this ensures we honor ResultMeasureValue in the source
    return stations, results

stations, results = load_data()

st.title('Water Quality Characteristic Explorer')
st.markdown(
    'Select a characteristic, filter by value and date, then review the map and trend of all stations that match.'
)

characteristics = sorted(results['CharacteristicName'].dropna().unique())
selected_char = st.sidebar.selectbox('Characteristic', characteristics)

char_data = results[results['CharacteristicName'] == selected_char].copy()

if char_data.empty:
    st.warning('No data available for this characteristic.')
    st.stop()

# date range controls
min_date = char_data['ActivityStartDate'].min()
max_date = char_data['ActivityStartDate'].max()

if pd.isna(min_date) or pd.isna(max_date):
    st.error('No valid dates for selected characteristic.')
    st.stop()

date_range = st.sidebar.date_input(
    'Date range',
    value=[min_date.date(), max_date.date()],
    min_value=min_date.date(),
    max_value=max_date.date()
)

if len(date_range) != 2:
    st.error('Please select a start date and an end date.')
    st.stop()

start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])

# apply date filter first (retains non-numeric values for mapping & total counts)
date_filtered = char_data[
    (char_data['ActivityStartDate'] >= start_date)
    & (char_data['ActivityStartDate'] <= end_date)
].copy()

if date_filtered.empty:
    st.warning('No samples for this characteristic in the selected date range.')
    st.stop()

# For filtering and calculations, we convert to numeric only at the moment of use
# The original data remains completely untouched

# Get numeric values only for slider and range logic (NOT stored in dataframes)
numeric_values = pd.to_numeric(date_filtered['ResultMeasureValue'], errors='coerce')
numeric_count = numeric_values.notna().sum()
non_numeric_count = len(date_filtered) - numeric_count

stats_msg = (
    f'{len(date_filtered):,} samples across {date_filtered["MonitoringLocationIdentifier"].nunique():,} stations, '
    f'{numeric_count:,} numeric measurements, '
    f'{non_numeric_count:,} non-numeric/empty samples.'
)

if numeric_count == 0:
    st.info('No numeric values in the selected date range; numeric value range filtering is disabled.')
    include_non_numeric = True
    value_range = None
    filtered_for_map = date_filtered.copy()
else:
    val_min = float(numeric_values.min())
    val_max = float(numeric_values.max())

    default_lo = val_min
    default_hi = val_max

    if val_min == val_max:
        value_range = (val_min, val_max)
    else:
        value_range = st.sidebar.slider(
            'Measurement range',
            min_value=val_min,
            max_value=val_max,
            value=(default_lo, default_hi),
            step=(val_max - val_min) / 500 if (val_max - val_min) > 0 else 1,
        )

    include_non_numeric = st.sidebar.checkbox(
        'Include non-numeric results in station map (qualifiers)',
        value=True,
        help='Station locations from qualifying samples will be included even if they are not numeric to preserve data completeness.'
    )

    if include_non_numeric:
        filtered_for_map = date_filtered.copy()
    else:
        # Filter to only rows where numeric value is in range
        numeric_in_range = pd.to_numeric(date_filtered['ResultMeasureValue'], errors='coerce')
        filtered_for_map = date_filtered[
            (numeric_in_range >= value_range[0]) & (numeric_in_range <= value_range[1])
        ].copy()

st.write(stats_msg)

# station map
valid_station_ids = filtered_for_map['MonitoringLocationIdentifier'].dropna().unique()
map_stations = stations[stations['MonitoringLocationIdentifier'].isin(valid_station_ids)].copy()
map_stations = map_stations.dropna(subset=['LatitudeMeasure', 'LongitudeMeasure'])

if map_stations.empty:
    st.warning('No station coordinates available for this filtered selection.')
else:
    map_stations = map_stations.rename(columns={'LatitudeMeasure': 'lat', 'LongitudeMeasure': 'lon'})
    st.subheader('Station locations on map')
    st.map(map_stations[['lat', 'lon']])

    # add a table of active station names with counts
    # Convert to numeric only for calculating stats; keep original data untouched
    stat_for_count = filtered_for_map.copy()
    
    # Calculate mean from numeric values only
    station_means = stat_for_count.groupby('MonitoringLocationIdentifier').apply(
        lambda group: pd.to_numeric(group['ResultMeasureValue'], errors='coerce').mean()
    ).reset_index(name='Mean_Value')
    
    # Count numeric values per station
    def count_numeric(group):
        return pd.to_numeric(group['ResultMeasureValue'], errors='coerce').notna().sum()
    
    station_numeric_counts = stat_for_count.groupby('MonitoringLocationIdentifier').apply(count_numeric).reset_index(name='Numeric_Count')
    
    # Count total samples per station
    station_total_counts = stat_for_count.groupby('MonitoringLocationIdentifier').size().reset_index(name='Sample_Count')
    
    # Merge all calculations
    station_summary = station_total_counts.merge(station_numeric_counts, on='MonitoringLocationIdentifier')
    station_summary = station_summary.merge(station_means, on='MonitoringLocationIdentifier')
    
    station_summary = station_summary.rename(columns={
        'Sample_Count': 'Sample Count', 
        'Mean_Value': 'Mean Value',
        'Numeric_Count': 'Numeric Count'
    })
    station_summary = station_summary.merge(
        map_stations[['MonitoringLocationIdentifier', 'MonitoringLocationName', 'lat', 'lon']],
        on='MonitoringLocationIdentifier',
        how='left'
    )

    st.dataframe(station_summary.sort_values('Sample Count', ascending=False))

# trend plot (overall and per station if small set)
# Convert to numeric only at plot time; original data remains untouched
trend = filtered_for_map.copy()
trend['ResultMeasureValueNumeric'] = pd.to_numeric(trend['ResultMeasureValue'], errors='coerce')
trend = trend[trend['ResultMeasureValueNumeric'].notna()].copy()

if trend.empty:
    st.warning('No numeric data for trend plot after filtering.')
else:
    st.subheader('Trend over time')
    trend_by_date = trend.groupby('ActivityStartDate')['ResultMeasureValueNumeric'].mean()
    st.line_chart(trend_by_date)

    if filtered_for_map['MonitoringLocationIdentifier'].nunique() <= 20:
        st.subheader('Trend by station')
        pivot = trend.pivot_table(
            index='ActivityStartDate',
            columns='MonitoringLocationIdentifier',
            values='ResultMeasureValueNumeric',
            aggfunc='mean'
        )
        st.line_chart(pivot)

st.sidebar.markdown('---')
st.sidebar.write('Data source: station.csv + narrowresult.csv')
