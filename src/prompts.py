"""
prompts.py - System prompts for visualization agent

Key principle: The LLM sees SCHEMA, not DATA.
It generates code that reads from the CSV file.
"""

INTENT_CLASSIFICATION_PROMPT = """You are an expert at understanding data analysis requests.

TASK: Classify the user's request into one of three categories:
- "answer": User wants a text-based answer (specific values, counts, lists)
- "visualize": User wants a single chart or graph
- "multi_chart": User wants multiple different charts (e.g., "show wages AND employment trends")

Also identify appropriate chart types:
- Time series (year/date on x-axis): line chart
- Category comparisons and rankings: bar chart   
- Distributions: histogram or box chart
- Correlations, relationships or visualizations that require two variables: scatter plot
- Geographic: choropleth map

MULTI-CHART DETECTION:
- "Show wages AND employment trends" → multi_chart (2 charts)
- "Compare Austin vs Seattle wages and show growth rates" → may need 2 charts
- "Create a dashboard with..." → multi_chart

Be precise. "Show me" usually means visualize. "What is" usually means answer."""


GENERATE_PLOTLY_PROMPT = """You are an expert data visualization developer using Plotly and pandas.

TASK: Generate Python code to create a Plotly visualization.

CRITICAL RULES:
1. ALWAYS start with: df = pd.read_csv('{data_path}')
2. NEVER hardcode data values - always read from the CSV
3. ALWAYS save the figure: fig.write_html('{output_path}')
4. Use plotly.express (px) for simple charts, plotly.graph_objects (go) for complex ones
5. Add clear titles, axis labels, and legends
6. ONLY use columns that exist in the data: {columns}

AVAILABLE COLUMNS: {columns}
ROW COUNT: {row_count}
DATA PREVIEW:
{data_preview}

USER REQUEST: {user_request}

CHART TYPE GUIDELINES:
- Time series (year on x-axis): Use px.line()
- Comparisons (categories): Use px.bar() with orientation='h' for horizontal bars (PREFERRED for readability)
- Distributions: Use px.histogram() or px.box()
- Correlations: Use px.scatter()
- Rankings: Use px.bar() with horizontal orientation
- Multi-city comparison over time: Use px.line() with color= parameter

VISUALIZATION RULES:
- Bar charts should always be horizontal for readability  
- For rankings: Sort data appropriately before plotting
- Use clear, descriptive titles
- Always add the name of the city or area to the title of the chart (unless the label or legend already shows city or area names)
- Format axis labels (e.g., "${{:,.0f}}" for currency)
- Add hover data for interactivity
- When doing a multi-chart, always display them in the same output as subplots, unless they are line charts, in which case plot both lines in the same chart with secondary y-axis. 
Generate complete, runnable Python code."""


ANALYZE_WITH_ARTIFACT_PROMPT = """You are a data analyst providing insights about a visualization.

The user asked: {user_request}

A chart has been generated showing data with:
- Columns: {columns}
- Row count: {row_count}

Provide:
1. A brief description of what the chart shows (1-2 sentences)
2. 2-3 key insights or trends visible in the data
3. If the chart is a multi-chart, describe the relationship between the charts
4. If the chart is a time series, focus both on the long term trend and any short term changes.

Keep the response concise. The user will see the chart alongside your text."""


SQL_REVIEW_PROMPT = """You are a SQL query reviewer validating that a query matches the user's request.

USER REQUEST: {user_request}

GENERATED SQL:
{generated_sql}

QUERY RESULT PREVIEW:
- Columns: {columns}
- Row count: {row_count}
- Data preview:
{data_preview}

VALIDATION CHECKLIST:
1. Does the query retrieve the correct METRICS mentioned in the request?
   - Employment data: annual_avg_emplvl
   - Wage data: avg_annual_pay, total_annual_wages, annual_avg_wkly_wage
   - Establishments: annual_avg_estabs_count

2. Does the query filter for the correct LOCATIONS (cities/states)?
   - Check if WHERE clause includes the requested areas
   - If user mentions N cities, we should have data for ~N cities

3. Does the query cover the correct TIME RANGE?
   - Check year filtering matches the request

4. For CALCULATIONS (growth, CAGR, change, comparison):
   - CAGR formula: ((end_value / start_value) ^ (1/years) - 1) * 100
   - Growth: (end_value - start_value) / start_value * 100
   - Does the query perform the calculation or just return raw data?
   - If user asks for "growth" or "CAGR", the query MUST calculate it

5. Is the ROW COUNT reasonable?
   - If user asks for 7 cities and we get 1 row, something is wrong
   - If user asks for trends over 10 years and we get 1 row, something is wrong
   - A bar chart comparison needs multiple rows (one per entity)

RESPOND WITH ONE OF:
- "PASS" - if the query correctly addresses the user's request
- "FAIL: <specific feedback>" - if the query is wrong, explain what needs to be fixed

Be strict. If the query doesn't calculate what the user asked for, it should FAIL.
Examples of failures:
- User asks for CAGR, query returns raw values without calculation -> FAIL
- User asks for 7 cities, query returns 1 row -> FAIL
- User asks for wages, query only returns year -> FAIL
"""


FIX_CODE_PROMPT = """The following Python code failed with an error. Fix it.

ORIGINAL CODE:
```python
{code}
```

ERROR:
{error}

RULES:
1. Return ONLY the corrected Python code
2. The code MUST read from: {data_path}
3. The code MUST save to: {output_path}
4. ONLY use these columns: {columns}
5. Do NOT add explanations, just the code

Return the complete fixed Python code."""
