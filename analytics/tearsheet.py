"""
Tear Sheet Generator for Apex Credit Monitor
Generates professional credit tear sheets from company data
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path


def generate_tearsheet_html(data: Dict[str, Any]) -> str:
    """
    Generate an HTML tear sheet from company snapshot data

    Args:
        data: Company snapshot data dictionary

    Returns:
        HTML string for the tear sheet
    """
    company_name = data.get("company_name", "Unknown Company")
    sector = data.get("sector", "")
    last_updated = data.get("last_updated", datetime.now().strftime("%Y-%m-%d"))

    overview = data.get("overview", {})
    ratings = data.get("ratings", {})
    quick_assessment = data.get("quick_assessment", {})
    key_ratios = data.get("key_ratios", {})
    debt_cap = data.get("debt_capitalization", [])
    credit_opinion = data.get("credit_opinion", {})

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{company_name} - Credit Tear Sheet</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 11px;
            line-height: 1.4;
            color: #333;
            background: #fff;
            padding: 20px;
        }}
        .tearsheet {{
            max-width: 1000px;
            margin: 0 auto;
        }}
        .header {{
            border-bottom: 3px solid #1a365d;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }}
        .header h1 {{
            font-size: 22px;
            color: #1a365d;
            margin-bottom: 5px;
        }}
        .header .meta {{
            color: #666;
            font-size: 10px;
        }}
        .section {{
            margin-bottom: 15px;
        }}
        .section-title {{
            background: #1a365d;
            color: white;
            padding: 5px 10px;
            font-size: 12px;
            font-weight: bold;
            margin-bottom: 8px;
        }}
        .section-content {{
            padding: 0 10px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }}
        .grid-3 {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 10px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 10px;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 4px 6px;
            text-align: left;
        }}
        th {{
            background: #f5f5f5;
            font-weight: 600;
        }}
        .metric-box {{
            background: #f8f9fa;
            padding: 8px;
            border-left: 3px solid #1a365d;
        }}
        .metric-label {{
            font-size: 9px;
            color: #666;
            text-transform: uppercase;
        }}
        .metric-value {{
            font-size: 14px;
            font-weight: bold;
            color: #1a365d;
        }}
        .rating-box {{
            text-align: center;
            padding: 5px;
            background: #f8f9fa;
            border-radius: 3px;
        }}
        .rating {{
            font-size: 16px;
            font-weight: bold;
            color: #1a365d;
        }}
        .rating-agency {{
            font-size: 9px;
            color: #666;
        }}
        .positive {{ color: #22543d; }}
        .negative {{ color: #c53030; }}
        .neutral {{ color: #744210; }}
        .description {{
            font-size: 10px;
            line-height: 1.5;
            color: #444;
        }}
        @media print {{
            body {{ padding: 10px; }}
            .tearsheet {{ max-width: 100%; }}
        }}
    </style>
</head>
<body>
    <div class="tearsheet">
        <div class="header">
            <h1>{company_name}</h1>
            <div class="meta">
                {sector} | Last Updated: {last_updated}
            </div>
        </div>

        <div class="grid">
            <div class="section">
                <div class="section-title">Business Overview</div>
                <div class="section-content">
                    <p class="description">{overview.get('business_description', 'N/A')}</p>
                    <p style="margin-top: 8px;"><strong>Ownership:</strong> {overview.get('ownership', 'N/A')} ({overview.get('public_private', 'N/A')})</p>
                    <p><strong>Status:</strong> {overview.get('recent_news', 'N/A')}</p>
                </div>
            </div>

            <div class="section">
                <div class="section-title">Credit Ratings</div>
                <div class="section-content">
                    <div class="grid-3">
                        <div class="rating-box">
                            <div class="rating">{ratings.get('moodys', {}).get('rating', '-')}</div>
                            <div class="rating-agency">Moody's</div>
                        </div>
                        <div class="rating-box">
                            <div class="rating">{ratings.get('sp', {}).get('rating', '-')}</div>
                            <div class="rating-agency">S&P</div>
                        </div>
                        <div class="rating-box">
                            <div class="rating">{ratings.get('fitch', {}).get('rating', '-')}</div>
                            <div class="rating-agency">Fitch</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">Key Credit Metrics</div>
            <div class="section-content">
                <div class="grid">
                    <div>
                        <table>
                            <tr>
                                <th>Metric</th>
                                <th>Value</th>
                            </tr>
                            <tr>
                                <td>Total Debt</td>
                                <td>{_format_number(quick_assessment.get('total_debt'))}m</td>
                            </tr>
                            <tr>
                                <td>Cash & Equivalents</td>
                                <td>{_format_number(quick_assessment.get('cash_on_hand'))}m</td>
                            </tr>
                            <tr>
                                <td>CFFO</td>
                                <td>{_format_number(quick_assessment.get('cffo'))}m</td>
                            </tr>
                            <tr>
                                <td>Interest Expense</td>
                                <td>{_format_number(quick_assessment.get('interest_expense'))}m</td>
                            </tr>
                        </table>
                    </div>
                    <div>
                        <table>
                            <tr>
                                <th>Ratio</th>
                                <th>Value</th>
                            </tr>
                            <tr>
                                <td>Debt / EBITDA</td>
                                <td>{_format_ratio(key_ratios.get('debt_to_ebitda'))}x</td>
                            </tr>
                            <tr>
                                <td>Net Debt / EBITDA</td>
                                <td>{_format_ratio(key_ratios.get('net_debt_to_ebitda'))}x</td>
                            </tr>
                            <tr>
                                <td>(EBITDA - Capex) / Interest</td>
                                <td>{_format_ratio(key_ratios.get('ebitda_minus_capex_to_interest'))}x</td>
                            </tr>
                            <tr>
                                <td>FCF / Debt</td>
                                <td>{_format_percent(key_ratios.get('fcf_to_debt'))}</td>
                            </tr>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">Debt Capitalization</div>
            <div class="section-content">
                <table>
                    <tr>
                        <th>Instrument</th>
                        <th>Amount (m)</th>
                        <th>Maturity</th>
                        <th>Coupon</th>
                        <th>Price</th>
                        <th>YTW</th>
                        <th>STW</th>
                    </tr>
                    {_generate_debt_rows(debt_cap)}
                </table>
            </div>
        </div>

        {_generate_credit_opinion_section(credit_opinion)}

        <div style="margin-top: 20px; font-size: 9px; color: #999; text-align: center;">
            Generated by XO S44 Credit Monitor | {datetime.now().strftime("%Y-%m-%d %H:%M")}
        </div>
    </div>
</body>
</html>
"""
    return html


