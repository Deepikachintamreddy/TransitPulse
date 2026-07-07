"""Gemini-powered natural language transit operations analyst agent.
Uses google-genai function calling to query aggregated reliability metrics.
"""

from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import types

from config import CFG
from db import DB


# ── Define Tools for Gemini Function Calling ──────────────────────────

def get_route_score(route_id: str) -> str:
    """Returns the current reliability score and basic metrics for a specific route."""
    try:
        timeline = DB.get_route_timeline(route_id)
        if not timeline:
            return f"Error: Route {route_id} was not found in the database."
        
        # Get the latest entry
        latest = timeline[-1]
        res = (
            f"Route: {route_id}\n"
            f"Date: {latest.get('date')}\n"
            f"Reliability Score: {latest.get('reliability_score'):.2f} / 100\n"
            f"Average Headway: {latest.get('mean_headway'):.1f} minutes\n"
            f"Average Dwell Time: {latest.get('mean_dwell_sec'):.1f} seconds\n"
            f"Bunching Events Count: {latest.get('bunching_count')}\n"
            f"Gap Events Count: {latest.get('gap_count')}"
        )
        return res
    except Exception as e:
        return f"Error querying route score: {str(e)}"


def get_worst_segments(limit: int = 5) -> str:
    """Returns a list of the N worst performing route segments that need schedule intervention."""
    try:
        worst = DB.get_worst_segments(limit=limit)
        if not worst:
            return "No segment metrics available in the database."
        
        lines = ["Worst Performing Route Segments:"]
        for idx, item in enumerate(worst):
            lines.append(
                f"{idx+1}. Route {item['route_id']}, Segment {item['stop_id']}: "
                f"Reliability Score: {item['reliability_score']:.2f}, "
                f"Trips: {item['total_trips']}, Bunching Rate: {item['bunching_rate']*100:.1f}%, "
                f"Gap Rate: {item['gap_rate']*100:.1f}%"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error querying worst segments: {str(e)}"


def compare_periods(route_id: str, date1: str, date2: str) -> str:
    """Compares route performance metrics between two dates."""
    try:
        metrics = DB.compare_periods(route_id, date1, date2)
        if len(metrics) < 2:
            return f"Compare error: Could not find data for route {route_id} on both dates {date1} and {date2}."
            
        res = f"Comparison of Route {route_id} between {date1} and {date2}:\n"
        for item in metrics:
            res += (
                f"- Date: {item.get('date', 'N/A')}: "
                f"Reliability: {item.get('reliability_score', 0):.2f}, "
                f"Headway: {item.get('mean_headway', 0):.1f} min, "
                f"Bunching: {item.get('bunching_count', 0)}, "
                f"Gaps: {item.get('gap_count', 0)}\n"
            )
        return res
    except Exception as e:
        return f"Error comparing periods: {str(e)}"


def explain_anomaly(anomaly_id_or_route: str) -> str:
    """Explains recent anomalies for a route or segment."""
    try:
        anomalies = DB.get_anomalies(route_id=anomaly_id_or_route, limit=5)
        if not anomalies:
            return f"No recent anomalies recorded for {anomaly_id_or_route}."
            
        lines = [f"Recent anomaly events for {anomaly_id_or_route}:"]
        for idx, a in enumerate(anomalies):
            lines.append(
                f"- Time: {a['timestamp_str']} | Vehicle: {a['vehicle_id']} | "
                f"Stop: {a['stop_id']} (Seq {a['stop_sequence']}) | "
                f"Type: {a['anomaly_type'].upper()} (Headway: {a['headway_min']:.1f} min vs Scheduled: {a['scheduled_headway_min']:.1f} min)"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error explaining anomalies: {str(e)}"


# Map of available function names to local python callables
TOOLS_MAP = {
    "get_route_score": get_route_score,
    "get_worst_segments": get_worst_segments,
    "compare_periods": compare_periods,
    "explain_anomaly": explain_anomaly
}


def ask_gemini(question: str) -> str:
    """Runs a function-calling session with Gemini using the google-genai SDK."""
    api_key = CFG.gemini_api_key
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        
    if not api_key:
        return (
            "Gemini Agent is offline because the GEMINI_API_KEY environment variable is not set. "
            "Please configure the key to enable operations intelligence chat."
        )

    # Initialize google-genai client
    client = genai.Client(api_key=api_key)

    system_instruction = (
        "You are TransitPulse's AI Lead Transit Operations Analyst. "
        "Your role is to help a transit depot manager decide which routes and segments need schedule "
        "intervention this week. "
        "You have direct access to database querying tools. You must adhere to the following rules:\n"
        "1. GROUND ALL CLAIMS IN DATA. Never state a route or segment performance number without querying it first.\n"
        "2. NEVER HALLUCINATE route IDs, segment IDs, or scores. If a route isn't returned, state it's not present.\n"
        "3. Keep answers clear, structured, and quantitative.\n"
        "4. ALWAYS end your response with a concrete recommended action (e.g., 'Recommendation: Recalibrate route DTC-015 scheduled headway')."
    )

    # List of functions provided to Gemini
    tools_declarations = [
        get_route_score,
        get_worst_segments,
        compare_periods,
        explain_anomaly
    ]

    try:
        # Step 1: Initial call to Gemini with the user's question
        response = client.models.generate_content(
            model=CFG.gemini_model,
            contents=question,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=tools_declarations
            )
        )
        
        # Step 2: Handle function calls if Gemini requests them
        # Note: In a production loop, there could be multiple turns of function calling.
        # We will handle up to 3 function execution cycles.
        contents = [question]
        
        for _ in range(3):
            if not response.function_calls:
                break
                
            # Build tool responses
            tool_responses = []
            for function_call in response.function_calls:
                func_name = function_call.name
                func_args = function_call.args
                
                print(f"Agent requested function call: {func_name}({func_args})")
                
                if func_name in TOOLS_MAP:
                    # Execute the function with arguments
                    func_to_call = TOOLS_MAP[func_name]
                    # Convert arguments map into correct keyword arguments
                    result = func_to_call(**func_args)
                else:
                    result = f"Error: Tool '{func_name}' is not registered."
                    
                # Append tool response in correct format
                tool_responses.append(
                    types.Part.from_function_response(
                        name=func_name,
                        response={"result": result}
                    )
                )
                
            # Add the model's function calls to content history
            contents.append(response.candidates[0].content)
            # Add the executed function results to context history
            contents.append(types.Content(role="user", parts=tool_responses))
            
            # Send results back to Gemini for final response synthesis or further tool calls
            response = client.models.generate_content(
                model=CFG.gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=tools_declarations
                )
            )

        return response.text
        
    except Exception as e:
        return f"Gemini Agent execution failed: {str(e)}"
