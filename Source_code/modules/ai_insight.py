import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def generate_report_insight(report_data: Dict[str, Any]) -> str:
    """
    Generate professional traffic safety insight based on the comparative report data.
    
    Args:
        report_data: JSON dictionary containing summary, statistics, and tests from the report.
        
    Returns:
        A Markdown formatted string with the AI's analysis.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Error: GOOGLE_API_KEY is not set in environment variables."

    try:
        import google.generativeai as genai
    except ImportError as e:
        import sys
        import pprint
        path_str = pprint.pformat(sys.path)
        return f"Error: Google Generative AI library is not installed. Details: {str(e)}\nExecutable: {sys.executable}\nPath: {path_str}"
    except Exception as e:
        return f"Error: Failed to import AI library. Details: {str(e)}"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash') 
        
        # Construct a concise prompt
        metadata = report_data.get("summary", {}).get("metadata", {})
        groups = report_data.get("summary", {}).get("groups", {})
        stats = report_data.get("statistics", {})
        tests = report_data.get("tests", {})
        
        # Convert complex objects to simple string representation for prompt
        prompt_context = f"""
        # Analysis Data
        Total Events: {metadata.get('total_events')}
        Total Videos: {metadata.get('total_videos')}
        
        # Group Summaries
        {json.dumps(groups, ensure_ascii=False, indent=2)}
        
        # Statistical Tests Results (Significant Only)
        {json.dumps({k:v for k,v in tests.items() if v.get('significant')}, ensure_ascii=False, indent=2)}
        
        # Key Statistics
        {json.dumps(stats, ensure_ascii=False, indent=2)}
        """

        prompt = f"""
        You are an expert Traffic Safety Data Analyst. 
        Analyze the following comparative data between road types (e.g., widened vs non-widened) and/or years.
        
        Data:
        {prompt_context}
        
        Please provide a professional, insightful analysis in Japanese. Use Markdown formatting.
        Structure your response as follows:
        1. **Overview (概要)**: Brief summary of the data scope.
        2. **Key Findings (主な発見事項)**: Highlight significant differences in overtake behaviors (distance, speed, risk).
        3. **Safety Implications (安全性への示唆)**: diverse specific road types (widened vs non-widened) affect cyclist safety based on the metrics (clearance distance, etc.).
        4. **Conclusion (結論)**: Final verdict on the observed changes.

        Keep it concise but detailed enough for a technical report.
        """
        
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        logger.error(f"AI Generation failed: {e}")
        return f"Error generating insight: {str(e)}"