def _format_number(value: Any) -> str:
    """Format a number for display"""
    if value is None:
        return "-"
    try:
        return f"{float(value):,.0f}"
    except:
        return str(value)


def _format_ratio(value: Any) -> str:
    """Format a ratio for display"""
    if value is None:
        return "-"
    try:
        return f"{float(value):.1f}"
    except:
        return str(value)


def _format_percent(value: Any) -> str:
    """Format a percentage for display"""
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.1f}%"
    except:
        return str(value)


def _generate_debt_rows(debt_instruments: List[Dict]) -> str:
    """Generate HTML rows for debt instruments"""
    if not debt_instruments:
        return "<tr><td colspan='7'>No debt instruments available</td></tr>"

    rows = []
    for inst in debt_instruments:
        row = f"""
        <tr>
            <td>{inst.get('instrument', '-')}</td>
            <td>{_format_number(inst.get('amount'))}</td>
            <td>{inst.get('maturity', '-')}</td>
            <td>{inst.get('coupon', '-')}</td>
            <td>{_format_number(inst.get('price'))}</td>
            <td>{_format_ratio(inst.get('ytw'))}</td>
            <td>{_format_number(inst.get('stw'))}</td>
        </tr>
        """
        rows.append(row)
    return "\n".join(rows)


def _generate_credit_opinion_section(opinion: Dict) -> str:
    """Generate the credit opinion section if available"""
    if not opinion or not opinion.get('summary'):
        return ""

    risks = opinion.get('key_risks', [])
    catalysts = opinion.get('key_catalysts', [])

    risks_html = "".join([f"<li>{r}</li>" for r in risks]) if risks else "<li>-</li>"
    catalysts_html = "".join([f"<li>{c}</li>" for c in catalysts]) if catalysts else "<li>-</li>"

    return f"""
    <div class="section">
        <div class="section-title">Credit Opinion</div>
        <div class="section-content">
            <p class="description">{opinion.get('summary', '')}</p>
            <div class="grid" style="margin-top: 10px;">
                <div>
                    <strong class="negative">Key Risks:</strong>
                    <ul style="margin-left: 15px; margin-top: 5px;">
                        {risks_html}
                    </ul>
                </div>
                <div>
                    <strong class="positive">Key Catalysts:</strong>
                    <ul style="margin-left: 15px; margin-top: 5px;">
                        {catalysts_html}
                    </ul>
                </div>
            </div>
            <p style="margin-top: 10px;"><strong>Recommendation:</strong> {opinion.get('recommendation', '-')}</p>
        </div>
    </div>
    """


def generate_tearsheet_from_json(json_path: str, output_path: Optional[str] = None) -> str:
    """
    Generate a tear sheet from a JSON snapshot file

    Args:
        json_path: Path to the JSON snapshot file
        output_path: Optional path for the output HTML file

    Returns:
        Path to the generated HTML file
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    html = generate_tearsheet_html(data)

    if output_path is None:
        output_path = json_path.replace('.json', '_tearsheet.html')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return output_path


def generate_all_tearsheets(snapshots_dir: str, output_dir: str) -> List[str]:
    """
    Generate tear sheets for all JSON snapshots in a directory

    Args:
        snapshots_dir: Directory containing JSON snapshot files
        output_dir: Directory to save HTML tear sheets

    Returns:
        List of generated file paths
    """
    snapshots_path = Path(snapshots_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    generated = []

    for json_file in snapshots_path.glob("*.json"):
        if json_file.name == "template.json":
            continue

        try:
            output_file = output_path / f"{json_file.stem}_tearsheet.html"
            result = generate_tearsheet_from_json(str(json_file), str(output_file))
            generated.append(result)
            print(f"Generated: {output_file.name}")
        except Exception as e:
            print(f"Error generating tear sheet for {json_file.name}: {e}")

    return generated


def generate_tearsheet_streamlit(data: Dict[str, Any]) -> str:
    """
    Generate tear sheet HTML optimized for Streamlit iframe embedding

    Args:
        data: Company snapshot data dictionary

    Returns:
        HTML string suitable for st.components.v1.html()
    """
    return generate_tearsheet_html(data)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python tearsheet_generator.py <json_file>             - Generate single tear sheet")
        print("  python tearsheet_generator.py --all <snapshots_dir> <output_dir>  - Generate all")
        sys.exit(1)

    if sys.argv[1] == "--all" and len(sys.argv) >= 4:
        generated = generate_all_tearsheets(sys.argv[2], sys.argv[3])
        print(f"\nGenerated {len(generated)} tear sheets")
    else:
        output = generate_tearsheet_from_json(sys.argv[1])
        print(f"Generated: {output}")
